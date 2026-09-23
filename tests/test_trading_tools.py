"""Tools de Trading fim a fim: preview→confirm, gate de escopo, e a tool de leitura."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
import respx

from cedro_mcp.client import CedroClient
from cedro_mcp.config import Settings
from cedro_mcp.credentials import ServiceAccountCredentialProvider
from cedro_mcp.errors import CedroEntitlementError, CedroError
from cedro_mcp.server import build_server

from ._principal import as_principal
from ._tools import tool_functions
from .conftest import BASE_URL

_SIGNIN_OK = httpx.Response(200, text="true", headers={"Set-Cookie": "JSESSIONID=abc123; Path=/"})
_BROKER_LOGIN_OK = httpx.Response(200, json={"isAuthenticated": "Y", "code": "0"})


def _trading_settings(settings: Settings) -> Settings:
    return replace(settings, trading_user="10034", trading_password="senha-oms")


def _tool_fns(settings: Settings, client: CedroClient) -> dict:
    mcp = build_server(settings=settings, client=client)
    return tool_functions(mcp._tool_manager.list_tools())  # noqa: SLF001


@respx.mock
def test_preview_then_confirm_sends_the_exact_previewed_order(
    settings: Settings, client: CedroClient
) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    send_route = respx.post(f"{BASE_URL}/services/negotiation/sendNewOrderSingleLimit").mock(
        return_value=httpx.Response(200, json={"code": "1", "message": "ok"})
    )
    fns = _tool_fns(_trading_settings(settings), client)

    preview = fns["trading_preview_order"](
        mode="limit", market="XBSP", symbol="PETR4", side="BUY", qty=100,
        account="10034", price=38.5,
    )
    assert "confirmation_token" in preview
    assert send_route.call_count == 0  # preview NUNCA chama a API

    result = fns["trading_confirm"](preview["confirmation_token"])
    assert result["accepted"] is True
    assert send_route.call_count == 1
    request = send_route.calls[0].request
    assert request.url.params["price"] == "38.5"
    assert request.url.params["quote"] == "PETR4"


@respx.mock
def test_confirm_token_is_single_use(settings: Settings, client: CedroClient) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    respx.post(f"{BASE_URL}/services/negotiation/sendNewOrderSingleMarket").mock(
        return_value=httpx.Response(200, json={"code": "1"})
    )
    fns = _tool_fns(_trading_settings(settings), client)
    preview = fns["trading_preview_order"](
        mode="market", market="XBSP", symbol="PETR4", side="BUY", qty=100, account="10034"
    )
    fns["trading_confirm"](preview["confirmation_token"])
    with pytest.raises(Exception, match="inválido"):
        fns["trading_confirm"](preview["confirmation_token"])


def test_preview_order_rejects_incomplete_stop_order(
    settings: Settings, client: CedroClient
) -> None:
    fns = _tool_fns(_trading_settings(settings), client)
    with pytest.raises(Exception, match="stop_trigger"):
        fns["trading_preview_order"](
            mode="stop", market="XBSP", symbol="PETR4", side="BUY", qty=100, account="10034"
        )


def test_preview_order_without_trading_credentials_gives_clear_error(
    settings: Settings, client: CedroClient
) -> None:
    """Sem CEDRO_TRADING_USER/PASS (ou sem seção de Trading no login), a tool nunca tenta
    montar a ordem contra credencial vazia — falha alto e cedo, antes de qualquer HTTP."""
    fns = _tool_fns(settings, client)  # settings SEM trading_user/password
    with pytest.raises(Exception, match="Trading"):
        fns["trading_preview_order"](
            mode="market", market="XBSP", symbol="PETR4", side="BUY", qty=100, account="10034"
        )


@respx.mock
def test_edit_order_confirm_flags_as_not_confirmed(settings: Settings, client: CedroClient) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    respx.post(f"{BASE_URL}/services/negotiation/editOrder").mock(
        return_value=httpx.Response(200, json={"code": "1", "message": "Edição realizada"})
    )
    fns = _tool_fns(_trading_settings(settings), client)
    preview = fns["trading_preview_edit_order"](
        market="XBSP", symbol="PETR4", side="BUY", order_type="Limited",
        origclordid="mcp-1", new_price=39.0, new_qty=100, account="10034",
    )
    result = fns["trading_confirm"](preview["confirmation_token"])
    assert result["confirmed"] is False
    assert "assíncron" in result["note"]


def test_write_tools_require_trading_trade_scope(settings: Settings, client: CedroClient) -> None:
    fns = _tool_fns(_trading_settings(settings), client)
    with as_principal("marketdata:read"):  # sem trading:trade
        with pytest.raises(CedroEntitlementError, match="trading:trade"):
            fns["trading_preview_order"](
                mode="market", market="XBSP", symbol="PETR4", side="BUY", qty=100,
                account="10034",
            )


@respx.mock
def test_confirm_from_another_principal_is_rejected_and_audited(
    settings: Settings,
    client: CedroClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Token de confirmação vazado não executa a ordem com a sessão de outro chamador."""
    # Service account tem uma chave só; aqui cada subject vira uma sessão, como no web login.
    monkeypatch.setattr(
        ServiceAccountCredentialProvider,
        "session_key",
        lambda self, principal: principal.subject if principal else "anon",
    )
    send_route = respx.post(f"{BASE_URL}/services/negotiation/sendNewOrderSingleMarket").mock(
        return_value=httpx.Response(200, json={"code": "1"})
    )
    fns = _tool_fns(_trading_settings(settings), client)
    with as_principal("marketdata:read", "trading:trade", subject="dono"):
        preview = fns["trading_preview_order"](
            mode="market", market="XBSP", symbol="PETR4", side="BUY", qty=100, account="10034"
        )
    caplog.set_level("INFO", logger="cedro_mcp.audit")
    with as_principal("marketdata:read", "trading:trade", subject="intruso"):
        with pytest.raises(CedroError, match="outra sessão"):
            fns["trading_confirm"](preview["confirmation_token"])
    assert send_route.call_count == 0
    assert "trading_confirm_rejected" in caplog.text
    assert preview["confirmation_token"] not in caplog.text


@respx.mock
def test_preview_and_confirm_are_audited_without_leaking_the_token(
    settings: Settings, client: CedroClient, caplog: pytest.LogCaptureFixture
) -> None:
    respx.post(f"{BASE_URL}/SignIn").mock(return_value=_SIGNIN_OK)
    respx.get(f"{BASE_URL}/services/negotiation/brokerServiceLogin").mock(
        return_value=_BROKER_LOGIN_OK
    )
    respx.post(f"{BASE_URL}/services/negotiation/sendNewOrderSingleMarket").mock(
        return_value=httpx.Response(200, json={"code": "1", "message": "ok"})
    )
    caplog.set_level("INFO", logger="cedro_mcp.audit")
    fns = _tool_fns(_trading_settings(settings), client)
    preview = fns["trading_preview_order"](
        mode="market", market="XBSP", symbol="PETR4", side="BUY", qty=100, account="10034"
    )
    fns["trading_confirm"](preview["confirmation_token"])
    events = [r.getMessage().split()[0] for r in caplog.records]
    assert events == [
        "event=trading_preview",
        "event=trading_confirm",
        "event=trading_confirm_result",
    ]
    assert "PETR4" in caplog.text
    assert preview["confirmation_token"] not in caplog.text
