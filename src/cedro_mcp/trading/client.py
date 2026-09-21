"""Cliente HTTP de Trading: sessão OMS por principal, disambiguação de 401, envio de ordem.

Sessão **separada** da Market Data REST mesmo que a pessoa seja a mesma (`SessionRegistry` de
`client.py` não é reaproveitado) — a auth em 3 camadas (`TradingSessionAuth`) é um protocolo
diferente por cima do mesmo `POST /SignIn`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from ..config import Settings
from ..credentials import CredentialProvider
from ..errors import CedroAuthError, CedroHTTPError
from .auth import TradingSessionAuth
from .models import OrderResponse

_ERROR_MESSAGES = {
    404: "Recurso não encontrado (confira o path — os endpoints de Trading são camelCase).",
    405: "Método não permitido (SignIn/sendNewOrderSingle*/cancelOrder/editOrder são POST; "
    "dailyOrder/historyOrder são GET).",
    408: "Serviço OMS não retornou em tempo hábil.",
    504: "Gateway timeout.",
}

_SEND_ORDER_401 = (
    "Não autorizado no envio de ordem. Se consultas (dailyOrder) e edição funcionam "
    "normalmente na mesma sessão, isto NÃO é sessão expirada — é falta de permissão de "
    "entrada de ordem na conta (code 24, \"conta não associada ao usuário\"), provisionamento "
    "do lado da Cedro. Reautenticar não resolve; peça a associação conta↔usuário à comercial."
)
_GENERIC_401 = (
    "Sessão de Trading expirada ou inválida. Se isto persistir após um retry automático, "
    "confira a credencial OMS usada no login."
)


@dataclass
class _TradingSession:
    http: httpx.Client
    auth: TradingSessionAuth


class TradingSessionRegistry:
    """Mantém uma sessão de Trading por chave de principal — mesmo padrão de `SessionRegistry`."""

    def __init__(
        self,
        settings: Settings,
        credential_provider: CredentialProvider,
        *,
        http: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._provider = credential_provider
        self._shared_http = http
        self._sessions: dict[str, _TradingSession] = {}

    def for_principal(self, principal: AccessToken | None) -> _TradingSession:
        key = self._provider.session_key(principal)
        session = self._sessions.get(key)
        if session is None:
            credentials = self._provider.trading_credentials_for(principal)
            http = self._shared_http or httpx.Client(
                base_url=self._settings.base_url, timeout=self._settings.http_timeout
            )
            auth = TradingSessionAuth(
                self._settings, credentials, remote_ip=self._settings.trading_remote_ip
            )
            session = _TradingSession(http=http, auth=auth)
            self._sessions[key] = session
        return session

    def close(self) -> None:
        for session in self._sessions.values():
            if session.http is not self._shared_http:
                session.http.close()
        self._sessions.clear()
        if self._shared_http is not None:
            self._shared_http.close()


class TradingClient:
    """Envio/edição/cancelamento/consulta de ordens — sempre atrás do gate de confirmação em
    `tools/trading.py`, este cliente nunca decide sozinho enviar nada."""

    def __init__(
        self,
        settings: Settings,
        credential_provider: CredentialProvider,
        http: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._registry = TradingSessionRegistry(settings, credential_provider, http=http)

    def close(self) -> None:
        self._registry.close()

    @staticmethod
    def _principal() -> AccessToken | None:
        return get_access_token()

    def _request(
        self, method: str, path: str, *, params: dict[str, Any], is_order_send: bool
    ) -> dict[str, Any]:
        session = self._registry.for_principal(self._principal())
        session.auth.ensure(session.http)
        headers = session.auth.identifier_header()
        resp = session.http.request(method, path, params=params, headers=headers)
        if resp.status_code == 401:
            session.auth.reset()
            session.auth.ensure(session.http)
            headers = session.auth.identifier_header()
            resp = session.http.request(method, path, params=params, headers=headers)
        return self._handle(resp, is_order_send=is_order_send)

    def send_order(self, endpoint: str, params: dict[str, Any]) -> OrderResponse:
        """``POST /services/negotiation/{endpoint}`` — um dos 8 `sendNewOrderSingle*`."""
        data = self._request(
            "POST", f"/services/negotiation/{endpoint}", params=params, is_order_send=True
        )
        return OrderResponse.model_validate(data or {})

    def cancel_order(self, params: dict[str, Any]) -> OrderResponse:
        data = self._request(
            "POST", "/services/negotiation/cancelOrder", params=params, is_order_send=False
        )
        return OrderResponse.model_validate(data or {})

    def edit_order(self, params: dict[str, Any]) -> OrderResponse:
        data = self._request(
            "POST", "/services/negotiation/editOrder", params=params, is_order_send=False
        )
        return OrderResponse.model_validate(data or {})

    def daily_orders(self, path: str) -> dict[str, Any]:
        """``GET /services/negotiation/dailyOrder/...`` — path já montado pela tool."""
        return self._request("GET", path, params={}, is_order_send=False) or {}

    def history_orders(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        return self._request("GET", path, params=params, is_order_send=False) or {}

    @staticmethod
    def _handle(resp: httpx.Response, *, is_order_send: bool) -> Any:
        if resp.status_code == 401:
            raise CedroAuthError(_SEND_ORDER_401 if is_order_send else _GENERIC_401)
        if resp.status_code >= 400:
            message = _ERROR_MESSAGES.get(resp.status_code, resp.text[:300])
            raise CedroHTTPError(resp.status_code, message)
        if not resp.content:
            return None
        content_type = resp.headers.get("content-type", "")
        if "json" not in content_type and not resp.text.lstrip().startswith(("{", "[")):
            # Erro de gateway às vezes devolve HTML com status 200 — nunca tenta desserializar.
            raise CedroHTTPError(resp.status_code, f"Resposta não-JSON: {resp.text[:200]!r}")
        try:
            return resp.json()
        except ValueError as exc:
            raise CedroHTTPError(resp.status_code, f"JSON inválido: {resp.text[:200]!r}") from exc
