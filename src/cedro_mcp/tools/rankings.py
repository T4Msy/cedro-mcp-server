"""Tools de rankings, volume e maiores altas/baixas — Market Data REST."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_READ
from ..models import CrossRankingItem, MoverItem, PlayerRankingItem, VolumeAtPrice
from ._helpers import READ_ONLY_ANNOTATIONS, parse_list, parse_one

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient


def register(mcp: "FastMCP", client: "CedroClient") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_player_ranking(symbol: str) -> list[PlayerRankingItem]:
        """Corretoras que mais negociaram um ativo.

        Brokers that traded an asset the most. GET /services/quotes/playerRanking/{symbol}
        """
        data = client.get_quotes(f"/services/quotes/playerRanking/{symbol}")
        return parse_list(data, PlayerRankingItem)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_cross_ranking(market: str, broker: str) -> list[CrossRankingItem]:
        """Ativos mais negociados por uma corretora num mercado.

        Assets most traded by one broker in a market.
        GET /services/quotes/crossRanking/{market}/{broker}
        """
        data = client.get_quotes(f"/services/quotes/crossRanking/{market}/{broker}")
        return parse_list(data, CrossRankingItem)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_volume_at_price(symbol: str) -> VolumeAtPrice:
        """Perfil de volume negociado por nível de preço (volume-at-price).

        Volume profile per price level. GET /services/quotes/volumeAtPrice/{symbol}
        """
        data = client.get_quotes(f"/services/quotes/volumeAtPrice/{symbol}")
        return parse_one(data, VolumeAtPrice)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_gainers(index: str) -> list[MoverItem]:
        """Top ativos em alta de um índice (gainers).

        Top gainers of an index. GET /services/quotes/highList/{index}
        """
        data = client.get_quotes(f"/services/quotes/highList/{index}")
        return parse_list(data, MoverItem)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_losers(index: str) -> list[MoverItem]:
        """Top ativos em baixa de um índice (losers).

        Top losers of an index. GET /services/quotes/fallList/{index}
        """
        data = client.get_quotes(f"/services/quotes/fallList/{index}")
        return parse_list(data, MoverItem)
