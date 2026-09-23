"""Tools rodam fora do event loop, enxergam o principal e cada chamada é logada."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from mcp.server.auth.middleware.auth_context import get_access_token

from cedro_mcp.auth.entitlements import EntitledFastMCP
from cedro_mcp.config import ConfigurationError, load_settings

from ._principal import as_principal


def test_sync_tool_runs_in_worker_thread_and_sees_the_principal() -> None:
    mcp = EntitledFastMCP("t")
    seen: dict = {}

    @mcp.tool()
    def probe() -> str:
        seen["thread"] = threading.get_ident()
        token = get_access_token()
        seen["subject"] = token.subject if token else None
        return "ok"

    with as_principal("marketdata:read", subject="cliente-x"):
        asyncio.run(mcp.call_tool("probe", {}))
    assert seen["thread"] != threading.get_ident()
    assert seen["subject"] == "cliente-x"


def test_slow_sync_tool_does_not_block_the_event_loop() -> None:
    mcp = EntitledFastMCP("t")

    @mcp.tool()
    def slow() -> str:
        time.sleep(0.3)
        return "ok"

    async def scenario() -> float:
        """Devolve quanto tempo o loop levou para dar 5 ticks de 20 ms com a tool rodando."""
        task = asyncio.ensure_future(mcp.call_tool("slow", {}))
        await asyncio.sleep(0)  # deixa a tool começar
        started = time.perf_counter()
        for _ in range(5):
            await asyncio.sleep(0.02)
        elapsed = time.perf_counter() - started
        await task
        return elapsed

    # Bloqueando o loop, os ticks só andariam depois dos 0,3 s da tool.
    assert asyncio.run(scenario()) < 0.25


def test_tool_schema_is_preserved_by_the_wrapper() -> None:
    mcp = EntitledFastMCP("t")

    @mcp.tool()
    def md_example(symbol: str, count: int = 5) -> list[str]:
        """Docstring da tool."""
        return [symbol] * count

    (tool,) = asyncio.run(mcp.list_tools())
    assert tool.name == "md_example"
    assert tool.description == "Docstring da tool."
    assert set(tool.inputSchema["properties"]) == {"symbol", "count"}
    assert tool.inputSchema["required"] == ["symbol"]


def test_tool_calls_are_logged_without_arguments(caplog: pytest.LogCaptureFixture) -> None:
    mcp = EntitledFastMCP("t")

    @mcp.tool()
    def boom(secret_arg: str) -> str:
        raise ValueError("falhou")

    caplog.set_level("INFO", logger="cedro_mcp.tools")
    with as_principal("marketdata:read", subject="cliente-x"):
        with pytest.raises(Exception, match="falhou"):
            asyncio.run(mcp.call_tool("boom", {"secret_arg": "nao-logar"}))
    assert "tool=boom" in caplog.text
    assert "outcome=error:ValueError" in caplog.text
    assert "cliente-x#" in caplog.text
    assert "nao-logar" not in caplog.text
    assert "test-token" not in caplog.text


def test_log_level_is_validated() -> None:
    assert load_settings({"MCP_LOG_LEVEL": "debug"}).log_level == "DEBUG"
    assert load_settings({}).log_level == "INFO"
    with pytest.raises(ConfigurationError, match="MCP_LOG_LEVEL"):
        load_settings({"MCP_LOG_LEVEL": "verbose"})
