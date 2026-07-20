"""Closed public MCP adapter for trusted Study input registration."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


REGISTER_INPUTS_TOOL_NAME = "study.register_inputs"
INPUT_TOOL_NAMES = frozenset({REGISTER_INPUTS_TOOL_NAME})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_RESOURCE_REF_RE = re.compile(r"^resource_[A-Za-z0-9_-]{43}$")
_NETWORK_REF_RE = re.compile(r"^network_[A-Za-z0-9_-]{43}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class McpInputToolInputError(ValueError):
    pass


def _input_ref_schema(kind: str) -> dict[str, Any]:
    reference = "fileResourceRef" if kind == "file" else "directoryResourceRef"
    constraints = (
        {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["read"]},
                    "const": ["read"],
                },
                "maxBytes": {"type": "integer", "minimum": 1},
            },
            "required": ["actions", "maxBytes"],
            "additionalProperties": False,
        }
        if kind == "file"
        else {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["enumerate", "read"]},
                    "const": ["enumerate", "read"],
                },
                "maxDepth": {"type": "integer", "minimum": 1},
                "maxEntries": {"type": "integer", "minimum": 1},
                "maxTotalBytes": {"type": "integer", "minimum": 1},
            },
            "required": ["actions", "maxDepth", "maxEntries", "maxTotalBytes"],
            "additionalProperties": False,
        }
    )
    return {
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "kind": {"type": "string", "const": kind},
            reference: {
                "type": "string",
                "pattern": r"^resource_[A-Za-z0-9_-]{43}$",
            },
            "displayName": {"type": "string", "minLength": 1, "maxLength": 160},
            "resourceRevisionDigest": {
                "type": "string",
                "pattern": r"^[0-9a-f]{64}$",
            },
            "constraints": constraints,
            "expiresAt": {"type": "string", "minLength": 1, "maxLength": 64},
        },
        "required": [
            "schemaVersion",
            "kind",
            reference,
            "displayName",
            "resourceRevisionDigest",
            "constraints",
            "expiresAt",
        ],
        "additionalProperties": False,
    }


def _network_input_ref_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "kind": {"type": "string", "const": "url"},
            "networkResourceRef": {
                "type": "string",
                "pattern": r"^network_[A-Za-z0-9_-]{43}$",
            },
            "displayOrigin": {"type": "string", "minLength": 9, "maxLength": 300},
            "sourceKind": {
                "type": "string",
                "enum": ["public_video", "web", "podcast"],
            },
            "adapter": {
                "type": "string",
                "enum": ["youtube", "generic_https"],
            },
            "publicIdentity": {
                "anyOf": [
                    {"type": "string", "minLength": 1, "maxLength": 300},
                    {"type": "null"},
                ]
            },
            "queryPresent": {"type": "boolean"},
            "sensitiveQuery": {"type": "boolean"},
            "resourceRevisionDigest": {
                "type": "string",
                "pattern": r"^[0-9a-f]{64}$",
            },
            "constraints": {
                "type": "object",
                "properties": {
                    "actions": {"type": "array", "const": ["fetch"]},
                    "methods": {"type": "array", "const": ["GET"]},
                    "maxResponseBytes": {"type": "integer", "minimum": 1},
                    "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 60},
                    "redirectPolicy": {
                        "type": "string",
                        "enum": ["none", "same_origin"],
                    },
                    "maxRedirects": {"type": "integer", "minimum": 0, "maximum": 5},
                },
                "required": [
                    "actions",
                    "methods",
                    "maxResponseBytes",
                    "timeoutSeconds",
                    "redirectPolicy",
                    "maxRedirects",
                ],
                "additionalProperties": False,
            },
            "expiresAt": {"type": "string", "minLength": 1, "maxLength": 64},
        },
        "required": [
            "schemaVersion",
            "kind",
            "networkResourceRef",
            "displayOrigin",
            "sourceKind",
            "adapter",
            "publicIdentity",
            "queryPresent",
            "sensitiveQuery",
            "resourceRevisionDigest",
            "constraints",
            "expiresAt",
        ],
        "additionalProperties": False,
    }


def input_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": REGISTER_INPUTS_TOOL_NAME,
            "title": "Register trusted study sources",
            "description": (
                "Freeze one or more opaque trusted InputRefs into authenticated, "
                "content-addressed SourceAssets. Complete paths and network addresses are never accepted or returned."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context": {
                        "type": "object",
                        "properties": {
                            "projectId": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 256,
                            },
                            "expectedProjectRevision": {
                                "type": "integer",
                                "minimum": 1,
                            },
                            "idempotencyKey": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 160,
                            },
                            "locale": {
                                "type": "string",
                                "minLength": 2,
                                "maxLength": 32,
                            },
                        },
                        "required": [
                            "projectId",
                            "expectedProjectRevision",
                            "idempotencyKey",
                        ],
                        "additionalProperties": False,
                    },
                    "inputRefs": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                _input_ref_schema("file"),
                                _input_ref_schema("directory"),
                                _network_input_ref_schema(),
                            ]
                        },
                        "minItems": 1,
                        "maxItems": 64,
                    },
                    "snapshotPolicy": {
                        "type": "string",
                        "enum": ["require_stable", "allow_conditional", "draft_only"],
                        "default": "require_stable",
                    },
                },
                "required": ["context", "inputRefs"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "projectId": {"type": "string"},
                    "projectRevision": {"type": "integer", "minimum": 1},
                    "artifactStage": {"type": "string", "const": "sources_ready"},
                    "taskId": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "object"}},
                    "completeness": {"type": "object"},
                },
                "required": [
                    "schemaVersion",
                    "projectId",
                    "projectRevision",
                    "artifactStage",
                    "taskId",
                    "sources",
                    "completeness",
                ],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        }
    ]


def _validated_input_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("kind") not in {
        "file",
        "directory",
        "url",
    }:
        raise McpInputToolInputError("InputRef is invalid")
    kind = value["kind"]
    if kind == "url":
        expected = {
            "schemaVersion",
            "kind",
            "networkResourceRef",
            "displayOrigin",
            "sourceKind",
            "adapter",
            "publicIdentity",
            "queryPresent",
            "sensitiveQuery",
            "resourceRevisionDigest",
            "constraints",
            "expiresAt",
        }
        constraints = value.get("constraints")
        if (
            set(value) != expected
            or value.get("schemaVersion") != 1
            or not isinstance(value.get("networkResourceRef"), str)
            or _NETWORK_REF_RE.fullmatch(value["networkResourceRef"]) is None
            or not isinstance(value.get("displayOrigin"), str)
            or not 9 <= len(value["displayOrigin"]) <= 300
            or not value["displayOrigin"].startswith("https://")
            or value.get("sourceKind")
            not in {"public_video", "web", "podcast"}
            or value.get("adapter") not in {"youtube", "generic_https"}
            or (
                value.get("publicIdentity") is not None
                and (
                    not isinstance(value["publicIdentity"], str)
                    or not 1 <= len(value["publicIdentity"]) <= 300
                )
            )
            or not isinstance(value.get("queryPresent"), bool)
            or not isinstance(value.get("sensitiveQuery"), bool)
            or not isinstance(value.get("resourceRevisionDigest"), str)
            or _SHA256_RE.fullmatch(value["resourceRevisionDigest"]) is None
            or not isinstance(constraints, dict)
            or set(constraints)
            != {
                "actions",
                "methods",
                "maxResponseBytes",
                "timeoutSeconds",
                "redirectPolicy",
                "maxRedirects",
            }
            or constraints.get("actions") != ["fetch"]
            or constraints.get("methods") != ["GET"]
            or constraints.get("redirectPolicy") not in {"none", "same_origin"}
            or any(
                isinstance(constraints.get(name), bool)
                or not isinstance(constraints.get(name), int)
                for name in (
                    "maxResponseBytes",
                    "timeoutSeconds",
                    "maxRedirects",
                )
            )
            or constraints["maxResponseBytes"] < 1
            or not 1 <= constraints["timeoutSeconds"] <= 60
            or not 0 <= constraints["maxRedirects"] <= 5
            or not isinstance(value.get("expiresAt"), str)
            or not 1 <= len(value["expiresAt"]) <= 64
        ):
            raise McpInputToolInputError("Network InputRef is invalid")
        return dict(value)
    reference = "fileResourceRef" if kind == "file" else "directoryResourceRef"
    expected = {
        "schemaVersion",
        "kind",
        reference,
        "displayName",
        "resourceRevisionDigest",
        "constraints",
        "expiresAt",
    }
    if set(value) != expected or value.get("schemaVersion") != 1:
        raise McpInputToolInputError("InputRef fields are invalid")
    if not isinstance(value.get(reference), str) or not _RESOURCE_REF_RE.fullmatch(
        value[reference]
    ):
        raise McpInputToolInputError("InputRef resource reference is invalid")
    if (
        not isinstance(value.get("displayName"), str)
        or not value["displayName"]
        or len(value["displayName"]) > 160
        or any(ord(character) < 0x20 for character in value["displayName"])
    ):
        raise McpInputToolInputError("InputRef display name is invalid")
    if not isinstance(
        value.get("resourceRevisionDigest"), str
    ) or not _SHA256_RE.fullmatch(value["resourceRevisionDigest"]):
        raise McpInputToolInputError("InputRef revision is invalid")
    constraints = value.get("constraints")
    if not isinstance(constraints, dict):
        raise McpInputToolInputError("InputRef authorization summary is invalid")
    if kind == "file":
        valid_constraints = (
            set(constraints) == {"actions", "maxBytes"}
            and constraints.get("actions") == ["read"]
            and not isinstance(constraints.get("maxBytes"), bool)
            and isinstance(constraints.get("maxBytes"), int)
            and constraints["maxBytes"] >= 1
        )
    else:
        valid_constraints = (
            set(constraints) == {"actions", "maxDepth", "maxEntries", "maxTotalBytes"}
            and constraints.get("actions") == ["enumerate", "read"]
            and all(
                not isinstance(constraints.get(name), bool)
                and isinstance(constraints.get(name), int)
                and constraints[name] >= 1
                for name in ("maxDepth", "maxEntries", "maxTotalBytes")
            )
        )
    expires_at = value.get("expiresAt")
    if (
        not valid_constraints
        or not isinstance(expires_at, str)
        or not 1 <= len(expires_at) <= 64
    ):
        raise McpInputToolInputError("InputRef authorization summary is invalid")
    return dict(value)


def _validated_arguments(
    arguments: Any,
) -> tuple[str, int, str, list[dict[str, Any]], str]:
    if (
        not isinstance(arguments, dict)
        or not {"context", "inputRefs"}.issubset(arguments)
        or not set(arguments).issubset({"context", "inputRefs", "snapshotPolicy"})
    ):
        raise McpInputToolInputError("Input registration fields are invalid")
    context = arguments.get("context")
    if (
        not isinstance(context, dict)
        or not {"projectId", "expectedProjectRevision", "idempotencyKey"}.issubset(
            context
        )
        or not set(context).issubset(
            {"projectId", "expectedProjectRevision", "idempotencyKey", "locale"}
        )
    ):
        raise McpInputToolInputError("Input registration context is invalid")
    project_id = context.get("projectId")
    revision = context.get("expectedProjectRevision")
    idempotency_key = context.get("idempotencyKey")
    if not isinstance(project_id, str) or not _PROJECT_RE.fullmatch(project_id):
        raise McpInputToolInputError("projectId is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise McpInputToolInputError("expectedProjectRevision is invalid")
    if not isinstance(idempotency_key, str) or not _ID_RE.fullmatch(idempotency_key):
        raise McpInputToolInputError("idempotencyKey is invalid")
    locale = context.get("locale")
    if locale is not None and (
        not isinstance(locale, str) or not 2 <= len(locale) <= 32
    ):
        raise McpInputToolInputError("locale is invalid")
    values = arguments.get("inputRefs")
    if not isinstance(values, list) or not 1 <= len(values) <= 64:
        raise McpInputToolInputError("inputRefs count is invalid")
    input_refs = [_validated_input_ref(value) for value in values]
    snapshot_policy = arguments.get("snapshotPolicy", "require_stable")
    if snapshot_policy not in {"require_stable", "allow_conditional", "draft_only"}:
        raise McpInputToolInputError("snapshotPolicy is invalid")
    return project_id, revision, idempotency_key, input_refs, snapshot_policy


def call_input_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    if tool_name != REGISTER_INPUTS_TOOL_NAME:
        raise McpInputToolInputError("Unknown input tool")
    project_id, revision, key, input_refs, policy = _validated_arguments(arguments)
    structured = service.register_study_inputs(
        audience=audience_session.audience,
        project_id=project_id,
        expected_project_revision=revision,
        idempotency_key=key,
        input_refs=input_refs,
        snapshot_policy=policy,
    )
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Registered {len(structured['sources'])} trusted source snapshot(s). "
                    "The source bytes are frozen; content inspection has not run yet."
                ),
            }
        ],
        "structuredContent": structured,
    }


__all__ = [
    "INPUT_TOOL_NAMES",
    "McpInputToolInputError",
    "REGISTER_INPUTS_TOOL_NAME",
    "call_input_tool",
    "input_tool_definitions",
]
