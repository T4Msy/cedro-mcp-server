"""Tool de livro de ofertas (DOM) — Market Data REST."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_READ
from ..models import Book
from ._helpers import READ_ONLY_ANNOTATIONS, parse_one

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient

# As três variações compartilham o mesmo schema de resposta.
_PATHS = {
    "full": "/services/quotes/book",
    "aggregated": "/services/quotes/aggregatedBook",
    "mini": "/services/quotes/miniBook",
}


def register(mcp: "FastMCP", client: "CedroClient") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_book(symbol: str, kind: Literal["full", "aggregated", "mini"] = "aggregated") -> Book:
        """Snapshot do livro de ofertas de um ativo (compra/venda por nível).

        Order-book (DOM) snapshot. kind: full | aggregated | mini (best offers).
        GET /services/quotes/{book|aggregatedBook|miniBook}/{symbol}
        """
        base = _PATHS[kind]
        data = client.get_quotes(f"{base}/{symbol}")
        return parse_one(data, Book)
