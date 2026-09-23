"""App ASGI do transporte Streamable HTTP: rate limit, healthcheck e métricas.

Streamable HTTP ASGI app + rate-limit middleware + ``/health`` + ``/metrics``. O
``FastMCP.streamable_http_app()`` devolve um app Starlette (com o lifespan do session manager já
configurado); acrescentamos as rotas operacionais e envolvemos tudo com o rate limit.
"""

from __future__ import annotations

import hashlib
import secrets

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import metrics
from .store import MemoryStore, Store, call

_ANONYMOUS_IP = "unknown-ip"
#: Teto do bucket AGREGADO por IP, como múltiplo do limite por token/chave — ver docstring
#: da classe (mitigação de bypass por rotação de bearer).
IP_LIMIT_MULTIPLIER = 5
#: Rotas operacionais: fora do rate limit (o healthcheck da plataforma não pode tomar 429).
HEALTH_PATHS = ("/health", "/healthz")
EXEMPT_PATHS = frozenset({*HEALTH_PATHS, "/metrics"})


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
    """Janela deslizante por token (+ teto agregado por IP), guardada no store.

    Com ``MemoryStore`` o estado é **por processo** (N réplicas ⇒ limite efetivo N × limit); com
    ``RedisStore`` (``MCP_REDIS_URL``) o limite é global entre réplicas.

    Toda tentativa conta na janela, inclusive as barradas: quem insiste acima do limite continua
    barrado até parar por uma janela inteira.

    ⚠️ **Bypass por rotação de bearer:** o bucket primário agrupa por hash do token — um chamador
    que manda um bearer *novo e nunca validado* a cada request sempre cai num bucket "fresco",
    furando o limite por token (a rejeição real só vem depois, no 401 da autenticação de
    verdade). Mitigado com um teto SECUNDÁRIO por IP (`limit × IP_LIMIT_MULTIPLIER`), que soma
    TODAS as tentativas daquele IP independente do token usado em cada uma.
    """

    def __init__(
        self, app: ASGIApp, *, limit: int, window: float, store: Store | None = None
    ) -> None:
        self.app = app
        self.limit = limit
        self.window = window
        self.store = store or MemoryStore()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or self.limit <= 0
            or scope.get("path") in EXEMPT_PATHS
        ):
            await self.app(scope, receive, send)
            return
        # Sempre avalia os DOIS buckets (sem short-circuit) — o teto por IP precisa contabilizar
        # a tentativa mesmo quando o bucket por-token já rejeitou, senão um atacante trocando de
        # token a cada request nunca alimentaria o agregado por IP.
        key_hits = await call(
            self.store, self.store.window_hit, f"rl:key:{_bucket_key(scope)}", self.window
        )
        ip_hits = await call(
            self.store, self.store.window_hit, f"rl:ip:{_client_ip(scope)}", self.window
        )
        over_key = key_hits > self.limit
        over_ip = ip_hits > self.limit * IP_LIMIT_MULTIPLIER
        if over_key or over_ip:
            metrics.RATE_LIMITED.labels("key" if over_key else "ip").inc()
            response = JSONResponse(
                {"error": "rate_limit_exceeded", "detail": "Too many requests."},
                status_code=429,
                headers={"Retry-After": str(int(self.window))},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _health_endpoint(store: Store):  # noqa: ANN202 — endpoint Starlette
    async def health(_request: Request) -> JSONResponse:
        """Liveness + dependência do store. Sem auth, sem rate limit, sem dados sensíveis."""
        backend = "memory" if store.is_local else "redis"
        if not await call(store, store.ping):
            return JSONResponse(
                {"status": "degraded", "store": backend, "detail": "store indisponível"},
                status_code=503,
            )
        return JSONResponse({"status": "ok", "store": backend})

    return health


def _metrics_route(token: str) -> Route:
    expected = f"Bearer {token}".encode()

    async def handler(request: Request) -> Response:
        provided = request.headers.get("authorization", "").encode()
        if not secrets.compare_digest(provided, expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return Response(metrics.render(), media_type=metrics.CONTENT_TYPE)

    return Route("/metrics", handler, methods=["GET"])


def create_app(
    mcp: FastMCP,
    *,
    rate_limit: int = 0,
    rate_window: float = 60.0,
    store: Store | None = None,
    metrics_token: str | None = None,
) -> ASGIApp:
    """Monta o app ASGI do MCP (Streamable HTTP) com rotas operacionais e rate limit."""
    http_app: Starlette = mcp.streamable_http_app()
    store = store or getattr(mcp, "cedro_store", None) or MemoryStore()

    health = _health_endpoint(store)
    http_app.router.routes.extend(Route(path, health, methods=["GET"]) for path in HEALTH_PATHS)
    # Sem token configurado, /metrics simplesmente não existe (404) — nunca aberto por padrão.
    if metrics_token:
        http_app.router.routes.append(_metrics_route(metrics_token))

    # Login pelo navegador (ver server.build_server() + web_login.py): as rotas /cedro-login
    # precisam viver no MESMO app Starlette que /authorize, /token etc. (montados pelo FastMCP
    # só quando auth_server_provider está setado), senão o redirect de authorize() pra
    # /cedro-login cairia em 404.
    login_provider = getattr(mcp, "cedro_login_provider", None)
    if login_provider is not None:
        http_app.router.routes.extend(login_provider.routes())

    app: ASGIApp = http_app
    if rate_limit > 0:
        app = RateLimitMiddleware(app, limit=rate_limit, window=rate_window, store=store)
    return app
