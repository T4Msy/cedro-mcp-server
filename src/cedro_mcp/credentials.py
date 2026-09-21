"""Credencial **downstream**: como o MCP se autentica nas APIs da Cedro.

Downstream credentials: how the MCP authenticates *to* Cedro's APIs (not how it authenticates its
own callers — isso é ``auth/``).

⚠️ **Pendência com o Saulo:** ainda não está decidido se o MCP usa uma *service account* única ou faz
*token exchange* para uma sessão por usuário (o que importa para atribuir consumo/**FEES** ao cliente
certo). Por isso isto é uma **interface**: quando a resposta vier, troca-se só a implementação.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.auth.provider import AccessToken

from .config import Settings


@dataclass(frozen=True)
class RestCredentials:
    """Usuário/senha usados no ``POST /SignIn`` do Market Data."""

    user: str | None
    password: str | None

    @property
    def is_complete(self) -> bool:
        return bool(self.user and self.password)


class CredentialProvider(Protocol):
    """Resolve a credencial Cedro a usar em nome de um principal autenticado.

    ``principal`` é ``None`` quando não há autenticação ativa (ex.: stdio em desenvolvimento).
    """

    def credentials_for(self, principal: AccessToken | None) -> RestCredentials: ...

    def session_key(self, principal: AccessToken | None) -> str:
        """Chave de isolamento da sessão HTTP (uma sessão `JSESSIONID` por chave)."""
        ...


class ServiceAccountCredentialProvider:
    """**Default atual:** uma única conta de serviço para todos os chamadores.

    Simples e suficiente para destravar o desenvolvimento. Custo: todo o consumo é atribuído a uma
    conta só (impacta FEES e rate limit por cliente) — ver pendência no topo do módulo.
    """

    def __init__(self, settings: Settings) -> None:
        self._credentials = RestCredentials(settings.user, settings.password)

    def credentials_for(self, principal: AccessToken | None) -> RestCredentials:
        return self._credentials

    def session_key(self, principal: AccessToken | None) -> str:
        return "service-account"


class PerUserCredentialProvider:
    """**Stub:** sessão Market Data por usuário, derivada da identidade do IAM.

    Preencher quando o Saulo definir o mecanismo. Provavelmente envolve:
    - trocar o token do IAM por credenciais/conta Market Data do cliente (token exchange), e
    - respeitar o **limite de conexões simultâneas** do Market Data ao manter N sessões.
    """

    def credentials_for(self, principal: AccessToken | None) -> RestCredentials:
        raise NotImplementedError(
            "Sessão por usuário ainda não definida — ver pendência com o Saulo "
            "(token exchange IAM → credencial Market Data, atribuição de FEES)."
        )

    def session_key(self, principal: AccessToken | None) -> str:
        if principal is None or not principal.subject:
            raise NotImplementedError("Principal sem `subject` não pode ter sessão dedicada.")
        return principal.subject
