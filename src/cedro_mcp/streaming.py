"""Cliente do Socket Crystal da Cedro (Telnet/TCP) para a Fase 2.

O Crystal não é WebSocket nem uma API request/response: é uma conexão TCP
persistente na porta 81. O MCP mantém uma única conexão por credencial, drena
o stream em uma thread e faz o parsing em outra, expondo snapshots locais para
as tools síncronas.
"""

from __future__ import annotations

import hashlib
import queue
import socket as socket_module
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from .config import Settings
from .credentials import CredentialProvider, SocketCredentials
from .errors import CedroAuthError, CedroError, CedroStreamError

_QUOTE = "quote"
_BOOK = "aggregatedBook"
_TAPE = "quoteTrade"
_HANDSHAKE_WAIT_SECONDS = 10.0
_RECONNECT_DELAY_SECONDS = 3.0


class CrystalTransport(Protocol):
    """Superfície mínima de um socket TCP, também usada pelos testes."""

    def sendall(self, payload: bytes) -> Any: ...

    def recv(self, size: int) -> bytes | bytearray | None: ...

    def close(self) -> Any: ...


CrystalSocketFactory = Callable[..., CrystalTransport]


def _credential_key(credentials: SocketCredentials) -> str:
    """Identificador opaco estável; senha e software key jamais viram chave/log."""
    if not credentials.is_complete:
        raise CedroAuthError(
            "Credencial de Market Data Socket Crystal ausente — refaça o login e preencha a "
            "seção Socket Crystal, ou configure CEDRO_CRYSTAL_USER/CEDRO_CRYSTAL_PASSWORD."
        )
    raw = (
        f"{credentials.user}\0{credentials.password}\0{credentials.software_key or ''}"
    ).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass
class _StreamCache:
    quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    books: dict[str, dict[str, Any]] = field(default_factory=dict)
    tapes: dict[str, deque[dict[str, Any]]] = field(default_factory=dict)
    book_ready: set[str] = field(default_factory=set)
    subscriptions: dict[str, set[str]] = field(default_factory=dict)
    connected_at: float | None = None
    last_message_at: float | None = None
    last_error: str | None = None
    host: str | None = None


def _hosts(raw: str | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (raw or "").split(",") if item.strip())


def _as_text(value: str) -> str:
    return value[:-1] if value.endswith("!") else value


class _CrystalConnection:
    """Uma sessão Crystal autenticada e o cache alimentado pelo stream."""

    def __init__(
        self,
        settings: Settings,
        credentials: SocketCredentials,
        socket_factory: CrystalSocketFactory,
    ) -> None:
        hosts = _hosts(settings.crystal_host)
        if not hosts:
            raise CedroStreamError(
                "CEDRO_CRYSTAL_HOST não está configurado. Use "
                "crystalhomologacao.cedrotech.com (homologação) ou "
                "datafeed1.cedrotech.com,datafeed2.cedrotech.com (produção)."
            )
        self._settings = settings
        self._hosts = hosts
        self._host_index = 0
        self._credentials = credentials
        self._socket_factory = socket_factory
        self._cache = _StreamCache()
        self._condition = threading.Condition(threading.RLock())
        self._send_lock = threading.Lock()
        self._socket: CrystalTransport | None = None
        self._reader: threading.Thread | None = None
        self._processor: threading.Thread | None = None
        self._reconnector: threading.Thread | None = None
        self._line_queue: queue.Queue[str | None] | None = None
        self._forced_host: str | None = None
        self._connected = False
        self._stopped = False
        self._login_invalid = False
        self._handshake_stage = 0
        self._handshake_buffer = ""
        self._session_error: str | None = None
        self._connect_initial()

    def _connect_initial(self) -> None:
        failures: list[str] = []
        for _ in range(len(self._hosts)):
            host = self._next_host()
            try:
                self._open_session(host, wait_ready=True)
                self._send_command("MDC 1")
                return
            except CedroAuthError:
                self.close()
                raise
            except CedroStreamError as exc:
                failures.append(str(exc))
                self._close_transport()
        self.close()
        detail = failures[-1] if failures else "nenhum host respondeu"
        raise CedroStreamError(f"Não foi possível conectar ao Socket Crystal: {detail}")

    def _next_host(self) -> str:
        if self._forced_host:
            host = self._forced_host
            self._forced_host = None
            return host
        host = self._hosts[self._host_index % len(self._hosts)]
        self._host_index += 1
        return host

    def _open_session(self, host: str, *, wait_ready: bool) -> None:
        try:
            transport = self._socket_factory(
                host,
                self._settings.crystal_port,
                timeout=self._settings.http_timeout,
            )
        except Exception as exc:
            raise CedroStreamError(
                f"Não foi possível abrir TCP em {host}:{self._settings.crystal_port}."
            ) from exc

        settimeout = getattr(transport, "settimeout", None)
        if callable(settimeout):
            settimeout(1.0)
        with self._condition:
            self._socket = transport
            self._cache.host = host
            self._cache.last_error = None
            for symbol, services in self._cache.subscriptions.items():
                if _BOOK in services:
                    self._cache.books.pop(symbol, None)
                    self._cache.book_ready.discard(symbol)
            self._session_error = None
            self._handshake_stage = 0
            self._handshake_buffer = ""
            self._connected = False
            self._line_queue = queue.Queue()
            line_queue = self._line_queue
            self._processor = threading.Thread(
                target=self._process_loop,
                args=(line_queue,),
                name="cedro-crystal-parser",
                daemon=True,
            )
            self._reader = threading.Thread(
                target=self._receive_loop,
                args=(transport, line_queue),
                name="cedro-crystal-reader",
                daemon=True,
            )
            self._processor.start()
            self._reader.start()

        if not wait_ready:
            return

        deadline = time.monotonic() + _HANDSHAKE_WAIT_SECONDS
        with self._condition:
            while not self._connected and not self._session_error and not self._stopped:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            if self._connected:
                self._cache.connected_at = time.time()
                return
            if self._login_invalid:
                raise CedroAuthError(self._session_error or "Invalid Login no Socket Crystal.")
            if self._session_error:
                raise CedroStreamError(self._session_error)
        raise CedroStreamError(
            f"O Socket Crystal não concluiu o handshake em {_HANDSHAKE_WAIT_SECONDS:.0f}s."
        )

    def _receive_loop(
        self,
        transport: CrystalTransport,
        line_queue: queue.Queue[str | None],
    ) -> None:
        remainder = ""
        try:
            while not self._stopped:
                try:
                    raw = transport.recv(4096)
                except (TimeoutError, socket_module.timeout):
                    continue
                if raw is None or raw == b"" or raw == bytearray():
                    raise ConnectionError("servidor encerrou o socket")
                chunk = bytes(raw).decode("utf-8", errors="replace")
                became_connected = False
                if not self._connected:
                    tail = self._handle_handshake(chunk)
                    became_connected = self._connected

                # O Crystal envia prompts sem newline e dados com \n; só os dados entram na fila.
                if self._connected:
                    buffer = tail if became_connected else remainder + chunk
                    parts = buffer.split("\n")
                    remainder = parts.pop()
                    for part in parts:
                        line = part.strip()
                        if line:
                            line_queue.put(line)
        except Exception as exc:
            if not self._stopped:
                self._session_failed(str(exc), transport)
        finally:
            line_queue.put(None)

    def _handle_handshake(self, chunk: str) -> str:
        with self._condition:
            self._handshake_buffer = (self._handshake_buffer + chunk)[-8_192:]
            lower = self._handshake_buffer.lower()
            if "invalid login" in lower:
                self._login_invalid = True
                self._session_error = "Invalid Login — reconexão automática desabilitada."
                self._condition.notify_all()
                return ""

            prompts = (
                ("connecting", self._credentials.software_key or ""),
                ("username", self._credentials.user or ""),
                ("password", self._credentials.password or ""),
            )
            while self._handshake_stage < 3:
                marker, response = prompts[self._handshake_stage]
                if marker not in lower:
                    break
                self._send_raw(response)
                self._handshake_stage += 1
            if self._handshake_stage >= 3 and "you are connected" in lower:
                self._connected = True
                self._session_error = None
                self._condition.notify_all()
                marker = lower.rfind("you are connected") + len("you are connected")
                tail = self._handshake_buffer[marker:]
                self._handshake_buffer = ""
                return tail
        return ""

    def _process_loop(self, line_queue: queue.Queue[str | None]) -> None:
        while not self._stopped:
            line = line_queue.get()
            if line is None:
                return
            try:
                self._process_line(line)
            except Exception:
                # Uma linha malformada não pode derrubar o dreno do stream.
                continue

    def _process_line(self, line: str) -> None:
        if line == "SYN":
            return
        self._cache.last_message_at = time.time()
        if line.startswith("T:"):
            self._process_quote(line)
        elif line.startswith("Z:"):
            self._process_book(line)
        elif line.startswith("V:"):
            self._process_tape(line)
        elif line.startswith("E:"):
            self._process_error(line)
        with self._condition:
            self._condition.notify_all()

    def _process_quote(self, line: str) -> None:
        fields = line.split(":")
        if len(fields) < 5:
            return
        symbol = fields[1].upper()
        values = dict(self._cache.quotes.get(symbol, {}).get("values", {}))
        for index in range(3, len(fields) - 1, 2):
            try:
                key = str(int(fields[index]))
            except (TypeError, ValueError):
                continue
            values[key] = _as_text(fields[index + 1])
        if values:
            self._cache.quotes[symbol] = {
                "symbol": symbol,
                "time": fields[2],
                "values": values,
                "raw": line,
            }

    def _book_level(self, fields: list[str]) -> dict[str, Any] | None:
        if len(fields) < 6:
            return None
        try:
            position = int(fields[0])
        except ValueError:
            return None
        return {
            "position": position,
            "side": "buy" if fields[1].upper() == "A" else "sell",
            "direction": fields[1].upper(),
            "price": fields[2],
            "quantity": fields[3],
            "orders": fields[4],
            "datetime": fields[5],
        }

    def _process_book(self, line: str) -> None:
        fields = line.split(":")
        if len(fields) < 3:
            return
        symbol = fields[1].upper()
        book = self._cache.books.setdefault(
            symbol,
            {"symbol": symbol, "bids": {}, "asks": {}, "raw": line},
        )
        operation = fields[2].upper()
        if operation == "E":
            self._cache.book_ready.add(symbol)
            return
        if operation in {"A", "U"}:
            level = self._book_level(fields[3:])
            if level is None:
                return
            side = book["bids"] if level["direction"] == "A" else book["asks"]
            side[level["position"]] = level
        elif operation == "D" and len(fields) >= 7:
            kind, direction, position = fields[3], fields[4].upper(), fields[5]
            try:
                position_i = int(position)
            except ValueError:
                return
            sides = [] if kind == "3" else [book["bids"] if direction == "A" else book["asks"]]
            for side in sides:
                for key in list(side):
                    if (kind == "2" and key <= position_i) or (kind == "1" and key == position_i):
                        side.pop(key, None)
        book["raw"] = line

    def _process_tape(self, line: str) -> None:
        fields = line.split(":")
        if len(fields) < 3:
            return
        symbol = fields[1].upper()
        history = self._cache.tapes.setdefault(
            symbol,
            deque(maxlen=self._settings.stream_tape_limit),
        )
        operation = fields[2].upper()
        if operation == "R":
            history.clear()
        elif operation == "A" and len(fields) >= 12:
            history.append(
                {
                    "operation": operation,
                    "time": fields[3],
                    "price": fields[4],
                    "buy_broker": fields[5],
                    "sell_broker": fields[6],
                    "quantity": fields[7],
                    "trade_id": fields[8],
                    "condition": fields[9],
                    "aggressor": fields[10],
                    "original_condition": _as_text(fields[11]),
                }
            )
        elif operation == "D" and len(fields) > 8:
            trade_id = fields[8]
            kept = [item for item in history if item.get("trade_id") != trade_id]
            history.clear()
            history.extend(kept)

    def _process_error(self, line: str) -> None:
        fields = line.split(":")
        try:
            code = int(fields[1])
        except (IndexError, ValueError):
            return
        if not 1 <= code <= 19:
            return
        with self._condition:
            self._cache.last_error = line
            if code == 12 and len(fields) >= 3 and fields[2]:
                self._forced_host = fields[2]
            self._condition.notify_all()
        if code == 12:
            self._close_transport()

    def _session_failed(self, message: str, transport: CrystalTransport) -> None:
        with self._condition:
            if self._socket is not transport or self._stopped:
                return
            self._connected = False
            self._session_error = f"Conexão Socket Crystal encerrada: {message}"
            self._cache.last_error = self._session_error
            self._condition.notify_all()
            should_reconnect = bool(self._cache.subscriptions) and not self._login_invalid
        self._close_transport(transport)
        if should_reconnect:
            with self._condition:
                if self._reconnector is None or not self._reconnector.is_alive():
                    self._reconnector = threading.Thread(
                        target=self._reconnect_loop,
                        name="cedro-crystal-reconnect",
                        daemon=True,
                    )
                    self._reconnector.start()

    def _reconnect_loop(self) -> None:
        while not self._stopped and self._cache.subscriptions and not self._login_invalid:
            time.sleep(_RECONNECT_DELAY_SECONDS)
            if self._stopped or self._login_invalid:
                return
            try:
                self._open_session(self._next_host(), wait_ready=True)
                self._send_command("MDC 1")
                self._resubscribe()
                return
            except CedroAuthError:
                self._login_invalid = True
                return
            except CedroStreamError as exc:
                with self._condition:
                    self._cache.last_error = str(exc)
                    self._condition.notify_all()

    def _resubscribe(self) -> None:
        for symbol, services in list(self._cache.subscriptions.items()):
            for service in sorted(services):
                if service == _QUOTE:
                    self._send_command(f"SQT {symbol}")
                elif service == _BOOK:
                    self._send_command(f"SAB {symbol}")
                elif service == _TAPE:
                    self._send_command(f"GQT {symbol} S {self._settings.stream_tape_limit}")

    def _send_raw(self, value: str) -> None:
        with self._send_lock:
            if self._socket is None:
                raise CedroStreamError("Socket Crystal não está aberto.")
            self._socket.sendall((value + "\r\n").encode("utf-8"))

    def _send_command(self, command: str) -> None:
        with self._condition:
            if not self._connected or self._socket is None:
                raise CedroStreamError(
                    self._cache.last_error or "A conexão do Socket Crystal não está ativa."
                )
        try:
            self._send_raw(command)
        except Exception as exc:
            raise CedroStreamError("Falha ao enviar comando para o Socket Crystal.") from exc

    def _ensure_subscription(self, symbol: str, service: str, command: str) -> str:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol não pode ser vazio.")
        with self._condition:
            if self._stopped:
                raise CedroStreamError("A conexão do Socket Crystal está fechada.")
            services = self._cache.subscriptions.setdefault(normalized, set())
            if service in services:
                return normalized
            services.add(service)
        try:
            self._send_command(command)
        except CedroStreamError:
            with self._condition:
                services = self._cache.subscriptions.get(normalized)
                if services is not None:
                    services.discard(service)
                    if not services:
                        self._cache.subscriptions.pop(normalized, None)
            raise
        return normalized

    def _snapshot(self, symbol: str, cache: dict[str, Any], label: str) -> dict[str, Any]:
        with self._condition:
            received = self._condition.wait_for(
                lambda: symbol in cache or self._cache.last_error is not None or self._stopped,
                timeout=self._settings.stream_snapshot_timeout,
            )
            if symbol in cache:
                return cache[symbol]
            if self._cache.last_error:
                raise CedroStreamError(self._cache.last_error)
        if not received:
            raise CedroStreamError(
                f"O Socket Crystal não enviou snapshot de {label} para {symbol} a tempo."
            )
        raise CedroStreamError("A conexão do Socket Crystal foi fechada antes do snapshot.")

    def get_quote(self, symbol: str) -> dict[str, Any]:
        normalized = self._ensure_subscription(symbol, _QUOTE, f"SQT {symbol.strip().upper()}")
        return self._snapshot(normalized, self._cache.quotes, "cotação")

    def get_book(self, symbol: str) -> dict[str, Any]:
        normalized = self._ensure_subscription(symbol, _BOOK, f"SAB {symbol.strip().upper()}")
        with self._condition:
            received = self._condition.wait_for(
                lambda: normalized in self._cache.book_ready
                or self._cache.last_error is not None
                or self._stopped,
                timeout=self._settings.stream_snapshot_timeout,
            )
            if normalized not in self._cache.books and not self._cache.last_error:
                if not received:
                    raise CedroStreamError(
                        f"O Socket Crystal não enviou snapshot de livro para {normalized} a tempo."
                    )
            if self._cache.last_error and normalized not in self._cache.books:
                raise CedroStreamError(self._cache.last_error)
            snapshot = self._cache.books.get(normalized)
        if snapshot is None:
            raise CedroStreamError("O Socket Crystal foi fechado antes do snapshot do livro.")
        return {
            **snapshot,
            "bids": [snapshot["bids"][key] for key in sorted(snapshot["bids"])],
            "asks": [snapshot["asks"][key] for key in sorted(snapshot["asks"])],
        }

    def get_tape(self, symbol: str, count: int) -> dict[str, Any]:
        normalized = self._ensure_subscription(
            symbol,
            _TAPE,
            f"GQT {symbol.strip().upper()} S {min(count, self._settings.stream_tape_limit)}",
        )
        with self._condition:
            received = self._condition.wait_for(
                lambda: normalized in self._cache.tapes
                or self._cache.last_error is not None
                or self._stopped,
                timeout=self._settings.stream_snapshot_timeout,
            )
            if normalized in self._cache.tapes:
                return {"symbol": normalized, "trades": list(self._cache.tapes[normalized])[-count:]}
            if self._cache.last_error:
                raise CedroStreamError(self._cache.last_error)
        if not received:
            raise CedroStreamError(f"O Socket Crystal não enviou negócios para {normalized} a tempo.")
        raise CedroStreamError("A conexão do Socket Crystal foi fechada antes da fita.")

    def unsubscribe(self, symbol: str) -> dict[str, Any]:
        normalized = symbol.strip().upper()
        with self._condition:
            services = set(self._cache.subscriptions.get(normalized, set()))
        commands = {_QUOTE: "USQ", _BOOK: "UAB", _TAPE: "UQT"}
        for service in sorted(services):
            self._send_command(f"{commands[service]} {normalized}")
        with self._condition:
            self._cache.subscriptions.pop(normalized, None)
            self._cache.quotes.pop(normalized, None)
            self._cache.books.pop(normalized, None)
            self._cache.tapes.pop(normalized, None)
        return {"symbol": normalized, "unsubscribed": sorted(services)}

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "connected": self._connected and not self._stopped,
                "host": self._cache.host,
                "port": self._settings.crystal_port,
                "subscriptions": {
                    symbol: sorted(services)
                    for symbol, services in self._cache.subscriptions.items()
                },
                "connected_at": self._cache.connected_at,
                "last_message_at": self._cache.last_message_at,
                "last_error": self._cache.last_error,
            }

    def _close_transport(self, transport: CrystalTransport | None = None) -> None:
        target = transport or self._socket
        if target is None:
            return
        try:
            target.close()
        except Exception:
            pass

    def close(self) -> None:
        with self._condition:
            if self._stopped:
                return
            self._stopped = True
            self._connected = False
            self._condition.notify_all()
        self._close_transport()


def _default_socket_factory(host: str, port: int, *, timeout: float) -> CrystalTransport:
    return socket_module.create_connection((host, port), timeout=timeout)


class MarketDataStreamClient:
    """Registro de conexões Crystal, uma por credencial dentro deste processo."""

    def __init__(
        self,
        settings: Settings,
        credential_provider: CredentialProvider,
        socket_factory: CrystalSocketFactory = _default_socket_factory,
    ) -> None:
        self._settings = settings
        self._provider = credential_provider
        self._socket_factory = socket_factory
        self._connections: dict[str, _CrystalConnection] = {}
        self._connection_failures: dict[str, CedroError] = {}
        self._lock = threading.RLock()

    def _connection_for(self, principal: AccessToken | None) -> _CrystalConnection:
        credentials = self._provider.socket_credentials_for(principal)
        key = _credential_key(credentials)
        with self._lock:
            failure = self._connection_failures.get(key)
            if failure is not None:
                raise failure
            connection = self._connections.get(key)
            if connection is None:
                try:
                    connection = _CrystalConnection(
                        self._settings,
                        credentials,
                        self._socket_factory,
                    )
                except CedroAuthError as exc:
                    self._connection_failures[key] = exc
                    raise
                self._connections[key] = connection
            return connection

    def _current(self) -> _CrystalConnection:
        return self._connection_for(get_access_token())

    def _existing_current(self) -> _CrystalConnection | None:
        credentials = self._provider.socket_credentials_for(get_access_token())
        key = _credential_key(credentials)
        with self._lock:
            return self._connections.get(key)

    def get_quote(self, symbol: str) -> dict[str, Any]:
        return self._current().get_quote(symbol)

    def get_book(self, symbol: str) -> dict[str, Any]:
        return self._current().get_book(symbol)

    def get_tape(self, symbol: str, count: int) -> dict[str, Any]:
        return self._current().get_tape(symbol, count)

    def unsubscribe(self, symbol: str) -> dict[str, Any]:
        connection = self._existing_current()
        if connection is None:
            return {"symbol": symbol.strip().upper(), "unsubscribed": []}
        return connection.unsubscribe(symbol)

    def status(self) -> dict[str, Any]:
        connection = self._existing_current()
        if connection is None:
            return {
                "connected": False,
                "host": None,
                "port": self._settings.crystal_port,
                "subscriptions": {},
                "connected_at": None,
                "last_message_at": None,
                "last_error": None,
            }
        return connection.status()

    def close(self) -> None:
        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
            self._connection_failures.clear()
        for connection in connections:
            connection.close()
