from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from card_service.mcp_card_tools import (
    GENERATE_CARDS_TOOL_NAME,
    LIST_CARDS_TOOL_NAME,
)
from card_service.mcp_card_plan_tools import (
    EDIT_CARD_PLAN_TOOL_NAME,
    LIST_CARD_PLANS_TOOL_NAME,
    PLAN_CARDS_TOOL_NAME,
    VALIDATE_CARD_PLANS_TOOL_NAME,
)
from card_service.mcp_candidate_tools import (
    GET_CANDIDATE_TOOL_NAME,
    LIST_CANDIDATES_TOOL_NAME,
    PREVIEW_EVIDENCE_TOOL_NAME,
    START_DISCOVERY_TOOL_NAME,
)
from card_service.mcp_anki_tools import (
    IMPORT_AND_VERIFY_TOOL_NAME,
    PREPARE_IMPORT_TOOL_NAME,
    REQUEST_IMPORT_CONFIRMATION_TOOL_NAME,
)
from card_service.mcp_artifact_tools import (
    GET_ARTIFACT_TOOL_NAME,
    GET_AUDIT_TOOL_NAME,
)
from card_service.mcp_package_tools import EXPORT_APKG_TOOL_NAME
from card_service.mcp_task_tools import (
    CANCEL_TASK_TOOL_NAME,
    GET_TASK_TOOL_NAME,
    LIST_RECOVERABLE_TASKS_TOOL_NAME,
    RESUME_TASK_TOOL_NAME,
)
from card_service.mcp_input_tools import REGISTER_INPUTS_TOOL_NAME
from card_service.mcp_inspection_tools import (
    GET_SOURCE_INSPECTION_TOOL_NAME,
    START_SOURCE_INSPECTION_TOOL_NAME,
)
from card_service.mcp_project_tools import (
    CREATE_PROJECT_TOOL_NAME,
    GET_PROJECT_TOOL_NAME,
    LIST_PROJECTS_TOOL_NAME,
)
from card_service.mcp_resource_tools import (
    NETWORK_GRANT_TOOL_NAME,
    OUTPUT_GRANT_TOOL_NAME,
    SOURCE_GRANT_TOOL_NAME,
)
from card_service.mcp_selection_tools import SET_SELECTION_TOOL_NAME
from card_service.mcp_system_tools import (
    AUTHORIZE_DISCOVERY_TOOL,
    LIST_PROFILES_TOOL,
    OPEN_LOCAL_SETTINGS_TOOL,
    REQUEST_OPERATION_CONFIRMATION_TOOL,
    REVOKE_GRANT_TOOL,
    VALIDATE_PROFILE_TOOL,
)
from card_service.mcp_stdio import CAPABILITY_TOOL_NAME, MCP_PROTOCOL_VERSION, serve
from card_service.service import CardServiceError
from card_service.trusted_mcp_audience import create_development_mcp_audience


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


def _run_messages(
    service: _CapabilityService,
    messages: list[object],
    *,
    trusted_audience: bool = False,
) -> list[dict[str, Any]]:
    source = io.StringIO(
        "".join(
            value if isinstance(value, str) else json.dumps(value) + "\n"
            for value in messages
        )
    )
    sink = io.StringIO()
    serve(
        service,
        source,
        sink,
        audience_session=(create_development_mcp_audience() if trusted_audience else None),
    )  # type: ignore[arg-type]
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
    capability_schema = tools[0]["outputSchema"]
    assert set(capability_schema["properties"]) == {
        "schemaVersion", "mcpBridge", "cardService", "error"
    }
    bridge_schema = capability_schema["properties"]["mcpBridge"]
    assert "audienceBinding" in bridge_schema["properties"]
    assert tools[0]["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert tools[0]["inputSchema"]["additionalProperties"] is False
    result = responses[2]["result"]
    assert result["structuredContent"]["mcpBridge"]["exposedTools"] == [CAPABILITY_TOOL_NAME]
    assert result["structuredContent"]["mcpBridge"]["audienceBinding"] == {
        "schemaVersion": 1, "available": False, "identifiersDisclosed": False
    }
    assert result["structuredContent"]["cardService"]["genericShell"] is False
    assert service.calls == [("system.get_capabilities", {})]
    assert responses[3]["result"] == {}


def test_mcp_bridge_reports_trusted_session_without_disclosing_identity() -> None:
    service = _CapabilityService()
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
        trusted_audience=True,
    )

    bridge = responses[0]["result"]["structuredContent"]["mcpBridge"]
    assert bridge["audienceBinding"] == {
        "schemaVersion": 1,
        "available": True,
        "mode": "development_explicit",
        "identifiersDisclosed": False,
        "toolArgumentsCanDeclareAudience": False,
    }
    serialized = json.dumps(bridge, sort_keys=True)
    assert "ownerDigest" not in serialized
    assert "hostId" not in serialized
    assert "sessionId" not in serialized
    assert bridge["exposedTools"] == [
        CAPABILITY_TOOL_NAME,
        AUTHORIZE_DISCOVERY_TOOL,
        LIST_PROFILES_TOOL,
        OPEN_LOCAL_SETTINGS_TOOL,
        REVOKE_GRANT_TOOL,
        VALIDATE_PROFILE_TOOL,
        REQUEST_OPERATION_CONFIRMATION_TOOL,
        SOURCE_GRANT_TOOL_NAME,
        OUTPUT_GRANT_TOOL_NAME,
        NETWORK_GRANT_TOOL_NAME,
        CREATE_PROJECT_TOOL_NAME,
        LIST_PROJECTS_TOOL_NAME,
        GET_PROJECT_TOOL_NAME,
        REGISTER_INPUTS_TOOL_NAME,
        START_SOURCE_INSPECTION_TOOL_NAME,
        GET_SOURCE_INSPECTION_TOOL_NAME,
        START_DISCOVERY_TOOL_NAME,
        LIST_CANDIDATES_TOOL_NAME,
        GET_CANDIDATE_TOOL_NAME,
        PREVIEW_EVIDENCE_TOOL_NAME,
        SET_SELECTION_TOOL_NAME,
        PLAN_CARDS_TOOL_NAME,
        LIST_CARD_PLANS_TOOL_NAME,
        EDIT_CARD_PLAN_TOOL_NAME,
        VALIDATE_CARD_PLANS_TOOL_NAME,
        GENERATE_CARDS_TOOL_NAME,
        LIST_CARDS_TOOL_NAME,
        EXPORT_APKG_TOOL_NAME,
        GET_TASK_TOOL_NAME,
        CANCEL_TASK_TOOL_NAME,
        LIST_RECOVERABLE_TASKS_TOOL_NAME,
        RESUME_TASK_TOOL_NAME,
        PREPARE_IMPORT_TOOL_NAME,
        REQUEST_IMPORT_CONFIRMATION_TOOL_NAME,
        IMPORT_AND_VERIFY_TOOL_NAME,
        GET_ARTIFACT_TOOL_NAME,
        GET_AUDIT_TOOL_NAME,
    ]


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
            "--development-trusted-mcp-session",
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
        assert [tool["name"] for tool in listed["result"]["tools"]] == [
            CAPABILITY_TOOL_NAME,
            AUTHORIZE_DISCOVERY_TOOL,
            LIST_PROFILES_TOOL,
            OPEN_LOCAL_SETTINGS_TOOL,
            REVOKE_GRANT_TOOL,
            VALIDATE_PROFILE_TOOL,
            REQUEST_OPERATION_CONFIRMATION_TOOL,
            SOURCE_GRANT_TOOL_NAME,
            OUTPUT_GRANT_TOOL_NAME,
            NETWORK_GRANT_TOOL_NAME,
            CREATE_PROJECT_TOOL_NAME,
            LIST_PROJECTS_TOOL_NAME,
            GET_PROJECT_TOOL_NAME,
            REGISTER_INPUTS_TOOL_NAME,
            START_SOURCE_INSPECTION_TOOL_NAME,
            GET_SOURCE_INSPECTION_TOOL_NAME,
            START_DISCOVERY_TOOL_NAME,
            LIST_CANDIDATES_TOOL_NAME,
            GET_CANDIDATE_TOOL_NAME,
            PREVIEW_EVIDENCE_TOOL_NAME,
            SET_SELECTION_TOOL_NAME,
            PLAN_CARDS_TOOL_NAME,
            LIST_CARD_PLANS_TOOL_NAME,
            EDIT_CARD_PLAN_TOOL_NAME,
            VALIDATE_CARD_PLANS_TOOL_NAME,
            GENERATE_CARDS_TOOL_NAME,
            LIST_CARDS_TOOL_NAME,
            EXPORT_APKG_TOOL_NAME,
            GET_TASK_TOOL_NAME,
            CANCEL_TASK_TOOL_NAME,
            LIST_RECOVERABLE_TASKS_TOOL_NAME,
            RESUME_TASK_TOOL_NAME,
            PREPARE_IMPORT_TOOL_NAME,
            REQUEST_IMPORT_CONFIRMATION_TOOL_NAME,
            IMPORT_AND_VERIFY_TOOL_NAME,
            GET_ARTIFACT_TOOL_NAME,
            GET_AUDIT_TOOL_NAME,
        ]
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
        assert capabilities["studyRuntime"]["publicCardPlanEditing"] is True
        assert capabilities["studyRuntime"]["publicCardPlanValidation"] is True
        assert capabilities["studyRuntime"]["publicCardGeneration"] is True
        assert capabilities["studyRuntime"]["publicCardQueries"] is True
        assert capabilities["studyRuntime"]["publicProjectQueries"] is True
        assert capabilities["studyRuntime"]["publicArtifactQueries"] is True
        assert capabilities["studyRuntime"]["publicAuditQueries"] is True
        assert capabilities["studyRuntime"]["publicCandidateDiscovery"] is True
        assert capabilities["studyRuntime"]["candidateDiscoveryAuthorizationReady"] is False
        assert capabilities["studyRuntime"]["publicAnkiWrite"] is True
        assert called["result"]["structuredContent"]["mcpBridge"]["transport"] == "stdio"
        assert called["result"]["structuredContent"]["mcpBridge"]["audienceBinding"]["available"] is True
        assert called["result"]["structuredContent"]["mcpBridge"]["audienceBinding"]["identifiersDisclosed"] is False
    finally:
        process.stdin.close()
        process.wait(timeout=5)
