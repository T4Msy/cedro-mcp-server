"""Configuração via variáveis de ambiente. Segredos NUNCA vêm em args de tool.

Config from environment variables. Secrets NEVER come from tool args.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://webfeeder.cedrotech.com"
DEFAULT_TRANSPORT = "streamable-http"
#: Único conteúdo servido por ``cedro-docs://`` por padrão: a skill pública de Market Data REST
#: (já curada para cliente), nunca o vault interno da Cedro — ver achado de segurança no dossiê
#: de arquitetura (docs/arquitetura/). Sobrescrever via CEDRO_DOCS_PATH só para desenvolvimento
#: local; nunca apontar para o vault em produção.
DEFAULT_DOCS_PATH = "../cedro-api-skills/cedro-api-skills/skills/market-data-rest"
#: Transportes suportados. "sse" NÃO está aqui de propósito — ver `_normalize_transport`.
_SUPPORTED_TRANSPORTS = ("stdio", DEFAULT_TRANSPORT)


class ConfigurationError(RuntimeError):
    """Configuração inválida/insegura detectada no startup do servidor.

    Invalid/unsafe configuration detected at server startup — fails loudly instead of
    silently degrading (ex.: auth desligada por acidente rodando em modo não-stdio).
    """


@dataclass(frozen=True)
class Settings:
    """Configuração imutável do servidor · immutable server settings."""

    # --- APIs da Cedro (downstream) ---
    base_url: str
    user: str | None
    password: str | None
    news_client_id: str | None
    news_client_secret: str | None
    docs_path: Path
    http_timeout: float
    #: Hosts TCP do Socket Crystal. Produção: datafeed1/datafeed2; homologação:
    #: crystalhomologacao.cedrotech.com. A porta padrão é 81.
    crystal_host: str | None = None
    crystal_port: int = 81
    #: Quanto uma tool de streaming espera pelo primeiro snapshot depois de assinar um ativo.
    stream_snapshot_timeout: float = 5.0
    #: Limite local do histórico de negócios por ativo, para não crescer indefinidamente.
    stream_tape_limit: int = 1_000
    #: Credenciais de serviço para Socket/Trading (só usadas por `ServiceAccountCredentialProvider`
    #: — dev/stdio; em produção via `MCP_WEB_LOGIN`, cada usuário traz a própria no formulário).
    crystal_user: str | None = None
    crystal_password: str | None = None
    #: Software key opcional enviada como primeira linha do handshake Crystal.
    crystal_software_key: str | None = None
    trading_user: str | None = None
    trading_password: str | None = None
    #: Parâmetro de login HTTP do Trading quando é diferente da identidade OMS.
    trading_signin_user: str | None = None
    trading_signin_password: str | None = None
    #: Identidade enviada no `user-identifier` e usada no brokerServiceLogin.
    trading_oms_account: str | None = None
    trading_oms_login: str | None = None
    trading_oms_password: str | None = None
    #: BASE64 é o default confirmado em campo; "rsa" nunca foi confirmado ao vivo — ver
    #: trading/identity.py e docs/arquitetura/10-trading-auth.md.
    trading_encryption: str = "base64"
    #: Só exigido quando trading_encryption == "rsa".
    trading_jwks_url: str | None = None
    #: Nome da aplicação enviado em `brokerServiceLogin` (`appname`) e nas ordens.
    trading_app_name: str = "cedro-connect-ia"
    #: IP de origem enviado em `user-identifier.remote_ip` e `sourceaddress` das ordens — a
    #: Cedro usa para rastreabilidade. Sem um IP real e estável configurado, cai num placeholder
    #: óbvio (nunca "127.0.0.1", que passaria despercebido como valor real).
    trading_remote_ip: str = "0.0.0.0"
    #: Host do Trading — SEPARADO de `base_url` de propósito. Achado real (21/09): uma credencial
    #: de certificação (`wfcertificacao.cedrotech.com`) contra produção (`webfeeder...`) dá 401
    #: vazio no brokerServiceLogin, sem nenhum dos padrões documentados (code 3/24) — é auth num
    #: host, requisição noutro. `None` = usa `base_url` (mesmo host da Market Data REST).
    trading_base_url: str | None = None
    #: Guardrails do preview (ver trading/guardrails.py). Teto de valor (qty × preço) por ordem —
    #: acima dele o preview é RECUSADO; 0 = sem teto.
    trading_max_order_value: float = 0.0
    #: Alerta (não recusa) quando um preço da ordem está mais que isto (%) longe do último
    #: negócio; 0 = desligado.
    trading_price_band_pct: float = 10.0

    # --- Auth do chamador (IAM / API key) ---
    iam_issuer: str | None = None
    iam_jwks_url: str | None = None
    iam_audience: str | None = None
    api_keys_raw: str | None = None

    # --- Transporte MCP ---
    transport: str = DEFAULT_TRANSPORT
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000
    mcp_path: str = "/mcp"
    #: URL pública deste MCP; exigida pelo AuthSettings como identificador do resource server.
    resource_url: str | None = None
    #: Opt-in EXPLÍCITO para subir sem auth em transporte não-stdio (demo local). Ver
    #: `ConfigurationError` em `server.build_server()` — sem isto, faltar `CEDRO_IAM_ISSUER`/
    #: `MCP_RESOURCE_URL` rodando em streamable-http falha no startup em vez de expor as tools
    #: silenciosamente sem autenticação.
    allow_unauthenticated_http: bool = False
    #: Login pelo navegador (ver web_login.py): o MCP vira sua própria autorização OAuth, cujo
    #: passo de "autorização" é o SignIn real na Market Data REST. Alternativa ao IAM/API key
    #: acima — mutuamente exclusiva com elas na prática (`build_server` escolhe uma ou outra).
    web_login_enabled: bool = False

    # --- Proteção anti-DNS-rebinding (Host/Origin) ---
    # ⚠️ O FastMCP só liga essa proteção sozinho quando o host é local (127.0.0.1/localhost/::1).
    # Servindo em 0.0.0.0 atrás de um load balancer, ela fica DESLIGADA por padrão — por isso
    # expomos os allowlists aqui. Em produção, defina MCP_ALLOWED_HOSTS.
    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()

    # --- Rate limit (por token) ---
    rate_limit: int = 0  # 0 = desligado
    rate_window: float = 60.0

    # --- Estado compartilhado (ver store.py) ---
    #: Redis para rate limit, confirmações, login pelo navegador e cota — entre réplicas e
    #: restarts. ``None`` = memória do processo (o comportamento de sempre).
    redis_url: str | None = None
    #: Segredo que cifra as credenciais do login pelo navegador no store. Obrigatório com Redis.
    store_secret: str | None = None

    # --- Métricas Prometheus (/metrics) ---
    #: Bearer exigido em /metrics. ``None`` = endpoint desligado (404).
    metrics_token: str | None = None

    # --- Cota mensal por plano (ver quota.py) ---
    #: plano → chamadas de tool por mês (UTC). Vazio = sem cota.
    plan_quotas: tuple[tuple[str, int], ...] = ()
    #: Plano de quem não tem escopo ``plan:<nome>`` no token. ``None`` = esses ficam sem cota.
    default_plan: str | None = None

    # --- Logs ---
    #: Nível do root logger (``cedro_mcp.tools`` loga cada chamada em INFO, ``cedro_mcp.audit``
    #: os eventos de Trading). Ver observability.py.
    log_level: str = "INFO"

    @property
    def has_rest_credentials(self) -> bool:
        return bool(self.user and self.password)

    @property
    def has_news_credentials(self) -> bool:
        return bool(self.news_client_id and self.news_client_secret)

    @property
    def trading_base_url_value(self) -> str:
        """Host efetivo do Trading — `trading_base_url` se configurado, senão `base_url`."""
        return self.trading_base_url or self.base_url

    @property
    def auth_enabled(self) -> bool:
        """Auth do chamador liga com IAM+URL pública, OU com login pelo navegador ligado."""
        return bool(self.iam_issuer and self.resource_url) or (
            self.web_login_enabled and bool(self.resource_url)
        )

    @property
    def dns_rebinding_protection_enabled(self) -> bool:
        return bool(self.allowed_hosts or self.allowed_origins)


def _csv(raw: str | None) -> tuple[str, ...]:
    """Divide uma lista separada por vírgula, ignorando itens vazios."""
    return tuple(item.strip() for item in (raw or "").split(",") if item.strip())


def _bool(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def _normalize_transport(raw: str | None) -> str:
    """Valida ``MCP_TRANSPORT`` contra os valores suportados.

    Antes, qualquer string era aceita e tratada como ``streamable-http`` em silêncio — o valor
    mais provável de alguém tentar por engano é justamente "sse" (é o nome usado antes do MCP
    adotar Streamable HTTP), então isso escondia exatamente o erro mais provável. Falha alto e
    cedo no startup em vez disso.
    """
    value = (raw or DEFAULT_TRANSPORT).strip().lower()
    if value not in _SUPPORTED_TRANSPORTS:
        raise ConfigurationError(
            f"MCP_TRANSPORT={value!r} não é suportado. Use um de {_SUPPORTED_TRANSPORTS} "
            "(o servidor fala Streamable HTTP, não SSE)."
        )
    return value


_SUPPORTED_TRADING_ENCRYPTIONS = ("base64", "rsa")


def _normalize_trading_encryption(raw: str | None) -> str:
    value = (raw or "base64").strip().lower()
    if value not in _SUPPORTED_TRADING_ENCRYPTIONS:
        raise ConfigurationError(
            f"CEDRO_TRADING_ENCRYPTION={value!r} não é suportado. Use um de "
            f"{_SUPPORTED_TRADING_ENCRYPTIONS}."
        )
    return value


def _parse_plan_quotas(raw: str | None) -> tuple[tuple[str, int], ...]:
    """``basico:20000,pro:100000`` → ``(("basico", 20000), ("pro", 100000))``."""
    quotas: list[tuple[str, int]] = []
    for item in _csv(raw):
        name, sep, limit = item.partition(":")
        if not sep or not name.strip() or not limit.strip().isdigit():
            raise ConfigurationError(
                f"MCP_PLAN_QUOTAS inválido em {item!r}. Formato: plano:limite,plano:limite "
                "(ex.: basico:20000,pro:100000,enterprise:500000)."
            )
        quotas.append((name.strip(), int(limit)))
    return tuple(quotas)


def _default_plan(env: dict[str, str]) -> str | None:
    plan = (env.get("MCP_DEFAULT_PLAN") or "").strip() or None
    known = {name for name, _ in _parse_plan_quotas(env.get("MCP_PLAN_QUOTAS"))}
    if plan and plan not in known:
        raise ConfigurationError(
            f"MCP_DEFAULT_PLAN={plan!r} não existe em MCP_PLAN_QUOTAS ({sorted(known) or 'vazio'})."
        )
    return plan


_SUPPORTED_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def _normalize_log_level(raw: str | None) -> str:
    value = (raw or "INFO").strip().upper()
    if value not in _SUPPORTED_LOG_LEVELS:
        raise ConfigurationError(
            f"MCP_LOG_LEVEL={value!r} não é suportado. Use um de {_SUPPORTED_LOG_LEVELS}."
        )
    return value


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    """Carrega Settings do ambiente (ou de um dict, para testes).

    Carrega ``.env`` (se existir) ANTES de ler o ambiente — não sobrescreve variáveis já
    definidas no processo (comportamento padrão do `python-dotenv`), então em produção (onde as
    env vars vêm do próprio orquestrador/plataforma) isto é um no-op seguro.
    """
    if environ is None:
        from dotenv import load_dotenv

        load_dotenv()
    env = environ if environ is not None else dict(os.environ)
    # `or`, não `.get(..., default)`: uma linha `CEDRO_DOCS_PATH=` vazia no .env é uma string
    # vazia presente no ambiente, não uma chave ausente — `.get` com default não pegaria isso.
    docs_raw = env.get("CEDRO_DOCS_PATH") or DEFAULT_DOCS_PATH
    return Settings(
        base_url=env.get("CEDRO_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        user=env.get("CEDRO_USER") or None,
        password=env.get("CEDRO_PASS") or None,
        news_client_id=env.get("CEDRO_NEWS_CLIENT_ID") or None,
        news_client_secret=env.get("CEDRO_NEWS_CLIENT_SECRET") or None,
        docs_path=Path(docs_raw).expanduser(),
        http_timeout=float(env.get("CEDRO_HTTP_TIMEOUT", "15")),
        crystal_host=env.get("CEDRO_CRYSTAL_HOST") or None,
        crystal_port=int(env.get("CEDRO_CRYSTAL_PORT", "81")),
        stream_snapshot_timeout=float(env.get("CEDRO_STREAM_SNAPSHOT_TIMEOUT", "5")),
        stream_tape_limit=int(env.get("CEDRO_STREAM_TAPE_LIMIT", "1000")),
        crystal_user=env.get("CEDRO_CRYSTAL_USER") or None,
        crystal_password=env.get("CEDRO_CRYSTAL_PASSWORD") or None,
        crystal_software_key=env.get("CEDRO_CRYSTAL_SOFTWARE_KEY") or None,
        trading_user=env.get("CEDRO_TRADING_USER") or None,
        trading_password=env.get("CEDRO_TRADING_PASS") or None,
        trading_signin_user=env.get("CEDRO_TRADING_SIGNIN_USER") or None,
        trading_signin_password=env.get("CEDRO_TRADING_SIGNIN_PASS") or None,
        trading_oms_account=env.get("CEDRO_OMS_ACCOUNT") or None,
        trading_oms_login=env.get("CEDRO_OMS_LOGIN") or None,
        trading_oms_password=env.get("CEDRO_OMS_PASSWORD") or None,
        trading_encryption=_normalize_trading_encryption(env.get("CEDRO_TRADING_ENCRYPTION")),
        trading_jwks_url=env.get("CEDRO_TRADING_JWKS_URL") or None,
        trading_app_name=env.get("CEDRO_TRADING_APP_NAME") or "cedro-connect-ia",
        trading_remote_ip=env.get("CEDRO_TRADING_REMOTE_IP") or "0.0.0.0",
        trading_base_url=(env.get("CEDRO_TRADING_BASE_URL") or "").rstrip("/") or None,
        trading_max_order_value=float(env.get("CEDRO_TRADING_MAX_ORDER_VALUE") or "0"),
        trading_price_band_pct=float(env.get("CEDRO_TRADING_PRICE_BAND_PCT") or "10"),
        iam_issuer=env.get("CEDRO_IAM_ISSUER") or None,
        iam_jwks_url=env.get("CEDRO_IAM_JWKS_URL") or None,
        iam_audience=env.get("CEDRO_IAM_AUDIENCE") or None,
        api_keys_raw=env.get("CEDRO_API_KEYS") or None,
        transport=_normalize_transport(env.get("MCP_TRANSPORT")),
        mcp_host=env.get("MCP_HOST", "127.0.0.1"),
        mcp_port=int(env.get("MCP_PORT", "8000")),
        mcp_path=env.get("MCP_PATH", "/mcp"),
        resource_url=env.get("MCP_RESOURCE_URL") or None,
        allow_unauthenticated_http=_bool(env.get("MCP_ALLOW_UNAUTHENTICATED_HTTP")),
        web_login_enabled=_bool(env.get("MCP_WEB_LOGIN")),
        allowed_hosts=_csv(env.get("MCP_ALLOWED_HOSTS")),
        allowed_origins=_csv(env.get("MCP_ALLOWED_ORIGINS")),
        rate_limit=int(env.get("MCP_RATE_LIMIT", "0")),
        rate_window=float(env.get("MCP_RATE_WINDOW", "60")),
        log_level=_normalize_log_level(env.get("MCP_LOG_LEVEL")),
        redis_url=env.get("MCP_REDIS_URL") or None,
        store_secret=env.get("MCP_STORE_SECRET") or None,
        metrics_token=env.get("MCP_METRICS_TOKEN") or None,
        plan_quotas=_parse_plan_quotas(env.get("MCP_PLAN_QUOTAS")),
        default_plan=_default_plan(env),
    )
