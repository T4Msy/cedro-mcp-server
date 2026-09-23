"""Tools de Trading — envio/edição/cancelamento de ordem (AÇÃO REAL) e consulta.

Toda tool que envia dinheiro para o mercado segue **preview → confirm**: `trading_preview_order`/
`trading_preview_cancel_order`/`trading_preview_edit_order` montam e validam a ordem, nunca
chamam a B3, e devolvem um resumo + `confirmation_token`. Só `trading_confirm(token)` executa de
verdade — o token amarra o payload exato do preview, então não dá pra "confirmar" algo diferente
do que foi mostrado. Nenhuma tool de escrita aqui chama a API Cedro fora desse fluxo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..auth.entitlements import require_scope
from ..auth.scopes import TRADING_READ
from ..trading.day_summary import DaySummary, summarize_day
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
