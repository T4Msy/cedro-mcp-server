"""Tools de notícias — Market Data REST (auth OAuth2 Bearer própria).

News tools. Datas no formato ``DDMMYYYY`` ou ``DDMMYYYYHHMMSS``.
Inclui os 3 endpoints antes ausentes no vault: newsAgency, newsQuery,
newsRelevantFactsByAgency (ver Gap Analysis).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from urllib.parse import quote

from pydantic import Field

from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_NEWS
from ..models import NewsAgency, NewsArticle, NewsItem
from ._helpers import READ_ONLY_ANNOTATIONS, parse_list, parse_one

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..client import CedroClient

#: DDMMYYYY (8 dígitos) ou DDMMYYYYHHMMSS (14 dígitos).
_DATE_PATTERN = r"^\d{8}(\d{6})?$"
DateStr = Annotated[str, Field(pattern=_DATE_PATTERN)]
#: A API documenta "max 100" só em texto — aplicado aqui de verdade.
Count = Annotated[int, Field(gt=0, le=100)]


def register(mcp: "FastMCP", client: "CedroClient") -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_NEWS)
    def news_get_last(count: Count) -> list[NewsItem]:
        """Últimas N notícias (limite de 100).

        Last N news (max 100). GET /services/news/newsLast/{count}
        """
        data = client.get_news(f"/services/news/newsLast/{count}")
        return parse_list(data, NewsItem)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_NEWS)
    def news_get_by_code(code: str) -> NewsArticle:
        """Corpo completo de uma notícia pelo seu código.

        Full article body by code. GET /services/news/newsByCode/{code}
        """
        data = client.get_news(f"/services/news/newsByCode/{quote(code, safe='')}")
        return parse_one(data, NewsArticle)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_NEWS)
    def news_by_date(start: DateStr, end: DateStr) -> list[NewsItem]:
        """Notícias entre duas datas (DDMMYYYY[HHMMSS]).

        News between two dates. GET /services/news/newsByDate/{start}/{end}
        """
        data = client.get_news(f"/services/news/newsByDate/{start}/{end}")
        return parse_list(data, NewsItem)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_NEWS)
    def news_by_agency(agency_code: str) -> list[NewsItem]:
        """Notícias de uma agência específica (ex.: 3=Bovespa, 4=BMF).

        News from an agency. GET /services/news/newsByAgency/{agency_code}
        """
        data = client.get_news(f"/services/news/newsByAgency/{quote(agency_code, safe='')}")
        return parse_list(data, NewsItem)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_NEWS)
    def news_relevant_facts(start: DateStr, end: DateStr) -> list[NewsItem]:
        """Fatos relevantes por período (DDMMYYYY[HHMMSS], limite 100).

        Material facts by period. GET /services/news/newsRelevantFacts/{start}/{end}
        """
        data = client.get_news(f"/services/news/newsRelevantFacts/{start}/{end}")
        return parse_list(data, NewsItem)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_NEWS)
    def news_relevant_facts_by_quote(
        start: DateStr, end: DateStr, symbol: str
    ) -> list[NewsItem]:
        """Fatos relevantes de um ativo por período.

        Material facts for an asset by period.
        GET /services/news/newsRelevantFactsByQuote/{start}/{end}/{symbol}
        """
        data = client.get_news(
            f"/services/news/newsRelevantFactsByQuote/{start}/{end}/{symbol}"
        )
        return parse_list(data, NewsItem)

    # ---- endpoints antes ausentes no vault (Gap 1 da Gap Analysis) ----------

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_NEWS)
    def news_list_agencies() -> list[NewsAgency]:
        """Lista as agências de notícias disponíveis.

        List available news agencies. GET /services/news/newsAgency
        """
        data = client.get_news("/services/news/newsAgency")
        return parse_list(data, NewsAgency)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_NEWS)
    def news_search(start: DateStr, end: DateStr, keyword: str) -> list[NewsItem]:
        """Busca notícias por período que contenham uma palavra-chave.

        Search news by period containing a keyword (title/description).
        GET /services/news/newsQuery/{start}/{end}/{keyword}
        """
        data = client.get_news(
            f"/services/news/newsQuery/{start}/{end}/{quote(keyword, safe='')}"
        )
        return parse_list(data, NewsItem)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    @require_scope(MARKETDATA_NEWS)
    def news_relevant_facts_by_agency(
        start: DateStr, end: DateStr, agency_codes: str
    ) -> list[NewsItem]:
        """Fatos relevantes de uma agência por período.

        Material facts from an agency by period.
        GET /services/news/newsRelevantFactsByAgency/{start}/{end}/{agency_codes}
        """
        # agency_codes é uma lista separada por vírgula (ex.: "3,4") — preserva a vírgula
        # literal (é o separador esperado pela API), só escapa o resto (espaço, barra, etc.).
        data = client.get_news(
            "/services/news/newsRelevantFactsByAgency/"
            f"{start}/{end}/{quote(agency_codes, safe=',')}"
        )
        return parse_list(data, NewsItem)
