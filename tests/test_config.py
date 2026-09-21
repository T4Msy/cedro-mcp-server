"""Testes de `load_settings`: default seguro de docs_path e validação de MCP_TRANSPORT."""

from __future__ import annotations

from pathlib import Path

import pytest

from cedro_mcp.config import ConfigurationError, DEFAULT_DOCS_PATH, load_settings


def test_docs_path_defaults_to_curated_skill_not_the_vault() -> None:
    settings = load_settings({})
    assert settings.docs_path == Path(DEFAULT_DOCS_PATH)
    assert "API's Cedro" not in str(settings.docs_path)


def test_docs_path_honors_explicit_override() -> None:
    settings = load_settings({"CEDRO_DOCS_PATH": "/tmp/custom-docs"})
    assert settings.docs_path == Path("/tmp/custom-docs")


@pytest.mark.parametrize("value", ["stdio", "streamable-http", "STDIO", " streamable-http "])
def test_transport_accepts_known_values(value: str) -> None:
    settings = load_settings({"MCP_TRANSPORT": value})
    assert settings.transport in ("stdio", "streamable-http")


def test_transport_rejects_sse_instead_of_silently_treating_as_streamable_http() -> None:
    with pytest.raises(ConfigurationError, match="MCP_TRANSPORT"):
        load_settings({"MCP_TRANSPORT": "sse"})


def test_transport_rejects_unknown_value() -> None:
    with pytest.raises(ConfigurationError, match="MCP_TRANSPORT"):
        load_settings({"MCP_TRANSPORT": "websocket"})


def test_transport_defaults_to_streamable_http_when_unset() -> None:
    settings = load_settings({})
    assert settings.transport == "streamable-http"
