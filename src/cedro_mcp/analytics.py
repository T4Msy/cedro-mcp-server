"""Cálculos sobre candles e negócios, feitos no servidor — puro, sem I/O.

Server-side analytics over candles and trades. Existe porque o modelo, recebendo 200 candles
crus, gasta contexto e erra aritmética. Aqui a conta é determinística e testada; a tool devolve
poucos números prontos.

Convenções: ``Candle.price`` é o fechamento do candle. Candles são ordenados por ``timeTrade``
(a API não garante a ordem); os sem data mantêm a ordem recebida. Indicador sem histórico
suficiente vem ``None`` — nunca um valor calculado com janela incompleta.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from .models import Candle, Trade

#: Períodos por ano, para anualizar a volatilidade. Intraday não é anualizado.
_PERIODS_PER_YEAR = {"D": 252, "1W": 52, "1M": 12, "1Y": 1}


def sort_candles(candles: Sequence[Candle]) -> list[Candle]:
    dated = [c for c in candles if c.timeTrade is not None]
    if len(dated) != len(candles):
        return list(candles)
    return sorted(candles, key=lambda c: c.timeTrade or datetime.min)


def closes(candles: Sequence[Candle]) -> list[float]:
    return [c.price for c in candles if c.price is not None]


def sma(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def ema_series(values: Sequence[float], window: int) -> list[float]:
    """EMA semeada com a SMA da primeira janela; vazia se não há histórico suficiente."""
    if window <= 0 or len(values) < window:
        return []
    k = 2 / (window + 1)
    current = sum(values[:window]) / window
    series = [current]
    for value in values[window:]:
        current = value * k + current * (1 - k)
        series.append(current)
    return series


def ema(values: Sequence[float], window: int) -> float | None:
    series = ema_series(values, window)
    return series[-1] if series else None


def rsi(values: Sequence[float], window: int = 14) -> float | None:
    """IFR de Wilder."""
    if len(values) <= window:
        return None
    deltas = [b - a for a, b in zip(values, values[1:])]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    for gain, loss in zip(gains[window:], losses[window:]):
        avg_gain = (avg_gain * (window - 1) + gain) / window
        avg_loss = (avg_loss * (window - 1) + loss) / window
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float, float, float] | None:
    """(macd, sinal, histograma) ou ``None`` sem histórico para a linha de sinal."""
    fast_series = ema_series(values, fast)
    slow_series = ema_series(values, slow)
    if not slow_series:
        return None
    # Alinha pelo fim: a série lenta começa mais tarde.
    offset = len(fast_series) - len(slow_series)
    macd_line = [f - s for f, s in zip(fast_series[offset:], slow_series)]
    signal_series = ema_series(macd_line, signal)
    if not signal_series:
        return None
    return macd_line[-1], signal_series[-1], macd_line[-1] - signal_series[-1]


def bollinger(values: Sequence[float], window: int = 20, k: float = 2.0) -> tuple[float, float, float] | None:
    """(inferior, média, superior)."""
    if len(values) < window:
        return None
    recent = values[-window:]
    mean = sum(recent) / window
    std = math.sqrt(sum((v - mean) ** 2 for v in recent) / window)
    return mean - k * std, mean, mean + k * std


def atr(candles: Sequence[Candle], window: int = 14) -> float | None:
    """Average True Range (Wilder)."""
    usable = [c for c in candles if None not in (c.high, c.low, c.price)]
    if len(usable) <= window:
        return None
    true_ranges = []
    for prev, cur in zip(usable, usable[1:]):
        assert cur.high is not None and cur.low is not None and prev.price is not None
        true_ranges.append(
            max(cur.high - cur.low, abs(cur.high - prev.price), abs(cur.low - prev.price))
        )
    value = sum(true_ranges[:window]) / window
    for tr in true_ranges[window:]:
        value = (value * (window - 1) + tr) / window
    return value


def log_returns(values: Sequence[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(values, values[1:]) if a > 0 and b > 0]


def volatility(values: Sequence[float], period: str) -> float | None:
    """Desvio padrão amostral dos log-retornos, em %; anualizado quando o período permite."""
    returns = log_returns(values)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
    return std * math.sqrt(_PERIODS_PER_YEAR.get(period, 1)) * 100


def max_drawdown(values: Sequence[float]) -> float | None:
    """Maior queda de um topo até um fundo posterior, em % (negativo)."""
    if len(values) < 2:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak)
    return worst * 100


def pct_change(first: float | None, last: float | None) -> float | None:
    if not first or last is None:
        return None
    return (last - first) / first * 100


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 3:
        return None
    a, b = a[-n:], b[-n:]
    mean_a, mean_b = sum(a) / n, sum(b) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    if var_a == 0 or var_b == 0:
        return None
    return cov / math.sqrt(var_a * var_b)


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None


# ---- relatórios -------------------------------------------------------------------------


class CandleSummary(BaseModel):
    symbol: str | None = None
    period: str
    candles: int
    first_time: datetime | None = None
    last_time: datetime | None = None
    open: float | None = None
    close: float | None = None
    high: float | None = None
    low: float | None = None
    change_pct: float | None = None
    total_volume_financier: float | None = None
    total_trades: float | None = None


def summarize_candles(candles: Sequence[Candle], period: str) -> CandleSummary:
    ordered = sort_candles(candles)
    prices = closes(ordered)
    highs = [c.high for c in ordered if c.high is not None]
    lows = [c.low for c in ordered if c.low is not None]
    first = ordered[0] if ordered else None
    volumes = [c.volumeFinancier for c in ordered if c.volumeFinancier is not None]
    trades = [c.quantityTrades for c in ordered if c.quantityTrades is not None]
    open_price = first.open if first and first.open is not None else (prices[0] if prices else None)
    return CandleSummary(
        symbol=first.symbol if first else None,
        period=period,
        candles=len(ordered),
        first_time=first.timeTrade if first else None,
        last_time=ordered[-1].timeTrade if ordered else None,
        open=open_price,
        close=prices[-1] if prices else None,
        high=max(highs) if highs else None,
        low=min(lows) if lows else None,
        change_pct=_round(pct_change(open_price, prices[-1] if prices else None), 2),
        total_volume_financier=sum(volumes) if volumes else None,
        total_trades=sum(trades) if trades else None,
    )


class IndicatorReport(BaseModel):
    symbol: str
    period: str
    candles: int
    last_close: float | None = None
    last_time: datetime | None = None
    change_pct: float | None = Field(None, description="Variação do 1º ao último fechamento (%)")
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_9: float | None = None
    ema_21: float | None = None
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    bollinger_lower: float | None = None
    bollinger_middle: float | None = None
    bollinger_upper: float | None = None
    atr_14: float | None = None
    volatility_pct: float | None = Field(
        None, description="Desvio dos log-retornos em %; anualizado para D/1W/1M/1Y"
    )
    max_drawdown_pct: float | None = None
    window_high: float | None = None
    window_low: float | None = None
    avg_volume_financier: float | None = None
    signals: list[str] = Field(default_factory=list)
    note: str = (
        "Indicadores técnicos calculados sobre os candles da Market Data. Descrevem o histórico, "
        "não são recomendação de investimento."
    )


def indicators(symbol: str, candles: Sequence[Candle], period: str) -> IndicatorReport:
    ordered = sort_candles(candles)
    prices = closes(ordered)
    highs = [c.high for c in ordered if c.high is not None]
    lows = [c.low for c in ordered if c.low is not None]
    volumes = [c.volumeFinancier for c in ordered if c.volumeFinancier is not None]
    last = prices[-1] if prices else None
    macd_values = macd(prices)
    bands = bollinger(prices)
    report = IndicatorReport(
        symbol=symbol,
        period=period,
        candles=len(ordered),
        last_close=last,
        last_time=ordered[-1].timeTrade if ordered else None,
        change_pct=_round(pct_change(prices[0] if prices else None, last), 2),
        sma_20=_round(sma(prices, 20)),
        sma_50=_round(sma(prices, 50)),
        sma_200=_round(sma(prices, 200)),
        ema_9=_round(ema(prices, 9)),
        ema_21=_round(ema(prices, 21)),
        rsi_14=_round(rsi(prices), 2),
        macd=_round(macd_values[0]) if macd_values else None,
        macd_signal=_round(macd_values[1]) if macd_values else None,
        macd_histogram=_round(macd_values[2]) if macd_values else None,
        bollinger_lower=_round(bands[0]) if bands else None,
        bollinger_middle=_round(bands[1]) if bands else None,
        bollinger_upper=_round(bands[2]) if bands else None,
        atr_14=_round(atr(ordered)),
        volatility_pct=_round(volatility(prices, period), 2),
        max_drawdown_pct=_round(max_drawdown(prices), 2),
        window_high=max(highs) if highs else None,
        window_low=min(lows) if lows else None,
        avg_volume_financier=_round(sum(volumes) / len(volumes), 2) if volumes else None,
    )
    report.signals = _signals(report)
    return report


def _signals(r: IndicatorReport) -> list[str]:
    """Leituras factuais (sem recomendação), só quando o indicador existe."""
    out: list[str] = []
    if r.last_close is not None:
        for name, value in (("SMA 50", r.sma_50), ("SMA 200", r.sma_200)):
            if value is not None:
                side = "acima" if r.last_close > value else "abaixo"
                out.append(f"Fechamento {side} da {name}.")
    if r.sma_50 is not None and r.sma_200 is not None:
        out.append("SMA 50 acima da SMA 200." if r.sma_50 > r.sma_200 else "SMA 50 abaixo da SMA 200.")
    if r.rsi_14 is not None:
        if r.rsi_14 >= 70:
            out.append("IFR(14) em zona de sobrecompra (≥ 70).")
        elif r.rsi_14 <= 30:
            out.append("IFR(14) em zona de sobrevenda (≤ 30).")
    if r.macd_histogram is not None:
        out.append("MACD acima da linha de sinal." if r.macd_histogram > 0 else "MACD abaixo da linha de sinal.")
    if r.last_close is not None and r.bollinger_upper is not None and r.bollinger_lower is not None:
        if r.last_close > r.bollinger_upper:
            out.append("Fechamento acima da banda superior de Bollinger.")
        elif r.last_close < r.bollinger_lower:
            out.append("Fechamento abaixo da banda inferior de Bollinger.")
    return out


class AssetStats(BaseModel):
    symbol: str
    candles: int
    last_close: float | None = None
    change_pct: float | None = None
    volatility_pct: float | None = None
    max_drawdown_pct: float | None = None
    avg_volume_financier: float | None = None
    error: str | None = None


class AssetComparison(BaseModel):
    period: str
    assets: list[AssetStats]
    #: Correlação dos log-retornos, por par, nos instantes em comum.
    correlations: dict[str, float | None] = Field(default_factory=dict)
    best_performer: str | None = None
    worst_performer: str | None = None
    note: str = "Comparação histórica; não é recomendação de investimento."


def _returns_by_time(candles: Sequence[Candle]) -> dict[datetime, float]:
    ordered = [c for c in sort_candles(candles) if c.timeTrade is not None and c.price]
    out: dict[datetime, float] = {}
    for prev, cur in zip(ordered, ordered[1:]):
        assert prev.price and cur.price and cur.timeTrade is not None
        out[cur.timeTrade] = math.log(cur.price / prev.price)
    return out


def compare(
    series: dict[str, Sequence[Candle]], errors: dict[str, str], period: str
) -> AssetComparison:
    stats: list[AssetStats] = []
    for symbol, candles in series.items():
        prices = closes(sort_candles(candles))
        volumes = [c.volumeFinancier for c in candles if c.volumeFinancier is not None]
        stats.append(
            AssetStats(
                symbol=symbol,
                candles=len(candles),
                last_close=prices[-1] if prices else None,
                change_pct=_round(pct_change(prices[0] if prices else None,
                                             prices[-1] if prices else None), 2),
                volatility_pct=_round(volatility(prices, period), 2),
                max_drawdown_pct=_round(max_drawdown(prices), 2),
                avg_volume_financier=_round(sum(volumes) / len(volumes), 2) if volumes else None,
            )
        )
    stats += [AssetStats(symbol=s, candles=0, error=e) for s, e in errors.items()]

    returns = {s: _returns_by_time(c) for s, c in series.items()}
    correlations: dict[str, float | None] = {}
    symbols = list(series)
    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            common = sorted(set(returns[a]) & set(returns[b]))
            correlations[f"{a}/{b}"] = _round(
                correlation([returns[a][t] for t in common], [returns[b][t] for t in common]), 3
            )

    ranked = [s for s in stats if s.change_pct is not None]
    ranked.sort(key=lambda s: s.change_pct or 0.0)
    return AssetComparison(
        period=period,
        assets=stats,
        correlations=correlations,
        best_performer=ranked[-1].symbol if ranked else None,
        worst_performer=ranked[0].symbol if ranked else None,
    )


class BrokerVolume(BaseModel):
    broker: int
    quantity: int
    volume: float


class TradesSummary(BaseModel):
    trades: int
    total_quantity: int
    total_volume: float
    vwap: float | None = None
    first_price: float | None = None
    last_price: float | None = None
    high: float | None = None
    low: float | None = None
    change_pct: float | None = None
    largest_trades: list[dict] = Field(default_factory=list)
    top_buyers: list[BrokerVolume] = Field(default_factory=list)
    top_sellers: list[BrokerVolume] = Field(default_factory=list)


def _price(trade: Trade) -> float | None:
    try:
        return float(str(trade.preco).replace(",", ".")) if trade.preco is not None else None
    except ValueError:
        return None


def summarize_trades(trades: Sequence[Trade], top: int = 5) -> TradesSummary:
    rows = [(t, _price(t), t.quantidade or 0) for t in trades]
    rows = [(t, p, q) for t, p, q in rows if p is not None]
    if any(t.date is not None for t, _, _ in rows):
        rows.sort(key=lambda r: r[0].date or 0)
    total_qty = sum(q for _, _, q in rows)
    total_vol = sum(p * q for _, p, q in rows if p is not None)
    prices = [p for _, p, _ in rows if p is not None]
    buyers: dict[int, list[float]] = defaultdict(lambda: [0, 0.0])
    sellers: dict[int, list[float]] = defaultdict(lambda: [0, 0.0])
    for t, p, q in rows:
        assert p is not None
        if t.corretoraComprando is not None:
            buyers[t.corretoraComprando][0] += q
            buyers[t.corretoraComprando][1] += p * q
        if t.corretoraVendendo is not None:
            sellers[t.corretoraVendendo][0] += q
            sellers[t.corretoraVendendo][1] += p * q

    def ranking(side: dict[int, list[float]]) -> list[BrokerVolume]:
        ordered = sorted(side.items(), key=lambda kv: kv[1][1], reverse=True)[:top]
        return [BrokerVolume(broker=b, quantity=int(v[0]), volume=round(v[1], 2)) for b, v in ordered]

    largest = sorted(rows, key=lambda r: (r[1] or 0) * r[2], reverse=True)[:top]
    return TradesSummary(
        trades=len(rows),
        total_quantity=total_qty,
        total_volume=round(total_vol, 2),
        vwap=round(total_vol / total_qty, 4) if total_qty else None,
        first_price=prices[0] if prices else None,
        last_price=prices[-1] if prices else None,
        high=max(prices) if prices else None,
        low=min(prices) if prices else None,
        change_pct=_round(pct_change(prices[0] if prices else None,
                                     prices[-1] if prices else None), 2),
        largest_trades=[
            {"price": p, "quantity": q, "buyer": t.corretoraComprando,
             "seller": t.corretoraVendendo, "date": t.date}
            for t, p, q in largest
        ],
        top_buyers=ranking(buyers),
        top_sellers=ranking(sellers),
    )
