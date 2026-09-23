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

from .trading.models import (
    OPEN_ORDER_STATES,
    ORD_TYPE_BY_MODE,
    ORDER_STATUSES,
    REQUIRED_FIELDS_BY_MODE,
    TIME_IN_FORCE_DESCRIPTIONS,
)

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


def render_trading_reference() -> str:
    """Markdown gerado das tabelas de `trading/models.py` — a mesma fonte que valida as ordens."""
    lines = [
        "# Referência de Trading (Cedro)",
        "",
        "Toda ordem passa por `trading_preview_order` → confirmação explícita do usuário → "
        "`trading_confirm`.",
        "",
        "## Tipos de ordem (`mode`)",
        "",
        "| mode | type (OMS) | Campos obrigatórios além dos comuns |",
        "|---|---|---|",
    ]
    for mode, required in REQUIRED_FIELDS_BY_MODE.items():
        fields = ", ".join(f"`{f}`" for f in required) or "—"
        lines.append(f"| `{mode}` | `{ORD_TYPE_BY_MODE[mode]}` | {fields} |")
    lines += [
        "",
        "Comuns a todos: `market` (XBSP/XBMF), `symbol`, `side` (BUY/SELL), `qty`, `account`. "
        "`mode=market` não leva `clordid` — cuidado redobrado com reenvio.",
        "",
        "## Validade (`time_in_force`)",
        "",
    ]
    lines += [f"- `{code}` — {desc}" for code, desc in TIME_IN_FORCE_DESCRIPTIONS.items()]
    lines += ["", "## Status de ordem (`state`)", ""]
    for code, desc in ORDER_STATUSES.items():
        suffix = " *(em aberto)*" if code in OPEN_ORDER_STATES else ""
        lines.append(f"- `{code}` — {desc}{suffix}")
    lines += [
        "",
        "## O que esta API não tem",
        "",
        "Posição, custódia, saldo e limite de risco não existem na API de Trading (são do "
        "Backoffice/Risk). `trading_get_day_summary` mostra só o executado HOJE.",
    ]
    return "\n".join(lines)


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

    @mcp.resource("cedro-ref://trading", mime_type="text/markdown")
    def trading_reference() -> str:
        """Referência de Trading: tipos de ordem e campos obrigatórios, validade e status.

        Trading reference generated from the server's own validation tables — always in sync
        with what trading_preview_order accepts.
        """
        return render_trading_reference()

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
