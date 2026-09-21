"""Entitlements: expor/executar apenas as tools que o contrato do chamador permite.

Dois níveis, porque esconder não é o mesmo que proibir:

- :func:`require_scope` — **nega a execução** de uma tool sem o escopo (defesa real).
- :class:`EntitledFastMCP` — **oculta da listagem** as tools sem escopo (o cliente nem vê o que
  não contratou).

Quando **não há autenticação configurada** (ex.: transporte stdio em desenvolvimento),
``get_access_token()`` devolve ``None`` e ambos liberam tudo — a autorização é responsabilidade do
deploy que ativa o IAM.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from mcp.types import Tool as MCPTool

from ..errors import CedroEntitlementError

F = TypeVar("F", bound=Callable[..., Any])

#: nome da tool → escopos exigidos. Preenchido pelo decorator no import dos módulos de tools.
_TOOL_SCOPES: dict[str, frozenset[str]] = {}


def tool_scopes(tool_name: str) -> frozenset[str]:
    """Escopos exigidos por uma tool (vazio = sem restrição)."""
    return _TOOL_SCOPES.get(tool_name, frozenset())


def require_scope(*scopes: str) -> Callable[[F], F]:
    """Exige os escopos para **executar** a tool e registra a exigência para a listagem.

    Aplicar **abaixo** de ``@mcp.tool()``::

        @mcp.tool()
        @require_scope(MARKETDATA_READ)
        def md_get_quote(...): ...
    """
    required = frozenset(scopes)

    def decorator(fn: F) -> F:
        _TOOL_SCOPES[fn.__name__] = required

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            token = get_access_token()
            if token is not None and not required.issubset(set(token.scopes)):
                missing = ", ".join(sorted(required - set(token.scopes)))
                raise CedroEntitlementError(
                    f"Acesso negado à tool '{fn.__name__}': escopo ausente ({missing}). "
                    f"Access denied: missing scope ({missing})."
                )
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


class EntitledFastMCP(FastMCP):
    """FastMCP que filtra a listagem de tools pelos escopos do token do chamador."""

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        token = get_access_token()
        if token is None:
            return tools
        granted = set(token.scopes)
        return [tool for tool in tools if tool_scopes(tool.name).issubset(granted)]
