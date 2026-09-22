"""Tools de notícias — Market Data REST (auth OAuth2 Bearer própria).

News tools. Datas no formato ``DDMMYYYY`` ou ``DDMMYYYYHHMMSS``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from urllib.parse import quote

from pydantic import Field

from ..auth.entitlements import require_scope
from ..auth.scopes import MARKETDATA_NEWS
from ..errors import CedroValidationError
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
    def news_search(
        count: Count | None = None,
        start: DateStr | None = None,
        end: DateStr | None = None,
        keyword: str | None = None,
        agency_codes: str | None = None,
        symbol: str | None = None,
        relevant_facts: bool = False,
    ) -> list[NewsItem]:
        """Busca notícias — últimas N, por período, por agência, por palavra-chave ou por
        fatos relevantes.

        Modos, na ordem de precedência:
        - `count` sozinho: últimas N notícias (max 100).
        - `relevant_facts=True` + `start`/`end` (+ opcional `symbol` OU `agency_codes`): fatos
          relevantes do período, de um ativo, ou de uma/mais agências (`agency_codes`
          separados por vírgula, ex. "3,4").
        - `keyword` + `start`/`end`: busca por palavra-chave no período.
        - `agency_codes` sozinho (sem datas): notícias de uma agência.
        - `start`/`end` sozinhos: notícias do período.

        GET /services/news/newsLast/{count}
        GET /services/news/newsRelevantFacts[ByQuote|ByAgency]/{start}/{end}[/...]
        GET /services/news/newsQuery/{start}/{end}/{keyword}
        GET /services/news/newsByAgency/{agency_code}
        GET /services/news/newsByDate/{start}/{end}
        """
        if count is not None and start is None and end is None and keyword is None:
            data = client.get_news(f"/services/news/newsLast/{count}")
        elif relevant_facts:
            if not start or not end:
                raise CedroValidationError("relevant_facts=True exige `start` e `end`.")
            if symbol:
                data = client.get_news(
                    f"/services/news/newsRelevantFactsByQuote/{start}/{end}/{symbol}"
                )
            elif agency_codes:
                data = client.get_news(
                    "/services/news/newsRelevantFactsByAgency/"
                    f"{start}/{end}/{quote(agency_codes, safe=',')}"
                )
            else:
                data = client.get_news(f"/services/news/newsRelevantFacts/{start}/{end}")
        elif keyword is not None:
            if not start or not end:
                raise CedroValidationError("`keyword` exige `start` e `end`.")
            data = client.get_news(
                f"/services/news/newsQuery/{start}/{end}/{quote(keyword, safe='')}"
            )
        elif agency_codes is not None and start is None and end is None:
            data = client.get_news(f"/services/news/newsByAgency/{quote(agency_codes, safe='')}")
        elif start and end:
            data = client.get_news(f"/services/news/newsByDate/{start}/{end}")
        else:
            raise CedroValidationError(
                "Informe `count`, `start`+`end`, `keyword`+`start`+`end`, ou `agency_codes`."
            )
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
    def news_list_agencies() -> list[NewsAgency]:
        """Lista as agências de notícias disponíveis.

        List available news agencies. GET /services/news/newsAgency
        """
        data = client.get_news("/services/news/newsAgency")
        return parse_list(data, NewsAgency)
