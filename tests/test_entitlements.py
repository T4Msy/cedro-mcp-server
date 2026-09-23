"""Entitlements: o cliente só VÊ e só EXECUTA as tools do plano que contratou."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from cedro_mcp.auth.scopes import MARKETDATA_NEWS, MARKETDATA_READ, MARKETDATA_STREAM
from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings
from cedro_mcp.errors import CedroEntitlementError
from cedro_mcp.server import build_server

from ._principal import as_principal
from ._tools import tool_functions
from .conftest import BASE_URL

MARKET_TOOLS = 14
NEWS_TOOLS = 3
#: 3 leitura (trading_list_orders_today, trading_get_order_history, trading_get_day_summary) + 4 escrita
#: (preview_order, preview_cancel_order, preview_edit_order, confirm).
TRADING_TOOLS = 7
STREAM_TOOLS = 5
#: account_get_usage — visível para qualquer escopo (consulta a própria cota).
ACCOUNT_TOOLS = 1


def _tool_names(mcp) -> set[str]:
    return {t.name for t in asyncio.run(mcp.list_tools())}


def _fns(mcp) -> dict:
    return tool_functions(mcp._tool_manager.list_tools())  # noqa: SLF001


# ---- listagem filtrada -----------------------------------------------------


def test_read_only_token_hides_news_tools(settings: Settings, client: CedroClient) -> None:
    mcp = build_server(settings=settings, client=client)
    with as_principal(MARKETDATA_READ):
        names = _tool_names(mcp)
    assert len(names) == MARKET_TOOLS + ACCOUNT_TOOLS
    assert not any(n.startswith("news_") for n in names)


def test_full_token_lists_all_tools(settings: Settings, client: CedroClient) -> None:
    mcp = build_server(settings=settings, client=client)
    with as_principal(MARKETDATA_READ, MARKETDATA_NEWS):
        names = _tool_names(mcp)
    assert len(names) == MARKET_TOOLS + NEWS_TOOLS + ACCOUNT_TOOLS
    assert len([n for n in names if n.startswith("news_")]) == NEWS_TOOLS


def test_stream_scope_lists_only_streaming_tools(settings: Settings, client: CedroClient) -> None:
    mcp = build_server(settings=settings, client=client)
    with as_principal(MARKETDATA_STREAM):
        names = _tool_names(mcp)
    assert len(names) == STREAM_TOOLS + ACCOUNT_TOOLS
    assert all(name.startswith(("stream_", "account_")) for name in names)


def test_no_auth_context_lists_everything(settings: Settings, client: CedroClient) -> None:
    """Sem autenticação ativa (stdio/dev), nada é filtrado."""
    mcp = build_server(settings=settings, client=client)
    assert len(_tool_names(mcp)) == (
        MARKET_TOOLS + NEWS_TOOLS + TRADING_TOOLS + STREAM_TOOLS + ACCOUNT_TOOLS
    )


# ---- execução negada -------------------------------------------------------


def test_news_tool_denied_without_news_scope(settings: Settings, client: CedroClient) -> None:
    """Esconder da listagem não basta: chamar direto também tem de ser negado."""
    fns = _fns(build_server(settings=settings, client=client))
    with as_principal(MARKETDATA_READ):
        with pytest.raises(CedroEntitlementError, match="marketdata:news"):
            fns["news_search"](count=5)


def test_market_tool_denied_without_read_scope(settings: Settings, client: CedroClient) -> None:
    fns = _fns(build_server(settings=settings, client=client))
    with as_principal(MARKETDATA_NEWS):
        with pytest.raises(CedroEntitlementError, match="marketdata:read"):
            fns["md_list_markets"]()


def test_stream_tool_denied_without_stream_scope(settings: Settings, client: CedroClient) -> None:
    fns = _fns(build_server(settings=settings, client=client))
    with as_principal(MARKETDATA_READ):
        with pytest.raises(CedroEntitlementError, match="marketdata:stream"):
            fns["stream_status"]()


@respx.mock
def test_tool_allowed_with_correct_scope_executes(
    settings: Settings, client: CedroClient
) -> None:
    """Com o escopo certo, o decorator sai da frente e a tool executa normalmente."""
    respx.post(f"{BASE_URL}/SignIn").mock(
        return_value=httpx.Response(
            200, text="true", headers={"Set-Cookie": "JSESSIONID=abc; Path=/"}
        )
    )
    respx.get(f"{BASE_URL}/services/quotes/listMarket").mock(
        return_value=httpx.Response(200, json=[{"code": "1", "name": "BOVESPA"}])
    )

    fns = _fns(build_server(settings=settings, client=client))
    with as_principal(MARKETDATA_READ):
        result = fns["md_list_markets"]()
    assert [m.name for m in result] == ["BOVESPA"]
