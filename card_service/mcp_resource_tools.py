from __future__ import annotations

import re
import time
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


SOURCE_GRANT_TOOL_NAME = "system.request_source_grant"
OUTPUT_GRANT_TOOL_NAME = "system.request_output_grant"
NETWORK_GRANT_TOOL_NAME = "system.request_network_grant"
RESOURCE_GRANT_TOOL_NAMES = (
    SOURCE_GRANT_TOOL_NAME,
    OUTPUT_GRANT_TOOL_NAME,
    NETWORK_GRANT_TOOL_NAME,
)
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RESOURCE_REF_RE = re.compile(r"^resource_[A-Za-z0-9_-]{43}$")
_NETWORK_REF_RE = re.compile(r"^network_[A-Za-z0-9_-]{43}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class McpResourceToolInputError(ValueError):
    pass


def _result_schema(ref_name: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "state": {
                "type": "string",
                "enum": ["awaiting_user", "selected", "cancelled", "failed"],
            },
            ref_name: {"type": "object"},
            "error": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
                "additionalProperties": False,
            },
        },
        "required": ["schemaVersion", "state"],
        "additionalProperties": False,
    }


def resource_tool_definitions() -> list[dict[str, Any]]:
    request_id = {
        "type": "string",
        "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        "maxLength": 128,
    }
    shared_annotations = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    return [
        {
            "name": SOURCE_GRANT_TOOL_NAME,
            "title": "Choose an Anki study source",
            "description": (
                "Open the trusted local picker for one file or input folder. "
                "Never accepts or returns an absolute path."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "grantRequestId": request_id,
                    "selectionKind": {
                        "type": "string",
                        "enum": ["file", "directory"],
                    },
                },
                "required": ["grantRequestId", "selectionKind"],
                "additionalProperties": False,
            },
            "outputSchema": _result_schema("inputRef"),
            "annotations": dict(shared_annotations),
        },
        {
            "name": OUTPUT_GRANT_TOOL_NAME,
            "title": "Choose an APKG output folder",
            "description": (
                "Open the trusted local picker for an output folder. "
                "The default grant permits create/versioned output and never replace."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"grantRequestId": request_id},
                "required": ["grantRequestId"],
                "additionalProperties": False,
            },
            "outputSchema": _result_schema("outputRef"),
            "annotations": dict(shared_annotations),
        },
        {
            "name": NETWORK_GRANT_TOOL_NAME,
            "title": "Add a trusted network study source",
            "description": (
                "Open a trusted local URL entry window. The tool never accepts or returns "
                "the entered address, path, query, header, cookie, or credential."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "grantRequestId": request_id,
                    "kind": {"type": "string", "const": "trusted_entry"},
                    "sourceKind": {
                        "type": "string",
                        "enum": ["public_video", "web", "podcast", "other"],
                    },
                },
                "required": ["grantRequestId", "kind", "sourceKind"],
                "additionalProperties": False,
            },
            "outputSchema": _result_schema("inputRef"),
            "annotations": {
                **shared_annotations,
                "openWorldHint": True,
            },
        },
    ]


def _validated_request(
    tool_name: str, arguments: Any
) -> tuple[str, str]:
    if not isinstance(arguments, dict):
        raise McpResourceToolInputError("Tool arguments must be an object")
    expected = {
        SOURCE_GRANT_TOOL_NAME: {"grantRequestId", "selectionKind"},
        OUTPUT_GRANT_TOOL_NAME: {"grantRequestId"},
        NETWORK_GRANT_TOOL_NAME: {
            "grantRequestId",
            "kind",
            "sourceKind",
        },
    }[tool_name]
    if set(arguments) != expected:
        raise McpResourceToolInputError("Tool arguments do not match the closed schema")
    request_id = arguments.get("grantRequestId")
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise McpResourceToolInputError("grantRequestId is invalid")
    if tool_name == SOURCE_GRANT_TOOL_NAME:
        kind = arguments.get("selectionKind")
        if kind not in {"file", "directory"}:
            raise McpResourceToolInputError("selectionKind is invalid")
        return request_id, str(kind)
    if tool_name == NETWORK_GRANT_TOOL_NAME:
        if arguments.get("kind") != "trusted_entry" or arguments.get(
            "sourceKind"
        ) not in {"public_video", "web", "podcast", "other"}:
            raise McpResourceToolInputError("network source kind is invalid")
        return request_id, str(arguments["sourceKind"])
    return request_id, "output_directory"


def _public_result(
    tool_name: str,
    result: dict[str, Any],
    *,
    expected_kind: str,
    expected_constraints: dict[str, Any],
) -> dict[str, Any]:
    state = result.get("state")
    if state in {"created", "open"}:
        return {"schemaVersion": 1, "state": "awaiting_user"}
    if state == "cancelled":
        return {"schemaVersion": 1, "state": "cancelled"}
    if tool_name == NETWORK_GRANT_TOOL_NAME:
        grant = result.get("networkGrant")
        if (
            state != "selected"
            or not isinstance(grant, dict)
            or grant.get("sourceKind") != expected_kind
            or not isinstance(grant.get("networkResourceRef"), str)
            or _NETWORK_REF_RE.fullmatch(grant["networkResourceRef"]) is None
            or not isinstance(grant.get("displayOrigin"), str)
            or not grant["displayOrigin"].startswith("https://")
            or grant.get("adapter") not in {"youtube", "generic_https"}
            or not isinstance(grant.get("resourceRevisionDigest"), str)
            or _SHA256_RE.fullmatch(grant["resourceRevisionDigest"]) is None
            or not isinstance(grant.get("constraints"), dict)
            or not isinstance(grant.get("expiresAt"), str)
            or not isinstance(grant.get("queryPresent"), bool)
            or not isinstance(grant.get("sensitiveQuery"), bool)
        ):
            return {
                "schemaVersion": 1,
                "state": "failed",
                "error": {
                    "code": str(result.get("errorCode") or "NETWORK_GRANT_INVALID")
                },
            }
        return {
            "schemaVersion": 1,
            "state": "selected",
            "inputRef": {
                "schemaVersion": 1,
                "kind": "url",
                "networkResourceRef": grant["networkResourceRef"],
                "displayOrigin": grant["displayOrigin"],
                "sourceKind": grant["sourceKind"],
                "adapter": grant["adapter"],
                "publicIdentity": grant.get("publicIdentity"),
                "queryPresent": grant["queryPresent"],
                "sensitiveQuery": grant["sensitiveQuery"],
                "resourceRevisionDigest": grant["resourceRevisionDigest"],
                "constraints": dict(grant["constraints"]),
                "expiresAt": grant["expiresAt"],
            },
        }
    if state != "selected" or not isinstance(result.get("resourceGrant"), dict):
        return {
            "schemaVersion": 1,
            "state": "failed",
            "error": {"code": "RESOURCE_SELECTION_FAILED"},
        }
    grant = result["resourceGrant"]
    selected_kind = (
        str(result.get("resourceSelection", {}).get("kind") or "")
        if isinstance(result.get("resourceSelection"), dict)
        else ""
    )
    if (
        expected_kind != selected_kind
        or selected_kind != str(grant.get("kind") or "")
        or not isinstance(grant.get("resourceRef"), str)
        or not _RESOURCE_REF_RE.fullmatch(grant["resourceRef"])
        or grant.get("constraints") != expected_constraints
        or not isinstance(grant.get("resourceRevisionDigest"), str)
        or not _SHA256_RE.fullmatch(grant["resourceRevisionDigest"])
        or not isinstance(grant.get("expiresAt"), str)
    ):
        return {
            "schemaVersion": 1,
            "state": "failed",
            "error": {"code": "RESOURCE_GRANT_INVALID"},
        }
    common = {
        "schemaVersion": 1,
        "displayName": str(grant.get("displayName") or "Selected resource")[:160],
        "resourceRevisionDigest": grant["resourceRevisionDigest"],
        "constraints": dict(expected_constraints),
        "expiresAt": grant["expiresAt"],
    }
    if tool_name == SOURCE_GRANT_TOOL_NAME and expected_kind in {"file", "directory"}:
        field = "fileResourceRef" if expected_kind == "file" else "directoryResourceRef"
        return {
            "schemaVersion": 1,
            "state": "selected",
            "inputRef": {
                **common,
                "kind": expected_kind,
                field: grant["resourceRef"],
            },
        }
    if tool_name == OUTPUT_GRANT_TOOL_NAME and expected_kind == "output_directory":
        return {
            "schemaVersion": 1,
            "state": "selected",
            "outputRef": {
                **common,
                "kind": "output_directory",
                "outputResourceRef": grant["resourceRef"],
            },
        }
    return {
        "schemaVersion": 1,
        "state": "failed",
        "error": {"code": "RESOURCE_GRANT_KIND_MISMATCH"},
    }


def call_resource_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
    user_action_timeout_seconds: float,
) -> dict[str, Any]:
    if tool_name not in RESOURCE_GRANT_TOOL_NAMES:
        raise McpResourceToolInputError("Unknown resource tool")
    request_id, kind = _validated_request(tool_name, arguments)
    deadline = time.monotonic() + max(0.0, float(user_action_timeout_seconds))
    expected_constraints = (
        {}
        if tool_name == NETWORK_GRANT_TOOL_NAME
        else service.public_local_resource_constraints(kind)
    )
    result = (
        service.request_network_resource_grant(
            audience=audience_session.audience,
            grant_request_id=request_id,
            source_kind=kind,
        )
        if tool_name == NETWORK_GRANT_TOOL_NAME
        else service.request_local_resource_picker(
            audience=audience_session.audience,
            grant_request_id=request_id,
            kind=kind,
        )
    )
    while result.get("state") in {"created", "open"} and time.monotonic() < deadline:
        time.sleep(0.05)
        result = (
            service.request_network_resource_grant(
                audience=audience_session.audience,
                grant_request_id=request_id,
                source_kind=kind,
            )
            if tool_name == NETWORK_GRANT_TOOL_NAME
            else service.request_local_resource_picker(
                audience=audience_session.audience,
                grant_request_id=request_id,
                kind=kind,
            )
        )
    structured = _public_result(
        tool_name,
        result,
        expected_kind=kind,
        expected_constraints=expected_constraints,
    )
    text = {
        "awaiting_user": "The trusted local picker is waiting for the user.",
        "selected": (
            "The trusted network source is available as an opaque reference."
            if tool_name == NETWORK_GRANT_TOOL_NAME
            else "The selected local resource is available as an opaque reference."
        ),
        "cancelled": "The user cancelled the trusted local picker.",
        "failed": (
            "The trusted network resource request failed."
            if tool_name == NETWORK_GRANT_TOOL_NAME
            else "The trusted local resource request failed."
        ),
    }[str(structured["state"])]
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": structured["state"] == "failed",
    }
