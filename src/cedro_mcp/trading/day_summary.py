"""Resumo do dia por ativo, calculado a partir das ordens do ``dailyOrder`` — puro, sem I/O.

A API de Trading **não expõe posição, custódia nem saldo** (é outro produto, Backoffice/Risk —
ver ENDPOINTS.md da skill trading). O que dá para responder com segurança é "o que foi executado
hoje por este usuário neste mercado": quantidade comprada/vendida, preço médio de cada lado e o
saldo líquido do dia. Não inclui posição de dias anteriores.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from .models import OPEN_ORDER_STATES


class SymbolDaySummary(BaseModel):
    symbol: str
    bought_qty: float = 0
    sold_qty: float = 0
    #: bought_qty − sold_qty. Positivo = comprou mais do que vendeu HOJE (não é posição total).
    net_qty: float = 0
    avg_buy_price: float | None = None
    avg_sell_price: float | None = None
    bought_value: float = 0
    sold_value: float = 0
    open_orders: int = 0


class DaySummary(BaseModel):
    account: str
    market: str
    symbols: list[SymbolDaySummary] = Field(default_factory=list)
    #: Contagem de ordens por estado (New, Filled, Canceled, Rejected, ...).
    orders_by_state: dict[str, int] = Field(default_factory=dict)
    total_orders: int = 0
    note: str = (
        "Calculado só das ordens de HOJE neste mercado — não é custódia nem posição consolidada "
        "(a API de Trading não expõe esses dados)."
    )


def field_value(bean: dict[str, Any], name: str) -> Any:
    """Lê um campo do item de ordem — aceita ``{code, value}`` e o formato achatado."""
    raw = bean.get(name)
    if isinstance(raw, dict):
        return raw.get("value")
    return raw


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return 0.0


def summarize_day(payload: dict[str, Any], *, account: str, market: str) -> DaySummary:
    beans = payload.get("listBeans") or []
    states: Counter[str] = Counter()
    per_symbol: dict[str, dict[str, float]] = {}

    for bean in beans:
        if not isinstance(bean, dict):
            continue
        state = str(field_value(bean, "state") or "Unknown")
        states[state] += 1
        symbol = str(field_value(bean, "quote") or "?")
        acc = per_symbol.setdefault(
            symbol, {"bq": 0.0, "sq": 0.0, "bv": 0.0, "sv": 0.0, "open": 0.0}
        )
        if state in OPEN_ORDER_STATES:
            acc["open"] += 1
        executed = _number(field_value(bean, "quantityExecuted"))
        if executed <= 0:
            continue
        price = _number(field_value(bean, "priceAverage")) or _number(field_value(bean, "price"))
        side = str(field_value(bean, "side") or "").upper()
        if side == "BUY":
            acc["bq"] += executed
            acc["bv"] += executed * price
        elif side == "SELL":
            acc["sq"] += executed
            acc["sv"] += executed * price

    symbols = [
        SymbolDaySummary(
            symbol=symbol,
            bought_qty=acc["bq"],
            sold_qty=acc["sq"],
            net_qty=acc["bq"] - acc["sq"],
            avg_buy_price=round(acc["bv"] / acc["bq"], 4) if acc["bq"] else None,
            avg_sell_price=round(acc["sv"] / acc["sq"], 4) if acc["sq"] else None,
            bought_value=round(acc["bv"], 2),
            sold_value=round(acc["sv"], 2),
            open_orders=int(acc["open"]),
        )
        for symbol, acc in sorted(per_symbol.items())
    ]
    return DaySummary(
        account=account,
        market=market,
        symbols=symbols,
        orders_by_state=dict(states),
        total_orders=sum(states.values()),
    )
