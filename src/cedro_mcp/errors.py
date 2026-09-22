"""Exceções do cliente Cedro, traduzidas em erros claros de tool.

Cedro client exceptions, surfaced as clear tool errors.
"""

from __future__ import annotations


class CedroError(RuntimeError):
    """Erro base do cliente Cedro."""


class CedroAuthError(CedroError):
    """Falha de autenticação (401) ou credenciais ausentes.

    Authentication failure (401) or missing credentials.
    """


class CedroEntitlementError(CedroError):
    """Chamador autenticado, mas sem o escopo/contrato exigido pela tool.

    Authenticated caller lacking the scope/contract required by the tool.
    """


class CedroHTTPError(CedroError):
    """Resposta HTTP de erro (404/405/408/504/…)."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class CedroStreamError(CedroError):
    """Falha de conexão, autenticação ou snapshot do Socket Crystal."""


class CedroValidationError(CedroError):
    """Combinação de parâmetros inválida numa tool consolidada (ex.: `mode` exige outro campo).

    Erro do lado do chamador, antes de qualquer chamada à API da Cedro — não é HTTP nem auth.
    """
