"""Testes de autenticação: sessão JSESSIONID, reauth em 401 e token de notícias."""

from __future__ import annotations

import httpx
import pytest
import respx

from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings
from cedro_mcp.errors import CedroAuthError

BASE_URL = "https://webfeeder.cedrotech.com"

_SIGNIN_OK = httpx.Response(
    200, text="true", headers={"Set-Cookie": "JSESSIONID=abc123; Path=/"}
)


@respx.mock
def test_signin_establishes_session(client: CedroClient) -> None:
    signin = respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    quote = respx.get(f"{BASE_URL}/services/quotes/quote/PETR4").mock(
        return_value=httpx.Response(200, json=[{"symbol": "PETR4"}])
    )

    result = client.get_quotes("/services/quotes/quote/PETR4")

    assert signin.call_count == 1
    assert quote.call_count == 1
    assert result == [{"symbol": "PETR4"}]


@respx.mock
def test_session_reused_across_calls(client: CedroClient) -> None:
    signin = respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/quotes/listMarket").mock(
        return_value=httpx.Response(200, json=[])
    )

    client.get_quotes("/services/quotes/listMarket")
    client.get_quotes("/services/quotes/listMarket")

    # SignIn só uma vez: a sessão é reaproveitada.
    assert signin.call_count == 1


@respx.mock
def test_reauth_once_on_401(client: CedroClient) -> None:
    signin = respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    quote = respx.get(f"{BASE_URL}/services/quotes/quote/PETR4").mock(
        side_effect=[
            httpx.Response(401),
            httpx.Response(200, json=[{"symbol": "PETR4"}]),
        ]
    )

    result = client.get_quotes("/services/quotes/quote/PETR4")

    assert signin.call_count == 2  # inicial + reautenticação
    assert quote.call_count == 2
    assert result == [{"symbol": "PETR4"}]


@respx.mock
def test_missing_rest_credentials_raises() -> None:
    settings = Settings(
        base_url=BASE_URL,
        user=None,
        password=None,
        news_client_id=None,
        news_client_secret=None,
        docs_path=__import__("pathlib").Path("."),
        http_timeout=5.0,
    )
    cedro = CedroClient(settings, http=httpx.Client(base_url=BASE_URL))
    with pytest.raises(CedroAuthError):
        cedro.get_quotes("/services/quotes/listMarket")
    cedro.close()


@respx.mock
def test_news_token_cached(client: CedroClient) -> None:
    token = respx.post(f"{BASE_URL}/connect/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 3600, "token_type": "Bearer"}
        )
    )
    news = respx.get(f"{BASE_URL}/services/news/newsLast/5").mock(
        return_value=httpx.Response(200, json=[])
    )

    client.get_news("/services/news/newsLast/5")
    client.get_news("/services/news/newsLast/5")

    assert token.call_count == 1  # token reaproveitado
    assert news.call_count == 2
    assert news.calls[0].request.headers["Authorization"] == "Bearer tok"
