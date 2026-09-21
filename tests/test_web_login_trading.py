"""Seção opcional de Trading no formulário de /cedro-login."""

from __future__ import annotations

import asyncio
from urllib.parse import urlencode

import httpx
import respx
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.requests import Request as StarletteRequest

from cedro_mcp.config import Settings
from cedro_mcp.credentials import WebLoginCredentialProvider
from cedro_mcp.web_login import CedroLoginProvider

BASE_URL = "https://webfeeder.cedrotech.com"
_SIGNIN_OK = httpx.Response(200, text="true", headers={"Set-Cookie": "JSESSIONID=abc123; Path=/"})
_BROKER_LOGIN_OK = httpx.Response(200, json={"isAuthenticated": "Y", "code": "0"})


def _client_info() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="test-client",
        client_secret="secret",
        redirect_uris=[AnyUrl("http://127.0.0.1:9999/callback")],
    )


def _params() -> AuthorizationParams:
    return AuthorizationParams(
        state="xyz",
        scopes=["marketdata:read", "trading:trade"],
        code_challenge="challenge",
        redirect_uri=AnyUrl("http://127.0.0.1:9999/callback"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )


async def _submit(provider: CedroLoginProvider, form: dict) -> httpx.Response:
    body = urlencode(form).encode()
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = StarletteRequest(scope, receive)
    return await provider._handle_login_submit(request)  # noqa: SLF001


def _start_flow(provider: CedroLoginProvider) -> str:
    client = _client_info()
    asyncio.run(provider.register_client(client))
    flow_url = asyncio.run(provider.authorize(client, _params()))
    return flow_url.split("flow_id=")[1]


def test_rest_only_login_leaves_trading_out_of_the_bundle(settings: Settings) -> None:
    provider = CedroLoginProvider(settings=settings)
    flow_id = _start_flow(provider)

    async def run():
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/SignIn").mock(return_value=_SIGNIN_OK)
            return await _submit(
                provider, {"flow_id": flow_id, "login": "u", "password": "p"}
            )

    response = asyncio.run(run())
    code = response.headers["location"].split("code=")[1].split("&")[0]
    bundle = provider._pending_credentials[code]  # noqa: SLF001
    assert bundle.rest is not None
    assert bundle.trading is None


def test_both_products_verified_and_bundled(settings: Settings) -> None:
    provider = CedroLoginProvider(settings=settings)
    flow_id = _start_flow(provider)

    async def run():
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/SignIn").mock(return_value=_SIGNIN_OK)
            router.get("/services/negotiation/brokerServiceLogin").mock(
                return_value=_BROKER_LOGIN_OK
            )
            return await _submit(
                provider,
                {
                    "flow_id": flow_id,
                    "login": "u",
                    "password": "p",
                    "trading_login": "10034",
                    "trading_password": "oms-pass",
                },
            )

    response = asyncio.run(run())
    assert response.status_code == 302
    code = response.headers["location"].split("code=")[1].split("&")[0]
    bundle = provider._pending_credentials[code]  # noqa: SLF001
    assert bundle.rest is not None
    assert bundle.trading is not None
    assert bundle.trading.user == "10034"

    async def exchange():
        client = _client_info()
        auth_code = await provider.load_authorization_code(client, code)
        return await provider.exchange_authorization_code(client, auth_code)

    token = asyncio.run(exchange())
    resolved = WebLoginCredentialProvider(provider)
    from mcp.server.auth.provider import AccessToken

    principal = AccessToken(token=token.access_token, client_id="c", scopes=[])
    assert resolved.trading_credentials_for(principal).user == "10034"


def test_half_filled_trading_fields_is_rejected_before_any_http_call(settings: Settings) -> None:
    provider = CedroLoginProvider(settings=settings)
    flow_id = _start_flow(provider)

    async def run():
        with respx.mock(base_url=BASE_URL):
            # Nenhuma rota mockada de propósito — se o código chegasse a fazer qualquer
            # chamada HTTP antes da checagem de campos, o respx acusaria "not mocked".
            return await _submit(
                provider,
                {"flow_id": flow_id, "login": "u", "password": "p", "trading_login": "10034"},
            )

    response = asyncio.run(run())
    assert response.status_code == 303
    assert "Trading" in response.headers["location"]
    # o flow continua pendente — o usuário pode tentar de novo com o formulário certo.
    assert flow_id in provider._flows  # noqa: SLF001


def test_invalid_trading_credentials_rejected_with_clear_error(settings: Settings) -> None:
    provider = CedroLoginProvider(settings=settings)
    flow_id = _start_flow(provider)

    async def run():
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/SignIn").mock(return_value=_SIGNIN_OK)
            router.get("/services/negotiation/brokerServiceLogin").mock(
                return_value=httpx.Response(200, json={"isAuthenticated": "N", "code": "24"})
            )
            return await _submit(
                provider,
                {
                    "flow_id": flow_id,
                    "login": "u",
                    "password": "p",
                    "trading_login": "10034",
                    "trading_password": "senha-errada",
                },
            )

    response = asyncio.run(run())
    assert response.status_code == 303
    assert "Trading" in response.headers["location"]
    # REST já validou, mas Trading falhou — o flow segue vivo pra tentar de novo.
    assert flow_id in provider._flows  # noqa: SLF001
