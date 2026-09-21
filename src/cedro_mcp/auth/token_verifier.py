"""Verificação do bearer do chamador: **IAM da Cedro (Identity Server)** ou **API key**.

Implementa o protocolo ``mcp.server.auth.provider.TokenVerifier``. Retornar ``None`` faz o SDK
responder **401**.

Ordem de resolução:
1. **API key** (integrações automatizadas) — resolvida pelo :class:`ApiKeyStore`.
2. **JWT do IAM** — validado por assinatura/expiração; `roles`/`claims` viram escopos MCP.
"""

from __future__ import annotations

from typing import Any, Callable

from mcp.server.auth.provider import AccessToken, TokenVerifier

from .api_key import ApiKeyStore
from .scopes import scopes_from_claims

#: Assinatura de um decodificador de JWT: recebe o token cru, devolve as claims.
#: Injetável para testes (evita rede/JWKS).
JwtDecoder = Callable[[str], dict[str, Any]]


def build_jwks_decoder(jwks_url: str, issuer: str, audience: str | None) -> JwtDecoder:
    """Decoder padrão: valida assinatura via JWKS do Identity Server (offline após cache).

    Importa `PyJWT` de forma preguiçosa para não exigir a dependência quando só se usa API key.
    """
    import jwt
    from jwt import PyJWKClient

    jwk_client = PyJWKClient(jwks_url)

    def decode(token: str) -> dict[str, Any]:
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
            options={"verify_aud": audience is not None},
        )

    return decode


class CedroTokenVerifier(TokenVerifier):
    """Valida o bearer do chamador (API key **ou** JWT do IAM)."""

    def __init__(
        self,
        *,
        api_key_store: ApiKeyStore | None = None,
        jwt_decoder: JwtDecoder | None = None,
        default_client_id: str = "cedro-mcp",
    ) -> None:
        self._api_key_store = api_key_store
        self._jwt_decoder = jwt_decoder
        self._default_client_id = default_client_id

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None

        principal = self._api_key_store.lookup(token) if self._api_key_store else None
        if principal is not None:
            return AccessToken(
                token=token,
                client_id=principal.subject,
                subject=principal.subject,
                scopes=list(principal.scopes),
                claims={"auth_method": "api_key"},
            )

        if self._jwt_decoder is None:
            return None

        try:
            claims = self._jwt_decoder(token)
        except Exception:
            # Assinatura inválida, token expirado, issuer/audience errados → 401.
            return None

        scopes = scopes_from_claims(claims)
        if not scopes:
            # Token válido, mas sem nenhum direito reconhecido: não há o que expor.
            return None

        subject = claims.get("sub")
        return AccessToken(
            token=token,
            client_id=str(claims.get("client_id") or subject or self._default_client_id),
            subject=str(subject) if subject else None,
            scopes=scopes,
            expires_at=claims.get("exp"),
            claims={**claims, "auth_method": "iam"},
        )
