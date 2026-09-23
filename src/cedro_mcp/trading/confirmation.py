"""Gate de confirmação humana em duas etapas para toda tool de Trading que escreve.

`preview` monta e valida a ordem/cancelamento/edição, nunca chama a B3, e devolve um resumo +
token. `confirm` (uma única tool, `trading_confirm`) usa o token pra executar de fato — o token
amarra o payload exato gerado no preview, então não dá pra "confirmar" uma ordem diferente da que
foi mostrada ao usuário. TTL curto e uso único (``pop`` atômico no store).

O token também fica amarrado ao **dono** (a chave de sessão de quem fez o preview): se vazar, outro
chamador autenticado não consegue executá-lo com a sessão dele.

Vive no store (``store.py``): com Redis, o preview pode acontecer numa réplica e o confirm em
outra. A chave é o hash do token, nunca o token.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from typing import Literal

from ..errors import CedroError
from ..session_pool import hash_key
from ..store import MemoryStore, Store

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
    #: Hash da chave de sessão de quem fez o preview — nunca a chave crua (pode ser o token).
    owner: str


class ConfirmationStore:
    """Ações pendentes de confirmação, por token de uso único."""

    def __init__(self, store: Store | None = None, ttl: float = _CONFIRMATION_TTL) -> None:
        self._store = store or MemoryStore()
        self._ttl = ttl

    @staticmethod
    def _key(token: str) -> str:
        return f"confirm:{hash_key(token)}"

    def create(
        self,
        kind: ActionKind,
        *,
        owner: str,
        summary: str,
        params: dict[str, str],
        endpoint: str | None = None,
    ) -> str:
        token = secrets.token_urlsafe(24)
        action = PendingAction(
            kind=kind, summary=summary, endpoint=endpoint, params=params, owner=hash_key(owner)
        )
        self._store.set(self._key(token), json.dumps(asdict(action)).encode(), ttl=self._ttl)
        return token

    def pop(self, token: str, *, owner: str) -> PendingAction:
        """Consome o token — uso único. Levanta se inválido, expirado, já usado ou de outro dono.

        Token de outro dono também é consumido (descartado): quem o apresentou não devia tê-lo, e
        o dono legítimo refaz o preview.
        """
        raw = self._store.pop(self._key(token))
        if raw is None:
            raise CedroError(
                "Token de confirmação inválido, expirado (validade de "
                f"{int(self._ttl)}s) ou já usado. Chame a tool de preview de novo."
            )
        action = PendingAction(**json.loads(raw))
        if not secrets.compare_digest(action.owner, hash_key(owner)):
            raise CedroError(
                "Token de confirmação emitido para outra sessão — descartado. Refaça o preview "
                "com a sua própria sessão."
            )
        return action
