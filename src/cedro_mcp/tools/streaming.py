"""Tools Fase 2: snapshots em tempo real via Socket Crystal TCP."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_STREAM
from ._helpers import READ_ONLY_ANNOTATIONS

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..streaming import MarketDataStreamClient

StreamCount = Annotated[int, Field(gt=0, le=1_000)]


def register(mcp: "FastMCP", client: "MarketDataStreamClient") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_STREAM)
    def stream_get_quote(symbol: str) -> dict[str, Any]:
        """Última cotação em tempo real do Socket Crystal para um ativo.

        Garante a assinatura de quote e devolve o snapshot atualizado (último, bid e ask).
        """
        return client.get_quote(symbol)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_STREAM)
    def stream_get_book(symbol: str) -> dict[str, Any]:
        """Livro de ofertas agregado em tempo real do Socket Crystal para um ativo.

        A resposta preserva a convenção da API: A = compras (bids) e B = vendas (asks).
        """
        return client.get_book(symbol)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_STREAM)
    def stream_get_tape(symbol: str, count: StreamCount = 20) -> dict[str, Any]:
        """Últimos negócios em tempo real do Socket Crystal para um ativo."""
        return client.get_tape(symbol, count)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_STREAM)
    def stream_unsubscribe(symbol: str) -> dict[str, Any]:
        """Cancela todas as assinaturas de streaming do ativo e limpa seus snapshots locais."""
        return client.unsubscribe(symbol)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_STREAM)
    def stream_status() -> dict[str, Any]:
        """Status da conexão Socket Crystal e dos ativos assinados nesta conta."""
        return client.status()
