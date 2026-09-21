"""Monta e codifica o header ``user-identifier`` exigido em quase toda chamada de negociação.

É um JSON com a identidade OMS — **incluindo a senha em claro** — codificado antes de ir no
header. Por isso isto só roda no servidor: a senha nunca chega ao cliente MCP.

A codificação varia por conta ("BASE64 ou RSA, conforme configuração do webfeeder" — a própria
doc da Cedro). BASE64 é o default confirmado em campo (`cedro-trading-smoke/UserIdentifier.cs`);
RSA-OAEP-SHA256 está implementado aqui pela especificação da skill (JWKS do Identity Server +
RSA-OAEP-SHA256 + base64), mas **nunca foi confirmado funcionando ao vivo** — ver
docs/arquitetura/10-trading-auth.md.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Literal

import httpx
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256

from ..credentials import TradingCredentials
from ..errors import CedroAuthError

Encoding = Literal["base64", "rsa"]


@dataclass(frozen=True)
class UserIdentifier:
    """Os 5 campos do JSON de identidade OMS, antes de codificar."""

    id: str
    user_name: str
    login_oms: str
    password: str
    remote_ip: str

    def to_json(self) -> str:
        # dict, não dataclasses.asdict — ordem de campos estável, igual ao exemplo de referência
        # (json.dumps preserva a ordem de inserção do dict, que é a ordem de declaração aqui).
        payload = {
            "id": self.id,
            "user_name": self.user_name,
            "login_oms": self.login_oms,
            "password": self.password,
            "remote_ip": self.remote_ip,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_identity(creds: TradingCredentials, *, remote_ip: str) -> UserIdentifier:
    """Monta a identidade a partir da credencial Trading. ``login_oms`` = ``user_name`` = login."""
    if not remote_ip:
        raise ValueError(
            "remote_ip é obrigatório e deve ser o IP real de origem — a Cedro usa para "
            "rastrear a ordem, não mande um placeholder como '127.0.0.1' em produção."
        )
    return UserIdentifier(
        id="1",
        user_name=creds.user or "",
        login_oms=creds.user or "",
        password=creds.password or "",
        remote_ip=remote_ip,
    )


def encode_base64(identity: UserIdentifier) -> str:
    """BASE64 do JSON UTF-8 — a codificação confirmada em campo, e o default desta API."""
    return base64.b64encode(identity.to_json().encode("utf-8")).decode("ascii")


def _rsa_public_key_from_jwk(jwk: dict) -> rsa.RSAPublicKey:
    def _b64url_to_int(value: str) -> int:
        padding_needed = "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(value + padding_needed)
        return int.from_bytes(raw, "big")

    n = _b64url_to_int(jwk["n"])
    e = _b64url_to_int(jwk["e"])
    return rsa.RSAPublicNumbers(e, n).public_key()


def encode_rsa(identity: UserIdentifier, *, jwks_url: str, http_timeout: float) -> str:
    """RSA-OAEP-SHA256 do JSON UTF-8, cifrado com a chave pública do JWKS do Identity Server.

    ⚠️ Implementado pela especificação da skill (AUTENTICACAO.md), mas **nunca confirmado ao
    vivo** — nenhuma conta de teste usada até agora precisou de RSA. Ver docs/arquitetura/
    10-trading-auth.md antes de habilitar `CEDRO_TRADING_ENCRYPTION=rsa` em produção.
    """
    resp = httpx.get(jwks_url, timeout=http_timeout)
    resp.raise_for_status()
    keys = resp.json().get("keys") or []
    if not keys:
        raise CedroAuthError(f"JWKS de {jwks_url} não retornou nenhuma chave.")
    public_key = _rsa_public_key_from_jwk(keys[0])
    ciphertext = public_key.encrypt(
        identity.to_json().encode("utf-8"),
        padding.OAEP(mgf=padding.MGF1(algorithm=SHA256()), algorithm=SHA256(), label=None),
    )
    return base64.b64encode(ciphertext).decode("ascii")


def encode_identity(
    identity: UserIdentifier,
    *,
    encoding: Encoding,
    jwks_url: str | None,
    http_timeout: float,
) -> str:
    if encoding == "base64":
        return encode_base64(identity)
    if not jwks_url:
        raise CedroAuthError(
            "CEDRO_TRADING_ENCRYPTION=rsa exige CEDRO_TRADING_JWKS_URL configurado."
        )
    return encode_rsa(identity, jwks_url=jwks_url, http_timeout=http_timeout)
