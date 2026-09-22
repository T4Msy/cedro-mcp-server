"""Tool de negócios realizados (Times & Trades) — Market Data REST."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_READ
from ..errors import CedroValidationError
from ..models import Trade
from ._helpers import READ_ONLY_ANNOTATIONS, parse_list

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient

#: yyyymmdd (8 dígitos) — usado tanto por `date` (dia inteiro) quanto por `start`/`end`.
_DATE8_PATTERN = r"^\d{8}$"
Date8Str = Annotated[str, Field(pattern=_DATE8_PATTERN)]
#: yyyymmdd (8 dígitos) ou yyyymmddHHmm (12 dígitos) — os dois formatos que `start`/`end` aceitam.
_DATE_PATTERN = r"^\d{8}(\d{4})?$"
DateStr = Annotated[str, Field(pattern=_DATE_PATTERN)]
#: Teto defensivo — a API não documenta um máximo, mas um `limit` sem teto permite pedir um
#: volume arbitrariamente grande de negócios numa única chamada.
Limit = Annotated[int, Field(gt=0, le=1000)]


def register(mcp: "FastMCP", client: "CedroClient") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_trades(
        symbol: str,
        date: Date8Str | None = None,
        start: DateStr | None = None,
        end: DateStr | None = None,
        indicator: int = 1,
        limit: Limit = 1000,
        offset: int = 0,
    ) -> list[Trade]:
        """Negócios realizados de um ativo (fita) — um dia inteiro ou um período.

        Passe `date` (yyyymmdd) para o dia inteiro, ou `start`/`end` (yyyymmdd ou
        yyyymmddHHmm) para um período com paginação (`indicator`: 1=trade, 0=any quote).
        GET /services/quotes/quoteTimesTradeDate/{symbol}/{date}
        GET /services/quotes/quoteTimesTrade/{symbol}/{indicator}/{limit}/{offset}/{start}/{end}
        """
        if date is not None:
            data = client.get_quotes(f"/services/quotes/quoteTimesTradeDate/{symbol}/{date}")
        elif start and end:
            path = (
                f"/services/quotes/quoteTimesTrade/{symbol}/{indicator}"
                f"/{limit}/{offset}/{start}/{end}"
            )
            data = client.get_quotes(path)
        else:
            raise CedroValidationError("Informe `date`, ou `start` e `end`.")
        return parse_list(data, Trade)
