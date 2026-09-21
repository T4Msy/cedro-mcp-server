"""Utilidades de parsing compartilhadas pelas tools.

Shared parsing utilities for the tools.
"""

from __future__ import annotations

from typing import Any, TypeVar

from mcp.types import ToolAnnotations
from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)

#: Todas as 26 tools deste servidor são GETs de leitura pura contra a API Market Data — nenhuma
#: executa ação/escrita. Sem isto, `@mcp.tool()` usa os defaults do SDK, que mostram no Inspector
#: valores errados pra este caso (ex.: "Destructive: Yes", "Idempotent: No").
READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def as_list(data: Any) -> list[Any]:
    """Normaliza a resposta em lista: envolve dict solto, passa lista adiante.

    Normalizes a response into a list: wraps a lone dict, passes lists through.
    """
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


def parse_list(data: Any, model: type[M]) -> list[M]:
    """Converte a resposta numa lista de modelos, tolerando itens não-dict."""
    return [model.model_validate(item) for item in as_list(data) if isinstance(item, dict)]


def parse_one(data: Any, model: type[M]) -> M:
    """Converte a resposta num único modelo (usa o 1º item se vier lista)."""
    items = as_list(data)
    payload = items[0] if items else {}
    if not isinstance(payload, dict):
        payload = {}
    return model.model_validate(payload)
