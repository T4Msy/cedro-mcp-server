"""Testes do CedroTokenVerifier: API key e JWT do IAM → AccessToken (ou 401)."""

from __future__ import annotations

import asyncio

from cedro_mcp.auth.api_key import EnvApiKeyStore
from cedro_mcp.auth.scopes import MARKETDATA_NEWS, MARKETDATA_READ, scopes_from_claims
from cedro_mcp.auth.token_verifier import CedroTokenVerifier

API_KEYS = "k_read:robo-cotacoes:marketdata:read;k_full:robo-news:marketdata:read|marketdata:news"


def verify(verifier: CedroTokenVerifier, token: str):
    return asyncio.run(verifier.verify_token(token))


# ---- API key ---------------------------------------------------------------


def test_api_key_resolves_principal_and_scopes() -> None:
    token = verify(CedroTokenVerifier(api_key_store=EnvApiKeyStore(API_KEYS)), "k_full")
    assert token is not None
    assert token.subject == "robo-news"
    assert set(token.scopes) == {MARKETDATA_READ, MARKETDATA_NEWS}
    assert token.claims["auth_method"] == "api_key"


def test_api_key_scopes_are_isolated_per_key() -> None:
    token = verify(CedroTokenVerifier(api_key_store=EnvApiKeyStore(API_KEYS)), "k_read")
    assert token is not None
    assert token.scopes == [MARKETDATA_READ]


def test_unknown_api_key_is_rejected() -> None:
    assert verify(CedroTokenVerifier(api_key_store=EnvApiKeyStore(API_KEYS)), "nao-existe") is None


def test_empty_token_is_rejected() -> None:
    assert verify(CedroTokenVerifier(api_key_store=EnvApiKeyStore(API_KEYS)), "") is None


def test_env_api_key_store_parses_scopes_with_colons() -> None:
    store = EnvApiKeyStore(API_KEYS)
    assert len(store) == 2
    principal = store.lookup("k_full")
    assert principal is not None
    # Os escopos contêm ":" — o parser não pode quebrá-los.
    assert principal.scopes == (MARKETDATA_READ, MARKETDATA_NEWS)


# ---- JWT do IAM ------------------------------------------------------------


def test_iam_jwt_maps_roles_to_scopes() -> None:
    def decoder(token: str) -> dict:
        assert token == "jwt-valido"
        return {"sub": "user-42", "roles": ["MarketData", "MarketDataNews"], "exp": 9999999999}

    access = verify(CedroTokenVerifier(jwt_decoder=decoder), "jwt-valido")
    assert access is not None
    assert access.subject == "user-42"
    assert set(access.scopes) == {MARKETDATA_READ, MARKETDATA_NEWS}
    assert access.expires_at == 9999999999
    assert access.claims["auth_method"] == "iam"


def test_iam_jwt_accepts_scope_claim() -> None:
    verifier = CedroTokenVerifier(
        jwt_decoder=lambda _t: {"sub": "u", "scope": "marketdata:read marketdata:news"}
    )
    access = verify(verifier, "x")
    assert access is not None
    assert set(access.scopes) == {MARKETDATA_READ, MARKETDATA_NEWS}


def test_invalid_jwt_is_rejected() -> None:
    def decoder(_token: str) -> dict:
        raise ValueError("assinatura inválida / expirado")

    assert verify(CedroTokenVerifier(jwt_decoder=decoder), "jwt-ruim") is None


def test_valid_jwt_without_known_scopes_is_rejected() -> None:
    """Token legítimo mas sem nenhum direito reconhecido não deve abrir o servidor."""
    verifier = CedroTokenVerifier(jwt_decoder=lambda _t: {"sub": "u", "roles": ["Outro"]})
    assert verify(verifier, "jwt-sem-escopo") is None


def test_no_decoder_and_no_api_key_rejects() -> None:
    assert verify(CedroTokenVerifier(), "qualquer") is None


def test_api_key_takes_precedence_over_jwt() -> None:
    """A API key é resolvida antes do JWT; o decoder nem deve ser chamado."""

    def decoder(_t: str) -> dict:
        raise AssertionError("decoder não deveria ser chamado para uma API key válida")

    access = verify(
        CedroTokenVerifier(api_key_store=EnvApiKeyStore(API_KEYS), jwt_decoder=decoder), "k_read"
    )
    assert access is not None


# ---- mapeamento de claims --------------------------------------------------


def test_scopes_from_claims_ignores_unknown_roles_and_dedups() -> None:
    claims = {"scope": "marketdata:read", "roles": ["MarketData", "Desconhecida"]}
    assert scopes_from_claims(claims) == [MARKETDATA_READ]
