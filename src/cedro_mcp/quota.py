"""Cota mensal por plano (ex.: 20k/100k/500k chamadas de tool por mês).

Monthly per-plan quota. O que conta é **chamada de tool** (o que o cliente percebe como
"requisição"), não request HTTP do protocolo MCP (listagem, handshake). Conta por identidade —
``subject`` do token, senão ``client_id`` — no mês-calendário UTC; zera no dia 1º.

**De onde vem o plano:** escopo ``plan:<nome>`` no token (IAM ou API key — ex.:
``CEDRO_API_KEYS=k_abc:robo:marketdata:read|plan:pro``). Sem esse escopo, vale
``MCP_DEFAULT_PLAN``; sem default, a identidade fica sem cota. No login pelo navegador o cliente não
consegue pedir ``plan:*`` (não está em ``valid_scopes``), então todo mundo cai no default.

Os contadores vivem no store: com Redis, a cota é global entre réplicas e sobrevive a restart; em
memória, é por processo e zera no restart.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcp.server.auth.provider import AccessToken

from .config import Settings
from .errors import CedroQuotaError
from .metrics import QUOTA_EXCEEDED
from .session_pool import hash_key
from .store import Store

PLAN_SCOPE_PREFIX = "plan:"
#: TTL dos contadores — cobre o mês mais longo com folga; o mês vai na chave.
_COUNTER_TTL = 40 * 24 * 3600
#: Tools que não consomem cota (consultar a própria cota não pode gastá-la).
EXEMPT_TOOLS = frozenset({"account_get_usage"})


def _month(now: datetime) -> str:
    return now.strftime("%Y%m")


def _next_reset(now: datetime) -> str:
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return f"{year:04d}-{month:02d}-01"


class QuotaPolicy:
    def __init__(self, settings: Settings, store: Store) -> None:
        self._limits = dict(settings.plan_quotas)
        self._default_plan = settings.default_plan
        self.store = store

    @property
    def enabled(self) -> bool:
        return bool(self._limits)

    def plan_for(self, principal: AccessToken) -> str | None:
        for scope in principal.scopes:
            if scope.startswith(PLAN_SCOPE_PREFIX):
                name = scope[len(PLAN_SCOPE_PREFIX):]
                if name in self._limits:
                    return name
        return self._default_plan

    def _key(self, principal: AccessToken, now: datetime) -> str:
        identity = principal.subject or principal.client_id
        return f"quota:{_month(now)}:{hash_key(identity)}"

    def consume(self, principal: AccessToken | None, tool: str) -> None:
        """Conta uma chamada; levanta ``CedroQuotaError`` se passou do limite do plano."""
        if not self.enabled or principal is None or tool in EXEMPT_TOOLS:
            return
        plan = self.plan_for(principal)
        if plan is None:
            return
        now = datetime.now(timezone.utc)
        used = self.store.incr(self._key(principal, now), _COUNTER_TTL)
        limit = self._limits[plan]
        if used > limit:
            QUOTA_EXCEEDED.labels(plan).inc()
            raise CedroQuotaError(
                f"Cota mensal do plano '{plan}' esgotada ({limit:,} chamadas). Ela renova em "
                f"{_next_reset(now)} (UTC). Para ampliar, fale com a comercial da Cedro."
            )

    def usage(self, principal: AccessToken | None) -> dict[str, object]:
        if principal is None:
            return {"plan": None, "limited": False, "note": "Sem autenticação — sem cota."}
        plan = self.plan_for(principal) if self.enabled else None
        if plan is None:
            return {"plan": None, "limited": False, "note": "Nenhuma cota se aplica a você."}
        now = datetime.now(timezone.utc)
        raw = self.store.get(self._key(principal, now))
        used = int(raw) if raw else 0
        limit = self._limits[plan]
        return {
            "plan": plan,
            "limited": True,
            "used": used,
            "limit": limit,
            "remaining": max(limit - used, 0),
            "resets_on": _next_reset(now),
        }
