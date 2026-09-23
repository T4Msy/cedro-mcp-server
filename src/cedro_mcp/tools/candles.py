"""Tool de candles (OHLC) — Market Data REST."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_READ
from ..analytics import CandleSummary, summarize_candles
from ..errors import CedroValidationError
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
    def md_get_candles(
        symbol: str,
        period: Period,
        mode: Literal["last", "range"] = "last",
        count: CandleCount | None = None,
        start: DateStr | None = None,
        end: DateStr | None = None,
        summary: bool = False,
    ) -> list[Candle] | CandleSummary:
        """Candles (OHLC) de um ativo — últimos N ou entre duas datas.

        mode="last" (default): últimos `count` candles. mode="range": candles entre `start` e
        `end` (yyyyMMddHHmm). period: 1/3/5 (min), D, 1W, 1M, 1Y.
        summary=True devolve só o agregado (abertura, fechamento, máxima, mínima, variação,
        volume) em vez da lista — use para períodos longos. Para tendência/risco, prefira
        md_get_indicators.
        GET /services/quotes/candleLast/{symbol}/{period}/{count}
        GET /services/quotes/candleDate/{symbol}/{period}/{start}/{end}
        """
        if mode == "last":
            if count is None:
                raise CedroValidationError("mode='last' exige `count`.")
            data = client.get_quotes(f"/services/quotes/candleLast/{symbol}/{period}/{count}")
        elif mode == "range":
            if not start or not end:
                raise CedroValidationError("mode='range' exige `start` e `end`.")
            data = client.get_quotes(
                f"/services/quotes/candleDate/{symbol}/{period}/{start}/{end}"
            )
        else:
            raise CedroValidationError(f"mode inválido: {mode!r} (use 'last' ou 'range').")
        candles = parse_list(data, Candle)
        return summarize_candles(candles, period) if summary else candles
