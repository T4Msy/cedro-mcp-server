"""Autenticação e autorização do **chamador** do MCP (IAM da Cedro + API key).

Caller-side auth/authorization. Não confundir com ``sessions.py``, que cuida da
autenticação **do MCP contra as APIs da Cedro** (downstream).
"""

from __future__ import annotations

from .entitlements import EntitledFastMCP, require_scope, tool_scopes
from .scopes import MARKETDATA_NEWS, MARKETDATA_READ, scopes_from_claims
from .token_verifier import CedroTokenVerifier

__all__ = [
    "EntitledFastMCP",
    "require_scope",
    "tool_scopes",
    "MARKETDATA_READ",
    "MARKETDATA_NEWS",
    "scopes_from_claims",
    "CedroTokenVerifier",
]
