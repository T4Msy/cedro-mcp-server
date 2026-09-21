"""Tools de negócios realizados (Times & Trades) — Market Data REST."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_READ
from ..models import Trade
from ._helpers import READ_ONLY_ANNOTATIONS, parse_list

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient

#: yyyymmdd (8 dígitos) ou yyyymmddHHmm (12 dígitos) — os dois formatos que este endpoint aceita.
_DATE_PATTERN = r"^\d{8}(\d{4})?$"
DateStr = Annotated[str, Field(pattern=_DATE_PATTERN)]
#: Teto defensivo — a API não documenta um máximo, mas um `limit` sem teto permite pedir um
#: volume arbitrariamente grande de negócios numa única chamada.
Limit = Annotated[int, Field(gt=0, le=1000)]


def register(mcp: "FastMCP", client: "CedroClient") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_trades_range(
        symbol: str,
        indicator: int,
        limit: Limit,
        offset: int,
        start: DateStr,
        end: DateStr,
    ) -> list[Trade]:
        """Negócios realizados de um ativo entre datas (fita).

        Executed trades between dates. indicator: 1=trade, 0=any quote.
        Dates: yyyymmdd or yyyymmddHHmm.
        GET /services/quotes/quoteTimesTrade/{symbol}/{indicator}/{limit}/{offset}/{start}/{end}
        """
        path = (
            f"/services/quotes/quoteTimesTrade/{symbol}/{indicator}"
            f"/{limit}/{offset}/{start}/{end}"
        )
        data = client.get_quotes(path)
        return parse_list(data, Trade)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_trades_date(symbol: str, date: Annotated[str, Field(pattern=r"^\d{8}$")]) -> list[Trade]:
        """Negócios realizados de um ativo numa data específica (dia inteiro).

        A full day's trades for an asset.
        GET /services/quotes/quoteTimesTradeDate/{symbol}/{date}
        """
        data = client.get_quotes(f"/services/quotes/quoteTimesTradeDate/{symbol}/{date}")
        return parse_list(data, Trade)
