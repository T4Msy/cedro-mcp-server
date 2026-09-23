"""SessionPool + SessionAuth sob concorrência: uma sessão e um SignIn por principal."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import respx

from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings
from cedro_mcp.credentials import RestCredentials
from cedro_mcp.session_pool import SessionPool
from cedro_mcp.sessions import SessionAuth

from .conftest import BASE_URL


def _signin_ok(_request: httpx.Request | None = None) -> httpx.Response:
    return httpx.Response(200, text="true", headers={"Set-Cookie": "JSESSIONID=abc; Path=/"})


def test_pool_creates_a_single_session_per_key_under_concurrency() -> None:
    created: list[object] = []

    def factory() -> object:
        time.sleep(0.01)  # alarga a janela de corrida
        session = object()
        created.append(session)
        return session

    pool: SessionPool[object] = SessionPool(close=lambda _: None)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: pool.get_or_create("k", factory), range(16)))
    assert len(created) == 1
    assert all(r is created[0] for r in results)


def test_pool_evicts_idle_sessions_and_closes_them() -> None:
    now = [0.0]
    closed: list[str] = []
    pool: SessionPool[str] = SessionPool(close=closed.append, idle_ttl=10, clock=lambda: now[0])
    pool.get_or_create("a", lambda: "sessao-a")
    now[0] = 11
    pool.get_or_create("b", lambda: "sessao-b")
    assert closed == ["sessao-a"]
    assert len(pool) == 1


def test_pool_evicts_least_recently_used_above_max_size() -> None:
    closed: list[str] = []
    pool: SessionPool[str] = SessionPool(close=closed.append, max_size=2)
    pool.get_or_create("a", lambda: "A")
    pool.get_or_create("b", lambda: "B")
    pool.get_or_create("a", lambda: "A2")  # "a" volta a ser a mais recente
    pool.get_or_create("c", lambda: "C")
    assert closed == ["B"]
    assert pool.get_or_create("a", lambda: "novo") == "A"


def test_pool_never_stores_the_raw_key() -> None:
    pool: SessionPool[str] = SessionPool(close=lambda _: None)
    pool.get_or_create("token-secreto", lambda: "s")
    assert "token-secreto" not in pool._entries  # noqa: SLF001


@respx.mock
def test_concurrent_ensure_does_a_single_signin() -> None:
    def slow_signin(request: httpx.Request) -> httpx.Response:
        time.sleep(0.02)
        return _signin_ok(request)

    route = respx.post(f"{BASE_URL}/SignIn").mock(side_effect=slow_signin)
    auth = SessionAuth(RestCredentials("u", "p"))
    with httpx.Client(base_url=BASE_URL) as http, ThreadPoolExecutor(max_workers=8) as executor:
        generations = set(executor.map(lambda _: auth.ensure(http), range(8)))
    assert route.call_count == 1
    assert generations == {1}


@respx.mock
def test_stale_invalidate_does_not_force_a_new_signin() -> None:
    """Thread atrasada com 401 da sessão antiga não derruba a sessão que outra já renovou."""
    route = respx.post(f"{BASE_URL}/SignIn").mock(side_effect=_signin_ok)
    auth = SessionAuth(RestCredentials("u", "p"))
    with httpx.Client(base_url=BASE_URL) as http:
        old = auth.ensure(http)
        auth.invalidate(old)
        new = auth.ensure(http)  # relogou
        auth.invalidate(old)  # 401 atrasado da geração antiga: ignorado
        assert auth.ensure(http) == new
    assert route.call_count == 2


@respx.mock
def test_concurrent_401s_trigger_a_single_relogin(settings: Settings) -> None:
    signin = respx.post(f"{BASE_URL}/SignIn").mock(side_effect=_signin_ok)
    lock = threading.Lock()
    calls = {"n": 0}

    def quote(_request: httpx.Request) -> httpx.Response:
        # As 4 primeiras chamadas pegam 401 (sessão expirada); as seguintes funcionam.
        with lock:
            calls["n"] += 1
            expired = calls["n"] <= 4
        time.sleep(0.02)
        return httpx.Response(401) if expired else httpx.Response(200, json=[])

    respx.get(f"{BASE_URL}/services/quotes/quote/PETR4").mock(side_effect=quote)
    barrier = threading.Barrier(4)

    def call(_: int) -> None:
        barrier.wait()  # as 4 threads disparam juntas, com a mesma geração de sessão
        client.get_quotes("/services/quotes/quote/PETR4")

    client = CedroClient(settings, http=httpx.Client(base_url=BASE_URL))
    # Login inicial fora da corrida, para todas partirem da mesma geração.
    session = client._registry.for_principal(None)  # noqa: SLF001
    session.auth.ensure(session.http)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(call, range(4)))
    client.close()
    # 1 login inicial + 1 relogin compartilhado pelas 4 threads que tomaram 401 juntas.
    assert signin.call_count == 2
