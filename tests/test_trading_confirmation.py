"""ConfirmationStore: token de uso único, TTL curto — o gate de segurança do envio de ordem."""

from __future__ import annotations

import time

import pytest

from cedro_mcp.errors import CedroError
from cedro_mcp.trading.confirmation import ConfirmationStore


def test_create_and_pop_returns_the_same_action() -> None:
    store = ConfirmationStore()
    token = store.create(
        "place_order", summary="BUY 100 PETR4", params={"quote": "PETR4"}, endpoint="sendNewOrderSingleLimit"
    )
    action = store.pop(token)
    assert action.kind == "place_order"
    assert action.params == {"quote": "PETR4"}
    assert action.endpoint == "sendNewOrderSingleLimit"


def test_token_is_single_use() -> None:
    store = ConfirmationStore()
    token = store.create("cancel_order", summary="cancel", params={})
    store.pop(token)
    with pytest.raises(CedroError, match="inválido"):
        store.pop(token)


def test_unknown_token_raises() -> None:
    store = ConfirmationStore()
    with pytest.raises(CedroError, match="inválido"):
        store.pop("nao-existe")


def test_token_expires_after_ttl() -> None:
    store = ConfirmationStore(ttl=0.05)
    token = store.create("edit_order", summary="edit", params={})
    time.sleep(0.1)
    with pytest.raises(CedroError, match="expirado"):
        store.pop(token)


def test_creating_new_action_garbage_collects_stale_ones() -> None:
    store = ConfirmationStore(ttl=0.05)
    stale_token = store.create("place_order", summary="old", params={}, endpoint="x")
    time.sleep(0.1)
    store.create("place_order", summary="new", params={}, endpoint="y")  # triggers _gc
    with pytest.raises(CedroError):
        store.pop(stale_token)
