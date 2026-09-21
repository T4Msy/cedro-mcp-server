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
    #: Credenciais de serviço para Socket/Trading (só usadas por `ServiceAccountCredentialProvider`
    #: — dev/stdio; em produção via `MCP_WEB_LOGIN`, cada usuário traz a própria no formulário).
    socket_user: str | None = None
    socket_password: str | None = None
    trading_user: str | None = None
    trading_password: str | None = None
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

    @property
    def has_rest_credentials(self) -> bool:
        return bool(self.user and self.password)

    @property
    def has_news_credentials(self) -> bool:
        return bool(self.news_client_id and self.news_client_secret)

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
        socket_user=env.get("CEDRO_SOCKET_USER") or None,
        socket_password=env.get("CEDRO_SOCKET_PASS") or None,
        trading_user=env.get("CEDRO_TRADING_USER") or None,
        trading_password=env.get("CEDRO_TRADING_PASS") or None,
        trading_encryption=_normalize_trading_encryption(env.get("CEDRO_TRADING_ENCRYPTION")),
        trading_jwks_url=env.get("CEDRO_TRADING_JWKS_URL") or None,
        trading_app_name=env.get("CEDRO_TRADING_APP_NAME") or "cedro-connect-ia",
        trading_remote_ip=env.get("CEDRO_TRADING_REMOTE_IP") or "0.0.0.0",
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
    )
