"""Estado compartilhável do servidor: memória (padrão, por processo) ou Redis (entre réplicas).

Shared server state: in-memory (default, per process) or Redis (across replicas and restarts).

O que mora aqui — tudo que precisa sobreviver a restart ou ser visto por outra réplica:

- rate limit (janela deslizante por token e por IP) — ``http_app.py``;
- tokens de confirmação de Trading — ``trading/confirmation.py``;
- clientes OAuth, flows, códigos e tokens do login pelo navegador — ``web_login.py``;
- contadores de cota mensal por plano — ``quota.py``;
- trilha de auditoria de Trading (log só-de-anexar) — ``observability.py``.

O que **não** mora aqui, de propósito: as sessões downstream (``JSESSIONID``/``httpx.Client`` de
``session_pool.py``) e o conector Socket. São objetos vivos de conexão, locais ao processo; cada
réplica faz o próprio ``SignIn`` e o mantém por até 12 h.

Credenciais nunca entram cruas no Redis — ``SecretBox`` cifra antes (ver ``web_login.py``). As
chaves também nunca são o token cru: quem grava usa ``session_pool.hash_key``.

API síncrona de propósito: as tools rodam em worker threads. Código async chama pelo
:func:`call` para não bloquear o event loop com I/O de rede do Redis.
"""

from __future__ import annotations

import base64
import hashlib
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

import anyio.to_thread
from cryptography.fernet import Fernet, InvalidToken

from .config import ConfigurationError, Settings

T = TypeVar("T")

KEY_PREFIX = "cedro-mcp:"


class Store(Protocol):
    #: True quando as operações são só memória local — dispensa pular para uma thread.
    is_local: bool

    def get(self, key: str) -> bytes | None: ...

    def set(self, key: str, value: bytes, ttl: float | None = None) -> None: ...

    def pop(self, key: str) -> bytes | None:
        """Lê e apaga atomicamente — base de tudo que é de uso único."""
        ...

    def delete(self, key: str) -> None: ...

    def incr(self, key: str, ttl: float) -> int:
        """Incrementa um contador; o TTL é aplicado quando ele nasce."""
        ...

    def window_hit(self, key: str, window: float, now: float | None = None) -> int:
        """Registra um hit numa janela deslizante e devolve quantos há dentro dela."""
        ...

    def append_log(self, key: str, entry: bytes, maxlen: int) -> None:
        """Acrescenta a um log só-de-anexar, guardando no máximo ``maxlen`` entradas."""
        ...

    def read_log(self, key: str, count: int) -> list[bytes]:
        """Últimas ``count`` entradas do log, da mais recente para a mais antiga."""
        ...

    def ping(self) -> bool: ...


async def call(store: Store, fn: Callable[..., T], *args: Any) -> T:
    """Executa uma operação do store a partir de código async sem travar o event loop."""
    if store.is_local:
        return fn(*args)
    return await anyio.to_thread.run_sync(fn, *args)


class MemoryStore:
    """Tudo em dicionários do processo — o comportamento de sempre. Some no restart."""

    is_local = True

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._values: dict[str, tuple[bytes, float | None]] = {}
        self._windows: dict[str, deque[float]] = {}
        self._logs: dict[str, deque[bytes]] = {}
        self._last_sweep = float("-inf")

    def _expired(self, expires_at: float | None) -> bool:
        return expires_at is not None and self._clock() >= expires_at

    def get(self, key: str) -> bytes | None:
        with self._lock:
            entry = self._values.get(key)
            if entry is None:
                return None
            if self._expired(entry[1]):
                del self._values[key]
                return None
            return entry[0]

    def set(self, key: str, value: bytes, ttl: float | None = None) -> None:
        expires_at = self._clock() + ttl if ttl is not None else None
        with self._lock:
            self._gc()
            self._values[key] = (value, expires_at)

    def pop(self, key: str) -> bytes | None:
        with self._lock:
            entry = self._values.pop(key, None)
        if entry is None or self._expired(entry[1]):
            return None
        return entry[0]

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)

    def incr(self, key: str, ttl: float) -> int:
        with self._lock:
            entry = self._values.get(key)
            if entry is None or self._expired(entry[1]):
                entry = (b"0", self._clock() + ttl)
            value = int(entry[0]) + 1
            self._values[key] = (str(value).encode(), entry[1])
            return value

    def window_hit(self, key: str, window: float, now: float | None = None) -> int:
        now = self._clock() if now is None else now
        with self._lock:
            hits = self._windows.get(key)
            if hits is not None:
                cutoff = now - window
                while hits and hits[0] <= cutoff:
                    hits.popleft()
            if not hits:
                # Recria em vez de manter a chave vazia viva: um atacante girando chaves não
                # pode crescer este dicionário sem limite.
                hits = self._windows[key] = deque()
            hits.append(now)
            # Varredura amortizada (no máximo uma por janela), não a cada request.
            if now - self._last_sweep >= window:
                self._drop_empty_windows(now, window)
                self._last_sweep = now
            return len(hits)

    def append_log(self, key: str, entry: bytes, maxlen: int) -> None:
        with self._lock:
            log = self._logs.get(key)
            if log is None or log.maxlen != maxlen:
                log = self._logs[key] = deque(log or (), maxlen=maxlen)
            log.append(entry)

    def read_log(self, key: str, count: int) -> list[bytes]:
        with self._lock:
            log = self._logs.get(key)
            return list(reversed(log))[:count] if log else []

    def window_keys(self) -> int:
        """Quantos buckets de janela estão vivos (para testes/diagnóstico)."""
        with self._lock:
            return len(self._windows)

    def ping(self) -> bool:
        return True

    def _drop_empty_windows(self, now: float, window: float) -> None:
        cutoff = now - window
        stale = [k for k, hits in self._windows.items() if not hits or hits[-1] <= cutoff]
        for k in stale:
            del self._windows[k]

    def _gc(self) -> None:
        now = self._clock()
        stale = [k for k, (_, exp) in self._values.items() if exp is not None and now >= exp]
        for k in stale:
            del self._values[k]


class RedisStore:
    """Redis compartilhado entre réplicas. Todas as chaves ganham o prefixo ``cedro-mcp:``."""

    is_local = False

    def __init__(self, client: Any) -> None:
        #: ``redis.Redis`` (ou ``fakeredis.FakeRedis`` nos testes).
        self._redis = client

    @classmethod
    def from_url(cls, url: str) -> RedisStore:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover — depende do extra instalado
            raise ConfigurationError(
                "MCP_REDIS_URL definido, mas o pacote `redis` não está instalado. "
                'Instale com: pip install "cedro-mcp-server[redis]".'
            ) from exc
        return cls(redis.Redis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0))

    @staticmethod
    def _k(key: str) -> str:
        return KEY_PREFIX + key

    def get(self, key: str) -> bytes | None:
        return self._redis.get(self._k(key))

    def set(self, key: str, value: bytes, ttl: float | None = None) -> None:
        px = max(int(ttl * 1000), 1) if ttl is not None else None
        self._redis.set(self._k(key), value, px=px)

    def pop(self, key: str) -> bytes | None:
        return self._redis.getdel(self._k(key))

    def delete(self, key: str) -> None:
        self._redis.delete(self._k(key))

    def incr(self, key: str, ttl: float) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(self._k(key))
        # NX: só define o TTL quando o contador nasce — incrementos seguintes não o renovam.
        pipe.expire(self._k(key), max(int(ttl), 1), nx=True)
        value, _ = pipe.execute()
        return int(value)

    def window_hit(self, key: str, window: float, now: float | None = None) -> int:
        # Relógio de parede (não monotônico): é compartilhado entre réplicas.
        now = time.time() if now is None else now
        k = self._k(key)
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(k, "-inf", now - window)
        pipe.zadd(k, {f"{now}:{uuid.uuid4().hex[:8]}": now})
        pipe.zcard(k)
        pipe.expire(k, max(int(window) + 1, 1))
        _, _, count, _ = pipe.execute()
        return int(count)

    def append_log(self, key: str, entry: bytes, maxlen: int) -> None:
        # Redis Stream com corte aproximado (~): barato e mantém ~maxlen entradas.
        self._redis.xadd(self._k(key), {"e": entry}, maxlen=maxlen, approximate=True)

    def read_log(self, key: str, count: int) -> list[bytes]:
        rows = self._redis.xrevrange(self._k(key), count=count)
        return [fields[b"e"] for _, fields in rows]

    def ping(self) -> bool:
        try:
            return bool(self._redis.ping())
        except Exception:  # noqa: BLE001 — qualquer falha de conexão = indisponível
            return False


def build_store(settings: Settings) -> Store:
    if settings.redis_url:
        return RedisStore.from_url(settings.redis_url)
    return MemoryStore()


class SecretBox:
    """Cifra simétrica (Fernet: AES-128-CBC + HMAC-SHA256) para credenciais guardadas no store.

    A chave vem de ``MCP_STORE_SECRET`` (qualquer string longa e aleatória; derivada com
    SHA-256). Trocar o segredo invalida todas as sessões guardadas — todo mundo reloga.
    """

    def __init__(self, secret: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)

    def seal(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def open(self, token: bytes) -> bytes | None:
        """Decifra; ``None`` se foi cifrado com outro segredo ou está corrompido."""
        try:
            return self._fernet.decrypt(token)
        except InvalidToken:
            return None


class PlainBox:
    """Sem cifra — só permitido com ``MemoryStore`` (o dado nunca sai do processo)."""

    def seal(self, data: bytes) -> bytes:
        return data

    def open(self, token: bytes) -> bytes | None:
        return token


def build_secret_box(settings: Settings, store: Store) -> SecretBox | PlainBox:
    if settings.store_secret:
        return SecretBox(settings.store_secret)
    if not store.is_local:
        raise ConfigurationError(
            "MCP_STORE_SECRET é obrigatório com MCP_REDIS_URL: as credenciais do login pelo "
            "navegador são cifradas antes de ir para o Redis, nunca gravadas em claro."
        )
    return PlainBox()
