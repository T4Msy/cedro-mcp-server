"""Testes de registro do servidor: tools e resources esperados presentes."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from cedro_mcp.client import CedroClient
from cedro_mcp.config import ConfigurationError, Settings
from cedro_mcp.server import build_server, build_token_verifier

EXPECTED_TOOLS = {
    # quotes
    "md_get_quote",
    "md_get_quote_info",
    "md_list_markets",
    "md_list_indices",
    "md_get_index_assets",
    "md_get_company_quotes",
    "md_list_options",
    # candles
    "md_get_candles_last",
    "md_get_candles_range",
    # book
    "md_get_book",
    # trades
    "md_get_trades_range",
    "md_get_trades_date",
    # rankings / volume / movers
    "md_get_player_ranking",
    "md_get_cross_ranking",
    "md_get_volume_at_price",
    "md_get_gainers",
    "md_get_losers",
    # news (inclui os 3 antes ausentes)
    "news_get_last",
    "news_get_by_code",
    "news_list_agencies",
    "news_search",
    "news_relevant_facts_by_agency",
}


def _server(settings: Settings, client: CedroClient):
    return build_server(settings=settings, client=client)


def test_all_expected_tools_registered(settings: Settings, client: CedroClient) -> None:
    mcp = _server(settings, client)
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    missing = EXPECTED_TOOLS - names
    assert not missing, f"tools faltando: {missing}"


def test_tool_count_matches_blueprint_scope(settings: Settings, client: CedroClient) -> None:
    mcp = _server(settings, client)
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    # F1: 17 tools de cotações/candles/book/negócios/rankings + 9 de notícias + 6 de Trading
    # (Fase 1 do roadmap "Cedro Connect IA").
    assert len([n for n in names if n.startswith("md_")]) == 17
    assert len([n for n in names if n.startswith("news_")]) == 9
    assert len([n for n in names if n.startswith("trading_")]) == 6


def test_docs_resources_registered(settings: Settings, client: CedroClient) -> None:
    mcp = _server(settings, client)
    resources = asyncio.run(mcp.list_resources())
    uris = {str(r.uri) for r in resources}
    assert "cedro-docs://index" in uris


# ---- guarda contra auth "falha aberta" -------------------------------------


def test_build_server_refuses_http_without_auth(settings: Settings, client: CedroClient) -> None:
    """streamable-http sem CEDRO_IAM_ISSUER/MCP_RESOURCE_URL deve recusar montar, não expor
    as tools silenciosamente sem autenticação."""
    unsafe = replace(settings, transport="streamable-http")
    with pytest.raises(ConfigurationError, match="CEDRO_IAM_ISSUER"):
        build_server(settings=unsafe, client=client)


def test_build_server_allows_http_without_auth_when_opted_in(
    settings: Settings, client: CedroClient
) -> None:
    """O opt-in explícito (MCP_ALLOW_UNAUTHENTICATED_HTTP) deve funcionar normalmente."""
    unsafe_but_opted_in = replace(
        settings, transport="streamable-http", allow_unauthenticated_http=True
    )
    build_server(settings=unsafe_but_opted_in, client=client)  # não deve levantar


def test_build_server_guard_can_be_disabled_explicitly(
    settings: Settings, client: CedroClient
) -> None:
    """`enforce_auth_guard=False` é a saída de emergência pra quem realmente precisa."""
    unsafe = replace(settings, transport="streamable-http")
    build_server(settings=unsafe, client=client, enforce_auth_guard=False)  # não deve levantar


def test_build_server_stdio_without_auth_is_unaffected(
    settings: Settings, client: CedroClient
) -> None:
    """stdio sem auth continua sendo o caminho normal de desenvolvimento local."""
    build_server(settings=settings, client=client)  # settings já é stdio; não deve levantar


# ---- audience obrigatório quando o IAM está habilitado ----------------------


def test_build_token_verifier_requires_audience_when_iam_enabled(settings: Settings) -> None:
    iam_settings = replace(
        settings,
        iam_issuer="https://sso.cedrotech.com",
        iam_jwks_url="https://sso.cedrotech.com/.well-known/jwks.json",
        iam_audience=None,
    )
    with pytest.raises(ConfigurationError, match="CEDRO_IAM_AUDIENCE"):
        build_token_verifier(iam_settings)


def test_build_token_verifier_ok_with_audience(settings: Settings) -> None:
    iam_settings = replace(
        settings,
        iam_issuer="https://sso.cedrotech.com",
        iam_jwks_url="https://sso.cedrotech.com/.well-known/jwks.json",
        iam_audience="cedro-mcp",
    )
    build_token_verifier(iam_settings)  # não deve levantar
