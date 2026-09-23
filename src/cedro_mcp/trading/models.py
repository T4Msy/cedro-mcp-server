"""Modelos e catálogo de tipos de ordem — Trading REST.

Enums em string descritiva (API REST v1) — nunca os códigos numéricos do protocolo FIX 4.4, que é
uma API totalmente diferente (ver ENUMS.md da skill).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

Market = Literal["XBSP", "XBMF"]
#: Mercados aceitos só em cancelOrder/editOrder, além dos de negociação.
CancelEditMarket = Literal["XBSP", "XBMF", "REFI", "FUND", "TEDI"]
Side = Literal["BUY", "SELL"]
TimeInForce = Literal["DAY", "GTC", "OPG", "IOC", "FOK", "GTD", "ATC", "GFA"]

#: As 8 variantes de envio — nome curto usado nas tools deste servidor, não o nome do endpoint.
OrderMode = Literal[
    "limit", "market", "start", "stop", "stop_conditional", "stop_moving", "stop_oco",
    "stop_simult",
]

#: modo → endpoint (`POST /services/negotiation/{endpoint}`).
ENDPOINT_BY_MODE: dict[str, str] = {
    "limit": "sendNewOrderSingleLimit",
    "market": "sendNewOrderSingleMarket",
    "start": "sendNewOrderSingleStart",
    "stop": "sendNewOrderSingleStop",
    "stop_conditional": "sendNewOrderSingleStopConditional",
    "stop_moving": "sendNewOrderSingleStopMoving",
    "stop_oco": "sendNewOrderSingleStopOCO",
    "stop_simult": "sendNewOrderSingleStopSimult",
}

#: modo → valor do parâmetro `type` (OrdType) — "Stop" cobre 5 dos 8 modos, ver ENUMS.md.
ORD_TYPE_BY_MODE: dict[str, str] = {
    "limit": "Limited",
    "market": "Market",
    "start": "Start",
    "stop": "Stop",
    "stop_conditional": "Stop",
    "stop_moving": "Stop",
    "stop_oco": "Stop",
    "stop_simult": "Stop",
}

#: modo → campos extras OBRIGATÓRIOS (além de market/quote/qtd/side/type/account/username/
#: sourceaddress, comuns a todos) — ver ENDPOINTS.md "Parâmetros específicos por tipo".
REQUIRED_FIELDS_BY_MODE: dict[str, tuple[str, ...]] = {
    "limit": ("price",),
    "market": (),
    "start": ("stop_trigger", "stop_limit"),
    "stop": ("stop_trigger", "stop_limit"),
    "stop_moving": ("stop_trigger", "stop_limit", "initial_change", "moving_start"),
    "stop_conditional": ("price", "nlgs_stop_px", "nlgs_stop_gain_px"),
    "stop_oco": ("price", "stop_limit", "stop_trigger"),
    "stop_simult": ("stop_limit", "stop_trigger", "target_limit", "target_trigger"),
}

#: Só o Mercado não aceita clordid pela spec (regra 4 da skill) — cuidado redobrado com reenvio.
MODES_WITHOUT_CLORDID = frozenset({"market"})

#: Status de ordem do dailyOrder/historyOrder (campo `state`) — ver ENUMS.md da skill.
ORDER_STATUSES: dict[str, str] = {
    "New": "Nova (recebida)",
    "PartiallyFilled": "Parcialmente executada",
    "Filled": "Completamente executada",
    "DoneForDay": "Encerrada para o dia",
    "Canceled": "Cancelada",
    "Replaced": "Editada/substituída",
    "PendingCancel": "Cancelamento pendente",
    "Rejected": "Rejeitada",
    "Suspend": "Suspensa",
    "PendingNew": "Pendente de confirmação",
    "Expired": "Expirada",
    "Received": "Recebida pelo sistema",
    "PendingReplace": "Edição pendente",
}

#: Status em que a ordem ainda pode executar (inclusive PendingCancel: até o cancelamento ser
#: confirmado, ela segue no book).
OPEN_ORDER_STATES = frozenset(
    {"New", "PartiallyFilled", "Replaced", "PendingCancel", "Suspend", "PendingNew", "Received",
     "PendingReplace"}
)

TIME_IN_FORCE_DESCRIPTIONS: dict[str, str] = {
    "DAY": "Válida no dia (default)",
    "GTC": "Válida até cancelar",
    "OPG": "Na abertura",
    "IOC": "Executa o possível na hora e cancela o resto",
    "FOK": "Executa tudo na hora ou cancela tudo",
    "GTD": "Válida até a data (validity_order)",
    "ATC": "No fechamento",
    "GFA": "Válida para o leilão",
}


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class OrderResponse(_Base):
    """Envelope de toda resposta de comando (envio/edição/cancelamento).

    ``code`` normalizado pra string: a doc diz `integer`, mas na prática chega como string em
    alguns retornos — normalizar aqui evita comparação frágil no resto do código.
    """

    code: str | None = None
    message: str | None = None
    messageDetails: str | None = None
    type: str | None = None

    @property
    def accepted(self) -> bool:
        """``code`` de sucesso costuma ser ``"1"`` ou ``"0"`` — qualquer outro é rejeição.

        A doc não publica a tabela completa de codes (ver ERROS.md) — trata **qualquer** code
        fora desse conjunto pequeno e confirmado como rejeição, nunca infere sucesso por
        ausência de erro.
        """
        return self.code in ("0", "1")


class DailyOrder(_Base):
    """Uma ordem do dia (`dailyOrder`/`historyOrder` → `listBeans[]`).

    A API devolve cada campo como ``{code, value}`` (ver CAMPOS-DA-ORDEM.md) — mantemos o item
    bruto (`extra="allow"`) em vez de mapear os ~60 campos; as tools extraem os poucos campos
    úteis (clOrdID, status, qtd, price) explicitamente.
    """

    model_config = ConfigDict(extra="allow")


@dataclass(frozen=True)
class OrderRequest:
    """Uma chamada de negociação pronta para executar — construída e validada por
    ``build_order_request``/``build_cancel_request``/``build_edit_request``, nunca montada à mão
    pelas tools (garante que a validação por modo sempre roda antes de qualquer HTTP real)."""

    endpoint: str
    params: dict[str, str]
    clordid: str | None
