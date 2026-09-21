"""Helper de teste: injeta um principal autenticado no contexto do MCP.

Test helper: injects an authenticated principal into the MCP auth context, do mesmo jeito que o
``AuthContextMiddleware`` faz num request HTTP real.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
from mcp.server.auth.provider import AccessToken


def make_token(*scopes: str, subject: str = "tester") -> AccessToken:
    return AccessToken(
        token="test-token",
        client_id=subject,
        subject=subject,
        scopes=list(scopes),
    )


@contextmanager
def as_principal(*scopes: str, subject: str = "tester") -> Iterator[AccessToken]:
    """Executa o bloco como um chamador autenticado com os escopos dados."""
    token = make_token(*scopes, subject=subject)
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        yield token
    finally:
        auth_context_var.reset(reset)
