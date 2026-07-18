from __future__ import annotations

import json
import re
import sys
from typing import Any, TextIO

from .service import CardService, CardServiceError
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
                    },
                    "required": ["transport", "protocolVersion", "exposedTools"],
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
                "text": "The local Card Service could not report its capabilities.",
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


def _handle_request(service: CardService, request: dict[str, Any]) -> dict[str, Any] | None:
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
                    "Start with system.get_capabilities. This M1 bridge intentionally "
                    "does not expose generation, export, import, credentials, or raw Worker commands."
                ),
            },
        )

    if method == "ping":
        return _response(request_id, result={})

    if method == "tools/list":
        return _response(request_id, result={"tools": [_tool_definition()]})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
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
                "exposedTools": [CAPABILITY_TOOL_NAME],
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
                            "Generation and Anki delivery tools remain disabled at this milestone."
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
                response = _handle_request(service, request)
        if response is not None:
            sink.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sink.flush()


def main() -> None:
    parser = build_parser("Codex Study MCP bridge for the local Card Service")
    service = create_service(parser.parse_args(), parser)
    serve(service)


if __name__ == "__main__":
    main()
