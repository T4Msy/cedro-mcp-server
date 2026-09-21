"""TradingClient: as 3 camadas de auth, e a disambiguação de 401 (sessão vs. permissão de ordem)."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
import respx

from cedro_mcp.config import Settings
from cedro_mcp.credentials import ServiceAccountCredentialProvider
from cedro_mcp.errors import CedroAuthError, CedroHTTPError
from cedro_mcp.trading.client import TradingClient

from ._principal import as_principal
from .conftest import BASE_URL

_SIGNIN_OK = httpx.Response(200, text="true", headers={"Set-Cookie": "JSESSIONID=abc123; Path=/"})
_BROKER_LOGIN_OK = httpx.Response(
    200, json={"isAuthenticated": "Y", "username": "10034", "code": "0", "message": "ok"}
)


def _trading_settings(settings: Settings) -> Settings:
    return replace(settings, trading_user="10034", trading_password="senha-oms")


@respx.mock
def test_send_order_full_handshake(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    respx.post(f"{BASE_URL}/services/negotiation/sendNewOrderSingleLimit").mock(
        return_value=httpx.Response(200, json={"code": "1", "message": "ok", "type": "ack"})
    )
    client = TradingClient(_trading_settings(settings), ServiceAccountCredentialProvider(_trading_settings(settings)))
    with as_principal("trading:trade"):
        response = client.send_order(
            "sendNewOrderSingleLimit",
            {"market": "XBSP", "quote": "PETR4", "qtd": "100", "price": "38.5"},
        )
    assert response.accepted
    assert response.code == "1"
    client.close()


@respx.mock
def test_broker_login_sends_both_header_and_username_query(settings: Settings) -> None:
    """code 3 do brokerServiceLogin é quase sempre esse detalhe faltando — trava de regressão."""
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    route = respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    respx.get(f"{BASE_URL}/services/negotiation/dailyOrder/10034/XBSP").mock(
        return_value=httpx.Response(200, json={"code": "0", "listBeans": []})
    )
    client = TradingClient(_trading_settings(settings), ServiceAccountCredentialProvider(_trading_settings(settings)))
    with as_principal("trading:trade"):
        client.daily_orders("/services/negotiation/dailyOrder/10034/XBSP")
    request = route.calls[0].request
    assert request.url.params["username"] == "10034"
    assert "user-identifier" in request.headers
    client.close()


@respx.mock
def test_broker_login_code_3_raises_with_hint(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=httpx.Response(
            200, json={"isAuthenticated": "N", "code": "3", "message": "O usuário deve ser informado."}
        )
    )
    client = TradingClient(_trading_settings(settings), ServiceAccountCredentialProvider(_trading_settings(settings)))
    with as_principal("trading:trade"), pytest.raises(CedroAuthError, match="code 3"):
        client.daily_orders("/services/negotiation/dailyOrder/10034/XBSP")
    client.close()


@respx.mock
def test_broker_login_401_includes_body_and_provisioning_hint(settings: Settings) -> None:
    """Achado real (21/09): brokerServiceLogin pode devolver 401 puro (não o padrão code 3/
    code 24 documentado) — SignIn já funcionou nesse ponto, então a mensagem precisa dizer isso
    e mostrar o corpo da resposta, em vez de só "HTTP 401" sem contexto."""
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=httpx.Response(401, text='{"error":"não autorizado"}')
    )
    client = TradingClient(_trading_settings(settings), ServiceAccountCredentialProvider(_trading_settings(settings)))
    with as_principal("trading:trade"), pytest.raises(CedroAuthError, match="não autorizado"):
        client.daily_orders("/services/negotiation/dailyOrder/10034/XBSP")
    client.close()


@respx.mock
def test_401_on_order_send_hints_at_account_permission_not_session(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    respx.post(f"{BASE_URL}/services/negotiation/sendNewOrderSingleLimit").mock(
        return_value=httpx.Response(401, text="<html>not authorized</html>")
    )
    client = TradingClient(_trading_settings(settings), ServiceAccountCredentialProvider(_trading_settings(settings)))
    with as_principal("trading:trade"), pytest.raises(CedroAuthError, match="code 24"):
        client.send_order("sendNewOrderSingleLimit", {"market": "XBSP"})
    client.close()


@respx.mock
def test_401_on_query_retries_once_then_raises_generic_session_message(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    order_route = respx.get(f"{BASE_URL}/services/negotiation/dailyOrder/10034/XBSP").mock(
        return_value=httpx.Response(401)
    )
    client = TradingClient(_trading_settings(settings), ServiceAccountCredentialProvider(_trading_settings(settings)))
    with as_principal("trading:trade"), pytest.raises(CedroAuthError, match="expirada"):
        client.daily_orders("/services/negotiation/dailyOrder/10034/XBSP")
    # SignIn+brokerServiceLogin rodam de novo no retry (reset() força reautenticação).
    assert order_route.call_count == 2
    client.close()


@respx.mock
def test_edit_order_marks_response_as_not_confirmed_by_caller(settings: Settings) -> None:
    """O client em si só expõe o envelope bruto — quem marca `confirmed: False` é a tool
    (trading_orders.py); este teste garante que o client não esconde nem reinterpreta code:1."""
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    respx.post(f"{BASE_URL}/services/negotiation/editOrder").mock(
        return_value=httpx.Response(200, json={"code": "1", "message": "Edição realizada"})
    )
    client = TradingClient(_trading_settings(settings), ServiceAccountCredentialProvider(_trading_settings(settings)))
    with as_principal("trading:trade"):
        response = client.edit_order({"origclordid": "mcp-1", "price": "39.0"})
    assert response.accepted
    client.close()


@respx.mock
def test_gateway_html_error_is_not_parsed_as_json(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    respx.get(f"{BASE_URL}/services/negotiation/dailyOrder/10034/XBSP").mock(
        return_value=httpx.Response(200, text="<html>gateway error</html>")
    )
    client = TradingClient(_trading_settings(settings), ServiceAccountCredentialProvider(_trading_settings(settings)))
    with as_principal("trading:trade"), pytest.raises(CedroHTTPError, match="não-JSON"):
        client.daily_orders("/services/negotiation/dailyOrder/10034/XBSP")
    client.close()
