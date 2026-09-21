"""Autenticação de Trading: `SignIn` + `brokerServiceLogin` + header `user-identifier`.

Três etapas, nesta ordem exata (ver AUTENTICACAO.md da skill trading):

1. ``POST /SignIn`` — igual à Market Data REST, mas com a credencial OMS (conta separada).
2. ``GET /services/negotiation/brokerServiceLogin?appname=...&username=...`` — SEMPRE GET (o
   ``POST`` documentado responde 405 em campo); manda o header ``user-identifier`` **e** o
   ``username`` na query, os dois — mandar só o header é uma causa real e documentada de
   ``code 3``.
3. O header ``user-identifier`` (identidade OMS codificada) vai em toda chamada de negociação
   depois disso, não só no login.
"""

from __future__ import annotations

import httpx

from ..config import Settings
from ..credentials import TradingCredentials
from ..errors import CedroAuthError
from .identity import build_identity, encode_identity


class TradingSessionAuth:
    """Sessão de negociação para uma credencial: cookie `JSESSIONID` + `user-identifier` prontos.

    Uma instância por principal (ver `client.py::TradingSessionRegistry`) — nunca compartilhada
    entre contas, mesmo que a pessoa seja a mesma em REST e Trading (são credenciais diferentes).
    """

    def __init__(self, settings: Settings, credentials: TradingCredentials, *, remote_ip: str) -> None:
        self._settings = settings
        self._credentials = credentials
        self._remote_ip = remote_ip
        self._authenticated = False
        self._identifier_header: str | None = None

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    def reset(self) -> None:
        """Marca a sessão como inválida — força SignIn + brokerServiceLogin de novo."""
        self._authenticated = False

    def identifier_header(self) -> dict[str, str]:
        """O header `user-identifier` pronto — só existe depois de `ensure()`."""
        if self._identifier_header is None:
            raise CedroAuthError("Sessão de Trading ainda não autenticada.")
        return {"user-identifier": self._identifier_header}

    def ensure(self, client: httpx.Client) -> None:
        if self._authenticated and "JSESSIONID" in client.cookies:
            return
        if not self._credentials.is_complete:
            raise CedroAuthError(
                "Credenciais de Trading ausentes — faça login com uma credencial OMS "
                "(ou defina CEDRO_TRADING_USER/CEDRO_TRADING_PASS em dev)."
            )

        # Etapa 1 — SignIn (mesmo endpoint da Market Data, credencial OMS).
        resp = client.post(
            "/SignIn",
            params={"login": self._credentials.user, "password": self._credentials.password},
        )
        body = (resp.text or "").strip().strip('"').lower()
        if resp.status_code != 200 or body == "false":
            raise CedroAuthError("SignIn recusado (login/senha OMS inválidos).")
        if "JSESSIONID" not in client.cookies:
            raise CedroAuthError("SignIn não retornou o cookie JSESSIONID.")

        # Etapa 2 + o header user-identifier, montado antes porque brokerServiceLogin já exige.
        identity = build_identity(self._credentials, remote_ip=self._remote_ip)
        encoded = encode_identity(
            identity,
            encoding=self._settings.trading_encryption,
            jwks_url=self._settings.trading_jwks_url,
            http_timeout=self._settings.http_timeout,
        )
        self._identifier_header = encoded

        resp = client.get(
            "/services/negotiation/brokerServiceLogin",
            params={
                "appname": self._settings.trading_app_name,
                "username": self._credentials.user,
            },
            headers=self.identifier_header(),
        )
        if resp.status_code != 200:
            raise CedroAuthError(f"brokerServiceLogin falhou (HTTP {resp.status_code}).")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise CedroAuthError("brokerServiceLogin não retornou JSON.") from exc
        if payload.get("isAuthenticated") != "Y":
            code = payload.get("code")
            message = payload.get("message") or payload.get("text") or "sem detalhe"
            hint = ""
            if str(code) == "3":
                hint = (
                    " (code 3 quase sempre é o user-identifier montado errado do nosso lado, "
                    "não permissão de conta — ver docs/arquitetura/10-trading-auth.md)"
                )
            raise CedroAuthError(f"brokerServiceLogin recusado: {message}{hint}")

        self._authenticated = True
