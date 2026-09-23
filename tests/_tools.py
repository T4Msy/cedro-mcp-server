"""Helper de teste: funções originais (síncronas) das tools registradas.

``EntitledFastMCP`` envolve cada tool num runner assíncrono (``observability.instrument_tool``);
``__wrapped__`` devolve a função registrada, com o gate de escopo incluído.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def tool_functions(tools: Iterable[Any]) -> dict[str, Any]:
    return {t.name: getattr(t.fn, "__wrapped__", t.fn) for t in tools}
