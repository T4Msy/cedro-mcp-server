"""user-identifier: montagem do JSON, BASE64 (confirmado em campo) e RSA (não confirmado ao
vivo, mas implementado pela especificação — ver AUTENTICACAO.md da skill trading)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256

from cedro_mcp.credentials import TradingCredentials
from cedro_mcp.trading.identity import build_identity, encode_base64, encode_identity, encode_rsa


def test_build_identity_requires_remote_ip() -> None:
    creds = TradingCredentials("10034", "senha")
    with pytest.raises(ValueError, match="remote_ip"):
        build_identity(creds, remote_ip="")


def test_build_identity_mirrors_login_into_user_name_and_login_oms() -> None:
    creds = TradingCredentials("10034", "senha")
    identity = build_identity(creds, remote_ip="203.0.113.7")
    assert identity.user_name == "10034"
    assert identity.login_oms == "10034"
    assert identity.password == "senha"
    assert identity.remote_ip == "203.0.113.7"


def test_to_json_has_exactly_the_five_documented_fields() -> None:
    creds = TradingCredentials("10034", "senha")
    identity = build_identity(creds, remote_ip="203.0.113.7")
    payload = json.loads(identity.to_json())
    assert set(payload) == {"id", "user_name", "login_oms", "password", "remote_ip"}


def test_encode_base64_roundtrips_the_json() -> None:
    creds = TradingCredentials("10034", "senha")
    identity = build_identity(creds, remote_ip="203.0.113.7")
    encoded = encode_base64(identity)
    decoded = json.loads(base64.b64decode(encoded))
    assert decoded["login_oms"] == "10034"
    assert decoded["password"] == "senha"


def test_encode_identity_dispatches_to_base64_by_default() -> None:
    creds = TradingCredentials("10034", "senha")
    identity = build_identity(creds, remote_ip="203.0.113.7")
    encoded = encode_identity(identity, encoding="base64", jwks_url=None, http_timeout=5.0)
    assert encoded == encode_base64(identity)


def test_encode_rsa_can_be_decrypted_with_the_matching_private_key() -> None:
    """Não temos como validar contra o Identity Server real — mas garantimos que a cifragem é
    RSA-OAEP-SHA256 de verdade, decifrável com a chave privada correspondente à pública do JWKS
    mockado, exatamente como a doc especifica."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()

    def _int_to_b64url(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    jwks = {
        "keys": [{"n": _int_to_b64url(public_numbers.n), "e": _int_to_b64url(public_numbers.e)}]
    }
    creds = TradingCredentials("10034", "senha")
    identity = build_identity(creds, remote_ip="203.0.113.7")

    with respx.mock:
        respx.get("https://sso-sandbox.cedrotech.com/jwks").mock(
            return_value=httpx.Response(200, json=jwks)
        )
        encoded = encode_rsa(
            identity,
            jwks_url="https://sso-sandbox.cedrotech.com/jwks",
            http_timeout=5.0,
        )

    ciphertext = base64.b64decode(encoded)
    plaintext = private_key.decrypt(
        ciphertext,
        padding.OAEP(mgf=padding.MGF1(algorithm=SHA256()), algorithm=SHA256(), label=None),
    )
    assert json.loads(plaintext) == json.loads(identity.to_json())


def test_encode_identity_rsa_requires_jwks_url() -> None:
    from cedro_mcp.errors import CedroAuthError

    creds = TradingCredentials("10034", "senha")
    identity = build_identity(creds, remote_ip="203.0.113.7")
    with pytest.raises(CedroAuthError, match="CEDRO_TRADING_JWKS_URL"):
        encode_identity(identity, encoding="rsa", jwks_url=None, http_timeout=5.0)
