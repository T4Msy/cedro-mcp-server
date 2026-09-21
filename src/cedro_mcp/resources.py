"""Resources ``cedro-docs://`` — expõem as notas de documentação para a IA consultar.

Exposes the documentation notes as ``cedro-docs://`` resources so the AI can read the endpoint
contracts it is calling. ``docs_path`` aponta para uma pasta de documentação curada e destinada a
cliente (a skill ``market-data-rest``), nunca para o vault interno completo.

**Esquema de URI:** ``cedro-docs://note/<token>`` onde ``<token>`` é um identificador **sem barras
nem espaços** (o matcher de templates do FastMCP compila ``{token}`` como ``[^/]+``, então caminhos
com ``/`` não casariam — por isso notas em subpasta usam um token com ``/`` trocado por ``__``). O
token é resolvido por um mapa construído a partir dos arquivos reais, o que também elimina qualquer
risco de path traversal por construção.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from .config import Settings

#: Teto de tamanho pra leitura de uma nota — a pasta de docs é controlada pelo operador (não por
#: input do chamador), mas não custa nada ter um limite defensivo antes de carregar tudo em memória.
_MAX_NOTE_BYTES = 1_000_000


def _slug(rel: str) -> str:
    """Token de URI sem barras nem espaços (barra→'__', espaço→'_')."""
    return rel.replace("/", "__").replace(" ", "_")


def build_note_map(root: Path) -> dict[str, Path]:
    """Mapa ``token → arquivo`` das notas de documentação (com desambiguação de colisões)."""
    mapping: dict[str, Path] = {}
    for note in sorted(root.rglob("*.md")):
        rel = note.relative_to(root).as_posix()
        token = _slug(rel)
        if token in mapping:  # colisão improvável — desambigua determinística
            i = 2
            while f"{token}-{i}" in mapping:
                i += 1
            token = f"{token}-{i}"
        mapping[token] = note
    return mapping


def register(mcp: "FastMCP", settings: "Settings") -> None:
    docs_root = settings.docs_path

    @mcp.resource("cedro-docs://index")
    def docs_index() -> str:
        """Índice das notas de documentação (cedro-docs://). Leia uma nota por seu token.

        Index of the documentation notes; read one via its ``cedro-docs://note/<token>`` URI.
        """
        if not docs_root.is_dir():
            return f"(documentação não encontrada em {docs_root})"
        mapping = build_note_map(docs_root)
        lines = [f"# Documentação Market Data ({len(mapping)} notas)", ""]
        # Ordena pela nota (caminho legível), mostrando o URI de leitura ao lado.
        for token, path in sorted(mapping.items(), key=lambda kv: kv[1]):
            rel = path.relative_to(docs_root).as_posix()
            lines.append(f"- {rel}\n  → cedro-docs://note/{token}")
        return "\n".join(lines)

    @mcp.resource("cedro-docs://note/{token}")
    def docs_note(token: str) -> str:
        """Conteúdo de uma nota, pelo token listado em ``cedro-docs://index``.

        A note's content, by the token listed in the index.
        """
        target = build_note_map(docs_root).get(token)
        if target is None or not target.is_file():
            raise ValueError(f"Nota não encontrada para o token: {token}")
        if target.stat().st_size > _MAX_NOTE_BYTES:
            raise ValueError(f"Nota grande demais pra ler de uma vez: {token}")
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Nota não está em UTF-8 válido: {token}") from exc
