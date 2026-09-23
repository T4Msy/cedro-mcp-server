"""Refresh token rotativo do login pelo navegador e trilha de auditoria persistente."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import fakeredis
import httpx
import pytest
import respx
from mcp.server.auth.provider import TokenError

from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings
from cedro_mcp.credentials import WebLoginCredentialProvider
from cedro_mcp.observability import audit, configure_audit, read_own_audit
from cedro_mcp.server import build_server
from cedro_mcp.store import MemoryStore, RedisStore, SecretBox
from cedro_mcp.web_login import CedroLoginProvider

from ._principal import as_principal
from ._tools import tool_functions
from .conftest import BASE_URL
from .test_infra import _login
from .test_web_login import _client_info, _params


def _logged_in(provider: CedroLoginProvider):  # noqa: ANN202
    client = _client_info()
    asyncio.run(provider.register_client(client))
    flow_id = asyncio.run(provider.authorize(client, _params())).split("flow_id=")[1]
    code = _login(provider, flow_id)
    auth_code = asyncio.run(provider.load_authorization_code(client, code))
    return client, asyncio.run(provider.exchange_authorization_code(client, auth_code))


# ---- refresh token ---------------------------------------------------------


def test_login_issues_a_refresh_token(settings: Settings) -> None:
    _, tokens = _logged_in(CedroLoginProvider(settings))
    assert tokens.refresh_token
    assert tokens.expires_in == 7 * 24 * 3600


def test_refresh_rotates_and_keeps_the_credentials(settings: Settings) -> None:
    provider = CedroLoginProvider(settings)
    client, first = _logged_in(provider)

    refresh = asyncio.run(provider.load_refresh_token(client, first.refresh_token))
    assert refresh is not None and refresh.scopes == ["marketdata:read"]
    second = asyncio.run(provider.exchange_refresh_token(client, refresh, refresh.scopes))

    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token
    # O access antigo morreu junto com o refresh usado.
    assert asyncio.run(provider.load_access_token(first.access_token)) is None
    access = asyncio.run(provider.load_access_token(second.access_token))
    assert access is not None and access.subject == "tester"
    assert WebLoginCredentialProvider(provider).rest_credentials_for(access).password == (
        "senha-rest"
    )
    # Refresh é de uso único.
    assert asyncio.run(provider.load_refresh_token(client, first.refresh_token)) is None
    with pytest.raises(TokenError):
        asyncio.run(provider.exchange_refresh_token(client, refresh, refresh.scopes))


def test_refresh_token_is_bound_to_its_client(settings: Settings) -> None:
    from mcp.shared.auth import OAuthClientInformationFull
    from pydantic import AnyUrl

    provider = CedroLoginProvider(settings)
    _, tokens = _logged_in(provider)
    other = OAuthClientInformationFull(
        client_id="outro", redirect_uris=[AnyUrl("http://127.0.0.1:1/cb")]
    )
    assert asyncio.run(provider.load_refresh_token(other, tokens.refresh_token)) is None


def test_refresh_survives_restart_with_redis_and_can_be_revoked(settings: Settings) -> None:
    server = fakeredis.FakeServer()
    box = SecretBox("segredo")

    def replica() -> CedroLoginProvider:
        return CedroLoginProvider(
            settings, store=RedisStore(fakeredis.FakeRedis(server=server)), box=box
        )

    client, tokens = _logged_in(replica())
    restarted = replica()
    refresh = asyncio.run(restarted.load_refresh_token(client, tokens.refresh_token))
    assert refresh is not None
    asyncio.run(restarted.revoke_token(refresh))
    assert asyncio.run(replica().load_refresh_token(client, tokens.refresh_token)) is None


# ---- auditoria -------------------------------------------------------------


@pytest.fixture
def audit_store():  # noqa: ANN201
    store = MemoryStore()
    configure_audit(store)
    yield store
    configure_audit(None)


def test_audit_events_are_stored_per_identity(audit_store: MemoryStore) -> None:
    with as_principal("trading:read", subject="ana"):
        audit("trading_preview", kind="place_order", summary="BUY 100 PETR4")
        audit("trading_confirm", kind="place_order", summary="BUY 100 PETR4")
    with as_principal("trading:read", subject="bruno"):
        audit("trading_preview", kind="cancel_order", summary="Cancelar X")
        mine = read_own_audit(10)
    assert [e["event"] for e in mine] == ["trading_preview"]
    assert mine[0]["summary"] == "Cancelar X"
    with as_principal("trading:read", subject="ana"):
        ana = read_own_audit(10)
    assert [e["event"] for e in ana] == ["trading_confirm", "trading_preview"]  # recente primeiro
    assert len(audit_store.read_log("audit:all", 10)) == 3
    assert "test-token" not in str(ana)


def test_audit_log_is_capped() -> None:
    store = MemoryStore()
    for i in range(5):
        store.append_log("k", str(i).encode(), maxlen=3)
    assert store.read_log("k", 10) == [b"4", b"3", b"2"]


def test_audit_log_on_redis_streams() -> None:
    store = RedisStore(fakeredis.FakeRedis())
    for i in range(5):
        store.append_log("k", str(i).encode(), maxlen=3)
    assert store.read_log("k", 2) == [b"4", b"3"]


def test_audit_store_failure_does_not_break_the_operation(caplog: pytest.LogCaptureFixture) -> None:
    class _Broken(MemoryStore):
        def append_log(self, key: str, entry: bytes, maxlen: int) -> None:
            raise ConnectionError("redis fora")

    configure_audit(_Broken())
    try:
        audit("trading_confirm", kind="place_order")  # não levanta
    finally:
        configure_audit(None)
    assert "audit_store_failed" in caplog.text


@respx.mock
def test_trading_get_audit_tool_after_preview(settings: Settings, client: CedroClient) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(
        return_value=httpx.Response(200, text="true", headers={"Set-Cookie": "JSESSIONID=a"})
    )
    mcp = build_server(
        settings=replace(settings, trading_user="10034", trading_password="senha-oms",
                         trading_price_band_pct=0),
        client=client,
    )
    fns = tool_functions(mcp._tool_manager.list_tools())  # noqa: SLF001
    try:
        with as_principal("marketdata:read", "trading:trade", "trading:read", subject="ana"):
            fns["trading_preview_order"](
                mode="limit", market="XBSP", symbol="PETR4", side="BUY", qty=100,
                account="10034", price=38.5,
            )
            result = fns["trading_get_audit"](limit=5)
    finally:
        configure_audit(None)
    assert result["count"] == 1
    assert result["events"][0]["event"] == "trading_preview"
    assert "PETR4" in result["events"][0]["summary"]
