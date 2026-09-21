"""Monta e valida os parâmetros de uma ordem por modo — puro, sem I/O, testável sem rede.

Uma função por tipo de comando (envio/cancelamento/edição), todas devolvendo um dict de query
params prontos para `TradingClient`. A validação de campo obrigatório por modo acontece **aqui**,
sempre antes de qualquer chamada HTTP — é o que garante que `trading_preview_order` nunca deixa
passar uma ordem Stop sem `stop_trigger`, por exemplo.
"""

from __future__ import annotations

import time
import uuid

from ..errors import CedroError
from .models import ENDPOINT_BY_MODE, MODES_WITHOUT_CLORDID, ORD_TYPE_BY_MODE, REQUIRED_FIELDS_BY_MODE


def new_clordid() -> str:
    """Chave de idempotência gerada pelo cliente — única por dia/sessão (regra 4 da skill)."""
    return f"mcp-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:10]}"


#: nome do campo do tool ↔ nome real do parâmetro na query string da API.
_FIELD_TO_PARAM = {
    "price": "price",
    "stop_trigger": "stoptrigger",
    "stop_limit": "stoplimit",
    "initial_change": "initialchange",
    "moving_start": "movingstart",
    "nlgs_stop_px": "nlgsstoppx",
    "nlgs_stop_gain_px": "nlgsstopgainpx",
    "fullfilled": "fullfilled",
    "target_limit": "targetlimit",
    "target_trigger": "targettrigger",
    "clordid_limit": "clordidlimit",
    "clordid_stop": "clordidstop",
    "clordlinkid": "clordlinkid",
}


def build_new_order(
    *,
    mode: str,
    market: str,
    symbol: str,
    side: str,
    qty: int,
    account: str,
    username: str,
    source_address: str,
    extra_fields: dict[str, float | str | bool | None],
    time_in_force: str | None = None,
    validity_order: str | None = None,
    order_tag: str | None = None,
    order_strategy: str | None = None,
    app_name: str | None = None,
) -> tuple[str, dict[str, str], str | None]:
    """Valida `extra_fields` contra o obrigatório do `mode` e monta os params da ordem.

    Devolve ``(endpoint, params, clordid)`` — ``clordid`` é ``None`` só para ``mode == "market"``
    (a API não aceita esse campo nesse tipo, ver regra 4 da skill).
    """
    if mode not in ENDPOINT_BY_MODE:
        raise CedroError(f"Modo de ordem desconhecido: {mode!r}. Use um de {sorted(ENDPOINT_BY_MODE)}.")

    required = REQUIRED_FIELDS_BY_MODE[mode]
    missing = [f for f in required if extra_fields.get(f) is None]
    if missing:
        raise CedroError(
            f"Ordem modo={mode!r} exige {list(required)} — faltando: {missing}. "
            "Ver ENDPOINTS.md da skill trading para o campo exato de cada tipo."
        )

    params: dict[str, str] = {
        "market": market,
        "quote": symbol,
        "qtd": str(qty),
        "side": side,
        "type": ORD_TYPE_BY_MODE[mode],
        "account": account,
        "username": username,
        "sourceaddress": source_address,
    }
    for field_name, value in extra_fields.items():
        if value is None:
            continue
        param_name = _FIELD_TO_PARAM.get(field_name, field_name)
        params[param_name] = str(value)

    if time_in_force:
        params["timeinforce"] = time_in_force
    if validity_order:
        params["validityorder"] = validity_order
    if order_tag:
        params["ordertag"] = order_tag
    if order_strategy:
        params["orderstrategy"] = order_strategy
    if app_name:
        params["appname"] = app_name

    clordid: str | None = None
    if mode not in MODES_WITHOUT_CLORDID:
        clordid = new_clordid()
        params["clordid"] = clordid

    return ENDPOINT_BY_MODE[mode], params, clordid


def build_cancel_order(
    *,
    market: str,
    symbol: str,
    side: str,
    remaining_qty: int,
    origclordid: str,
    username: str,
    source_address: str,
    cancel_reason: str | None = None,
) -> dict[str, str]:
    params = {
        "market": market,
        "origclordid": origclordid,
        "quote": symbol,
        "qtd": str(remaining_qty),
        "side": side,
        "username": username,
        "sourceaddress": source_address,
    }
    if cancel_reason:
        params["cancelreason"] = cancel_reason
    return params


def build_edit_order(
    *,
    market: str,
    symbol: str,
    side: str,
    order_type: str,
    origclordid: str,
    new_price: float,
    new_qty: int,
    account: str,
    username: str,
    source_address: str,
    stop_limit: float | None = None,
) -> dict[str, str]:
    """`stoplimit` é obrigatório em TODA edição (regra 10 da skill) — `0` se não for stop."""
    return {
        "market": market,
        "origclordid": origclordid,
        "price": str(new_price),
        "quote": symbol,
        "qtd": str(new_qty),
        "type": order_type,
        "side": side,
        "username": username,
        "sourceaddress": source_address,
        "account": account,
        "stoplimit": str(stop_limit if stop_limit is not None else 0),
    }
