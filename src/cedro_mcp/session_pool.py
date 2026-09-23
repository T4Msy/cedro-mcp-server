"""Pool thread-safe de sessões downstream por principal, com expiração por ociosidade e teto.

Thread-safe per-principal session pool with idle expiry and a size cap. Usado por
`client.SessionRegistry` (Market Data REST) e `trading.client.TradingSessionRegistry` — as tools
síncronas rodam em worker threads (ver `observability.instrument_tool`), então duas requisições
do mesmo principal podem pedir a sessão ao mesmo tempo.

A chave guardada é o **hash** da chave do provider, nunca ela crua: no login pelo navegador a
chave é o próprio access token do chamador.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")

#: Sessão sem uso há mais que isto é descartada. Longo de propósito: descartar força um novo
#: `SignIn`, e a conta Market Data tolera poucos logins por dia.
DEFAULT_IDLE_TTL = 12 * 3600.0
#: Teto de sessões simultâneas por processo; acima disso sai a usada há mais tempo (LRU).
DEFAULT_MAX_SIZE = 1_000


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class SessionPool(Generic[T]):
    """Uma sessão por chave, criada sob lock (nunca duas para a mesma chave) e expirada por LRU."""

    def __init__(
        self,
        *,
        close: Callable[[T], None],
        idle_ttl: float = DEFAULT_IDLE_TTL,
        max_size: int = DEFAULT_MAX_SIZE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._close = close
        self._idle_ttl = idle_ttl
        self._max_size = max_size
        self._clock = clock
        self._lock = threading.Lock()
        #: hash da chave → (sessão, último uso). Ordem = LRU (mais antiga primeiro).
        self._entries: OrderedDict[str, tuple[T, float]] = OrderedDict()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get_or_create(self, key: str, factory: Callable[[], T]) -> T:
        hashed = hash_key(key)
        now = self._clock()
        with self._lock:
            evicted = self._evict_idle(now)
            entry = self._entries.get(hashed)
            if entry is not None:
                session = entry[0]
                self._entries.move_to_end(hashed)
            else:
                session = factory()
                while len(self._entries) >= self._max_size:
                    evicted.append(self._entries.popitem(last=False)[1][0])
            self._entries[hashed] = (session, now)
        # Fecha fora do lock: close pode fazer I/O.
        for old in evicted:
            self._close(old)
        return session

    def close_all(self) -> None:
        with self._lock:
            sessions = [session for session, _ in self._entries.values()]
            self._entries.clear()
        for session in sessions:
            self._close(session)

    def _evict_idle(self, now: float) -> list[T]:
        evicted: list[T] = []
        while self._entries:
            hashed, (session, last_used) = next(iter(self._entries.items()))
            if now - last_used <= self._idle_ttl:
                break
            del self._entries[hashed]
            evicted.append(session)
        return evicted
