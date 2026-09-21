"""build_new_order/build_cancel_order/build_edit_order: validação por modo, sem I/O."""

from __future__ import annotations

import pytest

from cedro_mcp.errors import CedroError
from cedro_mcp.trading.orders import build_cancel_order, build_edit_order, build_new_order


def _common(**overrides):
    base = dict(
        market="XBSP",
        symbol="PETR4",
        side="BUY",
        qty=100,
        account="10034",
        username="10034",
        source_address="203.0.113.7",
        extra_fields={},
    )
    base.update(overrides)
    return base


def test_limit_requires_price() -> None:
    with pytest.raises(CedroError, match="price"):
        build_new_order(mode="limit", **_common())


def test_limit_builds_with_price() -> None:
    endpoint, params, clordid = build_new_order(
        mode="limit", **_common(extra_fields={"price": 38.5})
    )
    assert endpoint == "sendNewOrderSingleLimit"
    assert params["price"] == "38.5"
    assert params["type"] == "Limited"
    assert clordid is not None
    assert params["clordid"] == clordid


def test_market_never_gets_clordid() -> None:
    endpoint, params, clordid = build_new_order(mode="market", **_common())
    assert endpoint == "sendNewOrderSingleMarket"
    assert clordid is None
    assert "clordid" not in params
    assert "price" not in params


def test_stop_requires_trigger_and_limit() -> None:
    with pytest.raises(CedroError, match="stop_trigger"):
        build_new_order(mode="stop", **_common())
    with pytest.raises(CedroError, match="stop_limit"):
        build_new_order(mode="stop", **_common(extra_fields={"stop_trigger": 30.0}))


def test_stop_builds_with_both_fields() -> None:
    endpoint, params, clordid = build_new_order(
        mode="stop", **_common(extra_fields={"stop_trigger": 30.0, "stop_limit": 29.5})
    )
    assert endpoint == "sendNewOrderSingleStop"
    assert params["stoptrigger"] == "30.0"
    assert params["stoplimit"] == "29.5"
    assert params["type"] == "Stop"
    assert clordid is not None


def test_stop_moving_requires_all_four_fields() -> None:
    with pytest.raises(CedroError, match="initial_change"):
        build_new_order(
            mode="stop_moving",
            **_common(extra_fields={"stop_trigger": 30.0, "stop_limit": 29.5}),
        )


def test_stop_conditional_requires_its_own_fields() -> None:
    endpoint, params, _ = build_new_order(
        mode="stop_conditional",
        **_common(
            extra_fields={"price": 30.0, "nlgs_stop_px": 0.5, "nlgs_stop_gain_px": 0.5}
        ),
    )
    assert endpoint == "sendNewOrderSingleStopConditional"
    assert params["nlgsstoppx"] == "0.5"
    assert params["nlgsstopgainpx"] == "0.5"


def test_unknown_mode_raises() -> None:
    with pytest.raises(CedroError, match="Modo de ordem desconhecido"):
        build_new_order(mode="bogus", **_common())


def test_cancel_order_uses_remaining_quantity() -> None:
    params = build_cancel_order(
        market="XBSP",
        symbol="PETR4",
        side="BUY",
        remaining_qty=50,
        origclordid="mcp-1",
        username="10034",
        source_address="203.0.113.7",
    )
    assert params["qtd"] == "50"
    assert params["origclordid"] == "mcp-1"


def test_edit_order_defaults_stoplimit_to_zero() -> None:
    params = build_edit_order(
        market="XBSP",
        symbol="PETR4",
        side="BUY",
        order_type="Limited",
        origclordid="mcp-1",
        new_price=39.0,
        new_qty=100,
        account="10034",
        username="10034",
        source_address="203.0.113.7",
    )
    assert params["stoplimit"] == "0"


def test_edit_order_keeps_explicit_stoplimit() -> None:
    params = build_edit_order(
        market="XBSP",
        symbol="PETR4",
        side="BUY",
        order_type="Stop",
        origclordid="mcp-1",
        new_price=39.0,
        new_qty=100,
        account="10034",
        username="10034",
        source_address="203.0.113.7",
        stop_limit=38.5,
    )
    assert params["stoplimit"] == "38.5"
