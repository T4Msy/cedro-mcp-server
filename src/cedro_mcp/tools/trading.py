"""Tools de Trading — envio/edição/cancelamento de ordem (AÇÃO REAL) e consulta.

Toda tool que envia dinheiro para o mercado segue **preview → confirm**: `trading_preview_order`/
`trading_preview_cancel_order`/`trading_preview_edit_order` montam e validam a ordem, nunca
chamam a B3, e devolvem um resumo + `confirmation_token`. Só `trading_confirm(token)` executa de
verdade — o token amarra o payload exato do preview, então não dá pra "confirmar" algo diferente
do que foi mostrado. Nenhuma tool de escrita aqui chama a API Cedro fora desse fluxo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from ..auth.entitlements import require_scope
from ..auth.scopes import TRADING_READ
from ..observability import read_own_audit
from ..trading.day_summary import DaySummary, summarize_day
from ..trading.order_watch import MAX_TIMEOUT, OrderWatchResult, watch_order
from ._helpers import READ_ONLY_ANNOTATIONS
from .trading_orders import register_order_tools

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient
    from ..config import Settings
    from ..credentials import CredentialProvider
    from ..trading.client import TradingClient
    from ..trading.confirmation import ConfirmationStore


def register(
    mcp: "FastMCP",
    trading_client: "TradingClient",
    confirmation_store: "ConfirmationStore",
    credential_provider: "CredentialProvider",
    settings: "Settings",
    market_data: "CedroClient",
) -> None:
    _register_read_tools(mcp, trading_client)
    register_order_tools(
        mcp, trading_client, confirmation_store, credential_provider, settings, market_data
    )


def _register_read_tools(mcp: "FastMCP", client: "TradingClient") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(TRADING_READ)
    def trading_list_orders_today(
        account: str,
        market: str,
        symbol: str | None = None,
        status: str | None = None,
        status_generic: str | None = None,
        security_type: str | None = None,
    ) -> dict:
        """Ordens enviadas HOJE para a conta/mercado (consulta, sem efeito no mercado).

        Today's orders for the account/market — read-only. Filtros opcionais por ativo/status.
        market: XBSP (Bovespa) ou XBMF (BM&F). status: New/PartiallyFilled/Filled/Canceled/
        Rejected/... (ver ENUMS.md da skill trading). Para gatilho de preço nativo (ex.: "compra
        quando cair pra X"), veja trading_preview_order com mode=stop/start — mais robusto que
        qualquer motor de gatilho customizado, porque a B3 monitora, não este servidor.
        GET /services/negotiation/dailyOrder/{conta}/{mercado}[/{ativo}/{status}/{statusGeneric}/{securityType}]
        """
        segments = [account, market]
        if symbol or status or status_generic or security_type:
            segments += [symbol or "", status or "", status_generic or "", security_type or ""]
        path = "/services/negotiation/dailyOrder/" + "/".join(segments)
        return client.daily_orders(path)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(TRADING_READ)
    def trading_get_order_history(
        account: str,
        market: str,
        start_date: str,
        end_date: str,
        symbol: str | None = None,
        status: str | None = None,
    ) -> dict:
        """Histórico de ordens entre duas datas (dias ANTERIORES — para hoje use
        trading_list_orders_today; não use para polling repetido do mesmo intervalo, isso
        derruba o endpoint em code 101).

        Order history between two dates (past days only — not for today or repeated polling).
        Datas em yyyyMMdd (ex.: 20260101).
        GET /services/negotiation/historyOrder/{conta}/{mercado}/{inicio}/{fim}
        """
        path = f"/services/negotiation/historyOrder/{account}/{market}/{start_date}/{end_date}"
        params: dict[str, str] = {}
        if symbol:
            params["symbol"] = symbol
        if status:
            params["status"] = status
        return client.history_orders(path, params=params)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(TRADING_READ)
    def trading_get_day_summary(account: str, market: str) -> DaySummary:
        """Resumo do dia por ativo: quanto foi comprado/vendido HOJE, preço médio de cada lado,
        saldo líquido do dia e ordens em aberto — calculado das ordens do dailyOrder.

        NÃO é custódia nem posição consolidada: a API de Trading não expõe posição, saldo nem
        custódia (outro produto). Deixe isso claro ao usuário se ele perguntar "quanto eu tenho".

        Day summary per symbol computed from today's orders — not a custody/position report.
        market: XBSP (Bovespa) ou XBMF (BM&F).
        GET /services/negotiation/dailyOrder/{conta}/{mercado}
        """
        payload = client.daily_orders(f"/services/negotiation/dailyOrder/{account}/{market}")
        return summarize_day(payload, account=account, market=market)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(TRADING_READ)
    def trading_get_audit(limit: Annotated[int, Field(ge=1, le=200)] = 20) -> dict[str, Any]:
        """Sua trilha de auditoria de Trading neste servidor, da mais recente para a mais antiga:
        cada preview, confirmação, resultado do OMS, falha e confirmação rejeitada, com horário
        (UTC) e o resumo da ordem. Responde "quem mandou essa ordem e quando?".

        Mostra só os SEUS eventos. Não é o extrato da corretora: ordens enviadas por outros
        canais (home broker, mesa) não aparecem — para elas use trading_list_orders_today.
        """
        events = read_own_audit(limit)
        return {"events": events, "count": len(events)}

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(TRADING_READ)
    def trading_wait_order_status(
        account: str,
        market: str,
        clordid: str,
        timeout_seconds: Annotated[float, Field(ge=0, le=MAX_TIMEOUT)] = 20,
        expect_price: float | None = None,
        expect_qty: float | None = None,
    ) -> OrderWatchResult:
        """Acompanha uma ordem por até `timeout_seconds` (máx. 60 s) até ela ficar conclusiva:
        executada, cancelada, rejeitada ou expirada — com o texto do OMS em caso de rejeição.

        Use logo depois de trading_confirm para dizer ao usuário o que REALMENTE aconteceu (o
        retorno do confirm só diz que o OMS recebeu). Depois de uma EDIÇÃO, passe `expect_price`
        e/ou `expect_qty` com os valores novos: conclui quando a ordem já os mostra (edição
        aplicada) ou quando termina. `reached=false` com a ordem aberta não é falha — ela segue
        no book. Consulta o dailyOrder a cada 2 s; não chame em loop.
        """
        path = f"/services/negotiation/dailyOrder/{account}/{market}"
        return watch_order(
            lambda: client.daily_orders(path),
            clordid,
            timeout=timeout_seconds,
            expect_price=expect_price,
            expect_qty=expect_qty,
        )
