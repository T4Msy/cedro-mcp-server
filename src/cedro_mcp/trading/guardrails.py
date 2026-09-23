"""Guardrails de envio de ordem: teto de valor por ordem e alerta de preço fora da banda.

Rodam no **preview**, antes de o token de confirmação existir — o usuário vê os alertas no mesmo
resumo que vai confirmar. Puro, sem I/O: o preço de referência (último negócio da Market Data) é
buscado pela tool e passado aqui.

- Teto (``CEDRO_TRADING_MAX_ORDER_VALUE``): **recusa** o preview. Valor = qty × preço da ordem
  (``price``, senão ``stop_limit``, senão ``target_limit``, senão o preço de referência). Não
  aplica multiplicador de contrato: em futuros BM&F o valor calculado fica acima do financeiro
  real — erra para o lado seguro.
- Banda (``CEDRO_TRADING_PRICE_BAND_PCT``): só **alerta**. Preço bem longe do mercado pode ser
  intencional (stop distante), mas também é o erro clássico de digitação (38,50 → 385,0).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import CedroError

#: Ordem dos campos usados como "preço da ordem" para calcular o valor.
_VALUE_PRICE_FIELDS = ("price", "stop_limit", "target_limit")


@dataclass(frozen=True)
class GuardrailReport:
    reference_price: float | None
    order_value: float | None
    warnings: list[str] = field(default_factory=list)


def check_order(
    *,
    qty: int,
    prices: dict[str, float | None],
    reference_price: float | None,
    max_order_value: float,
    price_band_pct: float,
) -> GuardrailReport:
    """Valida uma ordem contra os guardrails. Levanta ``CedroError`` se passar do teto."""
    warnings: list[str] = []

    if price_band_pct > 0:
        if reference_price:
            for name, value in prices.items():
                if value is None or value <= 0:
                    continue
                deviation = abs(value - reference_price) / reference_price * 100
                if deviation > price_band_pct:
                    warnings.append(
                        f"{name}={value} está {deviation:.1f}% longe do último negócio "
                        f"({reference_price}) — acima da banda de {price_band_pct:g}%. Confira "
                        "se não é erro de digitação antes de confirmar."
                    )
        else:
            warnings.append(
                "Sem preço de referência da Market Data — não foi possível conferir se o preço "
                "está perto do mercado."
            )

    order_price = next((prices[f] for f in _VALUE_PRICE_FIELDS if prices.get(f)), None)
    order_price = order_price or reference_price
    order_value = round(qty * order_price, 2) if order_price else None

    if max_order_value > 0:
        if order_value is None:
            raise CedroError(
                "Ordem recusada no preview: há teto de valor por ordem configurado "
                f"({max_order_value:,.2f}) e não foi possível calcular o valor desta (ordem sem "
                "preço e sem cotação de referência da Market Data). Informe um preço limite."
            )
        if order_value > max_order_value:
            raise CedroError(
                f"Ordem recusada no preview: valor estimado {order_value:,.2f} (qty × preço) "
                f"passa do teto por ordem de {max_order_value:,.2f} "
                "(CEDRO_TRADING_MAX_ORDER_VALUE). Divida a ordem ou peça ajuste do teto."
            )

    return GuardrailReport(
        reference_price=reference_price, order_value=order_value, warnings=warnings
    )
