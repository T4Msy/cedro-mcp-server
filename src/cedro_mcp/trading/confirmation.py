"""Gate de confirmação humana em duas etapas para toda tool de Trading que escreve.

`preview` monta e valida a ordem/cancelamento/edição, nunca chama a B3, e devolve um resumo +
token. `confirm` (uma única tool, `trading_confirm`) usa o token pra executar de fato — o token
amarra o payload exato gerado no preview, então não dá pra "confirmar" uma ordem diferente da que
foi mostrada ao usuário. Mesmo padrão de `_gc_flows()` em `web_login.py`: TTL curto, em memória,
nunca persistido, de uso único.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Literal

from ..errors import CedroError

ActionKind = Literal["place_order", "cancel_order", "edit_order"]

#: Tempo pra ler o resumo e confirmar — curto de propósito (ordem real, preço pode mudar).
_CONFIRMATION_TTL = 120.0


@dataclass
class PendingAction:
    kind: ActionKind
    summary: str
    #: Endpoint só faz sentido para `place_order` (varia por tipo de ordem); cancel/edit têm
    #: endpoint fixo, resolvido em `tools/trading.py` na hora de executar.
    endpoint: str | None
    params: dict[str, str]
    created_at: float = field(default_factory=time.monotonic)


class ConfirmationStore:
    """Registro em memória de ações pendentes de confirmação, por token de uso único."""

    def __init__(self, ttl: float = _CONFIRMATION_TTL) -> None:
        self._ttl = ttl
        self._pending: dict[str, PendingAction] = {}

    def create(
        self, kind: ActionKind, *, summary: str, params: dict[str, str], endpoint: str | None = None
    ) -> str:
        self._gc()
        token = secrets.token_urlsafe(24)
        self._pending[token] = PendingAction(
            kind=kind, summary=summary, endpoint=endpoint, params=params
        )
        return token

    def pop(self, token: str) -> PendingAction:
        """Consome o token — uso único. Levanta se inválido, expirado ou já usado."""
        self._gc()
        action = self._pending.pop(token, None)
        if action is None:
            raise CedroError(
                "Token de confirmação inválido, expirado (validade de "
                f"{int(self._ttl)}s) ou já usado. Chame a tool de preview de novo."
            )
        return action

    def _gc(self) -> None:
        now = time.monotonic()
        stale = [t for t, a in self._pending.items() if now - a.created_at > self._ttl]
        for t in stale:
            self._pending.pop(t, None)
