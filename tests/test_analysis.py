"""Análises no servidor (indicadores, comparação, resumos) e acompanhamento de ordem."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import httpx
import pytest
import respx

from cedro_mcp import analytics
from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings
from cedro_mcp.models import Candle, Trade
from cedro_mcp.server import build_server
from cedro_mcp.trading.order_watch import watch_order

from ._tools import tool_functions
from .conftest import BASE_URL

_SIGNIN_OK = httpx.Response(200, text="true", headers={"Set-Cookie": "JSESSIONID=a; Path=/"})


def _candles(prices: list[float], symbol: str = "PETR4", start: datetime | None = None) -> list[Candle]:
    start = start or datetime(2026, 1, 1)
    return [
        Candle(symbol=symbol, price=p, open=p, high=p * 1.01, low=p * 0.99,
               volumeFinancier=1000.0, timeTrade=start + timedelta(days=i))
        for i, p in enumerate(prices)
    ]


def _raw(prices: list[float], symbol: str = "PETR4") -> list[dict]:
    """Formato da API: timeTrade yyyyMMddHHmm numérico, mais recente PRIMEIRO."""
    base = datetime(2026, 1, 1)
    rows = [
        {"symbol": symbol, "price": p, "open": p, "high": p + 1, "low": p - 1,
         "volumeFinancier": 1000.0,
         "timeTrade": int((base + timedelta(days=i)).strftime("%Y%m%d%H%M"))}
        for i, p in enumerate(prices)
    ]
    return list(reversed(rows))


# ---- funções puras ---------------------------------------------------------


def test_moving_averages() -> None:
    values = [float(v) for v in range(1, 11)]
    assert analytics.sma(values, 5) == 8.0
    assert analytics.sma(values, 20) is None  # nunca janela incompleta
    assert analytics.ema([2.0] * 30, 9) == pytest.approx(2.0)
    assert analytics.ema(values, 3) == pytest.approx(9.0)


def test_rsi_extremes() -> None:
    assert analytics.rsi([float(v) for v in range(30)]) == 100.0
    assert analytics.rsi([float(v) for v in range(30, 0, -1)]) == pytest.approx(0.0)
    assert analytics.rsi([5.0] * 30) == 50.0
    assert analytics.rsi([1.0, 2.0]) is None


def test_rsi_wilder_reference_value() -> None:
    # Série clássica do exemplo de IFR de Wilder, com os preços arredondados a 2 casas:
    # ganho médio 3,34/14 e perda média 1,40/14 → RS 2,3857 → IFR 70,46. (A referência publica
    # 70,53 porque usa os preços com mais casas decimais.)
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89,
              46.03, 45.61, 46.28, 46.28]
    assert analytics.rsi(closes) == pytest.approx(100 - 100 / (1 + 3.34 / 1.40), abs=1e-9)


def test_macd_needs_enough_history() -> None:
    assert analytics.macd([1.0] * 30) is None
    line, signal, hist = analytics.macd([float(v) for v in range(60)])
    assert line > 0 and hist == pytest.approx(line - signal)


def test_volatility_drawdown_and_correlation() -> None:
    assert analytics.volatility([10.0] * 10, "D") == 0.0
    assert analytics.max_drawdown([100.0, 120.0, 90.0, 130.0]) == pytest.approx(-25.0)
    a = [0.01, -0.02, 0.03, 0.01]
    assert analytics.correlation(a, a) == pytest.approx(1.0)
    assert analytics.correlation(a, [-x for x in a]) == pytest.approx(-1.0)
    assert analytics.correlation([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_indicator_report_and_factual_signals() -> None:
    prices = [10.0 + i * 0.1 for i in range(250)]  # tendência de alta constante
    report = analytics.indicators("PETR4", _candles(prices), "D")
    assert report.candles == 250
    assert report.last_close == pytest.approx(prices[-1])
    assert report.sma_200 is not None and report.sma_200 < report.last_close
    assert report.rsi_14 == 100.0
    assert "Fechamento acima da SMA 200." in report.signals
    assert "SMA 50 acima da SMA 200." in report.signals
    assert any("sobrecompra" in s for s in report.signals)


def test_short_history_leaves_long_indicators_null() -> None:
    report = analytics.indicators("PETR4", _candles([10.0 + i for i in range(40)]), "D")
    assert report.sma_20 is not None
    assert report.sma_50 is None and report.sma_200 is None


def test_candles_are_sorted_by_time_even_if_api_sends_newest_first() -> None:
    candles = list(reversed(_candles([1.0, 2.0, 3.0])))
    summary = analytics.summarize_candles(candles, "D")
    assert summary.open == 1.0 and summary.close == 3.0
    assert summary.change_pct == 200.0


def test_compare_ranks_and_correlates() -> None:
    up = [10.0 * (1.01 ** i) for i in range(30)]
    down = [10.0 * (0.99 ** i) for i in range(30)]
    result = analytics.compare(
        {"UP3": _candles(up, "UP3"), "DOWN3": _candles(down, "DOWN3")},
        {"ERR3": "HTTP 404"},
        "D",
    )
    assert result.best_performer == "UP3"
    assert result.worst_performer == "DOWN3"
    assert [a.symbol for a in result.assets] == ["UP3", "DOWN3", "ERR3"]
    assert result.assets[2].error == "HTTP 404"
    assert "UP3/DOWN3" in result.correlations


def test_trades_summary() -> None:
    trades = [
        Trade(preco="10.00", quantidade=100, corretoraComprando=1, corretoraVendendo=2, date=1),
        Trade(preco="12.00", quantidade=300, corretoraComprando=3, corretoraVendendo=2, date=2),
        Trade(preco="11,00", quantidade=100, corretoraComprando=1, corretoraVendendo=4, date=3),
    ]
    s = analytics.summarize_trades(trades)
    assert s.trades == 3
    assert s.total_quantity == 500
    assert s.total_volume == 5700.0
    assert s.vwap == pytest.approx(11.4)
    assert (s.first_price, s.last_price, s.high, s.low) == (10.0, 11.0, 12.0, 10.0)
    assert s.top_buyers[0].broker == 3
    assert s.top_sellers[0].broker == 2 and s.top_sellers[0].quantity == 400
    assert s.largest_trades[0]["price"] == 12.0


# ---- tools -----------------------------------------------------------------


def _fns(settings: Settings, client: CedroClient) -> dict:
    return tool_functions(build_server(settings=settings, client=client)._tool_manager.list_tools())  # noqa: SLF001


@respx.mock
def test_md_get_indicators_tool(settings: Settings, client: CedroClient) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    prices = [20.0 + math.sin(i / 5) for i in range(250)]
    route = respx.get(f"{BASE_URL}/services/quotes/candleLast/PETR4/D/250").mock(
        return_value=httpx.Response(200, json=_raw(prices))
    )
    report = _fns(settings, client)["md_get_indicators"](symbol="PETR4")
    assert route.call_count == 1
    assert report.last_close == pytest.approx(prices[-1])
    assert report.sma_200 is not None and report.macd is not None


@respx.mock
def test_md_compare_assets_tool_isolates_failures(settings: Settings, client: CedroClient) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/quotes/candleLast/PETR4/D/60").mock(
        return_value=httpx.Response(200, json=_raw([10.0 + i for i in range(60)]))
    )
    respx.get(f"{BASE_URL}/services/quotes/candleLast/VALE3/D/60").mock(
        return_value=httpx.Response(200, json=_raw([50.0 - i * 0.1 for i in range(60)], "VALE3"))
    )
    respx.get(f"{BASE_URL}/services/quotes/candleLast/XXXX9/D/60").mock(
        return_value=httpx.Response(404)
    )
    result = _fns(settings, client)["md_compare_assets"](symbols=["petr4", "VALE3", "XXXX9"])
    assert result.best_performer == "PETR4"
    assert {a.symbol: a.error is not None for a in result.assets} == {
        "PETR4": False, "VALE3": False, "XXXX9": True
    }
    assert result.correlations["PETR4/VALE3"] is not None


@respx.mock
def test_summary_modes(settings: Settings, client: CedroClient) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/quotes/candleLast/PETR4/D/3").mock(
        return_value=httpx.Response(200, json=_raw([1.0, 2.0, 3.0]))
    )
    respx.get(f"{BASE_URL}/services/quotes/quoteTimesTradeDate/PETR4/20260707").mock(
        return_value=httpx.Response(200, json=[
            {"preco": "38.50", "quantidade": 100, "corretoraComprando": 3,
             "corretoraVendendo": 90, "date": 1},
        ])
    )
    fns = _fns(settings, client)
    candle_summary = fns["md_get_candles"](symbol="PETR4", period="D", count=3, summary=True)
    assert candle_summary.close == 3.0 and candle_summary.candles == 3
    trades_summary = fns["md_get_trades"](symbol="PETR4", date="20260707", summary=True)
    assert trades_summary.total_quantity == 100
    assert isinstance(fns["md_get_candles"](symbol="PETR4", period="D", count=3), list)


# ---- trading_wait_order_status ---------------------------------------------


def _bean(state: str, price: str = "38.5", qty: str = "100", **extra: str) -> dict:
    fields = {"clOrdID": "mcp-1", "state": state, "price": price, "quantitySupplied": qty, **extra}
    return {"listBeans": [{k: {"code": "x", "value": v} for k, v in fields.items()}]}


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _watch(responses: list[dict], **kwargs: object):  # noqa: ANN202
    clock = _Clock()
    it = iter(responses)
    last: list[dict] = [{}]

    def fetch() -> dict:
        last[0] = next(it, last[0])
        return last[0]

    result = watch_order(fetch, "mcp-1", sleep=clock.sleep, clock=clock.time, **kwargs)  # type: ignore[arg-type]
    return result, clock


def test_watch_stops_at_final_state() -> None:
    result, clock = _watch(
        [_bean("New"), _bean("PartiallyFilled"), _bean("Filled", quantityExecuted="100")],
        timeout=30,
    )
    assert result.reached and result.state == "Filled" and result.checks == 3
    assert result.quantity_executed == 100
    assert clock.now == 4.0  # 2 intervalos de 2 s


def test_watch_times_out_without_calling_it_failure() -> None:
    result, _ = _watch([_bean("New")], timeout=5)
    assert not result.reached and result.is_open
    assert "não é falha" in result.note
    assert result.checks <= 3


def test_watch_detects_applied_edit() -> None:
    result, _ = _watch(
        [_bean("Replaced", price="38.5"), _bean("Replaced", price="39.0")],
        timeout=30, expect_price=39.0,
    )
    assert result.reached and result.price == 39.0 and "Edição aplicada" in result.note


def test_watch_reports_rejection_text_and_missing_order() -> None:
    rejected, _ = _watch([_bean("Rejected", text="Sem saldo")], timeout=10)
    assert rejected.reached and rejected.oms_text == "Sem saldo"
    missing, _ = _watch([{"listBeans": []}], timeout=0)
    assert not missing.found and "não encontrada" in missing.note


def test_watch_caps_timeout_and_interval() -> None:
    result, clock = _watch([_bean("New")], timeout=10_000, interval=0.01)
    assert clock.now <= 60 and result.checks <= 31
