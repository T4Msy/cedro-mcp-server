"""Testes de parsing: cada endpoint mockado → modelo Pydantic correto.

Exercita as tools reais (via ToolManager) contra fixtures, com httpx mockado.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings
from cedro_mcp.errors import CedroHTTPError
from cedro_mcp.server import build_server

from .conftest import BASE_URL, load_fixture

_SIGNIN_OK = httpx.Response(
    200, text="true", headers={"Set-Cookie": "JSESSIONID=abc123; Path=/"}
)


@pytest.fixture
def tool_fns(settings: Settings, client: CedroClient) -> dict:
    """Mapa nome→função das tools reais registradas no servidor."""
    mcp = build_server(settings=settings, client=client)
    tools = mcp._tool_manager.list_tools()  # noqa: SLF001 (uso interno, estável p/ teste)
    return {t.name: t.fn for t in tools}


@respx.mock
def test_md_get_quote(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/quotes/quote/PETR4").mock(
        return_value=httpx.Response(200, json=load_fixture("quote.json"))
    )
    result = tool_fns["md_get_quote"](["PETR4"])
    assert len(result) == 1
    assert result[0].symbol == "PETR4"
    assert result[0].lastTrade == 38.5
    assert result[0].marketCode == 1


@respx.mock
def test_md_get_quote_info(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    route = respx.get(f"{BASE_URL}/services/quotes/quoteInformation").mock(
        return_value=httpx.Response(200, json=load_fixture("quoteinformation.json"))
    )
    result = tool_fns["md_get_quote_info"]("PETR4")
    assert result.quotesIsinPaper == "BRPETRACNPR6"
    assert route.calls[0].request.url.params["description"] == "PETR4"


@respx.mock
def test_md_list_markets(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/quotes/listMarket").mock(
        return_value=httpx.Response(200, json=load_fixture("listmarket.json"))
    )
    result = tool_fns["md_list_markets"]()
    assert [m.name for m in result] == ["BOVESPA", "BMF"]


@respx.mock
def test_md_list_indices(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    route = respx.get(f"{BASE_URL}/services/quotes/indexList").mock(
        return_value=httpx.Response(200, json=load_fixture("indexlist.json"))
    )
    result = tool_fns["md_list_indices"](1)
    assert result[0].code == "IBOV"
    assert route.calls[0].request.url.params["marketcode"] == "1"


@respx.mock
def test_md_get_candles_last(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/quotes/candleLast/PETR4/D/2").mock(
        return_value=httpx.Response(200, json=load_fixture("candlelast.json"))
    )
    result = tool_fns["md_get_candles_last"]("PETR4", "D", 2)
    assert len(result) == 2
    assert result[0].high == 38.7


@respx.mock
def test_md_get_book_variants(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    agg = respx.get(f"{BASE_URL}/services/quotes/aggregatedBook/PETR4").mock(
        return_value=httpx.Response(200, json=load_fixture("book.json"))
    )
    mini = respx.get(f"{BASE_URL}/services/quotes/miniBook/PETR4").mock(
        return_value=httpx.Response(200, json=load_fixture("book.json"))
    )
    result = tool_fns["md_get_book"]("PETR4")  # default = aggregated
    assert result.symbol == "PETR4"
    assert len(result.compra) == 2
    assert agg.called
    tool_fns["md_get_book"]("PETR4", "mini")
    assert mini.called


@respx.mock
def test_md_get_trades_range(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(
        f"{BASE_URL}/services/quotes/quoteTimesTrade/PETR4/1/1000/0/20260101/20260107"
    ).mock(return_value=httpx.Response(200, json=load_fixture("trades.json")))
    result = tool_fns["md_get_trades_range"]("PETR4", 1, 1000, 0, "20260101", "20260107")
    assert result[0].preco == "38.50"
    assert result[0].quantidade == 100


@respx.mock
def test_md_get_player_ranking(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/quotes/playerRanking/PETR4").mock(
        return_value=httpx.Response(200, json=load_fixture("playerranking.json"))
    )
    result = tool_fns["md_get_player_ranking"]("PETR4")
    assert result[0].player == "XP INVESTIMENTOS"


@respx.mock
def test_md_get_gainers(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/quotes/highList/IBOV").mock(
        return_value=httpx.Response(200, json=load_fixture("highlist.json"))
    )
    result = tool_fns["md_get_gainers"]("IBOV")
    assert result[0].quote == "MGLU3"
    assert result[0].change == 7.36


@respx.mock
def test_news_get_last(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    )
    respx.get(f"{BASE_URL}/services/news/newsLast/5").mock(
        return_value=httpx.Response(200, json=load_fixture("newslast.json"))
    )
    result = tool_fns["news_get_last"](5)
    assert result[0].code == "1070292"
    assert result[0].title == "Ibovespa fecha em alta"


@respx.mock
def test_news_search_maps_missing_endpoint(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    )
    route = respx.get(
        f"{BASE_URL}/services/news/newsQuery/01012026/07012026/dividendos"
    ).mock(return_value=httpx.Response(200, json=[]))
    tool_fns["news_search"]("01012026", "07012026", "dividendos")
    assert route.called


@respx.mock
def test_http_error_maps_to_exception(tool_fns: dict) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/quotes/quote/XXXX").mock(
        return_value=httpx.Response(404)
    )
    with pytest.raises(CedroHTTPError) as exc:
        tool_fns["md_get_quote"](["XXXX"])
    assert exc.value.status_code == 404
