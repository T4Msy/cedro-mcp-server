"""Transporte HTTP: rate limit e rejeição de requisição sem token."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx

from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings
from cedro_mcp.http_app import RateLimitMiddleware, create_app
from cedro_mcp.server import build_server


class _OkApp:
    """App ASGI mínimo que sempre responde 200 (alvo do middleware)."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        self.calls += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _request(app, headers: list[tuple[bytes, bytes]] | None = None) -> int:
    """Executa um request ASGI e devolve o status."""
    scope = {"type": "http", "method": "GET", "path": "/mcp", "headers": headers or []}
    status: dict[str, int] = {}

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):  # noqa: ANN001
        if message["type"] == "http.response.start":
            status["code"] = message["status"]

    asyncio.run(app(scope, receive, send))
    return status["code"]


# ---- rate limit ------------------------------------------------------------


def test_rate_limit_blocks_after_limit_per_token() -> None:
    inner = _OkApp()
    app = RateLimitMiddleware(inner, limit=2, window=60)
    auth = [(b"authorization", b"Bearer token-a")]

    assert _request(app, auth) == 200
    assert _request(app, auth) == 200
    assert _request(app, auth) == 429  # estourou o limite
    assert inner.calls == 2  # o terceiro nem chegou no app


def test_rate_limit_buckets_are_per_token() -> None:
    """Um cliente barrado não pode derrubar o outro."""
    app = RateLimitMiddleware(_OkApp(), limit=1, window=60)
    assert _request(app, [(b"authorization", b"Bearer token-a")]) == 200
    assert _request(app, [(b"authorization", b"Bearer token-a")]) == 429
    assert _request(app, [(b"authorization", b"Bearer token-b")]) == 200


def test_rate_limit_disabled_passes_everything_through() -> None:
    inner = _OkApp()
    app = RateLimitMiddleware(inner, limit=0, window=60)
    for _ in range(5):
        assert _request(app) == 200
    assert inner.calls == 5


def test_rate_limit_window_expires(monkeypatch) -> None:  # noqa: ANN001
    import cedro_mcp.http_app as mod

    now = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    app = RateLimitMiddleware(_OkApp(), limit=1, window=10)
    auth = [(b"authorization", b"Bearer t")]

    assert _request(app, auth) == 200
    assert _request(app, auth) == 429
    now[0] += 11  # janela passou
    assert _request(app, auth) == 200


def test_rate_limit_evicts_empty_buckets_after_window(monkeypatch) -> None:  # noqa: ANN001
    """Buckets vazios não devem sobreviver pra sempre no dict (vazamento de memória)."""
    import cedro_mcp.http_app as mod

    now = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    app = RateLimitMiddleware(_OkApp(), limit=1, window=10)
    auth = [(b"authorization", b"Bearer t")]

    assert _request(app, auth) == 200
    assert len(app._hits) == 1
    now[0] += 11  # janela passou, bucket deveria esvaziar e ser removido
    assert _request(app, auth) == 200
    # Depois do request seguinte, só o bucket "fresco" (1 hit) deve existir — nunca cresce.
    assert len(app._hits) == 1


def test_rate_limit_bypass_by_rotating_tokens_is_capped_by_ip(monkeypatch) -> None:  # noqa: ANN001
    """Trocar de bearer a cada request furaria o limite por-token — o teto por IP pega isso."""
    import cedro_mcp.http_app as mod

    now = [2000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    app = RateLimitMiddleware(_OkApp(), limit=1, window=60)  # teto por IP = 1 * 5 = 5

    for i in range(5):
        headers = [(b"authorization", f"Bearer rotating-{i}".encode())]
        assert _request(app, headers) == 200  # cada token é "novo", passa no bucket por-token
    # 6ª tentativa (ainda outro token novo) deve ser barrada pelo teto agregado por IP.
    assert _request(app, [(b"authorization", b"Bearer rotating-5")]) == 429


def test_rate_limit_anonymous_clients_bucket_by_ip_not_shared() -> None:
    """Sem Authorization, agrupa por IP — um cliente anônimo não deve derrubar outro IP."""
    app = RateLimitMiddleware(_OkApp(), limit=1, window=60)
    scope_a = {"type": "http", "method": "GET", "path": "/mcp", "headers": [], "client": ("1.1.1.1", 1)}
    scope_b = {"type": "http", "method": "GET", "path": "/mcp", "headers": [], "client": ("2.2.2.2", 1)}

    async def receive():
        return {"type": "http.request", "body": b""}

    async def run(scope):
        status = {}

        async def send(message):  # noqa: ANN001
            if message["type"] == "http.response.start":
                status["code"] = message["status"]

        await app(scope, receive, send)
        return status["code"]

    assert asyncio.run(run(scope_a)) == 200
    assert asyncio.run(run(scope_a)) == 429  # mesmo IP, 2ª tentativa estourou
    assert asyncio.run(run(scope_b)) == 200  # IP diferente, bucket próprio


# ---- auth no transporte ----------------------------------------------------


def _auth_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        iam_issuer="https://sso-sandbox.cedrotech.com",
        resource_url="http://localhost:8000/mcp",
        api_keys_raw="k_read:robo:marketdata:read",
    )


def test_auth_enabled_flag(settings: Settings) -> None:
    assert not settings.auth_enabled
    assert _auth_settings(settings).auth_enabled


def _post(app, body: dict, headers: dict[str, str]) -> httpx.Response:
    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            return await ac.post("/mcp", json=body, headers=headers)

    return asyncio.run(call())


_TOOLS_LIST = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}


def test_request_without_token_is_rejected(settings: Settings, client: CedroClient) -> None:
    """Sem Authorization, o servidor não pode responder 200."""
    app = create_app(build_server(settings=_auth_settings(settings), client=client))
    assert _post(app, _TOOLS_LIST, {}).status_code == 401


def test_request_with_invalid_token_is_rejected(settings: Settings, client: CedroClient) -> None:
    app = create_app(build_server(settings=_auth_settings(settings), client=client))
    resp = _post(app, _TOOLS_LIST, {"Authorization": "Bearer nao-existe"})
    assert resp.status_code == 401


def test_dns_rebinding_protection_is_configurable(settings: Settings) -> None:
    """Servindo em 0.0.0.0 o FastMCP não liga a proteção sozinho — a config precisa ligar."""
    assert not settings.dns_rebinding_protection_enabled
    hardened = replace(settings, allowed_hosts=("mcp.cedrotech.com",))
    assert hardened.dns_rebinding_protection_enabled


# ---- ponta a ponta: entitlements pelo stack HTTP real -----------------------


def _list_tools_over_http(settings: Settings, client: CedroClient, api_key: str) -> list[str]:
    """Handshake MCP completo (initialize → tools/list) contra o app ASGI."""
    import json

    app = create_app(build_server(settings=settings, client=client))
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    async def call() -> list[str]:
        transport = httpx.ASGITransport(app=app)
        # O session manager só funciona com o lifespan do app rodando.
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://localhost:8000"
            ) as ac:
                init = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                }
                assert (await ac.post("/mcp", json=init, headers=headers)).status_code == 200
                resp = await ac.post("/mcp", json=_TOOLS_LIST, headers=headers)
                assert resp.status_code == 200
                payload = resp.text
                if resp.headers.get("content-type", "").startswith("text/event-stream"):
                    line = next(x for x in payload.splitlines() if x.startswith("data: "))
                    data = json.loads(line[6:])
                else:
                    data = resp.json()
                return [t["name"] for t in data["result"]["tools"]]

    return asyncio.run(call())


def test_readonly_key_sees_only_market_tools_over_http(
    settings: Settings, client: CedroClient
) -> None:
    names = _list_tools_over_http(_auth_settings(settings), client, "k_read")
    assert len(names) == 14
    assert not any(n.startswith("news_") for n in names)


def test_full_key_sees_all_tools_over_http(settings: Settings, client: CedroClient) -> None:
    settings = replace(
        _auth_settings(settings),
        api_keys_raw="k_full:robo:marketdata:read|marketdata:news",
    )
    names = _list_tools_over_http(settings, client, "k_full")
    assert len(names) == 17
    assert len([n for n in names if n.startswith("news_")]) == 3
