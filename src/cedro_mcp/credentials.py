"""Credenciais **downstream**: como o MCP se autentica nas APIs da Cedro.

Downstream credentials: how the MCP authenticates *to* Cedro's APIs (not how it authenticates its
own callers — isso é ``auth/``).

Três produtos, três credenciais **distintas** — nunca a mesma conta: Market Data REST e Market
Data Socket já são mutuamente exclusivas por login (ver docs/arquitetura/05-escopo-comercial.md),
e Trading é uma conta OMS separada. Por isso ``RestCredentials``/``SocketCredentials``/
``TradingCredentials`` são tipos distintos mesmo tendo o mesmo formato (usuário/senha) — o
type-checker impede passar a credencial errada para o cliente errado por engano.

⚠️ **Pendência com o Saulo:** ainda não está decidido se o MCP usa uma *service account* única ou faz
*token exchange* para uma sessão por usuário (o que importa para atribuir consumo/**FEES** ao cliente
certo) — isso vale só para o modo IAM (`PerUserCredentialProvider`, ainda stub). Em produção hoje o
modo ativo é ``WebLoginCredentialProvider`` (login pelo navegador), que já resolve por usuário.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from mcp.server.auth.provider import AccessToken

from .config import Settings
from .errors import CedroAuthError

if TYPE_CHECKING:
    from .web_login import CedroLoginProvider


@dataclass(frozen=True)
class RestCredentials:
    """Usuário/senha usados no ``POST /SignIn`` do Market Data REST."""

    user: str | None
    password: str | None

    @property
    def is_complete(self) -> bool:
        return bool(self.user and self.password)


@dataclass(frozen=True)
class SocketCredentials:
    """Usuário/senha do Market Data Socket (protocolo Crystal) — conta separada da REST."""

    user: str | None
    password: str | None
    #: Software key opcional, enviada como primeira linha do handshake Crystal.
    software_key: str | None = None

    @property
    def is_complete(self) -> bool:
        return bool(self.user and self.password)


@dataclass(frozen=True)
class TradingCredentials:
    """Credenciais do Trading: SignIn HTTP separado da identidade OMS.

    ``user``/``password`` são mantidos como os nomes históricos do par usado no
    ``POST /SignIn``. A identidade OMS pode ter login e senha próprios; quando
    esses campos não são informados, fazemos fallback para o par histórico para
    preservar o modo de serviço antigo.
    """

    user: str | None
    password: str | None
    oms_account: str | None = None
    oms_login: str | None = None
    oms_password: str | None = None

    @property
    def oms_account_value(self) -> str | None:
        """Conta OMS para parâmetros de ordem, quando configurada."""
        return self.oms_account or self.oms_login or self.user

    @property
    def oms_login_value(self) -> str | None:
        """Login usado no header ``user-identifier`` e no brokerServiceLogin."""
        return self.oms_login or self.oms_account or self.user

    @property
    def oms_password_value(self) -> str | None:
        """Senha usada na identidade OMS, com fallback legado para ``password``."""
        return self.oms_password or self.password

    @property
    def is_complete(self) -> bool:
        return bool(self.user and self.password and self.oms_login_value and self.oms_password_value)


@dataclass(frozen=True)
class CedroCredentialBundle:
    """As credenciais que um principal trouxe — cada produto é opcional e independente.

    Um usuário pode ter só Market Data REST contratado, ou os três — o bundle nunca força a
    presença de nenhum. Tools de um produto cujo campo aqui é ``None`` devem falhar com uma
    mensagem clara ("faça login com uma credencial de Trading"), não com um erro genérico.
    """

    rest: RestCredentials | None = None
    socket: SocketCredentials | None = None
    trading: TradingCredentials | None = None


class CredentialProvider(Protocol):
    """Resolve as credenciais Cedro a usar em nome de um principal autenticado, por produto.

    ``principal`` é ``None`` quando não há autenticação ativa (ex.: stdio em desenvolvimento).
    Um método por produto (em vez de devolver o bundle inteiro) deixa explícito, no próprio
    call site, qual credencial aquele cliente precisa — e cada implementação decide como
    reagir à ausência dela (ex.: ``CedroAuthError`` com instrução de qual login falta).
    """

    def rest_credentials_for(self, principal: AccessToken | None) -> RestCredentials: ...

    def socket_credentials_for(self, principal: AccessToken | None) -> SocketCredentials: ...

    def trading_credentials_for(self, principal: AccessToken | None) -> TradingCredentials: ...

    def session_key(self, principal: AccessToken | None) -> str:
        """Chave de isolamento de sessão (uma sessão por chave, por produto)."""
        ...


class ServiceAccountCredentialProvider:
    """**Default de desenvolvimento:** uma única conta de serviço por produto configurado.

    Simples e suficiente para destravar o desenvolvimento local (`stdio`). Custo: todo o consumo
    é atribuído a uma conta só por produto (impacta FEES e rate limit por cliente) — ver
    pendência no topo do módulo. Produtos sem credencial configurada devolvem uma credencial
    vazia (`is_complete == False`), não erro — a checagem de completude é responsabilidade de
    quem consome (`SessionAuth`/clients), igual já acontecia antes desta mudança.
    """

    def __init__(self, settings: Settings) -> None:
        self._rest = RestCredentials(settings.user, settings.password)
        self._socket = SocketCredentials(
            settings.crystal_user,
            settings.crystal_password,
            settings.crystal_software_key,
        )
        # Compatibilidade: o modo antigo tinha só CEDRO_TRADING_USER/PASS e usava
        # o mesmo par no SignIn e no user-identifier. O modo separado aceita o
        # par CEDRO_USER/PASS (ou CEDRO_TRADING_SIGNIN_*) + CEDRO_OMS_*.
        has_oms_identity = any(
            (
                settings.trading_oms_account,
                settings.trading_oms_login,
                settings.trading_oms_password,
            )
        )
        signin_user = settings.trading_signin_user or settings.trading_user
        signin_password = settings.trading_signin_password or settings.trading_password
        if has_oms_identity:
            signin_user = signin_user or settings.user
            signin_password = signin_password or settings.password
        self._trading = TradingCredentials(
            signin_user,
            signin_password,
            settings.trading_oms_account,
            settings.trading_oms_login,
            settings.trading_oms_password,
        )

    def rest_credentials_for(self, principal: AccessToken | None) -> RestCredentials:
        return self._rest

    def socket_credentials_for(self, principal: AccessToken | None) -> SocketCredentials:
        return self._socket

    def trading_credentials_for(self, principal: AccessToken | None) -> TradingCredentials:
        return self._trading

    def session_key(self, principal: AccessToken | None) -> str:
        return "service-account"


class PerUserCredentialProvider:
    """**Stub:** sessão Market Data/Trading por usuário, derivada da identidade do IAM.

    Preencher quando o Saulo definir o mecanismo. Provavelmente envolve:
    - trocar o token do IAM por credenciais/conta Market Data do cliente (token exchange), e
    - respeitar o **limite de conexões simultâneas** de cada produto ao manter N sessões (para o
      Socket, isso é crítico: 1 conexão por login — ver `socket/manager.py`).
    """

    def _not_implemented(self) -> NotImplementedError:
        return NotImplementedError(
            "Sessão por usuário ainda não definida — ver pendência com o Saulo "
            "(token exchange IAM → credencial Cedro, atribuição de FEES)."
        )

    def rest_credentials_for(self, principal: AccessToken | None) -> RestCredentials:
        raise self._not_implemented()

    def socket_credentials_for(self, principal: AccessToken | None) -> SocketCredentials:
        raise self._not_implemented()

    def trading_credentials_for(self, principal: AccessToken | None) -> TradingCredentials:
        raise self._not_implemented()

    def session_key(self, principal: AccessToken | None) -> str:
        if principal is None or not principal.subject:
            raise NotImplementedError("Principal sem `subject` não pode ter sessão dedicada.")
        return principal.subject


class WebLoginCredentialProvider:
    """Credenciais resolvidas a partir do login feito no navegador (``web_login.py``).

    ``principal`` aqui é o ``AccessToken`` emitido pelo :class:`~cedro_mcp.web_login.
    CedroLoginProvider` — o mesmo token que autenticou o chamador do MCP também é a chave pra
    achar o :class:`CedroCredentialBundle` associado a ele (um usuário pode ter preenchido só
    REST, só Socket, só Trading, ou os três no formulário de login). Uma credencial por token ⇒
    uma sessão por token e por produto (via `SessionRegistry`/`SocketConnectionRegistry`/
    `TradingClient`), nunca compartilhada entre clientes.
    """

    def __init__(self, login_provider: "CedroLoginProvider") -> None:
        self._login_provider = login_provider

    def _bundle_for(self, principal: AccessToken | None) -> CedroCredentialBundle:
        if principal is None:
            raise CedroAuthError("Não autenticado — faça login em /cedro-login primeiro.")
        bundle = self._login_provider.credentials_for_token(principal.token)
        if bundle is None:
            raise CedroAuthError(
                "Sessão de login não encontrada ou expirada — refaça o login pelo navegador."
            )
        return bundle

    def rest_credentials_for(self, principal: AccessToken | None) -> RestCredentials:
        bundle = self._bundle_for(principal)
        if bundle.rest is None:
            raise CedroAuthError(
                "Esta conta não fez login com uma credencial de Market Data REST — refaça o "
                "login em /cedro-login e preencha essa seção."
            )
        return bundle.rest

    def socket_credentials_for(self, principal: AccessToken | None) -> SocketCredentials:
        bundle = self._bundle_for(principal)
        if bundle.socket is None:
            raise CedroAuthError(
                "Esta conta não fez login com uma credencial de Market Data Socket — refaça o "
                "login em /cedro-login e preencha essa seção."
            )
        return bundle.socket

    def trading_credentials_for(self, principal: AccessToken | None) -> TradingCredentials:
        bundle = self._bundle_for(principal)
        if bundle.trading is None:
            raise CedroAuthError(
                "Esta conta não fez login com uma credencial de Trading — refaça o login em "
                "/cedro-login e preencha essa seção."
            )
        return bundle.trading

    def session_key(self, principal: AccessToken | None) -> str:
        if principal is None:
            raise CedroAuthError("Não autenticado — faça login em /cedro-login primeiro.")
        return principal.token
