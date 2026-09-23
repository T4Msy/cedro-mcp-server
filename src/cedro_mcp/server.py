"""Ponto de entrada do **Cedro Connect IA** — o MCP server das APIs da Cedro.

Entry point for the Cedro Connect IA MCP server (Market Data REST, streaming e Trading). Transporte padrão: **Streamable HTTP**
(cliente só precisa de URL + token). ``stdio`` continua disponível para desenvolvimento local.
"""

from __future__ import annotations

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# Imports absolutos (não relativos): o `mcp dev` carrega este arquivo pelo caminho,
# fora do contexto de pacote, e imports relativos (`from .`) quebrariam. O pacote
# está instalado (`pip install -e`), então o import absoluto resolve nos dois casos.
from cedro_mcp import prompts, resources, tools
from cedro_mcp.auth.api_key import EnvApiKeyStore
from cedro_mcp.auth.entitlements import EntitledFastMCP
from cedro_mcp.auth.scopes import (
    MARKETDATA_NEWS,
    MARKETDATA_READ,
    MARKETDATA_STREAM,
    TRADING_READ,
    TRADING_TRADE,
    TRADING_TRIGGER,
)
from cedro_mcp.auth.token_verifier import CedroTokenVerifier, build_jwks_decoder
from cedro_mcp.client import CedroClient
from cedro_mcp.config import ConfigurationError, Settings, load_settings
from cedro_mcp.credentials import (
    CredentialProvider,
    ServiceAccountCredentialProvider,
    WebLoginCredentialProvider,
)
from cedro_mcp.observability import configure_audit, configure_logging
from cedro_mcp.quota import QuotaPolicy
from cedro_mcp.store import Store, build_secret_box, build_store
from cedro_mcp.streaming import MarketDataStreamClient
from cedro_mcp.tools import account
from cedro_mcp.tools import trading as tools_trading
from cedro_mcp.trading.client import TradingClient
from cedro_mcp.trading.confirmation import ConfirmationStore
from cedro_mcp.web_login import CedroLoginProvider

#: Nome anunciado aos clientes MCP no handshake (``serverInfo.name``). Os clientes identificam o
#: servidor pela URL, não por este nome — trocá-lo não quebra conexões existentes.
SERVER_NAME = "cedro-connect-ia"

_INSTRUCTIONS = (
    "Cedro Connect IA — tools das APIs da Cedro: Market Data REST (cotações, candles, book, negócios, rankings e "
    "notícias) e streaming são somente leitura. Trading envia ordens REAIS: toda escrita passa "
    "por trading_preview_* e só executa com trading_confirm depois de o usuário confirmar "
    "explicitamente o resumo nesta conversa. As tools visíveis dependem do seu contrato/plano. "
    "Consulte os contratos em cedro-docs://index. "
    "Cedro API tools: market data is read-only; trading places REAL orders only via "
    "preview + explicit user confirmation. Visibility depends on your plan."
)


def build_token_verifier(settings: Settings) -> TokenVerifier:
    """Verifica o bearer do chamador: API key (automação) ou JWT do IAM."""
    api_key_store = EnvApiKeyStore(settings.api_keys_raw)
    jwt_decoder = None
    if settings.iam_jwks_url and settings.iam_issuer:
        if not settings.iam_audience:
            # Sem audience, `verify_aud` é pulada silenciosamente (ver build_jwks_decoder) — um
            # JWT emitido para OUTRO resource no mesmo Identity Server seria aceito aqui.
            raise ConfigurationError(
                "CEDRO_IAM_AUDIENCE é obrigatório quando a auth do IAM está habilitada "
                "(CEDRO_IAM_ISSUER + CEDRO_IAM_JWKS_URL definidos)."
            )
        jwt_decoder = build_jwks_decoder(
            settings.iam_jwks_url, settings.iam_issuer, settings.iam_audience
        )
    return CedroTokenVerifier(api_key_store=api_key_store, jwt_decoder=jwt_decoder)


def _issuer_url(resource_url: str, mcp_path: str) -> str:
    """Deriva a base pública (sem o path do MCP) a partir de ``MCP_RESOURCE_URL``.

    Ex.: ``http://127.0.0.1:8000/mcp`` + ``/mcp`` → ``http://127.0.0.1:8000``. Usado como
    ``issuer_url`` quando o próprio servidor é a autoridade OAuth (login pelo navegador) — ver
    ``web_login.py``.
    """
    base = resource_url[: -len(mcp_path)] if resource_url.endswith(mcp_path) else resource_url
    return base.rstrip("/") or resource_url


def build_server(
    settings: Settings | None = None,
    client: CedroClient | None = None,
    stream_client: MarketDataStreamClient | None = None,
    token_verifier: TokenVerifier | None = None,
    *,
    enforce_auth_guard: bool = True,
    store: Store | None = None,
) -> FastMCP:
    """Monta o servidor FastMCP com tools, resources e (se configurado) autenticação.

    Injeção de ``settings``/``client``/``token_verifier`` facilita os testes.
    Sem IAM configurado (``auth_enabled == False``), o servidor sobe **sem autenticação** —
    apropriado só para desenvolvimento local via stdio.

    ``enforce_auth_guard`` (default True) recusa montar o servidor sem auth em qualquer
    transporte que não seja stdio, a menos que ``settings.allow_unauthenticated_http`` seja
    explicitamente True — sem essa guarda, uma env var faltando/errada em produção (streamable-
    http) exporia todas as tools sem autenticação nenhuma, sem nenhum aviso. Testes que montam um
    servidor stdio-like sem auth não são afetados; quem realmente precisa de um servidor HTTP
    sem auth (demo local) passa ``enforce_auth_guard=False`` ou seta
    ``MCP_ALLOW_UNAUTHENTICATED_HTTP=true``.
    """
    settings = settings or load_settings()

    if (
        enforce_auth_guard
        and settings.transport != "stdio"
        and not settings.auth_enabled
        and not settings.allow_unauthenticated_http
    ):
        missing = [
            name
            for name, value in (
                ("MCP_RESOURCE_URL", settings.resource_url),
                ("CEDRO_IAM_ISSUER (auth via IAM) OU MCP_WEB_LOGIN=true (login pelo navegador)",
                 settings.iam_issuer or settings.web_login_enabled),
            )
            if not value
        ]
        raise ConfigurationError(
            "Auth do chamador desligada rodando em transporte "
            f"'{settings.transport}' (faltam: {', '.join(missing)}) — isso exporia todas as tools "
            "sem autenticação nenhuma. Defina as variáveis, ou explicitamente "
            "MCP_ALLOW_UNAUTHENTICATED_HTTP=true se isto for intencional (ex.: demo local)."
        )

    # Estado compartilhável (rate limit, confirmações, login, cota): memória ou Redis.
    store = store or build_store(settings)
    box = build_secret_box(settings, store)
    quota = QuotaPolicy(settings, store)
    configure_audit(store)

    login_provider: CedroLoginProvider | None = None
    credential_provider: CredentialProvider
    if settings.web_login_enabled:
        login_provider = CedroLoginProvider(settings, store=store, box=box)
        credential_provider = WebLoginCredentialProvider(login_provider)
    else:
        credential_provider = ServiceAccountCredentialProvider(settings)

    client = client or CedroClient(settings, credential_provider=credential_provider)
    stream_client = stream_client or MarketDataStreamClient(settings, credential_provider)
    trading_client = TradingClient(settings, credential_provider)
    confirmation_store = ConfirmationStore(store)

    kwargs: dict = {
        "instructions": _INSTRUCTIONS,
        "host": settings.mcp_host,
        "port": settings.mcp_port,
        "streamable_http_path": settings.mcp_path,
        # O protocolo MCP segue sem sessão entre requests. O cache Crystal é estado do processo;
        # deploys que o habilitam precisam respeitar uma única réplica por credencial Socket.
        "stateless_http": True,
    }

    # Sem isto, servindo em 0.0.0.0 o FastMCP deixa a proteção anti-DNS-rebinding desligada.
    if settings.dns_rebinding_protection_enabled:
        kwargs["transport_security"] = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(settings.allowed_hosts),
            allowed_origins=list(settings.allowed_origins),
        )

    if login_provider is not None:
        # O próprio MCP é a autoridade OAuth (login pelo navegador) — nada de IAM externo.
        kwargs["auth_server_provider"] = login_provider
        kwargs["auth"] = AuthSettings(
            issuer_url=_issuer_url(settings.resource_url, settings.mcp_path),
            resource_server_url=settings.resource_url,
            required_scopes=[MARKETDATA_READ],
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                # trading:*/marketdata:stream ficam de fora do default de propósito — nunca
                # concedidos automaticamente a um client que só se registrou (DCR). Um client
                # pode pedir explicitamente no /authorize, mas o gate real de segurança é outro:
                # nenhuma tool de Trading executa sem credencial de verdade no bundle (ver
                # credentials.py::WebLoginCredentialProvider.trading_credentials_for), scope é
                # só a primeira camada.
                valid_scopes=[
                    MARKETDATA_READ,
                    MARKETDATA_NEWS,
                    MARKETDATA_STREAM,
                    TRADING_READ,
                    TRADING_TRADE,
                    TRADING_TRIGGER,
                ],
                default_scopes=[MARKETDATA_READ, MARKETDATA_NEWS],
            ),
        )
    elif settings.auth_enabled:
        kwargs["token_verifier"] = token_verifier or build_token_verifier(settings)
        kwargs["auth"] = AuthSettings(
            issuer_url=settings.iam_issuer,
            resource_server_url=settings.resource_url,
            # Escopo mínimo para falar com o MCP de Market Data.
            required_scopes=[MARKETDATA_READ],
        )

    mcp = EntitledFastMCP(SERVER_NAME, quota=quota, **kwargs)

    tools.register_all(mcp, client, stream_client)
    tools_trading.register(
        mcp, trading_client, confirmation_store, credential_provider, settings, client
    )
    resources.register(mcp, settings)
    prompts.register(mcp)
    account.register(mcp, quota)

    if login_provider is not None:
        # Ponto de integração lido por http_app.create_app() pra montar /cedro-login no mesmo
        # app ASGI — não é um atributo do FastMCP em si, só carona pra não precisar mudar a
        # assinatura de build_server() em todo lugar que já a chama.
        mcp.cedro_login_provider = login_provider  # type: ignore[attr-defined]

    # Lido por http_app.create_app(): rate limit e /health usam o mesmo store.
    mcp.cedro_store = store  # type: ignore[attr-defined]

    # main() fecha esse registro no shutdown. A conexão só nasce quando uma tool stream_* for usada.
    mcp.cedro_stream_client = stream_client  # type: ignore[attr-defined]

    return mcp


def main() -> None:
    """Executa o servidor no transporte configurado (padrão: streamable-http)."""
    settings = load_settings()
    configure_logging(settings.log_level)
    mcp = build_server(settings)

    if settings.transport == "stdio":
        try:
            mcp.run()
        finally:
            mcp.cedro_stream_client.close()  # type: ignore[attr-defined]
        return

    import uvicorn

    from cedro_mcp.http_app import create_app

    app = create_app(
        mcp,
        rate_limit=settings.rate_limit,
        rate_window=settings.rate_window,
        metrics_token=settings.metrics_token,
    )
    try:
        uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
    finally:
        mcp.cedro_stream_client.close()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
