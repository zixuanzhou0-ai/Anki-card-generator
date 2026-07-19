"""Closed MCP adapters for deterministic source inspection."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


START_SOURCE_INSPECTION_TOOL_NAME = "study.start_source_inspection"
GET_SOURCE_INSPECTION_TOOL_NAME = "study.get_source_inspection"
INSPECTION_TOOL_NAMES = frozenset(
    {START_SOURCE_INSPECTION_TOOL_NAME, GET_SOURCE_INSPECTION_TOOL_NAME}
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")


class McpInspectionToolInputError(ValueError):
    pass


def _inspection_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "projectId": {"type": "string"},
            "projectRevision": {"type": "integer", "minimum": 1},
            "artifactStage": {"type": "string", "const": "sources_ready"},
            "taskId": {"type": "string"},
            "inspectionHandle": {
                "type": "string",
                "pattern": r"^study_[A-Za-z0-9_-]{43}$",
            },
            "completeness": {"type": "object"},
            "sources": {"type": "array", "items": {"type": "object"}},
            "nextAction": {
                "type": "string",
                "enum": ["discover_candidates", "resolve_issue"],
            },
        },
        "required": [
            "schemaVersion",
            "projectId",
            "projectRevision",
            "artifactStage",
            "taskId",
            "inspectionHandle",
            "completeness",
            "sources",
            "nextAction",
        ],
        "additionalProperties": False,
    }


def inspection_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": START_SOURCE_INSPECTION_TOOL_NAME,
            "title": "Inspect registered study sources",
            "description": (
                "Deterministically inspect authenticated SourceAssets and publish coverage, "
                "structured content nodes, support tiers, and explicit omissions. This does "
                "not call a model or access the network."
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
                    "sourceHandles": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "pattern": r"^study_[A-Za-z0-9_-]{43}$",
                        },
                        "minItems": 1,
                        "maxItems": 64,
                        "uniqueItems": True,
                    },
                },
                "required": ["context", "sourceHandles"],
                "additionalProperties": False,
            },
            "outputSchema": _inspection_output_schema(),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": GET_SOURCE_INSPECTION_TOOL_NAME,
            "title": "Read a source inspection",
            "description": (
                "Read an existing authenticated InspectionArtifact. This never starts parsing "
                "and never returns source text, absolute paths, or private staging details."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "inspectionHandle": {
                        "type": "string",
                        "pattern": r"^study_[A-Za-z0-9_-]{43}$",
                    }
                },
                "required": ["inspectionHandle"],
                "additionalProperties": False,
            },
            "outputSchema": _inspection_output_schema(),
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
    ]


def _start_arguments(arguments: Any) -> tuple[str, int, str, list[str]]:
    if not isinstance(arguments, dict) or set(arguments) != {
        "context",
        "sourceHandles",
    }:
        raise McpInspectionToolInputError("source inspection fields are invalid")
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
        raise McpInspectionToolInputError("source inspection context is invalid")
    project_id = context.get("projectId")
    revision = context.get("expectedProjectRevision")
    idempotency_key = context.get("idempotencyKey")
    locale = context.get("locale")
    if not isinstance(project_id, str) or not _PROJECT_RE.fullmatch(project_id):
        raise McpInspectionToolInputError("projectId is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise McpInspectionToolInputError("expectedProjectRevision is invalid")
    if not isinstance(idempotency_key, str) or not _ID_RE.fullmatch(idempotency_key):
        raise McpInspectionToolInputError("idempotencyKey is invalid")
    if locale is not None and (
        not isinstance(locale, str) or not 2 <= len(locale) <= 32
    ):
        raise McpInspectionToolInputError("locale is invalid")
    handles = arguments.get("sourceHandles")
    if (
        not isinstance(handles, list)
        or not 1 <= len(handles) <= 64
        or any(
            not isinstance(value, str) or not _HANDLE_RE.fullmatch(value)
            for value in handles
        )
        or len(handles) != len(set(handles))
    ):
        raise McpInspectionToolInputError("sourceHandles are invalid")
    return project_id, revision, idempotency_key, list(handles)


def _get_arguments(arguments: Any) -> str:
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"inspectionHandle"}
        or not isinstance(arguments.get("inspectionHandle"), str)
        or not _HANDLE_RE.fullmatch(arguments["inspectionHandle"])
    ):
        raise McpInspectionToolInputError("inspectionHandle is invalid")
    return arguments["inspectionHandle"]


def call_inspection_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    if tool_name == START_SOURCE_INSPECTION_TOOL_NAME:
        project_id, revision, key, handles = _start_arguments(arguments)
        structured = service.inspect_study_sources(
            audience=audience_session.audience,
            project_id=project_id,
            expected_project_revision=revision,
            idempotency_key=key,
            source_handles=handles,
        )
        text = (
            f"Inspected {structured['completeness']['processedSources']} of "
            f"{structured['completeness']['expectedSources']} registered source(s). "
            "Coverage and omissions are explicit; no model was called."
        )
    elif tool_name == GET_SOURCE_INSPECTION_TOOL_NAME:
        inspection_handle = _get_arguments(arguments)
        structured = service.get_study_source_inspection(
            audience=audience_session.audience,
            inspection_handle=inspection_handle,
        )
        text = "Loaded the existing authenticated source inspection. No parsing was started."
    else:
        raise McpInspectionToolInputError("Unknown inspection tool")
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }


__all__ = [
    "GET_SOURCE_INSPECTION_TOOL_NAME",
    "INSPECTION_TOOL_NAMES",
    "McpInspectionToolInputError",
    "START_SOURCE_INSPECTION_TOOL_NAME",
    "call_inspection_tool",
    "inspection_tool_definitions",
]
