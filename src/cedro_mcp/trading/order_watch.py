"""Espera uma ordem chegar a um estado conclusivo, consultando o ``dailyOrder`` com intervalo.

Existe porque a resposta de envio/edição/cancelamento só confirma que o OMS **recebeu** o
pedido — a execução, a rejeição e a aplicação de uma edição chegam depois, de forma assíncrona.
Sem isto o modelo precisa lembrar de reconsultar (e costuma não lembrar, ou consulta em loop).

Limites de propósito: no máximo 60 s, intervalo mínimo de 2 s (≤ 30 consultas), e só o
``dailyOrder`` — nunca o ``historyOrder``, que derruba em code 101 sob polling.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .day_summary import field_value
from .models import OPEN_ORDER_STATES

MAX_TIMEOUT = 60.0
MIN_INTERVAL = 2.0


class OrderWatchResult(BaseModel):
    clordid: str
    found: bool
    #: True quando a condição pedida foi atingida (estado final, ou a edição esperada aplicada).
    reached: bool
    state: str | None = None
    is_open: bool | None = None
    quantity: float | None = None
    quantity_executed: float | None = None
    quantity_remaining: float | None = None
    price: float | None = None
    average_price: float | None = None
    oms_text: str | None = None
    checks: int
    elapsed_seconds: float
    note: str


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def find_order(payload: dict[str, Any], clordid: str) -> dict[str, Any] | None:
    for bean in payload.get("listBeans") or []:
        if isinstance(bean, dict) and str(field_value(bean, "clOrdID") or "") == clordid:
            return bean
    return None


def _matches_edit(bean: dict[str, Any], price: float | None, qty: float | None) -> bool:
    if price is not None and _num(field_value(bean, "price")) != price:
        return False
    if qty is not None and _num(field_value(bean, "quantitySupplied")) != qty:
        return False
    return True


def watch_order(
    fetch: Callable[[], dict[str, Any]],
    clordid: str,
    *,
    timeout: float,
    interval: float = MIN_INTERVAL,
    expect_price: float | None = None,
    expect_qty: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> OrderWatchResult:
    """Consulta até a ordem ficar conclusiva (ou bater a edição esperada) ou o tempo acabar.

    Conclusivo: estado final (Filled, Canceled, Rejected, Expired, DoneForDay...). Com
    ``expect_price``/``expect_qty`` (depois de uma edição), conclusivo também é a ordem aberta já
    mostrando os valores novos.
    """
    timeout = min(max(timeout, 0.0), MAX_TIMEOUT)
    interval = max(interval, MIN_INTERVAL)
    started = clock()
    checks = 0
    bean: dict[str, Any] | None = None
    editing = expect_price is not None or expect_qty is not None
    while True:
        checks += 1
        bean = find_order(fetch() or {}, clordid)
        if bean is not None:
            state = str(field_value(bean, "state") or "")
            final = state not in OPEN_ORDER_STATES
            if final or (editing and _matches_edit(bean, expect_price, expect_qty)):
                return _result(bean, clordid, True, checks, clock() - started, editing)
        if clock() - started + interval > timeout:
            break
        sleep(interval)
    return _result(bean, clordid, False, checks, clock() - started, editing)


def _result(
    bean: dict[str, Any] | None,
    clordid: str,
    reached: bool,
    checks: int,
    elapsed: float,
    editing: bool,
) -> OrderWatchResult:
    if bean is None:
        return OrderWatchResult(
            clordid=clordid,
            found=False,
            reached=False,
            checks=checks,
            elapsed_seconds=round(elapsed, 1),
            note=(
                "Ordem não encontrada no dailyOrder desta conta/mercado. Confira o clordid, a "
                "conta e o mercado — ordem a mercado não tem clordid e não pode ser acompanhada "
                "por aqui."
            ),
        )
    state = str(field_value(bean, "state") or "") or None
    is_open = state in OPEN_ORDER_STATES if state else None
    if reached:
        note = (
            "Edição aplicada: a ordem já mostra os valores novos."
            if editing and is_open
            else f"Estado conclusivo: {state}."
        )
    else:
        note = (
            f"Tempo esgotado com a ordem ainda em {state}. Ela segue viva no book — isto não é "
            "falha. Consulte de novo mais tarde se o usuário pedir."
        )
        if editing:
            note += " A edição ainda não aparece aplicada (pode ter sido rejeitada)."
    return OrderWatchResult(
        clordid=clordid,
        found=True,
        reached=reached,
        state=state,
        is_open=is_open,
        quantity=_num(field_value(bean, "quantitySupplied")),
        quantity_executed=_num(field_value(bean, "quantityExecuted")),
        quantity_remaining=_num(field_value(bean, "quantityRemaining")),
        price=_num(field_value(bean, "price")),
        average_price=_num(field_value(bean, "priceAverage")),
        oms_text=(str(field_value(bean, "text")) if field_value(bean, "text") else None),
        checks=checks,
        elapsed_seconds=round(elapsed, 1),
        note=note,
    )
