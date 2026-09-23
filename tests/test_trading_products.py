"""Guardrails do preview, resumo do dia, prompts e resource de referência de Trading."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest
import respx

from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings, load_settings
from cedro_mcp.errors import CedroError
from cedro_mcp.server import build_server
from cedro_mcp.trading.day_summary import summarize_day
from cedro_mcp.trading.guardrails import check_order

from ._tools import tool_functions
from .conftest import BASE_URL

_SIGNIN_OK = httpx.Response(200, text="true", headers={"Set-Cookie": "JSESSIONID=abc; Path=/"})
_BROKER_LOGIN_OK = httpx.Response(200, json={"isAuthenticated": "Y", "code": "0"})


def _trading_settings(settings: Settings, **overrides: float) -> Settings:
    return replace(settings, trading_user="10034", trading_password="senha-oms", **overrides)


def _fns(settings: Settings, client: CedroClient) -> dict:
    mcp = build_server(settings=settings, client=client)
    return tool_functions(mcp._tool_manager.list_tools())  # noqa: SLF001


def _mock_last_trade(price: float) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/quotes/quote/PETR4").mock(
        return_value=httpx.Response(200, json=[{"symbol": "PETR4", "lastTrade": price}])
    )


# ---- guardrails (puro) -----------------------------------------------------


def test_price_far_from_market_only_warns() -> None:
    report = check_order(
        qty=100, prices={"price": 385.0}, reference_price=38.5,
        max_order_value=0, price_band_pct=10,
    )
    assert report.order_value == 38_500.0
    assert len(report.warnings) == 1
    assert "price=385.0" in report.warnings[0]


def test_price_inside_band_has_no_warning() -> None:
    report = check_order(
        qty=100, prices={"price": 39.0, "stop_trigger": None}, reference_price=38.5,
        max_order_value=0, price_band_pct=10,
    )
    assert report.warnings == []


def test_order_above_max_value_is_refused() -> None:
    with pytest.raises(CedroError, match="teto"):
        check_order(
            qty=1_000, prices={"price": 38.5}, reference_price=38.5,
            max_order_value=10_000, price_band_pct=0,
        )


def test_market_order_uses_reference_price_for_the_ceiling() -> None:
    with pytest.raises(CedroError, match="teto"):
        check_order(
            qty=1_000, prices={}, reference_price=38.5, max_order_value=10_000, price_band_pct=0
        )


def test_ceiling_without_any_price_refuses() -> None:
    with pytest.raises(CedroError, match="não foi possível calcular"):
        check_order(qty=100, prices={}, reference_price=None, max_order_value=10_000,
                    price_band_pct=0)


def test_missing_reference_price_is_a_warning() -> None:
    report = check_order(
        qty=100, prices={"price": 38.5}, reference_price=None, max_order_value=0,
        price_band_pct=10,
    )
    assert "Sem preço de referência" in report.warnings[0]


def test_guardrail_settings_from_env() -> None:
    s = load_settings(
        {"CEDRO_TRADING_MAX_ORDER_VALUE": "50000", "CEDRO_TRADING_PRICE_BAND_PCT": "5"}
    )
    assert s.trading_max_order_value == 50_000
    assert s.trading_price_band_pct == 5
    assert load_settings({}).trading_price_band_pct == 10


# ---- guardrails nas tools --------------------------------------------------


@respx.mock
def test_preview_returns_warnings_and_reference_price(
    settings: Settings, client: CedroClient
) -> None:
    _mock_last_trade(38.5)
    fns = _fns(_trading_settings(settings), client)
    preview = fns["trading_preview_order"](
        mode="limit", market="XBSP", symbol="PETR4", side="BUY", qty=100, account="10034",
        price=385.0,
    )
    assert preview["reference_price"] == 38.5
    assert preview["estimated_value"] == 38_500.0
    assert any("longe do último negócio" in w for w in preview["warnings"])
    assert "valor estimado=38,500.00" in preview["summary"]


@respx.mock
def test_preview_above_ceiling_creates_no_token(settings: Settings, client: CedroClient) -> None:
    _mock_last_trade(38.5)
    send = respx.post(f"{BASE_URL}/services/negotiation/sendNewOrderSingleLimit")
    fns = _fns(_trading_settings(settings, trading_max_order_value=1_000.0), client)
    with pytest.raises(CedroError, match="teto"):
        fns["trading_preview_order"](
            mode="limit", market="XBSP", symbol="PETR4", side="BUY", qty=100,
            account="10034", price=38.5,
        )
    assert send.call_count == 0


@respx.mock
def test_edit_preview_also_checks_the_band(settings: Settings, client: CedroClient) -> None:
    _mock_last_trade(38.5)
    fns = _fns(_trading_settings(settings), client)
    preview = fns["trading_preview_edit_order"](
        market="XBSP", symbol="PETR4", side="BUY", order_type="Limited",
        origclordid="mcp-1", new_price=3.85, new_qty=100, account="10034",
    )
    assert preview["warnings"]


def test_preview_output_schema_is_typed(settings: Settings, client: CedroClient) -> None:
    mcp = build_server(settings=_trading_settings(settings), client=client)
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    schema = tools["trading_preview_order"].outputSchema
    assert {"summary", "confirmation_token", "warnings", "estimated_value"} <= set(
        schema["properties"]
    )
    assert set(tools["trading_confirm"].outputSchema["properties"]) >= {"accepted", "code"}


# ---- resumo do dia ---------------------------------------------------------


def _bean(**fields: object) -> dict:
    """Item de ordem no formato oficial `{code, value}`."""
    return {name: {"code": "x", "value": value} for name, value in fields.items()}


def test_day_summary_aggregates_fills_per_symbol() -> None:
    payload = {
        "listBeans": [
            _bean(quote="PETR4", side="BUY", state="Filled", quantityExecuted="100",
                  priceAverage="38.00"),
            _bean(quote="PETR4", side="BUY", state="PartiallyFilled", quantityExecuted="100",
                  priceAverage="40.00"),
            _bean(quote="PETR4", side="SELL", state="Filled", quantityExecuted="50",
                  priceAverage="41.00"),
            _bean(quote="VALE3", side="BUY", state="Rejected", quantityExecuted="0"),
            # formato achatado (algumas instalações não mandam o wrapper)
            {"quote": "VALE3", "side": "SELL", "state": "New", "quantityExecuted": 0},
        ]
    }
    summary = summarize_day(payload, account="10034", market="XBSP")
    petr, vale = summary.symbols
    assert petr.symbol == "PETR4"
    assert petr.bought_qty == 200
    assert petr.sold_qty == 50
    assert petr.net_qty == 150
    assert petr.avg_buy_price == 39.0
    assert petr.avg_sell_price == 41.0
    assert petr.open_orders == 1  # a PartiallyFilled
    assert vale.bought_qty == 0
    assert vale.open_orders == 1
    assert summary.orders_by_state == {"Filled": 2, "PartiallyFilled": 1, "Rejected": 1, "New": 1}
    assert summary.total_orders == 5
    assert "não é custódia" in summary.note


def test_day_summary_handles_empty_day() -> None:
    summary = summarize_day({"code": "0"}, account="1", market="XBSP")
    assert summary.symbols == []
    assert summary.total_orders == 0


@respx.mock
def test_day_summary_tool_calls_daily_order(settings: Settings, client: CedroClient) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    route = respx.get(f"{BASE_URL}/services/negotiation/dailyOrder/10034/XBSP").mock(
        return_value=httpx.Response(200, json={"listBeans": [_bean(
            quote="PETR4", side="BUY", state="Filled", quantityExecuted="10", priceAverage="38"
        )]})
    )
    fns = _fns(_trading_settings(settings), client)
    summary = fns["trading_get_day_summary"](account="10034", market="XBSP")
    assert route.call_count == 1
    assert summary.symbols[0].bought_value == 380.0


# ---- prompts e resource ----------------------------------------------------


def test_prompts_are_registered_and_render(settings: Settings, client: CedroClient) -> None:
    mcp = build_server(settings=settings, client=client)
    names = {p.name for p in asyncio.run(mcp.list_prompts())}
    assert names == {"analise_de_ativo", "revisar_ordens_do_dia", "preparar_ordem"}
    result = asyncio.run(mcp.get_prompt("analise_de_ativo", {"symbol": "PETR4"}))
    text = result.messages[0].content.text
    assert "md_get_quote(['PETR4'])" in text
    order = asyncio.run(mcp.get_prompt("preparar_ordem", {"pedido": "compra 100 PETR4"}))
    assert "trading_confirm" in order.messages[0].content.text


def test_trading_reference_resource_matches_validation_tables(
    settings: Settings, client: CedroClient
) -> None:
    mcp = build_server(settings=settings, client=client)
    (content,) = asyncio.run(mcp.read_resource("cedro-ref://trading"))
    text = content.content
    assert "| `stop_oco` | `Stop` | `price`, `stop_limit`, `stop_trigger` |" in text
    assert "`PartiallyFilled` — Parcialmente executada *(em aberto)*" in text
    assert "`Filled` — Completamente executada\n" in text
