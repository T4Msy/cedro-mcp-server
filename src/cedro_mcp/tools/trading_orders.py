"""Tools de escrita de Trading (AÇÃO REAL): preview→confirm para enviar, editar e cancelar ordem.

Separado de `trading.py` só por tamanho — é registrado por ele, não standalone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from urllib.parse import quote

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.types import ToolAnnotations
from pydantic import Field
from typing_extensions import NotRequired, TypedDict

from ..auth.entitlements import require_scope
from ..auth.scopes import TRADING_TRADE
from ..errors import CedroError
from ..models import Quote
from ..observability import audit
from ..session_pool import hash_key
from ..trading.guardrails import GuardrailReport, check_order
from ..trading.models import OrderMode
from ..trading.orders import build_cancel_order, build_edit_order, build_new_order
from ._helpers import READ_ONLY_ANNOTATIONS, parse_list

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient
    from ..config import Settings
    from ..credentials import CredentialProvider
    from ..trading.client import TradingClient
    from ..trading.confirmation import ActionKind, ConfirmationStore

TRADE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
)

#: A doc lista o Mercado (BUY/SELL a mercado, sem limite de preço) como o extremo oposto do
#: Limite — mantido igual ao par ENDPOINT_BY_MODE/ORD_TYPE_BY_MODE de trading/models.py.
_MODE_DESCRIPTIONS = {
    "limit": "Limite — só executa a um preço máx (compra)/mín (venda) igual ou melhor",
    "market": "Mercado — executa já, ao melhor preço disponível, sem controle de preço",
    "start": "Start — dispara ao atingir um patamar mínimo (captura rompimento de alta)",
    "stop": "Stop — condicional clássica de disparo (stop loss / start gain)",
    "stop_conditional": "Stop Conditional — combina gatilho de perda e de ganho na mesma ordem",
    "stop_moving": "Stop Moving (trailing) — o preço de disparo se ajusta com a cotação",
    "stop_oco": "Stop OCO — duas pernas vinculadas; a execução de uma cancela a outra",
    "stop_simult": "Stop Simult — múltiplos níveis de stop/alvo disparados simultaneamente",
}


class OrderPreview(TypedDict):
    """Resultado de um preview — nada foi enviado ainda."""

    summary: str
    confirmation_token: str
    clordid: NotRequired[str | None]
    #: Último negócio usado pelos guardrails (None = Market Data indisponível).
    reference_price: NotRequired[float | None]
    #: qty × preço da ordem — base do teto CEDRO_TRADING_MAX_ORDER_VALUE.
    estimated_value: NotRequired[float | None]
    #: Alertas para mostrar ao usuário ANTES de pedir a confirmação.
    warnings: NotRequired[list[str]]


class OrderConfirmation(TypedDict):
    """Resultado da execução real de um preview."""

    summary: str
    accepted: bool
    code: str | None
    message: str | None
    messageDetails: str | None
    confirmed: NotRequired[bool]
    note: NotRequired[str]


#: Campos de PREÇO conferidos contra a banda — `initial_change`/`nlgs_*` são variações, não preço.
_BAND_CHECKED_FIELDS = (
    "price", "stop_trigger", "stop_limit", "moving_start", "target_limit", "target_trigger"
)


def _principal() -> AccessToken | None:
    return get_access_token()


def register_order_tools(
    mcp: "FastMCP",
    client: "TradingClient",
    store: "ConfirmationStore",
    credential_provider: "CredentialProvider",
    settings: "Settings",
    market_data: "CedroClient",
) -> None:
    guardrails_on = settings.trading_price_band_pct > 0 or settings.trading_max_order_value > 0

    def _reference_price(symbol: str) -> float | None:
        """Último negócio pela Market Data REST — best-effort: falha vira alerta, não erro."""
        if not guardrails_on:
            return None
        try:
            data = market_data.get_quotes(f"/services/quotes/quote/{quote(symbol, safe='')}")
        except Exception:  # noqa: BLE001 — sem referência, os guardrails avisam ou recusam
            return None
        quotes = parse_list(data, Quote)
        return quotes[0].lastTrade if quotes and quotes[0].lastTrade else None

    def _guardrails(symbol: str, qty: int, prices: dict[str, float | None]) -> GuardrailReport:
        return check_order(
            qty=qty,
            prices=prices,
            reference_price=_reference_price(symbol),
            max_order_value=settings.trading_max_order_value,
            price_band_pct=settings.trading_price_band_pct,
        )

    def _trading_identity() -> tuple[str, str]:
        """(username, source_address) da credencial Trading do principal atual."""
        creds = credential_provider.trading_credentials_for(_principal())
        return creds.oms_login_value or "", settings.trading_remote_ip

    def _owner() -> str:
        """Chave de sessão do chamador — amarra o token de confirmação a quem fez o preview."""
        return credential_provider.session_key(_principal())

    def _create_pending(
        kind: "ActionKind",
        summary: str,
        params: dict[str, str],
        endpoint: str | None = None,
        warnings: list[str] | None = None,
    ) -> str:
        token = store.create(
            kind, owner=_owner(), summary=summary, params=params, endpoint=endpoint
        )
        audit(
            "trading_preview",
            kind=kind,
            summary=summary,
            token_id=hash_key(token)[:12],
            warnings=len(warnings or []),
        )
        return token

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(TRADING_TRADE)
    def trading_preview_order(
        mode: OrderMode,
        market: str,
        symbol: str,
        side: str,
        qty: int,
        account: str,
        price: float | None = None,
        stop_trigger: float | None = None,
        stop_limit: float | None = None,
        initial_change: float | None = None,
        moving_start: float | None = None,
        nlgs_stop_px: float | None = None,
        nlgs_stop_gain_px: float | None = None,
        target_limit: float | None = None,
        target_trigger: float | None = None,
        time_in_force: str | None = None,
        validity_order: str | None = None,
        order_tag: str | None = None,
        order_strategy: str | None = None,
    ) -> OrderPreview:
        """AÇÃO REAL (envio de ordem) — monta e valida, NÃO envia nada à B3 ainda. Mostre o
        resumo devolvido ao usuário e só chame trading_confirm depois de um "sim" explícito
        dele nesta conversa, agora — nunca reaproveite uma confirmação de antes.

        Real action preview — validates and returns a summary + confirmation_token; does NOT
        submit anything yet. Call trading_confirm(token) only after explicit human confirmation.

        mode: limit (exige price) | market (sem price) | start/stop (exigem stop_trigger +
        stop_limit) | stop_moving (+ initial_change + moving_start) | stop_conditional (price +
        nlgs_stop_px + nlgs_stop_gain_px) | stop_oco (price + stop_limit + stop_trigger) |
        stop_simult (stop_limit + stop_trigger + target_limit + target_trigger). Para "compra
        quando o preço cair/subir pra X" (gatilho de 1 ativo), use start/stop/stop_conditional —
        é o próprio OMS da B3 que monitora o gatilho, mais robusto que qualquer alternativa.
        market: XBSP (Bovespa) ou XBMF (BM&F). side: BUY ou SELL.

        Guardrails: recusa se qty × preço passar do teto configurado; devolve `warnings` quando
        um preço está longe do último negócio — mostre os alertas ao usuário junto do resumo.
        """
        username, source_address = _trading_identity()
        if not username:
            raise CedroError(
                "Sem credencial de Trading nesta sessão — faça login em /cedro-login e "
                "preencha a seção de Trading."
            )
        extra_fields = {
            "price": price,
            "stop_trigger": stop_trigger,
            "stop_limit": stop_limit,
            "initial_change": initial_change,
            "moving_start": moving_start,
            "nlgs_stop_px": nlgs_stop_px,
            "nlgs_stop_gain_px": nlgs_stop_gain_px,
            "target_limit": target_limit,
            "target_trigger": target_trigger,
        }
        endpoint, params, clordid = build_new_order(
            mode=mode,
            market=market,
            symbol=symbol,
            side=side,
            qty=qty,
            account=account,
            username=username,
            source_address=source_address,
            extra_fields=extra_fields,
            time_in_force=time_in_force,
            validity_order=validity_order,
            order_tag=order_tag,
            order_strategy=order_strategy,
            app_name=settings.trading_app_name,
        )
        report = _guardrails(
            symbol, qty, {name: extra_fields.get(name) for name in _BAND_CHECKED_FIELDS}
        )
        summary = (
            f"{_MODE_DESCRIPTIONS[mode]} — {side} {qty} {symbol} @ {market}"
            f"{f', price={price}' if price is not None else ''}"
            f"{f', valor estimado={report.order_value:,.2f}' if report.order_value else ''}"
            f"{f', clordid={clordid}' if clordid else ' (SEM clordid — tipo Mercado)'}"
        )
        token = _create_pending("place_order", summary, params, endpoint, report.warnings)
        return {
            "summary": summary,
            "confirmation_token": token,
            "clordid": clordid,
            "reference_price": report.reference_price,
            "estimated_value": report.order_value,
            "warnings": report.warnings,
        }

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(TRADING_TRADE)
    def trading_preview_cancel_order(
        market: str,
        symbol: str,
        side: str,
        remaining_qty: Annotated[int, Field(gt=0)],
        origclordid: str,
        cancel_reason: str | None = None,
    ) -> OrderPreview:
        """AÇÃO REAL (cancelamento) — monta e valida, NÃO cancela ainda. Mostre o resumo e só
        chame trading_confirm após confirmação explícita.

        remaining_qty: quantidade RESTANTE da ordem (não a original) se ela já executou em
        parte. origclordid: o clordid retornado quando a ordem foi enviada.
        """
        username, source_address = _trading_identity()
        if not username:
            raise CedroError(
                "Sem credencial de Trading nesta sessão — faça login em /cedro-login e "
                "preencha a seção de Trading."
            )
        params = build_cancel_order(
            market=market,
            symbol=symbol,
            side=side,
            remaining_qty=remaining_qty,
            origclordid=origclordid,
            username=username,
            source_address=source_address,
            cancel_reason=cancel_reason,
        )
        summary = f"Cancelar {origclordid} — {side} {remaining_qty} {symbol} @ {market}"
        token = _create_pending("cancel_order", summary, params)
        return {"summary": summary, "confirmation_token": token}

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(TRADING_TRADE)
    def trading_preview_edit_order(
        market: str,
        symbol: str,
        side: str,
        order_type: str,
        origclordid: str,
        new_price: float,
        new_qty: int,
        account: str,
        stop_limit: float | None = None,
    ) -> OrderPreview:
        """AÇÃO REAL (edição) — monta e valida, NÃO edita ainda. Mostre o resumo e só chame
        trading_confirm após confirmação explícita.

        ⚠️ Mesmo depois de confirmado, um retorno de sucesso do OMS NÃO garante que a edição foi
        aplicada — é assíncrono. Depois de trading_confirm, reconsulte com
        trading_list_orders_today e compare qty/price, ou avise o usuário que a confirmação real
        ainda está pendente. stop_limit: obrigatório mesmo se a ordem não é stop — mande 0 (é o
        default se omitido).
        """
        username, source_address = _trading_identity()
        if not username:
            raise CedroError(
                "Sem credencial de Trading nesta sessão — faça login em /cedro-login e "
                "preencha a seção de Trading."
            )
        params = build_edit_order(
            market=market,
            symbol=symbol,
            side=side,
            order_type=order_type,
            origclordid=origclordid,
            new_price=new_price,
            new_qty=new_qty,
            account=account,
            username=username,
            source_address=source_address,
            stop_limit=stop_limit,
        )
        report = _guardrails(symbol, new_qty, {"price": new_price, "stop_limit": stop_limit})
        summary = f"Editar {origclordid} — novo price={new_price}, novo qty={new_qty}"
        token = _create_pending("edit_order", summary, params, warnings=report.warnings)
        return {
            "summary": summary,
            "confirmation_token": token,
            "reference_price": report.reference_price,
            "estimated_value": report.order_value,
            "warnings": report.warnings,
        }

    @mcp.tool(annotations=TRADE_ANNOTATIONS)
    @require_scope(TRADING_TRADE)
    def trading_confirm(confirmation_token: str) -> OrderConfirmation:
        """Executa de verdade a ordem/cancelamento/edição de um preview — SÓ chame depois que o
        usuário confirmou explicitamente, nesta conversa, o resumo exato que o preview devolveu.

        Executes for real what a trading_preview_* call prepared. Token de uso único, expira em
        poucos minutos — se expirar, refaça o preview (os dados podem ter mudado).
        """
        token_id = hash_key(confirmation_token)[:12]
        try:
            action = store.pop(confirmation_token, owner=_owner())
        except CedroError as exc:
            audit("trading_confirm_rejected", token_id=token_id, reason=str(exc))
            raise
        audit("trading_confirm", kind=action.kind, summary=action.summary, token_id=token_id)
        try:
            if action.kind == "place_order":
                assert action.endpoint is not None
                response = client.send_order(action.endpoint, action.params)
            elif action.kind == "cancel_order":
                response = client.cancel_order(action.params)
            else:
                response = client.edit_order(action.params)
        except Exception as exc:
            audit("trading_confirm_failed", token_id=token_id, error=type(exc).__name__)
            raise
        audit(
            "trading_confirm_result",
            token_id=token_id,
            accepted=response.accepted,
            code=response.code,
            message=response.message,
        )

        result: OrderConfirmation = {
            "summary": action.summary,
            "accepted": response.accepted,
            "code": response.code,
            "message": response.message,
            "messageDetails": response.messageDetails,
        }
        if action.kind == "edit_order":
            result["confirmed"] = False
            result["note"] = (
                "code de sucesso aqui confirma só que o OMS RECEBEU o pedido de edição, não "
                "que foi aplicado — a rejeição real é assíncrona. Chame "
                "trading_list_orders_today e compare qty/price antes de dizer ao usuário que "
                "a edição está feita."
            )
        return result
