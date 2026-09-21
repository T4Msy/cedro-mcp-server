"""Tools de candles (OHLC) — Market Data REST."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_READ
from ..models import Candle
from ._helpers import READ_ONLY_ANNOTATIONS, parse_list

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient

#: Períodos aceitos por candleLast/candleDate (ver notas de candles) — validados via Literal
#: no schema da tool, não apenas documentados em texto.
Period = Literal["1", "3", "5", "D", "1W", "1M", "1Y"]

#: yyyyMMddHHmm — 12 dígitos, formato exigido por candleDate.
_DATE_PATTERN = r"^\d{12}$"
DateStr = Annotated[str, Field(pattern=_DATE_PATTERN)]

#: A API não documenta um teto pra `qtdeCandles` — sem um, um `count` gigante vira uma resposta
#: gigante e uma chamada upstream cara. Mesmo padrão defensivo de `Count`/`Limit` em outras tools.
CandleCount = Annotated[int, Field(gt=0, le=1000)]


def register(mcp: "FastMCP", client: "CedroClient") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_candles_last(symbol: str, period: Period, count: CandleCount) -> list[Candle]:
        """Últimos N candles de um ativo.

        Last N candles of an asset. period: 1/3/5 (min), D, 1W, 1M, 1Y.
        GET /services/quotes/candleLast/{symbol}/{period}/{count}
        """
        data = client.get_quotes(f"/services/quotes/candleLast/{symbol}/{period}/{count}")
        return parse_list(data, Candle)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_candles_range(
        symbol: str, period: Period, start: DateStr, end: DateStr
    ) -> list[Candle]:
        """Candles de um ativo entre duas datas (formato yyyyMMddHHmm).

        Candles between two dates (yyyyMMddHHmm).
        GET /services/quotes/candleDate/{symbol}/{period}/{start}/{end}
        """
        data = client.get_quotes(
            f"/services/quotes/candleDate/{symbol}/{period}/{start}/{end}"
        )
        return parse_list(data, Candle)
