"""API da Cedro simulada para os evals — respostas plausíveis e determinísticas.

Intercepta só o tráfego ``httpx`` (os clientes do servidor). O SDK da Anthropic 1.x usa
``httpx2`` e passa direto para a API real.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

import httpx
import respx

BASE = "https://webfeeder.cedrotech.com"

#: Último negócio por ativo. PETR4 = 38,50 é o número que os cenários conferem na resposta.
LAST_TRADE = {"PETR4": 38.50, "VALE3": 61.20, "ITUB4": 33.10, "BBAS3": 27.80}


def _quote(request: httpx.Request) -> httpx.Response:
    symbols = request.url.path.rsplit("/", 1)[-1].split(",")
    return httpx.Response(200, json=[
        {"symbol": s.upper(), "lastTrade": LAST_TRADE.get(s.upper(), 20.0),
         "previous": round(LAST_TRADE.get(s.upper(), 20.0) * 0.99, 2), "change": 1.01,
         "bid": LAST_TRADE.get(s.upper(), 20.0) - 0.01, "ask": LAST_TRADE.get(s.upper(), 20.0),
         "volumeFinancier": 1.2e9}
        for s in symbols
    ])


def _candles(request: httpx.Request) -> httpx.Response:
    _, symbol, _period, count = request.url.path.rsplit("/", 3)
    last = LAST_TRADE.get(symbol.upper(), 20.0)
    n = int(count)
    base = datetime(2026, 9, 22)
    rows = []
    for i in range(n):
        # Tendência de alta suave terminando no último negócio.
        price = round(last * (0.80 + 0.20 * (i + 1) / n), 2)
        rows.append({
            "symbol": symbol.upper(), "price": price, "open": price, "high": price * 1.01,
            "low": price * 0.99, "volumeFinancier": 1e9,
            "timeTrade": int((base - timedelta(days=n - 1 - i)).strftime("%Y%m%d%H%M")),
        })
    return httpx.Response(200, json=list(reversed(rows)))


class CedroMock:
    """Guarda as ordens recebidas para o dailyOrder refletir o que o modelo enviou."""

    def __init__(self) -> None:
        self.orders: list[dict[str, str]] = []

    def _send(self, request: httpx.Request) -> httpx.Response:
        self.orders.append(dict(request.url.params))
        return httpx.Response(200, json={"code": "1", "message": "Ordem recebida pelo OMS"})

    def _daily(self, _request: httpx.Request) -> httpx.Response:
        beans = []
        for order in self.orders:
            fields = {
                "clOrdID": order.get("clordid", ""), "quote": order.get("quote", ""),
                "side": order.get("side", ""), "state": "Filled",
                "quantitySupplied": order.get("qtd", "0"),
                "quantityExecuted": order.get("qtd", "0"), "quantityRemaining": "0",
                "price": order.get("price", ""), "priceAverage": order.get("price", ""),
            }
            beans.append({k: {"code": "x", "value": v} for k, v in fields.items()})
        return httpx.Response(200, json={"code": "0", "listBeans": beans})

    @contextmanager
    def active(self) -> Iterator[respx.MockRouter]:
        with respx.mock(assert_all_called=False) as router:
            router.post(f"{BASE}/SignIn").respond(
                200, text="true", headers={"Set-Cookie": "JSESSIONID=eval; Path=/"}
            )
            router.get(f"{BASE}/services/negotiation/brokerServiceLogin").respond(
                200, json={"isAuthenticated": "Y", "code": "0"}
            )
            router.post(f"{BASE}/connect/token").respond(
                200, json={"access_token": "news", "expires_in": 3600}
            )
            router.get(url__regex=rf"{BASE}/services/quotes/quote/.+").mock(side_effect=_quote)
            router.get(url__regex=rf"{BASE}/services/quotes/candleLast/.+").mock(
                side_effect=_candles
            )
            router.get(url__regex=rf"{BASE}/services/quotes/quoteInformation.*").respond(
                200, json=[{"companyName": "PETROLEO BRASILEIRO S.A.", "segmentName": "Petróleo"}]
            )
            router.get(url__regex=rf"{BASE}/services/quotes/book/.+").respond(
                200, json={"symbol": "PETR4", "compra": [{"preco": 38.49, "quantidade": 5000}],
                           "venda": [{"preco": 38.50, "quantidade": 3000}]}
            )
            router.post(url__regex=rf"{BASE}/services/negotiation/sendNewOrderSingle\w*").mock(
                side_effect=self._send
            )
            router.post(url__regex=rf"{BASE}/services/negotiation/(cancelOrder|editOrder)").respond(
                200, json={"code": "1", "message": "Pedido recebido"}
            )
            router.get(url__regex=rf"{BASE}/services/negotiation/dailyOrder/.+").mock(
                side_effect=self._daily
            )
            router.get(url__regex=re.escape(BASE) + r"/.*news.*").respond(200, json=[])
            # Qualquer outra rota: 404 (vira erro de tool, não quebra o harness).
            router.route(url__startswith=BASE).respond(404)
            yield router
