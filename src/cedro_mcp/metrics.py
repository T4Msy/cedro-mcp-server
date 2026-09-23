"""Métricas Prometheus: tools, chamadas às APIs da Cedro, SignIn, rate limit e cota.

Prometheus metrics. Expostas em ``/metrics`` (``http_app.py``) só quando ``MCP_METRICS_TOKEN``
está definido — o scraper manda ``Authorization: Bearer <token>``. Cada réplica expõe as suas;
o Prometheus agrega.

Labels com cardinalidade controlada: ``endpoint`` é o path cortado nos 3 primeiros segmentos
(``/services/quotes/quote/PETR4`` → ``/services/quotes/quote``), nunca símbolo, conta ou usuário.
"""

from __future__ import annotations

import time

import httpx
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

#: Registry próprio (não o global): testes montam o servidor várias vezes no mesmo processo.
REGISTRY = CollectorRegistry()

TOOL_CALLS = Counter(
    "cedro_mcp_tool_calls_total",
    "Chamadas de tool por resultado.",
    ["tool", "outcome", "error_type"],
    registry=REGISTRY,
)
TOOL_DURATION = Histogram(
    "cedro_mcp_tool_duration_seconds",
    "Duração das chamadas de tool.",
    ["tool"],
    registry=REGISTRY,
)
UPSTREAM_REQUESTS = Counter(
    "cedro_mcp_upstream_requests_total",
    "Requisições às APIs da Cedro por status HTTP ('error' = falha de rede/timeout).",
    ["api", "endpoint", "status"],
    registry=REGISTRY,
)
UPSTREAM_DURATION = Histogram(
    "cedro_mcp_upstream_duration_seconds",
    "Latência das requisições às APIs da Cedro.",
    ["api", "endpoint"],
    registry=REGISTRY,
)
SIGNINS = Counter(
    "cedro_mcp_signin_total",
    "Logins (SignIn) feitos contra a Cedro — a conta tolera poucos por dia.",
    ["api", "outcome"],
    registry=REGISTRY,
)
RATE_LIMITED = Counter(
    "cedro_mcp_rate_limited_total",
    "Requisições barradas pelo rate limit.",
    ["bucket"],
    registry=REGISTRY,
)
QUOTA_EXCEEDED = Counter(
    "cedro_mcp_quota_exceeded_total",
    "Chamadas de tool barradas pela cota mensal do plano.",
    ["plan"],
    registry=REGISTRY,
)

CONTENT_TYPE = CONTENT_TYPE_LATEST


def render() -> bytes:
    return generate_latest(REGISTRY)


def endpoint_label(path: str) -> str:
    segments = [s for s in path.split("/") if s][:3]
    return "/" + "/".join(segments)


class MetricsTransport(httpx.BaseTransport):
    """Transport que mede toda requisição de um ``httpx.Client`` (inclusive as que falham)."""

    def __init__(self, api: str, inner: httpx.BaseTransport | None = None) -> None:
        self._api = api
        self._inner = inner or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        endpoint = endpoint_label(request.url.path)
        started = time.perf_counter()
        status = "error"
        try:
            response = self._inner.handle_request(request)
            status = str(response.status_code)
            return response
        finally:
            UPSTREAM_REQUESTS.labels(self._api, endpoint, status).inc()
            UPSTREAM_DURATION.labels(self._api, endpoint).observe(time.perf_counter() - started)

    def close(self) -> None:
        self._inner.close()


def instrumented_client(api: str, **kwargs: object) -> httpx.Client:
    """``httpx.Client`` com métricas por endpoint. ``api``: market_data | news | trading."""
    return httpx.Client(transport=MetricsTransport(api), **kwargs)  # type: ignore[arg-type]
