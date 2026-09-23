"""Logs operacionais, trilha de auditoria de Trading e execução de tools fora do event loop.

Operational logs, Trading audit trail and off-loop tool execution.

- ``cedro_mcp.tools``: uma linha por chamada de tool (nome, principal, resultado, duração). Nunca
  loga argumentos nem retorno — podem conter conta/ordem do cliente.
- ``cedro_mcp.audit``: eventos de Trading (preview, confirm, rejeição). É a trilha que responde
  "quem mandou esta ordem". Além do log, cada evento vai para o store (``configure_audit``):
  um log global (``audit:all``, últimos 10 mil) e um por identidade (últimos 500) — em memória ou,
  com Redis, persistente. O usuário lê os próprios com ``trading_get_audit``.

O principal aparece só como ``client_id`` + prefixo do hash do token: nunca o token em si (no
login pelo navegador ele é a credencial do chamador).
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
import time
from datetime import datetime, timezone
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import anyio.to_thread
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from . import store as store_mod
from .errors import CedroQuotaError
from .metrics import TOOL_CALLS, TOOL_DURATION

if TYPE_CHECKING:
    from .quota import QuotaPolicy

tool_logger = logging.getLogger("cedro_mcp.tools")
audit_logger = logging.getLogger("cedro_mcp.audit")

AUDIT_ALL_KEY = "audit:all"
AUDIT_ALL_MAXLEN = 10_000
AUDIT_USER_MAXLEN = 500
#: Store que recebe a trilha de auditoria — definido por build_server(). None = só log.
_audit_store: store_mod.Store | None = None


def configure_audit(store: store_mod.Store | None) -> None:
    global _audit_store
    _audit_store = store


def audit_identity_key(token: AccessToken | None) -> str:
    """Chave do log por identidade: ``subject``, senão ``client_id`` — em hash."""
    if token is None:
        return "audit:user:anonymous"
    from .session_pool import hash_key

    return f"audit:user:{hash_key(token.subject or token.client_id)}"


def configure_logging(level: str) -> None:
    """Configura o root logger uma vez, no startup (``main``)."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def principal_label() -> str:
    """Identificação não-secreta do chamador atual, para log."""
    token = get_access_token()
    if token is None:
        return "anonymous"
    digest = hashlib.sha256(token.token.encode()).hexdigest()[:12]
    return f"{token.client_id}#{digest}"


def _format(fields: dict[str, Any]) -> str:
    return " ".join(f"{key}={value!r}" for key, value in fields.items())


def audit(event: str, **fields: Any) -> None:
    """Registra um evento de auditoria de Trading: no log e, se configurado, no store."""
    label = principal_label()
    audit_logger.info("event=%s principal=%s %s", event, label, _format(fields))
    if _audit_store is None:
        return
    entry = json.dumps(
        {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            "principal": label,
            **fields,
        },
        default=str,
        ensure_ascii=False,
    ).encode()
    try:
        _audit_store.append_log(AUDIT_ALL_KEY, entry, AUDIT_ALL_MAXLEN)
        _audit_store.append_log(audit_identity_key(get_access_token()), entry, AUDIT_USER_MAXLEN)
    except Exception:  # noqa: BLE001 — auditoria no store nunca derruba a operação
        audit_logger.exception("event=audit_store_failed original_event=%s", event)


def read_own_audit(limit: int) -> list[dict[str, Any]]:
    """Eventos de auditoria do chamador atual, do mais recente para o mais antigo."""
    if _audit_store is None:
        return []
    raw = _audit_store.read_log(audit_identity_key(get_access_token()), limit)
    return [json.loads(item) for item in raw]


def instrument_tool(
    fn: Callable[..., Any], name: str, quota: QuotaPolicy | None = None
) -> Callable[..., Any]:
    """Envolve uma tool: cota, execução fora do event loop, log e métricas de cada chamada.

    A cota (``quota.py``) é conferida antes de executar: estourada, a tool nem roda.

    O FastMCP 1.x chama tools síncronas **direto no event loop** — uma chamada lenta à Cedro (ou
    um ``SignIn``) travaria todas as outras requisições do processo, inclusive ``/cedro-login``.
    ``anyio.to_thread.run_sync`` propaga os contextvars, então ``get_access_token()`` continua
    enxergando o principal dentro da thread.

    ``functools.wraps`` preserva nome, docstring e assinatura (o schema da tool não muda);
    ``__wrapped__`` aponta para a função original, que os testes chamam direto.
    """
    run_in_thread = not inspect.iscoroutinefunction(fn)

    @functools.wraps(fn)
    async def wrapper(**kwargs: Any) -> Any:
        started = time.perf_counter()
        outcome, error_type = "ok", ""
        try:
            if quota is not None and quota.enabled:
                await store_mod.call(quota.store, quota.consume, get_access_token(), name)
            if run_in_thread:
                return await anyio.to_thread.run_sync(functools.partial(fn, **kwargs))
            return await fn(**kwargs)
        except CedroQuotaError:
            outcome = "quota_exceeded"
            raise
        except Exception as exc:
            outcome, error_type = "error", type(exc).__name__
            raise
        finally:
            elapsed = time.perf_counter() - started
            TOOL_CALLS.labels(name, outcome, error_type).inc()
            TOOL_DURATION.labels(name).observe(elapsed)
            tool_logger.info(
                "tool=%s principal=%s outcome=%s duration_ms=%d",
                name,
                principal_label(),
                outcome if not error_type else f"error:{error_type}",
                elapsed * 1000,
            )

    return wrapper
