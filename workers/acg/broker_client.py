from __future__ import annotations

import base64
import hashlib
import hmac
import json
import socket
import struct
import threading
import time
import uuid
from typing import Any, TextIO


ALLOWED_BROKER_OPERATIONS = frozenset(
    {"model.openai_chat", "model.anthropic_messages", "model.gemini_content", "tts.synthesize"}
)
BROKER_REQUEST_PREFIX = "__ANKI_CARD_BROKER_REQUEST__"
BROKER_RESPONSE_PREFIX = "__ANKI_CARD_BROKER_RESPONSE__"
BROKER_TRANSPORTS = frozenset({"authenticated_loopback_json", "authenticated_stdio_json"})
_configured_client: "WorkerBrokerClient | None" = None
_configuration_lock = threading.RLock()


class WorkerBrokerError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode_key(value: str) -> bytes:
    try:
        key = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise WorkerBrokerError("Broker channel proof is invalid") from error
    if len(key) != 32:
        raise WorkerBrokerError("Broker channel proof is invalid")
    return key


def _sign(key: bytes, value: dict[str, Any]) -> str:
    unsigned = {name: child for name, child in value.items() if name != "mac"}
    return base64.urlsafe_b64encode(hmac.new(key, _canonical(unsigned), hashlib.sha256).digest()).decode("ascii").rstrip("=")


class WorkerBrokerClient:
    def __init__(
        self,
        descriptor: dict[str, Any],
        *,
        control_reader: TextIO | None = None,
        control_writer: TextIO | None = None,
    ) -> None:
        self.transport = str(descriptor.get("transport") or "")
        if descriptor.get("schemaVersion") != 1 or self.transport not in BROKER_TRANSPORTS:
            raise WorkerBrokerError("Unsupported broker descriptor")
        self.host = ""
        self.port = 0
        self.control_reader = control_reader
        self.control_writer = control_writer
        if self.transport == "authenticated_loopback_json":
            if descriptor.get("host") != "127.0.0.1":
                raise WorkerBrokerError("Broker must use IPv4 loopback")
            self.host = "127.0.0.1"
            self.port = int(descriptor["port"])
            if not 1 <= self.port <= 65535:
                raise WorkerBrokerError("Broker port is invalid")
        elif control_reader is None or control_writer is None:
            raise WorkerBrokerError("Broker stdio control channel is missing")
        self.task_id = str(descriptor["taskId"])
        if not self.task_id:
            raise WorkerBrokerError("Broker task binding is missing")
        self.key = _decode_key(str(descriptor["channelProof"]))
        self.maximum_bytes = int(descriptor["maximumMessageBytes"])
        if not 1024 <= self.maximum_bytes <= 16 * 1024 * 1024:
            raise WorkerBrokerError("Broker message limit is invalid")
        allowed_operations = frozenset(str(value) for value in descriptor.get("allowedOperations") or [])
        if not allowed_operations or not allowed_operations <= ALLOWED_BROKER_OPERATIONS:
            raise WorkerBrokerError("Broker descriptor contains unknown operations")
        self.allowed_operations = allowed_operations
        self.expires_at_ms = int(descriptor["expiresAtUnixMs"])
        self._exchange_lock = threading.RLock()

    def request(self, operation: str, payload: dict[str, Any], *, request_id: str | None = None) -> Any:
        if int(time.time() * 1000) >= self.expires_at_ms:
            raise WorkerBrokerError("Broker descriptor expired")
        if operation not in self.allowed_operations:
            raise WorkerBrokerError("Broker operation is not allowed by the descriptor")
        request = {
            "schemaVersion": 1,
            "taskId": self.task_id,
            "requestId": request_id or str(uuid.uuid4()),
            "operation": operation,
            "payload": payload,
        }
        request["mac"] = _sign(self.key, request)
        encoded = _canonical(request)
        if len(encoded) > self.maximum_bytes:
            raise WorkerBrokerError("Broker request exceeded its size limit")
        with self._exchange_lock:
            if self.transport == "authenticated_loopback_json":
                response = self._exchange_loopback(encoded)
            else:
                response = self._exchange_stdio(encoded)
        if not isinstance(response, dict) or not hmac.compare_digest(str(response.get("mac") or ""), _sign(self.key, response)):
            raise WorkerBrokerError("Broker response authentication failed")
        if response.get("taskId") != self.task_id or response.get("requestId") != request["requestId"]:
            raise WorkerBrokerError("Broker response binding mismatch")
        if not response.get("ok"):
            error = response.get("error") or {}
            raise WorkerBrokerError(f"{error.get('code') or 'BROKER_FAILED'}: {error.get('message') or 'Broker request failed'}")
        return response.get("result")

    def _exchange_loopback(self, encoded: bytes) -> Any:
        with socket.create_connection((self.host, self.port), timeout=30) as connection:
            connection.sendall(struct.pack(">I", len(encoded)) + encoded)
            header = self._read_exact(connection, 4)
            length = struct.unpack(">I", header)[0]
            if not 1 <= length <= self.maximum_bytes:
                raise WorkerBrokerError("Broker response exceeded its size limit")
            return json.loads(self._read_exact(connection, length).decode("utf-8"))

    def _exchange_stdio(self, encoded: bytes) -> Any:
        assert self.control_reader is not None and self.control_writer is not None
        self.control_writer.write(BROKER_REQUEST_PREFIX + encoded.decode("utf-8") + "\n")
        self.control_writer.flush()
        maximum_line = len(BROKER_RESPONSE_PREFIX) + self.maximum_bytes + 2
        line = self.control_reader.readline(maximum_line)
        if not line or len(line.encode("utf-8")) >= maximum_line or not line.endswith("\n"):
            raise WorkerBrokerError("Broker stdio response ended early or exceeded its size limit")
        if not line.startswith(BROKER_RESPONSE_PREFIX):
            raise WorkerBrokerError("Broker stdio response framing is invalid")
        try:
            return json.loads(line[len(BROKER_RESPONSE_PREFIX) :])
        except ValueError as error:
            raise WorkerBrokerError("Broker stdio response is invalid JSON") from error

    @staticmethod
    def _read_exact(connection: socket.socket, length: int) -> bytes:
        chunks: list[bytes] = []
        while length:
            chunk = connection.recv(length)
            if not chunk:
                raise WorkerBrokerError("Broker response ended early")
            chunks.append(chunk)
            length -= len(chunk)
        return b"".join(chunks)


def configure_stdio_broker(descriptor: dict[str, Any], *, control_reader: TextIO, control_writer: TextIO) -> None:
    global _configured_client
    with _configuration_lock:
        if _configured_client is not None:
            raise WorkerBrokerError("Broker client is already configured")
        if descriptor.get("transport") != "authenticated_stdio_json":
            raise WorkerBrokerError("Bootstrap broker must use authenticated stdio")
        _configured_client = WorkerBrokerClient(
            descriptor,
            control_reader=control_reader,
            control_writer=control_writer,
        )


def configured_broker_client() -> WorkerBrokerClient | None:
    with _configuration_lock:
        return _configured_client
