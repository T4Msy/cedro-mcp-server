"""Infra: store (memória/Redis), login persistido, cota por plano, métricas e healthcheck."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import fakeredis
import httpx
import pytest
import respx
from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
from mcp.server.auth.provider import AccessToken
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.requests import Request as StarletteRequest

from cedro_mcp import metrics
from cedro_mcp.client import CedroClient
from cedro_mcp.config import ConfigurationError, Settings, load_settings
from cedro_mcp.credentials import WebLoginCredentialProvider
from cedro_mcp.errors import CedroQuotaError
from cedro_mcp.http_app import RateLimitMiddleware, create_app
from cedro_mcp.quota import QuotaPolicy
from cedro_mcp.server import build_server
from cedro_mcp.store import MemoryStore, RedisStore, SecretBox, build_secret_box
from cedro_mcp.web_login import CedroLoginProvider

from .conftest import BASE_URL
from .test_http import _OkApp, _request
from .test_web_login import _client_info, _params


def _redis_pair() -> tuple[RedisStore, RedisStore]:
    """Duas "réplicas" falando com o mesmo Redis."""
    server = fakeredis.FakeServer()
    return (
        RedisStore(fakeredis.FakeRedis(server=server)),
        RedisStore(fakeredis.FakeRedis(server=server)),
    )


@pytest.fixture(params=["memory", "redis"])
def store(request: pytest.FixtureRequest):  # noqa: ANN201
    if request.param == "memory":
        return MemoryStore()
    return _redis_pair()[0]


# ---- store -----------------------------------------------------------------


def test_store_set_get_pop_delete(store) -> None:  # noqa: ANN001
    store.set("a", b"1", ttl=60)
    assert store.get("a") == b"1"
    assert store.pop("a") == b"1"
    assert store.pop("a") is None  # uso único
    store.set("b", b"2")
    store.delete("b")
    assert store.get("b") is None


def test_store_incr_and_window(store) -> None:  # noqa: ANN001
    assert [store.incr("c", ttl=60) for _ in range(3)] == [1, 2, 3]
    assert [store.window_hit("w", window=60) for _ in range(3)] == [1, 2, 3]
    assert store.ping() is True


def test_memory_store_ttl_expires() -> None:
    now = [0.0]
    store = MemoryStore(clock=lambda: now[0])
    store.set("k", b"v", ttl=10)
    store.incr("n", ttl=10)
    now[0] = 11
    assert store.get("k") is None
    assert store.incr("n", ttl=10) == 1  # contador expirado recomeça


def test_redis_store_is_shared_between_replicas() -> None:
    a, b = _redis_pair()
    a.set("k", b"v", ttl=60)
    assert b.pop("k") == b"v"
    assert a.get("k") is None


def test_secret_box_round_trip_and_wrong_secret() -> None:
    sealed = SecretBox("segredo-1").seal(b"senha")
    assert b"senha" not in sealed
    assert SecretBox("segredo-1").open(sealed) == b"senha"
    assert SecretBox("segredo-2").open(sealed) is None


def test_redis_without_store_secret_refuses_to_start(settings: Settings) -> None:
    redis_store = _redis_pair()[0]
    with pytest.raises(ConfigurationError, match="MCP_STORE_SECRET"):
        build_secret_box(settings, redis_store)
    assert isinstance(
        build_secret_box(replace(settings, store_secret="s"), redis_store), SecretBox
    )


# ---- login pelo navegador persistido ---------------------------------------


def _login(provider: CedroLoginProvider, flow_id: str) -> str:
    async def submit() -> str:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/SignIn").mock(
                return_value=httpx.Response(
                    200, text="true", headers={"Set-Cookie": "JSESSIONID=abc; Path=/"}
                )
            )
            scope = {
                "type": "http",
                "method": "POST",
                "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
            }

            async def receive():
                body = b"flow_id=%s&login=tester&password=senha-rest" % flow_id.encode()
                return {"type": "http.request", "body": body, "more_body": False}

            response = await provider._handle_login_submit(StarletteRequest(scope, receive))  # noqa: SLF001
            return response.headers["location"]

    redirect = asyncio.run(submit())
    return redirect.split("code=")[1].split("&")[0]


def test_web_login_survives_restart_and_crosses_replicas(settings: Settings) -> None:
    """authorize numa réplica, formulário em outra, token validado numa terceira (ou após
    restart) — e nada sensível em claro no Redis."""
    server = fakeredis.FakeServer()
    raw = fakeredis.FakeRedis(server=server)
    box = SecretBox("segredo-do-deploy")

    def replica() -> CedroLoginProvider:
        return CedroLoginProvider(
            settings, store=RedisStore(fakeredis.FakeRedis(server=server)), box=box
        )

    a, b, c = replica(), replica(), replica()
    client = _client_info()
    asyncio.run(a.register_client(client))
    flow_id = asyncio.run(a.authorize(client, _params())).split("flow_id=")[1]
    code = _login(b, flow_id)
    auth_code = asyncio.run(c.load_authorization_code(client, code))
    assert auth_code is not None
    token = asyncio.run(c.exchange_authorization_code(client, auth_code)).access_token

    restarted = replica()
    access = asyncio.run(restarted.load_access_token(token))
    assert access is not None and access.subject == "tester"
    creds = WebLoginCredentialProvider(restarted).rest_credentials_for(access)
    assert creds.password == "senha-rest"

    dump = b"".join(
        key + (raw.get(key) or b"") for key in raw.keys("*") if raw.type(key) == b"string"
    )
    assert b"senha-rest" not in dump  # credencial cifrada
    assert token.encode() not in dump  # token nem como chave nem como valor

    asyncio.run(restarted.revoke_token(access))
    assert asyncio.run(a.load_access_token(token)) is None


def test_changing_store_secret_logs_everyone_out(settings: Settings) -> None:
    server = fakeredis.FakeServer()
    old = CedroLoginProvider(
        settings, store=RedisStore(fakeredis.FakeRedis(server=server)), box=SecretBox("v1")
    )
    client = _client_info()
    asyncio.run(old.register_client(client))
    flow_id = asyncio.run(old.authorize(client, _params())).split("flow_id=")[1]
    code = _login(old, flow_id)
    token = asyncio.run(
        old.exchange_authorization_code(
            client, asyncio.run(old.load_authorization_code(client, code))
        )
    ).access_token

    rotated = CedroLoginProvider(
        settings, store=RedisStore(fakeredis.FakeRedis(server=server)), box=SecretBox("v2")
    )
    assert rotated.credentials_for_token(token) is None


def test_login_flow_is_single_use(settings: Settings) -> None:
    provider = CedroLoginProvider(settings)
    client = _client_info()
    asyncio.run(provider.register_client(client))
    flow_id = asyncio.run(provider.authorize(client, _params())).split("flow_id=")[1]
    _login(provider, flow_id)
    assert provider._load_flow(flow_id) is None  # noqa: SLF001


def test_dcr_client_persists(settings: Settings) -> None:
    a, b = _redis_pair()
    box = SecretBox("s")
    client = OAuthClientInformationFull(
        client_id="c1", redirect_uris=[AnyUrl("http://127.0.0.1:1/cb")]
    )
    asyncio.run(CedroLoginProvider(settings, store=a, box=box).register_client(client))
    loaded = asyncio.run(CedroLoginProvider(settings, store=b, box=box).get_client("c1"))
    assert loaded is not None and loaded.client_id == "c1"


# ---- cota por plano --------------------------------------------------------


def _principal(*scopes: str, subject: str = "cliente-x") -> AccessToken:
    return AccessToken(token=f"tok-{subject}", client_id="app", scopes=list(scopes),
                       subject=subject)


def _quota_settings(settings: Settings, **overrides: object) -> Settings:
    return replace(settings, plan_quotas=(("basico", 2), ("pro", 5)), **overrides)


def test_quota_blocks_after_limit_and_counts_per_identity(settings: Settings) -> None:
    policy = QuotaPolicy(_quota_settings(settings), MemoryStore())
    basic = _principal("marketdata:read", "plan:basico")
    policy.consume(basic, "md_get_quote")
    policy.consume(basic, "md_get_quote")
    with pytest.raises(CedroQuotaError, match="basico"):
        policy.consume(basic, "md_get_quote")
    # Outra identidade tem a própria cota.
    policy.consume(_principal("plan:basico", subject="outro"), "md_get_quote")


def test_quota_plan_resolution(settings: Settings) -> None:
    policy = QuotaPolicy(_quota_settings(settings, default_plan="basico"), MemoryStore())
    assert policy.plan_for(_principal("plan:pro")) == "pro"
    assert policy.plan_for(_principal()) == "basico"  # default
    assert policy.plan_for(_principal("plan:inexistente")) == "basico"
    no_default = QuotaPolicy(_quota_settings(settings), MemoryStore())
    assert no_default.plan_for(_principal()) is None
    for _ in range(10):
        no_default.consume(_principal(), "md_get_quote")  # sem plano, sem cota


def test_usage_tool_is_exempt_and_reports(settings: Settings) -> None:
    policy = QuotaPolicy(_quota_settings(settings), MemoryStore())
    p = _principal("plan:basico")
    policy.consume(p, "md_get_quote")
    for _ in range(5):
        policy.consume(p, "account_get_usage")
    usage = policy.usage(p)
    assert usage["used"] == 1
    assert usage["remaining"] == 1
    assert usage["limit"] == 2


def test_quota_is_global_across_replicas_with_redis(settings: Settings) -> None:
    a, b = _redis_pair()
    p = _principal("plan:basico")
    QuotaPolicy(_quota_settings(settings), a).consume(p, "t")
    QuotaPolicy(_quota_settings(settings), b).consume(p, "t")
    with pytest.raises(CedroQuotaError):
        QuotaPolicy(_quota_settings(settings), a).consume(p, "t")


def _mock_list_markets() -> respx.Route:
    respx.post(f"{BASE_URL}/SignIn").mock(
        return_value=httpx.Response(200, text="true", headers={"Set-Cookie": "JSESSIONID=a"})
    )
    return respx.get(f"{BASE_URL}/services/quotes/listMarket").mock(
        return_value=httpx.Response(200, json=[{"code": "1", "name": "BOVESPA"}])
    )


@respx.mock
def test_quota_enforced_on_real_tool_calls(settings: Settings, client: CedroClient) -> None:
    route = _mock_list_markets()
    mcp = build_server(settings=_quota_settings(settings), client=client)
    token = auth_context_var.set(AuthenticatedUser(_principal("marketdata:read", "plan:basico")))
    try:
        for _ in range(2):
            asyncio.run(mcp.call_tool("md_list_markets", {}))
        with pytest.raises(Exception, match="Cota mensal"):
            asyncio.run(mcp.call_tool("md_list_markets", {}))
        assert route.call_count == 2  # a 3ª nem chegou à Cedro
        usage = asyncio.run(mcp.call_tool("account_get_usage", {}))
    finally:
        auth_context_var.reset(token)
    blocks = usage[0] if isinstance(usage, tuple) else usage  # (conteúdo, structured)
    assert '"remaining": 0' in blocks[0].text


def test_plan_quota_config_parsing() -> None:
    s = load_settings({"MCP_PLAN_QUOTAS": "basico:20000, pro:100000", "MCP_DEFAULT_PLAN": "pro"})
    assert s.plan_quotas == (("basico", 20000), ("pro", 100000))
    assert s.default_plan == "pro"
    with pytest.raises(ConfigurationError, match="MCP_PLAN_QUOTAS"):
        load_settings({"MCP_PLAN_QUOTAS": "basico=20000"})
    with pytest.raises(ConfigurationError, match="MCP_DEFAULT_PLAN"):
        load_settings({"MCP_PLAN_QUOTAS": "basico:1", "MCP_DEFAULT_PLAN": "ouro"})


# ---- healthcheck, métricas e rate limit global -----------------------------


def _get(app, path: str, headers: dict[str, str] | None = None) -> httpx.Response:  # noqa: ANN001
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            return await ac.get(path, headers=headers)

    return asyncio.run(run())


def test_health_endpoints_ignore_rate_limit(settings: Settings, client: CedroClient) -> None:
    app = create_app(build_server(settings=settings, client=client), rate_limit=1)
    for path in ("/health", "/healthz", "/health", "/healthz"):
        resp = _get(app, path)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "store": "memory"}


def test_health_reports_store_down(settings: Settings, client: CedroClient) -> None:
    class _DownStore(MemoryStore):
        def ping(self) -> bool:
            return False

    app = create_app(build_server(settings=settings, client=client, store=_DownStore()))
    resp = _get(app, "/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


def test_metrics_endpoint_requires_token(settings: Settings, client: CedroClient) -> None:
    mcp = build_server(settings=settings, client=client)
    assert _get(create_app(mcp), "/metrics").status_code == 404  # desligado por padrão

    app = create_app(mcp, metrics_token="scrape-me")
    assert _get(app, "/metrics").status_code == 401
    assert _get(app, "/metrics", {"Authorization": "Bearer errado"}).status_code == 401
    ok = _get(app, "/metrics", {"Authorization": "Bearer scrape-me"})
    assert ok.status_code == 200
    assert "cedro_mcp_tool_calls_total" in ok.text


@respx.mock
def test_upstream_and_signin_metrics(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(
        return_value=httpx.Response(200, text="true", headers={"Set-Cookie": "JSESSIONID=a"})
    )
    respx.get(f"{BASE_URL}/services/quotes/quote/PETR4").mock(
        return_value=httpx.Response(200, json=[])
    )

    def sample(name: str, labels: dict[str, str]) -> float:
        return metrics.REGISTRY.get_sample_value(name, labels) or 0.0

    quote_labels = {"api": "market_data", "endpoint": "/services/quotes/quote", "status": "200"}
    before_quote = sample("cedro_mcp_upstream_requests_total", quote_labels)
    before_signin = sample("cedro_mcp_signin_total", {"api": "market_data", "outcome": "ok"})

    real = CedroClient(settings)  # sem http injetado: usa o cliente instrumentado
    real.get_quotes("/services/quotes/quote/PETR4")
    real.close()

    assert sample("cedro_mcp_upstream_requests_total", quote_labels) == before_quote + 1
    assert (
        sample("cedro_mcp_signin_total", {"api": "market_data", "outcome": "ok"})
        == before_signin + 1
    )


@respx.mock
def test_tool_call_metrics(settings: Settings, client: CedroClient) -> None:
    _mock_list_markets()
    mcp = build_server(settings=settings, client=client)

    def sample(outcome: str, error_type: str) -> float:
        labels = {"tool": "md_list_markets", "outcome": outcome, "error_type": error_type}
        return metrics.REGISTRY.get_sample_value("cedro_mcp_tool_calls_total", labels) or 0.0

    ok_before = sample("ok", "")
    asyncio.run(mcp.call_tool("md_list_markets", {}))
    assert sample("ok", "") == ok_before + 1

    err_before = sample("error", "CedroEntitlementError")
    token = auth_context_var.set(AuthenticatedUser(_principal("marketdata:news")))
    try:
        with pytest.raises(Exception, match="escopo ausente"):
            asyncio.run(mcp.call_tool("md_list_markets", {}))
    finally:
        auth_context_var.reset(token)
    assert sample("error", "CedroEntitlementError") == err_before + 1


def test_endpoint_label_has_bounded_cardinality() -> None:
    assert metrics.endpoint_label("/services/quotes/quote/PETR4,VALE3") == "/services/quotes/quote"
    assert metrics.endpoint_label("/SignIn") == "/SignIn"
    assert (
        metrics.endpoint_label("/services/negotiation/dailyOrder/10034/XBSP")
        == "/services/negotiation/dailyOrder"
    )


def test_rate_limit_is_global_across_replicas_with_redis() -> None:
    a, b = _redis_pair()
    auth = [(b"authorization", b"Bearer t")]
    replica_a = RateLimitMiddleware(_OkApp(), limit=2, window=60, store=a)
    replica_b = RateLimitMiddleware(_OkApp(), limit=2, window=60, store=b)
    assert _request(replica_a, auth) == 200
    assert _request(replica_b, auth) == 200
    assert _request(replica_a, auth) == 429  # 3ª do mesmo token, ainda que noutra réplica
