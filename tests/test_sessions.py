"""SessionRegistry: isolamento (ou compartilhamento) de sessão por principal."""

from __future__ import annotations

import httpx
import pytest

from cedro_mcp.client import SessionRegistry
from cedro_mcp.config import Settings
from cedro_mcp.credentials import (
    PerUserCredentialProvider,
    RestCredentials,
    ServiceAccountCredentialProvider,
)

from ._principal import make_token


def test_service_account_shares_one_session_across_principals(settings: Settings) -> None:
    """Com service account, todos os chamadores caem na MESMA sessão (comportamento atual)."""
    registry = SessionRegistry(settings, ServiceAccountCredentialProvider(settings))
    a = registry.for_principal(make_token("marketdata:read", subject="cliente-a"))
    b = registry.for_principal(make_token("marketdata:read", subject="cliente-b"))
    assert a is b
    registry.close()


def test_service_account_returns_env_credentials(settings: Settings) -> None:
    provider = ServiceAccountCredentialProvider(settings)
    assert provider.rest_credentials_for(None) == RestCredentials("tester", "secret")
    assert provider.session_key(None) == "service-account"


def test_injected_http_client_is_shared(settings: Settings) -> None:
    http = httpx.Client(base_url=settings.base_url)
    registry = SessionRegistry(settings, ServiceAccountCredentialProvider(settings), http=http)
    session = registry.for_principal(None)
    assert session.http is http
    registry.close()


def test_per_user_provider_is_an_explicit_stub() -> None:
    """O slot per-user existe, mas falha alto — não finge funcionar."""
    provider = PerUserCredentialProvider()
    token = make_token("marketdata:read", subject="cliente-a")
    assert provider.session_key(token) == "cliente-a"
    with pytest.raises(NotImplementedError, match="Saulo"):
        provider.rest_credentials_for(token)


def test_per_user_provider_requires_subject() -> None:
    with pytest.raises(NotImplementedError):
        PerUserCredentialProvider().session_key(None)


class _PerPrincipalProvider:
    """Provider fictício que isola por subject, para provar que o registry suporta isso."""

    def rest_credentials_for(self, principal):  # noqa: ANN001
        return RestCredentials(principal.subject, "senha")

    def session_key(self, principal):  # noqa: ANN001
        return principal.subject


def test_registry_isolates_sessions_when_provider_keys_per_principal(settings: Settings) -> None:
    registry = SessionRegistry(settings, _PerPrincipalProvider())
    a = registry.for_principal(make_token(subject="cliente-a"))
    b = registry.for_principal(make_token(subject="cliente-b"))
    assert a is not b
    assert a.http is not b.http  # cookie jars independentes
    registry.close()
