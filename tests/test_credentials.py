"""CedroCredentialBundle e os providers: cada produto (REST/Socket/Trading) é independente."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from mcp.server.auth.provider import AccessToken

from cedro_mcp.credentials import (
    CedroCredentialBundle,
    RestCredentials,
    ServiceAccountCredentialProvider,
    SocketCredentials,
    TradingCredentials,
    WebLoginCredentialProvider,
)
from cedro_mcp.config import Settings
from cedro_mcp.errors import CedroAuthError


def _token(value: str = "tok") -> AccessToken:
    return AccessToken(token=value, client_id="test-client", scopes=["marketdata:read"])


@dataclass
class _FakeLoginProvider:
    """Só o que WebLoginCredentialProvider precisa: resolver token→bundle."""

    credentials_by_token: dict[str, CedroCredentialBundle] = field(default_factory=dict)

    def credentials_for_token(self, token: str) -> CedroCredentialBundle | None:
        return self.credentials_by_token.get(token)


def test_bundle_defaults_to_no_product() -> None:
    bundle = CedroCredentialBundle()
    assert bundle.rest is None
    assert bundle.socket is None
    assert bundle.trading is None


def test_service_account_provider_resolves_all_three_from_settings(settings: Settings) -> None:
    from dataclasses import replace

    settings = replace(
        settings,
        crystal_user="s-user",
        crystal_password="s-pass",
        trading_user="t-user",
        trading_password="t-pass",
    )
    provider = ServiceAccountCredentialProvider(settings)
    assert provider.rest_credentials_for(None) == RestCredentials("tester", "secret")
    assert provider.socket_credentials_for(None) == SocketCredentials("s-user", "s-pass")
    assert provider.trading_credentials_for(None) == TradingCredentials("t-user", "t-pass")


def test_service_account_provider_returns_incomplete_credentials_when_unset(
    settings: Settings,
) -> None:
    """Produto sem env var configurada não deve levantar — só devolve credencial incompleta."""
    provider = ServiceAccountCredentialProvider(settings)
    socket_creds = provider.socket_credentials_for(None)
    assert not socket_creds.is_complete


# ---- WebLoginCredentialProvider: cada produto do bundle é independente -------------------


def test_web_login_resolves_only_the_product_present_in_the_bundle() -> None:
    login_provider = _FakeLoginProvider(
        credentials_by_token={"tok": CedroCredentialBundle(rest=RestCredentials("u", "p"))}
    )
    provider = WebLoginCredentialProvider(login_provider)
    principal = _token()

    assert provider.rest_credentials_for(principal) == RestCredentials("u", "p")
    with pytest.raises(CedroAuthError, match="Socket"):
        provider.socket_credentials_for(principal)
    with pytest.raises(CedroAuthError, match="Trading"):
        provider.trading_credentials_for(principal)


def test_web_login_resolves_all_three_when_all_present() -> None:
    login_provider = _FakeLoginProvider(
        credentials_by_token={
            "tok": CedroCredentialBundle(
                rest=RestCredentials("u1", "p1"),
                socket=SocketCredentials("u2", "p2"),
                trading=TradingCredentials("u3", "p3"),
            )
        }
    )
    provider = WebLoginCredentialProvider(login_provider)
    principal = _token()

    assert provider.rest_credentials_for(principal).user == "u1"
    assert provider.socket_credentials_for(principal).user == "u2"
    assert provider.trading_credentials_for(principal).user == "u3"


def test_web_login_rejects_unauthenticated_principal() -> None:
    provider = WebLoginCredentialProvider(_FakeLoginProvider())
    with pytest.raises(CedroAuthError, match="Não autenticado"):
        provider.rest_credentials_for(None)
