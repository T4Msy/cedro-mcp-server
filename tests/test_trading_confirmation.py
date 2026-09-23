"""ConfirmationStore: token de uso único, TTL curto — o gate de segurança do envio de ordem."""

from __future__ import annotations

import time

import pytest

from cedro_mcp.errors import CedroError
from cedro_mcp.store import MemoryStore, RedisStore
from cedro_mcp.trading.confirmation import ConfirmationStore

OWNER = "sessao-do-dono"


def test_create_and_pop_returns_the_same_action() -> None:
    store = ConfirmationStore()
    token = store.create(
        "place_order",
        owner=OWNER,
        summary="BUY 100 PETR4",
        params={"quote": "PETR4"},
        endpoint="sendNewOrderSingleLimit",
    )
    action = store.pop(token, owner=OWNER)
    assert action.kind == "place_order"
    assert action.params == {"quote": "PETR4"}
    assert action.endpoint == "sendNewOrderSingleLimit"


def test_token_is_single_use() -> None:
    store = ConfirmationStore()
    token = store.create("cancel_order", owner=OWNER, summary="cancel", params={})
    store.pop(token, owner=OWNER)
    with pytest.raises(CedroError, match="inválido"):
        store.pop(token, owner=OWNER)


def test_unknown_token_raises() -> None:
    store = ConfirmationStore()
    with pytest.raises(CedroError, match="inválido"):
        store.pop("nao-existe", owner=OWNER)


def test_token_expires_after_ttl() -> None:
    store = ConfirmationStore(ttl=0.05)
    token = store.create("edit_order", owner=OWNER, summary="edit", params={})
    time.sleep(0.1)
    with pytest.raises(CedroError, match="expirado"):
        store.pop(token, owner=OWNER)


def test_creating_new_action_garbage_collects_stale_ones() -> None:
    store = ConfirmationStore(ttl=0.05)
    stale_token = store.create("place_order", owner=OWNER, summary="old", params={}, endpoint="x")
    time.sleep(0.1)
    store.create("place_order", owner=OWNER, summary="new", params={}, endpoint="y")  # triggers _gc
    with pytest.raises(CedroError):
        store.pop(stale_token, owner=OWNER)


def test_token_from_another_owner_is_rejected_and_discarded() -> None:
    """Token vazado não executa com a sessão de outro chamador — e não fica reutilizável."""
    store = ConfirmationStore()
    token = store.create("cancel_order", owner=OWNER, summary="cancel", params={})
    with pytest.raises(CedroError, match="outra sessão"):
        store.pop(token, owner="sessao-de-outro")
    with pytest.raises(CedroError, match="inválido"):
        store.pop(token, owner=OWNER)


def test_neither_owner_nor_token_are_stored_raw() -> None:
    backing = MemoryStore()
    store = ConfirmationStore(backing)
    token = store.create("cancel_order", owner=OWNER, summary="cancel", params={})
    ((key, (value, _)),) = backing._values.items()  # noqa: SLF001
    assert token not in key
    assert OWNER.encode() not in value


def test_confirmation_created_on_one_replica_is_confirmed_on_another() -> None:
    """Com Redis, preview e confirm podem cair em réplicas diferentes."""
    import fakeredis

    server = fakeredis.FakeServer()
    replica_a = ConfirmationStore(RedisStore(fakeredis.FakeRedis(server=server)))
    replica_b = ConfirmationStore(RedisStore(fakeredis.FakeRedis(server=server)))
    token = replica_a.create("cancel_order", owner=OWNER, summary="cancel", params={"q": "1"})
    assert replica_b.pop(token, owner=OWNER).params == {"q": "1"}
    with pytest.raises(CedroError, match="inválido"):
        replica_a.pop(token, owner=OWNER)  # uso único vale entre réplicas
