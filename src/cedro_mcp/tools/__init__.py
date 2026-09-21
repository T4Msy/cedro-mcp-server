"""Registro das tools F1 (Market Data REST) no servidor FastMCP.

Registers the F1 (Market Data REST) tools on the FastMCP server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import book, candles, news, quotes, rankings, trades

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient

_MODULES = (quotes, candles, book, trades, rankings, news)


def register_all(mcp: "FastMCP", client: "CedroClient") -> None:
    """Registra todas as tools de todos os módulos."""
    for module in _MODULES:
        module.register(mcp, client)
