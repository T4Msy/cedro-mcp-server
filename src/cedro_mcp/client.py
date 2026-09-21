"""Cliente HTTP da API Market Data: sessão por principal, bearer de notícias, erros e datas.

Market Data HTTP client. A sessão ``JSESSIONID`` é isolada por **principal** (o chamador autenticado),
via :class:`SessionRegistry` + :class:`~cedro_mcp.credentials.CredentialProvider`. As tools não
precisam saber disso: o principal é resolvido do contexto de autenticação do MCP.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from .config import Settings
from .credentials import CredentialProvider, ServiceAccountCredentialProvider
from .errors import CedroAuthError, CedroHTTPError
from .sessions import NewsAuth, SessionAuth

# Erros HTTP documentados para os endpoints REST (ver [[REST - MOC]] e nota `quote`).
#
# 401 é ambíguo na própria API (ver ERROS.md da skill market-data-rest, confirmado ao vivo com
# md_get_gainers/md_get_losers falhando com o resto da sessão funcionando normalmente): pode ser
# sessão de verdade inválida, OU o produto/endpoint específico não estar provisionado no plano da
# conta (o caso documentado é candleLast/candleDate, mas o padrão — funciona em tudo, 401 só num
# endpoint — é o mesmo). client.py já reautentica 1x antes de propagar; se o 401 persiste depois
# do retry, "sessão expirada" deixou de ser a explicação mais provável.
_ERROR_MESSAGES = {
    401: (
        "Não autorizado. Se outras tools funcionam normalmente na mesma sessão, isto "
        "provavelmente NÃO é sessão expirada — é o produto deste endpoint específico não estar "
        "provisionado no plano da conta Market Data (peça a liberação à comercial da Cedro). "
        "Unauthorized — likely a plan/entitlement gap for this specific endpoint, not an "
        "expired session, if other tools work fine in the same session."
    ),
    404: "Recurso não encontrado. Not found.",
    405: "Método não permitido. Method not allowed.",
    408: "Serviço não retornou em tempo hábil. Service timeout.",
    504: "Gateway timeout.",
}


@dataclass
class _Session:
    """Um cliente HTTP + a autenticação de sessão associada a um principal."""

    http: httpx.Client
    auth: SessionAuth


class SessionRegistry:
    """Mantém uma sessão ``JSESSIONID`` por chave de principal.

    Se um ``httpx.Client`` for injetado (testes/dev), ele é **compartilhado** por todas as chaves —
    o isolamento real de cookies só existe quando o registry cria os clientes.
    """

    def __init__(
        self,
        settings: Settings,
        credential_provider: CredentialProvider,
        http: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._provider = credential_provider
        self._shared_http = http
        self._sessions: dict[str, _Session] = {}

    def for_principal(self, principal: AccessToken | None) -> _Session:
        key = self._provider.session_key(principal)
        session = self._sessions.get(key)
        if session is None:
            credentials = self._provider.rest_credentials_for(principal)
            http = self._shared_http or httpx.Client(
                base_url=self._settings.base_url, timeout=self._settings.http_timeout
            )
            session = _Session(http=http, auth=SessionAuth(credentials))
            self._sessions[key] = session
        return session

    def close(self) -> None:
        for session in self._sessions.values():
            if session.http is not self._shared_http:
                session.http.close()
        self._sessions.clear()
        if self._shared_http is not None:
            self._shared_http.close()


class CedroClient:
    """Encapsula a autenticação e as chamadas REST à API Market Data."""

    def __init__(
        self,
        settings: Settings,
        credential_provider: CredentialProvider | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._registry = SessionRegistry(
            settings,
            credential_provider or ServiceAccountCredentialProvider(settings),
            http=http,
        )
        # Notícias usam client_credentials (não é credencial de usuário) → um token compartilhado.
        self._news_http = http or httpx.Client(
            base_url=settings.base_url, timeout=settings.http_timeout
        )
        self._news_owned = http is None
        self._news = NewsAuth(settings)

    def close(self) -> None:
        self._registry.close()
        if self._news_owned:
            self._news_http.close()

    def __enter__(self) -> CedroClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def _principal() -> AccessToken | None:
        """Principal autenticado do request atual (``None`` sem autenticação ativa)."""
        return get_access_token()

    # ---- cotações (sessão JSESSIONID por principal) -------------------------

    def get_quotes(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET num endpoint de cotações, garantindo sessão e reautenticando 1x em 401."""
        session = self._registry.for_principal(self._principal())
        session.auth.ensure(session.http)
        resp = session.http.get(path, params=params)
        if resp.status_code == 401:
            # Sessão pode ter expirado: reautentica uma vez e tenta de novo.
            session.auth.reset()
            session.auth.ensure(session.http)
            resp = session.http.get(path, params=params)
        return self._handle(resp)

    # ---- notícias (bearer OAuth2 compartilhado) -----------------------------

    def get_news(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET num endpoint de notícias com Authorization Bearer."""
        headers = self._news.ensure_header(self._news_http)
        resp = self._news_http.get(path, params=params, headers=headers)
        if resp.status_code == 401:
            self._news.reset()
            headers = self._news.ensure_header(self._news_http)
            resp = self._news_http.get(path, params=params, headers=headers)
        return self._handle(resp)

    # ---- interno ------------------------------------------------------------

    @staticmethod
    def _handle(resp: httpx.Response) -> Any:
        if resp.status_code == 401:
            raise CedroAuthError(_ERROR_MESSAGES[401])
        if resp.status_code >= 400:
            message = _ERROR_MESSAGES.get(resp.status_code, resp.text[:200])
            raise CedroHTTPError(resp.status_code, message)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text


# ---- helpers de data (formatos divergem por recurso) ------------------------
# Candles usam yyyyMMddHHmm; negócios yyyymmdd[HHmm]; notícias DDMMYYYY[HHMMSS].


def fmt_candle_datetime(value: datetime) -> str:
    """Formata data/hora para candles: ``yyyyMMddHHmm``."""
    return value.strftime("%Y%m%d%H%M")


def fmt_trade_date(value: datetime, *, with_time: bool = False) -> str:
    """Formata data para negócios: ``yyyymmdd`` (ou ``yyyymmddHHmm``)."""
    return value.strftime("%Y%m%d%H%M") if with_time else value.strftime("%Y%m%d")


def fmt_news_datetime(value: datetime, *, with_time: bool = False) -> str:
    """Formata data para notícias: ``DDMMYYYY`` (ou ``DDMMYYYYHHMMSS``)."""
    return value.strftime("%d%m%Y%H%M%S") if with_time else value.strftime("%d%m%Y")
