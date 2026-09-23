"""Tools de análise: indicadores técnicos e comparação entre ativos, calculados no servidor.

Analysis tools. Buscam os candles na Market Data REST e devolvem números prontos
(``analytics.py``) em vez de centenas de candles crus para o modelo somar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import BeforeValidator, Field

from .. import analytics
from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_READ
from ..errors import CedroError, CedroValidationError
from ..models import Candle
from ._helpers import READ_ONLY_ANNOTATIONS, as_list, parse_list
from .candles import Period

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient

#: 200 cobre a SMA 200; 1000 é o mesmo teto de md_get_candles.
IndicatorCount = Annotated[int, Field(ge=30, le=1000)]
CompareCount = Annotated[int, Field(ge=10, le=500)]
CompareSymbols = Annotated[
    list[str], BeforeValidator(as_list), Field(min_length=2, max_length=10)
]


def fetch_last_candles(client: "CedroClient", symbol: str, period: str, count: int) -> list[Candle]:
    data = client.get_quotes(f"/services/quotes/candleLast/{symbol}/{period}/{count}")
    return parse_list(data, Candle)


def register(mcp: "FastMCP", client: "CedroClient") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_indicators(
        symbol: str, period: Period = "D", count: IndicatorCount = 250
    ) -> analytics.IndicatorReport:
        """Indicadores técnicos de um ativo, calculados no servidor sobre os últimos `count`
        candles: SMA 20/50/200, EMA 9/21, IFR 14, MACD, Bollinger, ATR, volatilidade, drawdown
        máximo, máxima/mínima da janela e leituras factuais (ex.: "fechamento acima da SMA 200").

        Prefira esta tool a md_get_candles quando a pergunta é sobre tendência, força ou risco —
        não some candles na mão. Indicador sem histórico suficiente vem null.
        period: 1/3/5 (min), D, 1W, 1M, 1Y. Não é recomendação de investimento.
        """
        candles = fetch_last_candles(client, symbol, period, count)
        if not candles:
            raise CedroValidationError(f"Nenhum candle retornado para {symbol} ({period}).")
        return analytics.indicators(symbol, candles, period)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_compare_assets(
        symbols: CompareSymbols, period: Period = "D", count: CompareCount = 60
    ) -> analytics.AssetComparison:
        """Compara 2 a 10 ativos lado a lado nos últimos `count` candles: variação, volatilidade,
        drawdown máximo, volume médio, correlação entre os retornos de cada par e melhor/pior
        desempenho. Ativo que falhar aparece com `error`, sem derrubar os outros.

        Use para "PETR4 ou VALE3?", "como meus ativos andaram no mês", "esses dois andam
        juntos?". Não é recomendação de investimento.
        """
        series: dict[str, list[Candle]] = {}
        errors: dict[str, str] = {}
        for symbol in dict.fromkeys(s.strip().upper() for s in symbols if s.strip()):
            try:
                candles = fetch_last_candles(client, symbol, period, count)
            except CedroError as exc:
                errors[symbol] = str(exc)
                continue
            if candles:
                series[symbol] = candles
            else:
                errors[symbol] = "Nenhum candle retornado."
        return analytics.compare(series, errors, period)
