from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import socketserver
import struct
import threading
import time
import uuid
from typing import Any, Callable


MAX_BROKER_MESSAGE_BYTES = 1024 * 1024
MAX_BROKER_REQUESTS = 4096
ALLOWED_BROKER_OPERATIONS = frozenset(
    {"model.openai_chat", "model.anthropic_messages", "model.gemini_content", "tts.synthesize"}
)


class BrokerIpcError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(key: bytes, value: dict[str, Any]) -> str:
    unsigned = {name: child for name, child in value.items() if name != "mac"}
    return base64.urlsafe_b64encode(hmac.new(key, _canonical_bytes(unsigned), hashlib.sha256).digest()).decode("ascii").rstrip("=")


def _verify(key: bytes, value: dict[str, Any]) -> bool:
    supplied = str(value.get("mac") or "")
    return bool(supplied) and hmac.compare_digest(supplied, _sign(key, value))


def _read_exact(connection: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise BrokerIpcError("IPC_TRUNCATED", "Broker IPC message ended early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_message(connection: socket.socket, maximum_bytes: int) -> dict[str, Any]:
    header = _read_exact(connection, 4)
    length = struct.unpack(">I", header)[0]
    if not 1 <= length <= maximum_bytes:
        raise BrokerIpcError("IPC_MESSAGE_LIMIT", "Broker IPC message exceeded its size limit")
    try:
        value = json.loads(_read_exact(connection, length).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise BrokerIpcError("IPC_INVALID_JSON", "Broker IPC message is invalid JSON") from error
    if not isinstance(value, dict):
        raise BrokerIpcError("IPC_INVALID_JSON", "Broker IPC message must be an object")
    return value


def _write_message(connection: socket.socket, value: dict[str, Any], maximum_bytes: int) -> None:
    payload = _canonical_bytes(value)
    if len(payload) > maximum_bytes:
        raise BrokerIpcError("IPC_MESSAGE_LIMIT", "Broker IPC response exceeded its size limit")
    connection.sendall(struct.pack(">I", len(payload)) + payload)


class _ThreadingLoopbackServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True


class TaskBrokerChannel:
    """Authenticated, replay-safe, task-scoped JSON channel for one Worker tree."""

    def __init__(
        self,
        *,
        task_id: str,
        handler: Callable[[str, dict[str, Any]], Any],
        max_message_bytes: int = MAX_BROKER_MESSAGE_BYTES,
        max_requests: int = MAX_BROKER_REQUESTS,
        lifetime_seconds: float = 15 * 60,
    ) -> None:
        self.task_id = task_id
        self.handler = handler
        self.max_message_bytes = max(1024, int(max_message_bytes))
        self.max_requests = max(1, int(max_requests))
        self.expires_at = time.time() + max(1.0, float(lifetime_seconds))
        self.key = os.urandom(32)
        self._request_cache: dict[str, tuple[str, dict[str, Any]]] = {}
        self._lock = threading.RLock()
        channel = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                channel._handle_connection(self.request)

        self.server = _ThreadingLoopbackServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name=f"broker-ipc-{task_id}")
        self.thread.start()

    def descriptor(self) -> dict[str, Any]:
        host, port = self.server.server_address
        return {
            "schemaVersion": 1,
            "transport": "authenticated_loopback_json",
            "host": host,
            "port": port,
            "taskId": self.task_id,
            "channelProof": base64.urlsafe_b64encode(self.key).decode("ascii").rstrip("="),
            "maximumMessageBytes": self.max_message_bytes,
            "maximumRequests": self.max_requests,
            "expiresAtUnixMs": int(self.expires_at * 1000),
            "allowedOperations": sorted(ALLOWED_BROKER_OPERATIONS),
        }

    def _response(self, request_id: str, *, result: Any = None, error: BrokerIpcError | None = None) -> dict[str, Any]:
        response: dict[str, Any] = {"schemaVersion": 1, "taskId": self.task_id, "requestId": request_id}
        if error:
            response["ok"] = False
            response["error"] = {"code": error.code, "message": str(error)}
        else:
            response["ok"] = True
            response["result"] = result
        response["mac"] = _sign(self.key, response)
        return response

    def _handle_connection(self, connection: socket.socket) -> None:
        connection.settimeout(30)
        request_id = "unknown"
        try:
            request = _read_message(connection, self.max_message_bytes)
            request_id = str(request.get("requestId") or "")
            if not _verify(self.key, request):
                raise BrokerIpcError("IPC_AUTH_FAILED", "Broker IPC authentication failed")
            if time.time() >= self.expires_at:
                raise BrokerIpcError("IPC_EXPIRED", "Broker IPC channel expired")
            if request.get("schemaVersion") != 1 or request.get("taskId") != self.task_id:
                raise BrokerIpcError("IPC_TASK_MISMATCH", "Broker IPC task binding mismatch")
            try:
                uuid.UUID(request_id)
            except ValueError as error:
                raise BrokerIpcError("IPC_REQUEST_ID_INVALID", "Broker IPC request ID is invalid") from error
            operation = str(request.get("operation") or "")
            if operation not in ALLOWED_BROKER_OPERATIONS:
                raise BrokerIpcError("IPC_OPERATION_BLOCKED", "Broker IPC operation is not allowed")
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise BrokerIpcError("IPC_PAYLOAD_INVALID", "Broker IPC payload must be an object")
            request_digest = hashlib.sha256(_canonical_bytes({key: value for key, value in request.items() if key != "mac"})).hexdigest()
            with self._lock:
                cached = self._request_cache.get(request_id)
                if cached is not None:
                    if cached[0] != request_digest:
                        raise BrokerIpcError("IPC_REPLAY_CONFLICT", "Broker IPC request ID was replayed with different data")
                    response = cached[1]
                else:
                    if len(self._request_cache) >= self.max_requests:
                        raise BrokerIpcError("IPC_REQUEST_LIMIT", "Broker IPC request limit was reached")
                    try:
                        result = self.handler(operation, payload)
                        try:
                            response = self._response(request_id, result=result)
                            _canonical_bytes(response)
                        except (TypeError, ValueError):
                            response = self._response(
                                request_id,
                                error=BrokerIpcError("IPC_RESULT_INVALID", "Broker result is not valid JSON"),
                            )
                    except BrokerIpcError as error:
                        response = self._response(request_id, error=error)
                    except Exception:
                        response = self._response(
                            request_id,
                            error=BrokerIpcError("BROKER_HANDLER_FAILED", "Broker operation failed"),
                        )
                    self._request_cache[request_id] = (request_digest, response)
        except BrokerIpcError as error:
            response = self._response(request_id, error=error)
        try:
            _write_message(connection, response, self.max_message_bytes)
        except (BrokerIpcError, OSError):
            return

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def __enter__(self) -> "TaskBrokerChannel":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
