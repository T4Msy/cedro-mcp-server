"""Testes de `cedro-docs://`: leitura de nota (raiz e subpasta), guarda de path-traversal,
arquivo grande demais e arquivo não-UTF8.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings
from cedro_mcp.server import build_server


def _read(settings: Settings, client: CedroClient, uri: str) -> str:
    mcp = build_server(settings=settings, client=client)
    contents = asyncio.run(mcp.read_resource(uri))
    return list(contents)[0].content


def test_docs_note_reads_valid_note(
    tmp_path: Path, settings: Settings, client: CedroClient
) -> None:
    (tmp_path / "nota.md").write_text("# Título\nConteúdo da nota.", encoding="utf-8")
    docs_settings = replace(settings, docs_path=tmp_path)
    content = _read(docs_settings, client, "cedro-docs://note/nota.md")
    assert content == "# Título\nConteúdo da nota."


def test_docs_note_reads_note_in_subfolder(
    tmp_path: Path, settings: Settings, client: CedroClient
) -> None:
    # O template de resource do FastMCP casa `{token}` com `[^/]+` (regex sem barra), então uma
    # nota em subpasta precisa de um token sem "/" — resolvido pelo mapa token→arquivo, que troca
    # "/" por "__" na hora de gerar o token.
    (tmp_path / "_shared" / "references").mkdir(parents=True)
    (tmp_path / "_shared" / "references" / "ENDPOINTS.md").write_text(
        "# Endpoints", encoding="utf-8"
    )
    docs_settings = replace(settings, docs_path=tmp_path)
    content = _read(
        docs_settings, client, "cedro-docs://note/_shared__references__ENDPOINTS.md"
    )
    assert content == "# Endpoints"


def test_docs_note_rejects_path_traversal(
    tmp_path: Path, settings: Settings, client: CedroClient
) -> None:
    # A busca é por token no mapa construído a partir dos arquivos reais (build_note_map) — não
    # há resolução de path a partir do token, então ".." (ou qualquer token desconhecido) nunca
    # bate em nenhuma entrada do mapa e cai direto no caso de "não encontrada".
    (tmp_path / "vault").mkdir()
    docs_settings = replace(settings, docs_path=tmp_path / "vault")
    with pytest.raises(ValueError, match="não encontrada"):
        _read(docs_settings, client, "cedro-docs://note/..")


def test_docs_note_missing_file_raises(
    tmp_path: Path, settings: Settings, client: CedroClient
) -> None:
    docs_settings = replace(settings, docs_path=tmp_path)
    with pytest.raises(ValueError, match="não encontrada"):
        _read(docs_settings, client, "cedro-docs://note/nao-existe.md")


def test_docs_note_rejects_oversized_file(
    tmp_path: Path, settings: Settings, client: CedroClient
) -> None:
    big = tmp_path / "grande.md"
    big.write_bytes(b"a" * (1_000_000 + 1))
    docs_settings = replace(settings, docs_path=tmp_path)
    with pytest.raises(ValueError, match="grande demais"):
        _read(docs_settings, client, "cedro-docs://note/grande.md")


def test_docs_note_rejects_non_utf8_file(
    tmp_path: Path, settings: Settings, client: CedroClient
) -> None:
    bad = tmp_path / "binario.md"
    bad.write_bytes(b"\xff\xfe\x00\x01invalid-utf8")
    docs_settings = replace(settings, docs_path=tmp_path)
    with pytest.raises(ValueError, match="UTF-8"):
        _read(docs_settings, client, "cedro-docs://note/binario.md")
