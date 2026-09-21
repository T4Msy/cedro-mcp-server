"""Tools de cotações e ativos (Market Data REST).

Quotes & assets tools. Mapeia os endpoints sob ``/services/quotes/``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_READ
from ..models import Index, Market, Quote, QuoteInformation, SymbolList
from ._helpers import READ_ONLY_ANNOTATIONS, parse_list, parse_one

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient


def register(mcp: "FastMCP", client: "CedroClient") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_quote(symbols: list[str]) -> list[Quote]:
        """Snapshot de cotação (preço, topo de book, volumes) de 1+ ativos.

        Quote snapshot (price, top-of-book, volumes) for one or more assets.
        GET /services/quotes/quote/{symbols}
        """
        # Vírgula é o separador esperado pela API entre símbolos — preservada literal; cada
        # símbolo é escapado individualmente antes de entrar no path.
        joined = ",".join(quote(s, safe="") for s in symbols)
        data = client.get_quotes(f"/services/quotes/quote/{joined}")
        return parse_list(data, Quote)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_quote_info(symbol: str) -> QuoteInformation:
        """Metadados cadastrais de um ativo (ISIN, empresa, segmento, moeda).

        Registry metadata for an asset (ISIN, company, segment, currency).
        GET /services/quotes/quoteInformation?description={symbol}
        """
        data = client.get_quotes(
            "/services/quotes/quoteInformation", params={"description": symbol}
        )
        return parse_one(data, QuoteInformation)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_list_markets() -> list[Market]:
        """Lista todos os mercados disponíveis.

        List all available markets. GET /services/quotes/listMarket
        """
        data = client.get_quotes("/services/quotes/listMarket")
        return parse_list(data, Market)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_list_indices(market_code: int) -> list[Index]:
        """Lista os índices de um mercado (ex.: IBOV, IBRA no mercado 1=Bovespa).

        List a market's indices. GET /services/quotes/indexList?marketcode={market_code}
        """
        data = client.get_quotes(
            "/services/quotes/indexList", params={"marketcode": market_code}
        )
        return parse_list(data, Index)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_index_assets(market: str, index: str) -> list[Quote]:
        """Cotação de todos os ativos de um índice (ex.: BOVESPA/IBOV).

        Quotes for every asset in an index. GET /services/quotes/quotesIndex/{market}/{index}
        """
        data = client.get_quotes(f"/services/quotes/quotesIndex/{market}/{index}")
        return parse_list(data, Quote)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_get_company_quotes(company: str, types: int, markets: int) -> SymbolList:
        """Códigos dos papéis de uma empresa, por tipo e mercado.

        A company's asset codes, by type and market.
        GET /services/quotes/companyQuotes?company=&types=&markets=
        types: 1=spot, 2=options, 3=index, 7=Forex, 10=NYSE. markets: 1=Bovespa, 3=BMF, 6=Soma.
        """
        data = client.get_quotes(
            "/services/quotes/companyQuotes",
            params={"company": company, "types": types, "markets": markets},
        )
        return parse_one(data, SymbolList)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_READ)
    def md_list_options(symbol: str) -> SymbolList:
        """Códigos das opções de um ativo subjacente.

        Option codes for an underlying asset. GET /services/quotes/optionsQuote/{symbol}
        """
        data = client.get_quotes(f"/services/quotes/optionsQuote/{symbol}")
        return parse_one(data, SymbolList)
