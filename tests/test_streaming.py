"""Fase 2: Socket Crystal TCP, cache por conta e tools de streaming."""

from __future__ import annotations

import queue
from dataclasses import replace
import pytest

from cedro_mcp.config import Settings
from cedro_mcp.credentials import RestCredentials, SocketCredentials, TradingCredentials
from cedro_mcp.errors import CedroAuthError
from cedro_mcp.streaming import MarketDataStreamClient


class _Provider:
    def __init__(self, socket: SocketCredentials) -> None:
        self._socket = socket

    def rest_credentials_for(self, principal: object) -> RestCredentials:
        raise AssertionError("REST não deve ser usado por uma tool stream_*")

    def socket_credentials_for(self, principal: object) -> SocketCredentials:
        return self._socket

    def trading_credentials_for(self, principal: object) -> TradingCredentials:
        raise AssertionError("Trading não deve ser usado por uma tool stream_*")

    def session_key(self, principal: object) -> str:
        return "test"


class _FakeSocket:
    def __init__(self, rejected: bool = False) -> None:
        self.sent: list[str] = []
        self._messages: queue.Queue[bytes | None] = queue.Queue()
        self.timeout: float | None = 5.0
        if rejected:
            self._messages.put(b"Connecting...Username:Password:Invalid Login")
        else:
            self._messages.put(b"Connecting...Username:Password:You are connected")

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = timeout

    def sendall(self, payload: bytes) -> None:
        command = payload.decode("utf-8").rstrip("\r\n")
        self.sent.append(command)
        if command.startswith("SQT "):
            symbol = command.split()[1].upper()
            self._messages.put(f"T:{symbol}:101758:2:13.32:3:13.31:4:13.33!\n".encode())
        elif command.startswith("SAB "):
            symbol = command.split()[1].upper()
            self._messages.put(
                (
                    f"Z:{symbol}:A:0:A:13.31:100:2:101758\n"
                    f"Z:{symbol}:A:0:V:13.33:200:3:101758\n"
                    f"Z:{symbol}:E\n"
                ).encode()
            )
        elif command.startswith("GQT "):
            symbol = command.split()[1].upper()
            self._messages.put(
                f"V:{symbol}:A:101758:13.32:1:2:10:99:0:1:0\n".encode()
            )

    def recv(self, size: int) -> bytes | None:
        return self._messages.get()

    def close(self) -> None:
        self._messages.put(None)


class _Factory:
    def __init__(self, rejected: bool = False) -> None:
        self.calls = 0
        self.socket = _FakeSocket(rejected=rejected)

    def __call__(self, host: str, port: int, *, timeout: float) -> _FakeSocket:
        self.calls += 1
        assert host == "crystal.test"
        assert port == 81
        assert timeout == 5.0
        return self.socket


@pytest.fixture
def stream_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        crystal_host="crystal.test",
        crystal_port=81,
        stream_snapshot_timeout=1.0,
        stream_tape_limit=10,
    )


def test_reuses_one_connection_and_parses_crystal_stream(stream_settings: Settings) -> None:
    factory = _Factory()
    client = MarketDataStreamClient(
        stream_settings,
        _Provider(SocketCredentials("socket-user", "socket-pass")),  # type: ignore[arg-type]
        socket_factory=factory,
    )
    try:
        quote = client.get_quote("petr4")
        assert quote["values"]["2"] == "13.32"

        book = client.get_book("PETR4")
        assert book["bids"][0]["price"] == "13.31"
        assert book["asks"][0]["price"] == "13.33"

        tape = client.get_tape("PETR4", 1)
        assert tape["trades"][0]["price"] == "13.32"
        assert factory.calls == 1
        assert factory.socket.sent[:4] == ["", "socket-user", "socket-pass", "MDC 1"]
        assert "SQT PETR4" in factory.socket.sent
        assert "SAB PETR4" in factory.socket.sent
        assert "GQT PETR4 S 1" in factory.socket.sent

        status = client.status()
        assert status["connected"] is True
        assert status["host"] == "crystal.test"
        assert status["subscriptions"] == {"PETR4": ["aggregatedBook", "quote", "quoteTrade"]}

        unsubscribed = client.unsubscribe("PETR4")
        assert unsubscribed["unsubscribed"] == ["aggregatedBook", "quote", "quoteTrade"]
        assert {item for item in factory.socket.sent if item.endswith("PETR4")} >= {
            "USQ PETR4",
            "UAB PETR4",
            "UQT PETR4",
        }
    finally:
        client.close()


def test_status_does_not_open_a_socket_just_to_report_idle_state(stream_settings: Settings) -> None:
    factory = _Factory()
    client = MarketDataStreamClient(
        stream_settings,
        _Provider(SocketCredentials("socket-user", "socket-pass")),  # type: ignore[arg-type]
        socket_factory=factory,
    )
    try:
        assert client.status()["connected"] is False
        assert factory.calls == 0
    finally:
        client.close()


def test_missing_socket_credential_fails_before_any_connection(stream_settings: Settings) -> None:
    factory = _Factory()
    client = MarketDataStreamClient(
        stream_settings,
        _Provider(SocketCredentials(None, None)),  # type: ignore[arg-type]
        socket_factory=factory,
    )
    try:
        with pytest.raises(CedroAuthError, match="Socket Crystal ausente"):
            client.get_quote("PETR4")
        assert factory.calls == 0
    finally:
        client.close()


def test_invalid_login_is_not_retried_automatically(stream_settings: Settings) -> None:
    factory = _Factory(rejected=True)
    client = MarketDataStreamClient(
        stream_settings,
        _Provider(SocketCredentials("socket-user", "wrong-pass")),  # type: ignore[arg-type]
        socket_factory=factory,
    )
    try:
        with pytest.raises(CedroAuthError, match="Invalid Login"):
            client.get_quote("PETR4")
        with pytest.raises(CedroAuthError, match="Invalid Login"):
            client.get_quote("PETR4")
        assert factory.calls == 1
    finally:
        client.close()
