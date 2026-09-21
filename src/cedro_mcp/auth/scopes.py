"""Escopos MCP e o mapeamento vindo dos `roles`/`claims` do Identity Server.

MCP scopes and the mapping from the Identity Server's `roles`/`claims`.

⚠️ **Provisório:** os nomes abaixo ainda **não foram confirmados** com a Cedro (pendência com o
Saulo). Este módulo é o **único ponto de verdade** — renomear aqui basta.
"""

from __future__ import annotations

from typing import Any

#: Acesso de leitura ao Market Data (cotações, candles, book, negócios, rankings).
MARKETDATA_READ = "marketdata:read"

#: Acesso ao módulo de Notícias (plano/contrato separado dentro de Market Data).
MARKETDATA_NEWS = "marketdata:news"

ALL_SCOPES: tuple[str, ...] = (MARKETDATA_READ, MARKETDATA_NEWS)

#: Tradução `role` do IAM → escopos MCP. Ajustar quando o Saulo confirmar os nomes reais.
IAM_ROLE_TO_SCOPES: dict[str, tuple[str, ...]] = {
    "MarketData": (MARKETDATA_READ,),
    "MarketDataNews": (MARKETDATA_NEWS,),
}


def scopes_from_claims(claims: dict[str, Any]) -> list[str]:
    """Extrai os escopos MCP das claims de um token do IAM.

    Aceita as formas usuais de OAuth2/OIDC, nesta ordem de precedência:
    - ``scope`` (string separada por espaço) ou ``scp`` (string ou lista);
    - ``roles`` (lista), traduzidas por :data:`IAM_ROLE_TO_SCOPES`.

    Escopos desconhecidos são **preservados** (não filtramos o que não conhecemos);
    roles desconhecidas são ignoradas.
    """
    scopes: list[str] = []

    raw_scope = claims.get("scope") or claims.get("scp")
    if isinstance(raw_scope, str):
        scopes.extend(raw_scope.split())
    elif isinstance(raw_scope, list):
        scopes.extend(str(s) for s in raw_scope)

    roles = claims.get("roles")
    if isinstance(roles, str):
        roles = [roles]
    if isinstance(roles, list):
        for role in roles:
            scopes.extend(IAM_ROLE_TO_SCOPES.get(str(role), ()))

    # Dedup preservando a ordem.
    return list(dict.fromkeys(scopes))
