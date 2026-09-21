"""App ASGI do transporte Streamable HTTP + middleware de rate limit.

Streamable HTTP ASGI app + rate-limit middleware. O ``FastMCP.streamable_http_app()`` devolve um app
Starlette (com o lifespan do session manager já configurado); envolvemos ele com o rate limit.
"""

from __future__ import annotations

import hashlib
import time
from collections import deque

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_ANONYMOUS_IP = "unknown-ip"
#: Teto do bucket AGREGADO por IP, como múltiplo do limite por token/chave — ver docstring
#: da classe (mitigação de bypass por rotação de bearer).
IP_LIMIT_MULTIPLIER = 5


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else _ANONYMOUS_IP


def _bucket_key(scope: Scope) -> str:
    """Chave do bucket primário: hash do bearer (limita **por token**, sem precisar
    decodificá-lo); sem `Authorization`, agrupa por IP do cliente em vez de um único bucket
    "anonymous" compartilhado — assim um cliente anônimo não esgota a cota de todos os outros.
    """
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            return hashlib.sha256(value).hexdigest()
    return f"ip:{_client_ip(scope)}"


class RateLimitMiddleware:
    """Janela deslizante em memória, por token (+ teto agregado por IP).

    ⚠️ **Escopo:** o estado é **por processo**. Com várias réplicas atrás de um load balancer, o
    limite efetivo é `réplicas × limit`. Para limite global, trocar por um backend compartilhado
    (Redis) — ver a nota de arquitetura no vault.

    ⚠️ **Bypass por rotação de bearer:** o bucket primário agrupa por hash do token — um chamador
    que manda um bearer *novo e nunca validado* a cada request sempre cai num bucket "fresco",
    furando o limite por token (a rejeição real só vem depois, no 401 da autenticação de
    verdade). Mitigado com um teto SECUNDÁRIO por IP (`limit × IP_LIMIT_MULTIPLIER`), que soma
    TODAS as tentativas daquele IP independente do token usado em cada uma.

    Buckets vazios (nada dentro da janela) são removidos do dicionário a cada acesso — sem isso,
    um atacante girando chaves indefinidamente cresceria o estado em memória sem limite.
    """

    def __init__(self, app: ASGIApp, *, limit: int, window: float) -> None:
        self.app = app
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        self._ip_hits: dict[str, deque[float]] = {}

    def _allow(self, hits_map: dict[str, deque[float]], key: str, limit: int, now: float) -> bool:
        hits = hits_map.get(key)
        if hits is not None:
            cutoff = now - self.window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                del hits_map[key]  # bucket esvaziou — não deixa a chave viva pra sempre
                hits = None
        if hits is not None and len(hits) >= limit:
            return False
        if hits is None:
            hits = hits_map[key] = deque()
        hits.append(now)
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.limit <= 0:
            await self.app(scope, receive, send)
            return
        now = time.monotonic()
        # Sempre avalia os DOIS buckets (sem short-circuit) — o teto por IP precisa contabilizar
        # a tentativa mesmo quando o bucket por-token já rejeitou, senão um atacante trocando de
        # token a cada request nunca alimentaria o agregado por IP.
        allowed_by_key = self._allow(self._hits, _bucket_key(scope), self.limit, now)
        allowed_by_ip = self._allow(
            self._ip_hits, _client_ip(scope), self.limit * IP_LIMIT_MULTIPLIER, now
        )
        if not (allowed_by_key and allowed_by_ip):
            response = JSONResponse(
                {"error": "rate_limit_exceeded", "detail": "Too many requests."},
                status_code=429,
                headers={"Retry-After": str(int(self.window))},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(mcp: FastMCP, *, rate_limit: int = 0, rate_window: float = 60.0) -> ASGIApp:
    """Monta o app ASGI do MCP (Streamable HTTP), opcionalmente com rate limit."""
    app: ASGIApp | Starlette = mcp.streamable_http_app()
    if rate_limit > 0:
        app = RateLimitMiddleware(app, limit=rate_limit, window=rate_window)
    return app
