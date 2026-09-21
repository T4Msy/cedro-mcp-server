"""Login pelo navegador (web_login.py): página HTML, verificação real de SignIn (mockada),
emissão de código/token, e resolução de credencial de volta pro CedroClient."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest
import respx
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings
from cedro_mcp.credentials import WebLoginCredentialProvider
from cedro_mcp.http_app import create_app
from cedro_mcp.server import build_server
from cedro_mcp.web_login import CedroLoginProvider

BASE_URL = "https://webfeeder.cedrotech.com"


def _web_login_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        transport="streamable-http",
        resource_url="http://localhost:8000/mcp",
        web_login_enabled=True,
    )


def _client_info() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="test-client",
        client_secret="secret",
        redirect_uris=[AnyUrl("http://127.0.0.1:9999/callback")],
    )


def _params(**overrides: object) -> AuthorizationParams:
    base = dict(
        state="xyz",
        scopes=["marketdata:read"],
        code_challenge="challenge",
        redirect_uri=AnyUrl("http://127.0.0.1:9999/callback"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    base.update(overrides)
    return AuthorizationParams(**base)  # type: ignore[arg-type]


# ---- provider, direto (sem passar pelo round-trip HTTP de /authorize e /token) ---------


def test_authorize_returns_our_own_login_url_not_a_third_party() -> None:
    provider = CedroLoginProvider(settings=None)  # type: ignore[arg-type]
    url = asyncio.run(provider.authorize(_client_info(), _params()))
    assert url.startswith("/cedro-login?flow_id=")


def test_exchange_requires_a_real_pending_credential() -> None:
    from mcp.server.auth.provider import AuthorizationCode, TokenError

    provider = CedroLoginProvider(settings=None)  # type: ignore[arg-type]
    fake_code = AuthorizationCode(
        code="nao-existe",
        scopes=["marketdata:read"],
        expires_at=9999999999.0,
        client_id="test-client",
        code_challenge="challenge",
        redirect_uri=AnyUrl("http://127.0.0.1:9999/callback"),
        redirect_uri_provided_explicitly=True,
    )
    with pytest.raises(TokenError, match="invalid_grant"):
        asyncio.run(provider.exchange_authorization_code(_client_info(), fake_code))


def test_full_flow_issues_token_and_credential_provider_resolves_it(
    settings: Settings,
) -> None:
    """authorize() → login submit (SignIn mockado) → exchange → WebLoginCredentialProvider."""
    provider = CedroLoginProvider(settings=settings)
    client = _client_info()
    asyncio.run(provider.register_client(client))

    flow_url = asyncio.run(provider.authorize(client, _params()))
    flow_id = flow_url.split("flow_id=")[1]

    async def do_login() -> str:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/SignIn").mock(
                return_value=httpx.Response(
                    200, text="true", headers={"Set-Cookie": "JSESSIONID=abc123; Path=/"}
                )
            )
            from starlette.requests import Request as StarletteRequest

            scope = {
                "type": "http",
                "method": "POST",
                "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
            }

            async def receive():
                body = b"flow_id=%s&login=tester&password=secret" % flow_id.encode()
                return {"type": "http.request", "body": body, "more_body": False}

            starlette_request = StarletteRequest(scope, receive)
            response = await provider._handle_login_submit(starlette_request)
            return response.headers["location"]

    redirect = asyncio.run(do_login())
    assert redirect.startswith("http://127.0.0.1:9999/callback?")
    assert "code=" in redirect
    code = redirect.split("code=")[1].split("&")[0]

    auth_code = asyncio.run(provider.load_authorization_code(client, code))
    assert auth_code is not None
    token = asyncio.run(provider.exchange_authorization_code(client, auth_code))
    assert token.token_type == "Bearer"

    access_token = asyncio.run(provider.load_access_token(token.access_token))
    assert access_token is not None
    assert access_token.subject == "tester"

    cred_provider = WebLoginCredentialProvider(provider)
    creds = cred_provider.credentials_for(access_token)
    assert creds.user == "tester"
    assert creds.password == "secret"


def test_wrong_credentials_are_rejected_by_real_signin_check(settings: Settings) -> None:
    from starlette.requests import Request as StarletteRequest

    provider = CedroLoginProvider(settings=settings)
    client = _client_info()
    asyncio.run(provider.register_client(client))
    flow_url = asyncio.run(provider.authorize(client, _params()))
    flow_id = flow_url.split("flow_id=")[1]

    async def do_login() -> int:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/SignIn").mock(return_value=httpx.Response(200, text="false"))
            scope = {
                "type": "http",
                "method": "POST",
                "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
            }

            async def receive():
                body = b"flow_id=%s&login=tester&password=wrong" % flow_id.encode()
                return {"type": "http.request", "body": body, "more_body": False}

            request = StarletteRequest(scope, receive)
            response = await provider._handle_login_submit(request)
            return response.status_code

    assert asyncio.run(do_login()) == 303  # volta pro form com erro, não emite código


# ---- HTTP end-to-end: as rotas /cedro-login estão montadas no app -----------------------


def test_login_page_route_is_mounted_on_the_http_app(
    settings: Settings, client: CedroClient
) -> None:
    app = create_app(build_server(settings=_web_login_settings(settings), client=client))

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            return await ac.get("/cedro-login?flow_id=nao-existe")

    resp = asyncio.run(call())
    # flow_id desconhecido → página de "sessão expirada", não 404 (prova que a rota existe)
    assert resp.status_code == 400
    assert "expirada" in resp.text.lower()


def test_authorize_endpoint_redirects_to_our_login_page(settings: Settings) -> None:
    """GET /authorize (padrão MCP/OAuth) deve mandar o navegador pra /cedro-login, não pra
    um provedor terceiro."""
    from cedro_mcp.client import CedroClient as _Client

    dummy_client = _Client(settings)
    app = create_app(build_server(settings=_web_login_settings(settings), client=dummy_client))

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:8000", follow_redirects=False
        ) as ac:
            # Registro dinâmico primeiro (é o que um MCP client faz sozinho).
            reg = await ac.post(
                "/register",
                json={
                    "redirect_uris": ["http://127.0.0.1:9999/callback"],
                    "client_name": "test",
                },
            )
            assert reg.status_code == 201, reg.text
            client_id = reg.json()["client_id"]
            return await ac.get(
                "/authorize",
                params={
                    "client_id": client_id,
                    "response_type": "code",
                    "redirect_uri": "http://127.0.0.1:9999/callback",
                    "code_challenge": "abc",
                    "code_challenge_method": "S256",
                },
            )

    resp = asyncio.run(call())
    dummy_client.close()
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/cedro-login?flow_id=")
