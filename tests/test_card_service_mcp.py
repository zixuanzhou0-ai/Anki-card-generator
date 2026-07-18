from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from card_service.mcp_stdio import CAPABILITY_TOOL_NAME, MCP_PROTOCOL_VERSION, serve
from card_service.service import CardServiceError


ROOT = Path(__file__).resolve().parents[1]
FAKE_WORKER = ROOT / "tests" / "fixtures" / "card_service" / "fake_worker.py"


class _CapabilityService:
    def __init__(self, result: dict[str, Any] | None = None, error: CardServiceError | None = None):
        self.result = result or {
            "schemaVersion": 1,
            "service": "codex-study-card-service",
            "genericShell": False,
            "secretBearingRequests": False,
        }
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, params))
        if self.error is not None:
            raise self.error
        return self.result


def _run_messages(service: _CapabilityService, messages: list[object]) -> list[dict[str, Any]]:
    source = io.StringIO(
        "".join(
            value if isinstance(value, str) else json.dumps(value) + "\n"
            for value in messages
        )
    )
    sink = io.StringIO()
    serve(service, source, sink)  # type: ignore[arg-type]
    return [json.loads(line) for line in sink.getvalue().splitlines()]


def test_mcp_bridge_negotiates_and_exposes_only_read_only_capabilities() -> None:
    service = _CapabilityService()
    responses = _run_messages(
        service,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "test-host", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": CAPABILITY_TOOL_NAME, "arguments": {}},
            },
            {"jsonrpc": "2.0", "id": 4, "method": "ping", "params": {}},
        ],
    )

    assert [response["id"] for response in responses] == [1, 2, 3, 4]
    assert responses[0]["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert responses[0]["result"]["capabilities"] == {"tools": {"listChanged": False}}
    tools = responses[1]["result"]["tools"]
    assert [tool["name"] for tool in tools] == [CAPABILITY_TOOL_NAME]
    assert tools[0]["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert tools[0]["inputSchema"]["additionalProperties"] is False
    result = responses[2]["result"]
    assert result["structuredContent"]["mcpBridge"]["exposedTools"] == [CAPABILITY_TOOL_NAME]
    assert result["structuredContent"]["cardService"]["genericShell"] is False
    assert service.calls == [("system.get_capabilities", {})]
    assert responses[3]["result"] == {}


def test_mcp_bridge_rejects_invalid_protocol_and_tool_shapes() -> None:
    responses = _run_messages(
        _CapabilityService(),
        [
            "{not-json}\n",
            [],
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "runtime.run_worker"}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": CAPABILITY_TOOL_NAME, "arguments": {"method": "runtime.export_apkg"}},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "runtime.export_apkg", "params": {}},
        ],
    )

    assert [response["error"]["code"] for response in responses] == [
        -32700,
        -32600,
        -32602,
        -32602,
        -32601,
    ]
    serialized = json.dumps(responses)
    assert "runtime.export_apkg" not in serialized


def test_mcp_bridge_does_not_echo_card_service_error_details() -> None:
    service = _CapabilityService(
        error=CardServiceError(
            "CAPABILITY_FAILED",
            r"secret-canary at C:\Users\Example\private.json",
            retryable=True,
        )
    )
    responses = _run_messages(
        service,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": CAPABILITY_TOOL_NAME, "arguments": {}},
            }
        ],
    )

    result = responses[0]["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"] == {
        "code": "CAPABILITY_FAILED",
        "retryable": True,
    }
    serialized = json.dumps(result)
    assert "secret-canary" not in serialized
    assert "private.json" not in serialized


def test_real_mcp_stdio_process_reports_card_service_capabilities(tmp_path: Path) -> None:
    state_dir = (tmp_path / "mcp-state").resolve()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "card_service.mcp_stdio",
            "--state-dir",
            str(state_dir),
            "--development-unpackaged-runtime",
            "--worker",
            str(FAKE_WORKER.resolve()),
            "--python",
            str(Path(sys.executable).resolve()),
        ],
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdin is not None and process.stdout is not None

    def rpc(request: dict[str, Any]) -> dict[str, Any]:
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        return json.loads(process.stdout.readline())

    try:
        initialized = rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1"},
                },
            }
        )
        assert initialized["result"]["serverInfo"]["name"] == "anki-study-card-service"
        listed = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert [tool["name"] for tool in listed["result"]["tools"]] == [CAPABILITY_TOOL_NAME]
        called = rpc(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": CAPABILITY_TOOL_NAME, "arguments": {}},
            }
        )
        capabilities = called["result"]["structuredContent"]["cardService"]
        assert capabilities["service"] == "codex-study-card-service"
        assert capabilities["genericShell"] is False
        assert capabilities["secretBearingRequests"] is False
        assert called["result"]["structuredContent"]["mcpBridge"]["transport"] == "stdio"
    finally:
        process.stdin.close()
        process.wait(timeout=5)
