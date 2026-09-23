"""Tool de conta: uso da cota mensal do plano do chamador.

Account tool: the caller's monthly plan quota usage. Não consome cota (ver ``quota.EXEMPT_TOOLS``)
e não exige escopo além do mínimo para conectar ao servidor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.auth.middleware.auth_context import get_access_token

from ._helpers import READ_ONLY_ANNOTATIONS

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..quota import QuotaPolicy


def register(mcp: "FastMCP", quota: "QuotaPolicy") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def account_get_usage() -> dict[str, Any]:
        """Quanto da cota mensal do seu plano já foi usado (chamadas de tool), quanto resta e
        quando renova. Não consome cota.

        Monthly plan quota usage for the caller: used, remaining and reset date (UTC).
        """
        return quota.usage(get_access_token())
