"""API keys — credencial alternativa para **integrações automatizadas** (sem tela de login).

API keys for automated integrations. O store padrão lê de variável de ambiente, o que destrava o
desenvolvimento; o store definitivo (IAM/DB) é só outra implementação de :class:`ApiKeyStore`.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiKeyPrincipal:
    """Identidade resolvida a partir de uma API key."""

    subject: str
    scopes: tuple[str, ...]


class ApiKeyStore(Protocol):
    """Resolve uma API key crua num principal (ou ``None`` se inválida)."""

    def lookup(self, api_key: str) -> ApiKeyPrincipal | None: ...


class EnvApiKeyStore:
    """Store em memória, carregado de uma string de ambiente.

    Formato (``CEDRO_API_KEYS``), registros separados por ``;``::

        <key>:<subject>:<escopos>

    onde ``<escopos>`` é uma lista separada por ``|``. Exemplo::

        k_abc:robo-cotacoes:marketdata:read;k_xyz:robo-news:marketdata:read|marketdata:news

    O primeiro registro dá ``key=k_abc``, ``subject=robo-cotacoes``, ``scopes=("marketdata:read",)``.
    """

    def __init__(self, raw: str | None) -> None:
        self._keys: dict[str, ApiKeyPrincipal] = {}
        for position, record in enumerate((raw or "").split(";")):
            record = record.strip()
            if not record:
                continue
            # Os DOIS primeiros ":" separam key/subject; todo o resto é a lista de escopos —
            # que contém ":" (ex.: "marketdata:read"), daí o maxsplit=2.
            parts = record.split(":", 2)
            if len(parts) != 3:
                # Nunca logar `record` cru — pode conter a própria API key.
                logger.warning(
                    "CEDRO_API_KEYS: registro na posição %d não segue o formato "
                    "key:subject:escopos — ignorado.",
                    position,
                )
                continue
            key, subject, scopes_raw = parts
            scopes = tuple(s for s in scopes_raw.split("|") if s)
            if not (key and subject and scopes):
                logger.warning(
                    "CEDRO_API_KEYS: registro incompleto na posição %d (subject=%r) — ignorado.",
                    position,
                    subject or "<vazio>",
                )
                continue
            self._keys[key] = ApiKeyPrincipal(subject=subject, scopes=scopes)

    def __len__(self) -> int:
        return len(self._keys)

    def lookup(self, api_key: str) -> ApiKeyPrincipal | None:
        """Compara em tempo constante para não vazar a chave por timing."""
        for known, principal in self._keys.items():
            if hmac.compare_digest(known, api_key):
                return principal
        return None
