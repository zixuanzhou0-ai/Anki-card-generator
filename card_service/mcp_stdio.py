from __future__ import annotations

import json
import re
import sys
from typing import Any, TextIO

from .mcp_card_plan_tools import (
    CARD_PLAN_TOOL_NAMES,
    McpCardPlanToolInputError,
    call_card_plan_tool,
    card_plan_tool_definitions,
)
from .mcp_candidate_tools import (
    CANDIDATE_TOOL_NAMES,
    McpCandidateToolInputError,
    call_candidate_tool,
    candidate_tool_definitions,
)
from .mcp_input_tools import (
    INPUT_TOOL_NAMES,
    McpInputToolInputError,
    call_input_tool,
    input_tool_definitions,
)
from .mcp_inspection_tools import (
    INSPECTION_TOOL_NAMES,
    McpInspectionToolInputError,
    call_inspection_tool,
    inspection_tool_definitions,
)
from .mcp_selection_tools import (
    SELECTION_TOOL_NAMES,
    McpSelectionToolInputError,
    call_selection_tool,
    selection_tool_definitions,
)
from .mcp_project_tools import (
    PROJECT_TOOL_NAMES,
    McpProjectToolInputError,
    call_project_tool,
    project_tool_definitions,
)
from .mcp_resource_tools import (
    RESOURCE_GRANT_TOOL_NAMES,
    McpResourceToolInputError,
    call_resource_tool,
    resource_tool_definitions,
)
from .service import CardService, CardServiceError
from .trusted_mcp_audience import (
    TrustedMcpAudienceError,
    TrustedMcpAudienceSession,
    create_development_mcp_audience,
    create_packaged_mcp_audience,
)
from .stdio import build_parser, create_service


MCP_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {
        "2024-11-05",
        "2025-03-26",
        "2025-06-18",
        MCP_PROTOCOL_VERSION,
    }
)
SERVER_NAME = "anki-study-card-service"
SERVER_VERSION = "0.1.0"
CAPABILITY_TOOL_NAME = "system.get_capabilities"
_SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _tool_definition() -> dict[str, Any]:
    return {
        "name": CAPABILITY_TOOL_NAME,
        "title": "Get Anki Study Capabilities",
        "description": (
            "Report the local Anki Study Card Service, managed runtime, sandbox, "
            "broker, and method availability without returning credentials or local paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "schemaVersion": {"type": "integer", "const": 1},
                "mcpBridge": {
                    "type": "object",
                    "properties": {
                        "transport": {"type": "string", "const": "stdio"},
                        "protocolVersion": {"type": "string"},
                        "exposedTools": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "audienceBinding": {"type": "object"},
                    },
                    "required": ["transport", "protocolVersion", "exposedTools", "audienceBinding"],
                    "additionalProperties": False,
                },
                "cardService": {"type": "object"},
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "retryable": {"type": "boolean"},
                    },
                    "required": ["code", "retryable"],
                    "additionalProperties": False,
                },
            },
            "oneOf": [
                {"required": ["schemaVersion", "mcpBridge", "cardService"]},
                {"required": ["error"]},
            ],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }


def _tool_definitions(
    audience_session: TrustedMcpAudienceSession | None,
) -> list[dict[str, Any]]:
    definitions = [_tool_definition()]
    if audience_session is not None:
        definitions.extend(resource_tool_definitions())
        definitions.extend(project_tool_definitions())
        definitions.extend(input_tool_definitions())
        definitions.extend(inspection_tool_definitions())
        definitions.extend(candidate_tool_definitions())
        definitions.extend(selection_tool_definitions())
        definitions.extend(card_plan_tool_definitions())
    return definitions


def _response(
    request_id: Any,
    *,
    result: Any = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return _response(request_id, error={"code": code, "message": message})


def _public_error_code(error: CardServiceError) -> str:
    return error.code if _SAFE_ERROR_CODE.fullmatch(error.code) else "CARD_SERVICE_ERROR"


def _tool_error(error: CardServiceError | None = None) -> dict[str, Any]:
    code = _public_error_code(error) if error is not None else "INTERNAL_ERROR"
    return {
        "content": [
            {
                "type": "text",
                "text": "The local Card Service could not complete the requested operation.",
            }
        ],
        "structuredContent": {
            "error": {
                "code": code,
                "retryable": bool(error.retryable) if error is not None else False,
            }
        },
        "isError": True,
    }


def _handle_request(
    service: CardService,
    request: dict[str, Any],
    audience_session: TrustedMcpAudienceSession | None = None,
    user_action_timeout_seconds: float = 300.0,
) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})
    if (
        request.get("jsonrpc") != "2.0"
        or not isinstance(method, str)
        or not isinstance(params, dict)
    ):
        return _rpc_error(request_id, -32600, "Invalid Request")

    if method == "notifications/initialized" or method == "notifications/cancelled":
        return None

    if method == "initialize":
        requested_version = params.get("protocolVersion")
        if requested_version is not None and not isinstance(requested_version, str):
            return _rpc_error(request_id, -32602, "Invalid initialize parameters")
        protocol_version = (
            requested_version
            if requested_version in SUPPORTED_PROTOCOL_VERSIONS
            else MCP_PROTOCOL_VERSION
        )
        return _response(
            request_id,
            result={
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
                "instructions": (
                    "Start with system.get_capabilities. Trusted launcher sessions may request "
                    "opaque source and output grants through native pickers and create a local "
                    "Study project, freeze selected InputRefs with study.register_inputs, then "
                    "run deterministic source inspection. Existing authenticated candidate discoveries "
                    "can be listed, reviewed with bounded evidence replay, and saved as a reliable local "
                    "portfolio, deterministically planned into supported CardPlans, "
                    "edited within a closed agent schema, and reviewed/revalidated with "
                    "all eight local validation states. Starting candidate discovery, card generation, "
                    "export, import, credentials, and raw Worker commands remain unavailable."
                ),
            },
        )

    if method == "ping":
        return _response(request_id, result={})

    if method == "tools/list":
        return _response(
            request_id, result={"tools": _tool_definitions(audience_session)}
        )

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name in RESOURCE_GRANT_TOOL_NAMES:
            if audience_session is None:
                return _rpc_error(request_id, -32602, "Unknown tool")
            try:
                result = call_resource_tool(
                    service,
                    tool_name=str(tool_name),
                    arguments=arguments,
                    audience_session=audience_session,
                    user_action_timeout_seconds=user_action_timeout_seconds,
                )
            except McpResourceToolInputError:
                return _rpc_error(request_id, -32602, "Invalid resource tool arguments")
            except CardServiceError as error:
                return _response(request_id, result=_tool_error(error))
            except Exception:
                return _response(request_id, result=_tool_error())
            return _response(request_id, result=result)
        if tool_name in PROJECT_TOOL_NAMES:
            if audience_session is None:
                return _rpc_error(request_id, -32602, "Unknown tool")
            try:
                result = call_project_tool(
                    service,
                    tool_name=str(tool_name),
                    arguments=arguments,
                    audience_session=audience_session,
                )
            except McpProjectToolInputError:
                return _rpc_error(request_id, -32602, "Invalid project tool arguments")
            except CardServiceError as error:
                return _response(request_id, result=_tool_error(error))
            except Exception:
                return _response(request_id, result=_tool_error())
            return _response(request_id, result=result)
        if tool_name in INPUT_TOOL_NAMES:
            if audience_session is None:
                return _rpc_error(request_id, -32602, "Unknown tool")
            try:
                result = call_input_tool(
                    service,
                    tool_name=str(tool_name),
                    arguments=arguments,
                    audience_session=audience_session,
                )
            except McpInputToolInputError:
                return _rpc_error(request_id, -32602, "Invalid input tool arguments")
            except CardServiceError as error:
                return _response(request_id, result=_tool_error(error))
            except Exception:
                return _response(request_id, result=_tool_error())
            return _response(request_id, result=result)
        if tool_name in INSPECTION_TOOL_NAMES:
            if audience_session is None:
                return _rpc_error(request_id, -32602, "Unknown tool")
            try:
                result = call_inspection_tool(
                    service,
                    tool_name=str(tool_name),
                    arguments=arguments,
                    audience_session=audience_session,
                )
            except McpInspectionToolInputError:
                return _rpc_error(request_id, -32602, "Invalid inspection tool arguments")
            except CardServiceError as error:
                return _response(request_id, result=_tool_error(error))
            except Exception:
                return _response(request_id, result=_tool_error())
            return _response(request_id, result=result)
        if tool_name in SELECTION_TOOL_NAMES:
            if audience_session is None:
                return _rpc_error(request_id, -32602, "Unknown tool")
            try:
                result = call_selection_tool(
                    service,
                    tool_name=str(tool_name),
                    arguments=arguments,
                    audience_session=audience_session,
                )
            except McpSelectionToolInputError:
                return _rpc_error(request_id, -32602, "Invalid selection tool arguments")
            except CardServiceError as error:
                return _response(request_id, result=_tool_error(error))
            except Exception:
                return _response(request_id, result=_tool_error())
            return _response(request_id, result=result)
        if tool_name in CARD_PLAN_TOOL_NAMES:
            if audience_session is None:
                return _rpc_error(request_id, -32602, "Unknown tool")
            try:
                result = call_card_plan_tool(
                    service,
                    tool_name=str(tool_name),
                    arguments=arguments,
                    audience_session=audience_session,
                )
            except McpCardPlanToolInputError:
                return _rpc_error(
                    request_id, -32602, "Invalid card plan tool arguments"
                )
            except CardServiceError as error:
                return _response(request_id, result=_tool_error(error))
            except Exception:
                return _response(request_id, result=_tool_error())
            return _response(request_id, result=result)
        if tool_name in CANDIDATE_TOOL_NAMES:
            if audience_session is None:
                return _rpc_error(request_id, -32602, "Unknown tool")
            try:
                result = call_candidate_tool(
                    service,
                    tool_name=str(tool_name),
                    arguments=arguments,
                    audience_session=audience_session,
                )
            except McpCandidateToolInputError:
                return _rpc_error(request_id, -32602, "Invalid candidate tool arguments")
            except CardServiceError as error:
                return _response(request_id, result=_tool_error(error))
            except Exception:
                return _response(request_id, result=_tool_error())
            return _response(request_id, result=result)
        if tool_name != CAPABILITY_TOOL_NAME:
            return _rpc_error(request_id, -32602, "Unknown tool")
        if not isinstance(arguments, dict) or arguments:
            return _rpc_error(request_id, -32602, "Tool arguments must be an empty object")
        try:
            capabilities = service.dispatch("system.get_capabilities", {})
        except CardServiceError as error:
            return _response(request_id, result=_tool_error(error))
        except Exception:
            return _response(request_id, result=_tool_error())
        structured = {
            "schemaVersion": 1,
            "mcpBridge": {
                "transport": "stdio",
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "exposedTools": [
                    definition["name"]
                    for definition in _tool_definitions(audience_session)
                ],
                "audienceBinding": (
                    audience_session.public_summary()
                    if audience_session is not None
                    else {"schemaVersion": 1, "available": False, "identifiersDisclosed": False}
                ),
            },
            "cardService": capabilities,
        }
        return _response(
            request_id,
            result={
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "The local Card Service capability snapshot is available. "
                            "Deterministic source inspection, authenticated candidate review, and local "
                            "portfolio selection are available. Starting candidate discovery, generation, "
                            "and Anki delivery "
                            "remain disabled at this milestone."
                        ),
                    }
                ],
                "structuredContent": structured,
            },
        )

    if request_id is None:
        return None
    return _rpc_error(request_id, -32601, "Method not found")


def serve(
    service: CardService,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    *,
    audience_session: TrustedMcpAudienceSession | None = None,
    user_action_timeout_seconds: float = 300.0,
) -> None:
    source = input_stream or sys.stdin
    sink = output_stream or sys.stdout
    for raw_line in source:
        if not raw_line.strip():
            continue
        try:
            request = json.loads(raw_line)
        except (TypeError, ValueError):
            response = _rpc_error(None, -32700, "Parse error")
        else:
            if not isinstance(request, dict):
                response = _rpc_error(None, -32600, "Invalid Request")
            else:
                response = _handle_request(
                    service,
                    request,
                    audience_session,
                    user_action_timeout_seconds,
                )
        if response is not None:
            sink.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sink.flush()


def main() -> None:
    parser = build_parser("Codex Study MCP bridge for the local Card Service")
    arguments = parser.parse_args()
    service = create_service(arguments, parser)
    try:
        if arguments.runtime_package is not None:
            audience_session = create_packaged_mcp_audience(service.runtime_package.root)
        elif arguments.development_trusted_mcp_session:
            audience_session = create_development_mcp_audience()
        else:
            audience_session = None
    except TrustedMcpAudienceError as error:
        parser.error(f"{error.code}: trusted MCP launch proof is unavailable")
    serve(service, audience_session=audience_session)


if __name__ == "__main__":
    main()
