"""Autenticação do MCP **contra** as APIs da Cedro (downstream).

Dois esquemas distintos (ver [[Autenticacao REST (SignIn + JSESSIONID)]] e [[Noticias REST - MOC]]):
- Cotações: ``POST /SignIn`` → cookie de sessão ``JSESSIONID`` (reanexado em toda chamada).
- Notícias: OAuth2 ``POST /connect/token`` (client_credentials) → ``Authorization: Bearer``.

Para a autenticação do **chamador** do MCP (IAM/API key), ver o pacote ``auth/``.
"""

from __future__ import annotations

import threading
import time

import httpx

from .config import Settings
from .credentials import RestCredentials
from .errors import CedroAuthError
from .metrics import SIGNINS

# Margem de segurança para renovar o token antes de expirar (segundos).
_TOKEN_REFRESH_MARGIN = 30.0


class SessionAuth:
    """Gerencia a sessão ``JSESSIONID`` do módulo de cotações, para uma credencial.

    Thread-safe: requisições concorrentes do mesmo principal fazem **um** ``SignIn`` só. Cada
    login bem-sucedido incrementa ``generation``; quem recebe 401 chama :meth:`invalidate` com
    a geração que usou, então N threads com 401 simultâneo não disparam N logins.
    """

    def __init__(self, credentials: RestCredentials) -> None:
        self._credentials = credentials
        self._authenticated = False
        self._generation = 0
        self._lock = threading.Lock()

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    def reset(self) -> None:
        """Marca a sessão como inválida (força novo SignIn na próxima chamada)."""
        with self._lock:
            self._authenticated = False

    def invalidate(self, generation: int) -> None:
        """Invalida só se a sessão ainda é a da ``generation`` informada."""
        with self._lock:
            if generation == self._generation:
                self._authenticated = False

    def ensure(self, client: httpx.Client) -> int:
        """Garante uma sessão válida; faz ``POST /SignIn`` se necessário. Devolve a geração."""
        with self._lock:
            if self._authenticated and "JSESSIONID" in client.cookies:
                return self._generation
            if not self._credentials.is_complete:
                raise CedroAuthError(
                    "Credenciais REST ausentes: defina CEDRO_USER e CEDRO_PASS. "
                    "Missing REST credentials: set CEDRO_USER and CEDRO_PASS."
                )
            try:
                resp = client.post(
                    "/SignIn",
                    params={
                        "login": self._credentials.user,
                        "password": self._credentials.password,
                    },
                )
            except httpx.HTTPError:
                SIGNINS.labels("market_data", "error").inc()
                raise
            # /SignIn responde 200 com corpo "true"/"false" e Set-Cookie JSESSIONID.
            body = (resp.text or "").strip().strip('"').lower()
            if resp.status_code != 200 or body == "false":
                SIGNINS.labels("market_data", "refused").inc()
                raise CedroAuthError("SignIn recusado (login/senha inválidos). Invalid credentials.")
            if "JSESSIONID" not in client.cookies:
                SIGNINS.labels("market_data", "refused").inc()
                raise CedroAuthError(
                    "SignIn não retornou o cookie JSESSIONID. No session cookie returned."
                )
            SIGNINS.labels("market_data", "ok").inc()
            self._authenticated = True
            self._generation += 1
            return self._generation


class NewsAuth:
    """Gerencia o token OAuth2 do módulo de notícias, com cache até expirar.

    As credenciais de notícias são de **cliente** (client_credentials), não de usuário final —
    por isso são compartilhadas entre principais.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0

    def invalidate(self, header: dict[str, str]) -> None:
        """Descarta o token só se ainda é o que gerou ``header`` (outra thread pode ter renovado)."""
        with self._lock:
            if header.get("Authorization") == f"Bearer {self._token}":
                self._token = None
                self._expires_at = 0.0

    def ensure_header(self, client: httpx.Client, *, now: float | None = None) -> dict[str, str]:
        """Retorna o header Authorization Bearer, renovando o token se preciso."""
        with self._lock:
            current = now if now is not None else time.monotonic()
            if self._token and current < self._expires_at:
                return {"Authorization": f"Bearer {self._token}"}
            if not self._settings.has_news_credentials:
                raise CedroAuthError(
                    "Credenciais de Notícias ausentes: defina CEDRO_NEWS_CLIENT_ID e "
                    "CEDRO_NEWS_CLIENT_SECRET. Missing news credentials."
                )
            resp = client.post(
                "/connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.news_client_id,
                    "client_secret": self._settings.news_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code != 200:
                raise CedroAuthError(f"Falha ao obter token de notícias (HTTP {resp.status_code}).")
            payload = resp.json()
            token = payload.get("access_token")
            if not token:
                raise CedroAuthError("Resposta de /connect/token sem access_token.")
            expires_in = float(payload.get("expires_in", 3600))
            self._token = token
            self._expires_at = current + max(expires_in - _TOKEN_REFRESH_MARGIN, 0.0)
            return {"Authorization": f"Bearer {token}"}
