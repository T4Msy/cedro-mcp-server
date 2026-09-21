"""Login pelo navegador: o cliente MCP (Claude Desktop, claude.ai, etc.) clica em
"Autenticar", uma aba abre pedindo o login/senha da Market Data REST, e o MCP client recebe
um token automaticamente ao final — sem copiar/colar nada.

Implementado como um ``OAuthAuthorizationServerProvider`` (o mecanismo padrão do protocolo MCP
para servidores remotos) cujo passo de "autorização" **é** o login real na Cedro: em vez de
redirecionar para um terceiro (o padrão usual desse protocolo — ver a docstring do Protocol),
mostramos nosso próprio formulário (`/cedro-login`), validamos a credencial contra o `POST
/SignIn` de verdade, e só então emitimos um token de acesso opaco associado a ela.

**O que isto é e o que não é** (ver docs/arquitetura/06-credential-transport.md, Alternativa C):
a credencial do cliente nunca é exposta ao MCP client, só o token — mas ela FICA em memória do
processo, associada ao token, enquanto ele for válido. É estado em memória, nunca persistido em
disco, nunca uma base de senhas real; reinicia o processo, todo mundo reloga. Ainda assim é mais
exposição do que a Alternativa A (header por requisição, sem custódia nenhuma) — trade-off aceito
aqui deliberadamente, a pedido explícito do usuário, para ganhar a UX de "clicar e autenticar".
"""

from __future__ import annotations

import html
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    OAuthToken,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from .credentials import RestCredentials

if TYPE_CHECKING:
    from .config import Settings

#: Tempo pra completar o formulário depois de abrir a aba (evita códigos/flows pendurados
#: pra sempre em memória se o usuário fechar a aba sem terminar).
_FLOW_TTL = 600.0
#: RFC 6749 recomenda curto — o code é trocado por um token imediatamente após o POST.
_CODE_TTL = 300.0
#: Sem refresh token nesta v1 (ver módulo) — expira, o cliente reabre a aba e refaz o login.
_ACCESS_TOKEN_TTL = 60 * 60 * 24 * 30  # 30 dias


@dataclass
class _PendingFlow:
    client: OAuthClientInformationFull
    params: AuthorizationParams
    created_at: float = field(default_factory=time.monotonic)


async def _verify_rest_credentials(settings: "Settings", creds: RestCredentials) -> None:
    """``POST /SignIn`` real contra a Market Data — só pra validar, sessão descartada.

    Reimplementa a checagem de ``SessionAuth.ensure`` (ver sessions.py) de forma assíncrona e
    isolada: não queremos reaproveitar/poluir nenhum ``SessionRegistry`` de tools com esta sessão
    de verificação.
    """
    async with httpx.AsyncClient(base_url=settings.base_url, timeout=settings.http_timeout) as http:
        resp = await http.post(
            "/SignIn", params={"login": creds.user, "password": creds.password}
        )
    body = (resp.text or "").strip().strip('"').lower()
    if resp.status_code != 200 or body == "false" or "JSESSIONID" not in resp.cookies:
        raise TokenError("access_denied", "Login ou senha da Market Data inválidos.")


class CedroLoginProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """Ver docstring do módulo. Todo o estado é em memória, por processo."""

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._flows: dict[str, _PendingFlow] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._pending_credentials: dict[str, RestCredentials] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        #: Único estado que o resto do servidor lê (`credentials.py`) — token → credencial.
        self.credentials_by_token: dict[str, RestCredentials] = {}

    # ---- Dynamic Client Registration (RFC 7591) — o MCP client se registra sozinho ----

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info

    # ---- authorize(): em vez de redirecionar pra outro provedor, mostra NOSSA página -----

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        self._gc_flows()
        flow_id = secrets.token_urlsafe(24)
        self._flows[flow_id] = _PendingFlow(client=client, params=params)
        return f"/cedro-login?flow_id={flow_id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        if code is None or code.expires_at < time.time() or code.client_id != client.client_id:
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        creds = self._pending_credentials.pop(authorization_code.code, None)
        self._auth_codes.pop(authorization_code.code, None)
        if creds is None:
            raise TokenError("invalid_grant", "Código de autorização inválido, expirado ou já usado.")
        token = secrets.token_urlsafe(32)
        self.credentials_by_token[token] = creds
        self._access_tokens[token] = AccessToken(
            token=token,
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + _ACCESS_TOKEN_TTL,
            subject=creds.user,
        )
        return OAuthToken(
            access_token=token,
            token_type="Bearer",
            expires_in=_ACCESS_TOKEN_TTL,
            scope=" ".join(authorization_code.scopes),
        )

    # ---- Sem refresh token nesta v1 — ver docstring do módulo -----------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        raise TokenError(
            "unsupported_grant_type",
            "Refresh token não suportado — reabra a aba de login quando o acesso expirar.",
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        entry = self._access_tokens.get(token)
        if entry is None:
            return None
        if entry.expires_at is not None and entry.expires_at < time.time():
            self._forget_token(token)
            return None
        return entry

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self._forget_token(token.token)

    def _forget_token(self, token: str) -> None:
        self._access_tokens.pop(token, None)
        self.credentials_by_token.pop(token, None)

    def _gc_flows(self) -> None:
        """Descarta flows abertos que o usuário nunca terminou (aba fechada, etc.)."""
        now = time.monotonic()
        stale = [fid for fid, flow in self._flows.items() if now - flow.created_at > _FLOW_TTL]
        for fid in stale:
            self._flows.pop(fid, None)

    # ---- Nossa página de login, montada como rotas Starlette extras -----------------

    def routes(self) -> list[Route]:
        return [
            Route("/cedro-login", self._handle_login_page, methods=["GET"]),
            Route("/cedro-login", self._handle_login_submit, methods=["POST"]),
        ]

    async def _handle_login_page(self, request: Request) -> HTMLResponse:
        flow_id = request.query_params.get("flow_id", "")
        error = request.query_params.get("error")
        if flow_id not in self._flows:
            return HTMLResponse(_render_expired_page(), status_code=400)
        return HTMLResponse(_render_login_page(flow_id, error))

    async def _handle_login_submit(self, request: Request) -> Response:
        form = await request.form()
        flow_id = str(form.get("flow_id", ""))
        login = str(form.get("login", "")).strip()
        password = str(form.get("password", ""))

        flow = self._flows.get(flow_id)
        if flow is None:
            return HTMLResponse(_render_expired_page(), status_code=400)

        if not login or not password:
            return RedirectResponse(
                f"/cedro-login?flow_id={flow_id}&error="
                + html.escape("Preencha login e senha."),
                status_code=303,
            )

        creds = RestCredentials(user=login, password=password)
        try:
            await _verify_rest_credentials(self._settings, creds)
        except TokenError:
            return RedirectResponse(
                f"/cedro-login?flow_id={flow_id}&error="
                + html.escape("Login ou senha inválidos — confira e tente de novo."),
                status_code=303,
            )
        except httpx.HTTPError:
            return RedirectResponse(
                f"/cedro-login?flow_id={flow_id}&error="
                + html.escape("Não consegui falar com a Market Data agora. Tente de novo."),
                status_code=303,
            )

        del self._flows[flow_id]
        code = secrets.token_urlsafe(32)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=flow.params.scopes or [],
            expires_at=time.time() + _CODE_TTL,
            client_id=flow.client.client_id,
            code_challenge=flow.params.code_challenge,
            redirect_uri=flow.params.redirect_uri,
            redirect_uri_provided_explicitly=flow.params.redirect_uri_provided_explicitly,
            resource=flow.params.resource,
            subject=login,
        )
        self._pending_credentials[code] = creds
        redirect_url = construct_redirect_uri(
            str(flow.params.redirect_uri), code=code, state=flow.params.state
        )
        return RedirectResponse(redirect_url, status_code=302)


# ---- HTML — sem framework de template, só strings escapadas -------------------------


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0b0f14; color: #e6edf3;
         display: flex; min-height: 100vh; align-items: center; justify-content: center; margin: 0; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 32px;
           width: 100%; max-width: 380px; }}
  h1 {{ font-size: 1.1rem; margin: 0 0 4px; }}
  p.sub {{ color: #8b949e; margin: 0 0 20px; font-size: 0.9rem; }}
  label {{ display: block; font-size: 0.85rem; margin: 14px 0 6px; color: #c9d1d9; }}
  input {{ width: 100%; box-sizing: border-box; padding: 9px 10px; border-radius: 6px;
           border: 1px solid #30363d; background: #0d1117; color: #e6edf3; font-size: 0.95rem; }}
  button {{ margin-top: 20px; width: 100%; padding: 10px; border-radius: 6px; border: none;
            background: #2ea043; color: white; font-size: 0.95rem; cursor: pointer; }}
  button:hover {{ background: #3fb950; }}
  .error {{ background: #3d1f1f; border: 1px solid #f85149; color: #ffa198; padding: 10px 12px;
            border-radius: 6px; font-size: 0.85rem; margin-bottom: 14px; }}
  .hint {{ color: #6e7681; font-size: 0.78rem; margin-top: 18px; line-height: 1.4; }}
</style>
</head>
<body><div class="card">{body}</div></body>
</html>"""


def _render_login_page(flow_id: str, error: str | None) -> str:
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    body = f"""
<h1>Cedro Market Data MCP</h1>
<p class="sub">Entre com a credencial que você já usa na Market Data REST.</p>
{error_html}
<form method="post" action="/cedro-login">
  <input type="hidden" name="flow_id" value="{html.escape(flow_id)}">
  <label for="login">Login</label>
  <input id="login" name="login" type="text" autocomplete="username" autofocus required>
  <label for="password">Senha</label>
  <input id="password" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Autenticar</button>
</form>
<p class="hint">Sua senha é enviada direto pra Cedro pra confirmar o login (o mesmo SignIn que a
Market Data REST já usa) e nunca é salva em disco. Depois de autenticar, esta aba fecha sozinha
e volta pro seu app de IA.</p>
"""
    return _page("Entrar — Cedro Market Data MCP", body)


def _render_expired_page() -> str:
    body = """
<h1>Sessão de login expirada</h1>
<p class="sub">Feche esta aba e clique em "Autenticar" de novo no seu app de IA.</p>
"""
    return _page("Sessão expirada — Cedro Market Data MCP", body)
