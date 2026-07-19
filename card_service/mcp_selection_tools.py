"""Closed MCP adapter for deterministic candidate portfolio selection."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


SET_SELECTION_TOOL_NAME = "study.set_selection"
SELECTION_TOOL_NAMES = frozenset({SET_SELECTION_TOOL_NAME})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_OPERATIONS = frozenset({"add", "remove", "accept_recommended"})


class McpSelectionToolInputError(ValueError):
    pass


def _handle_schema() -> dict[str, Any]:
    return {"type": "string", "pattern": r"^study_[A-Za-z0-9_-]{43}$"}


def selection_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": SET_SELECTION_TOOL_NAME,
            "title": "Save a reliable learning portfolio",
            "description": (
                "Add or remove exact authenticated candidates, or deterministically accept "
                "recommended candidates using coverage-first portfolio selection. Hard-blocked, "
                "excluded, duplicate, stale, cross-discovery, and over-budget candidates are "
                "rejected. This writes only local authenticated state and never calls a model, "
                "TTS, network service, or Anki."
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
                    "discoveryHandle": _handle_schema(),
                    "operation": {
                        "type": "string",
                        "enum": sorted(_OPERATIONS),
                    },
                    "candidateHandles": {
                        "type": "array",
                        "items": _handle_schema(),
                        "maxItems": 1000,
                        "uniqueItems": True,
                    },
                    "budget": {
                        "type": "object",
                        "properties": {
                            "maxNewCards": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 1000,
                            },
                            "targetDailyReviewMinutes": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 1440,
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["context", "discoveryHandle", "operation"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "projectId": {"type": "string"},
                    "projectRevision": {"type": "integer", "minimum": 1},
                    "artifactStage": {"type": "string", "const": "selection_ready"},
                    "taskId": {"type": "string"},
                    "selectionHandle": _handle_schema(),
                    "selectedCount": {"type": "integer", "minimum": 1},
                    "budget": {"type": "object"},
                    "coverage": {"type": "array", "items": {"type": "object"}},
                    "redundancyWarnings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "estimatedReviewDebt": {"type": "object"},
                    "issueCodes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "nextAction": {"type": "string", "const": "plan_cards"},
                },
                "required": [
                    "schemaVersion",
                    "projectId",
                    "projectRevision",
                    "artifactStage",
                    "taskId",
                    "selectionHandle",
                    "selectedCount",
                    "budget",
                    "coverage",
                    "redundancyWarnings",
                    "estimatedReviewDebt",
                    "issueCodes",
                    "nextAction",
                ],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        }
    ]


def _arguments(
    arguments: Any,
) -> tuple[str, int, str, str, str, list[str] | None, dict[str, int] | None]:
    if (
        not isinstance(arguments, dict)
        or not {"context", "discoveryHandle", "operation"}.issubset(arguments)
        or not set(arguments).issubset(
            {
                "context",
                "discoveryHandle",
                "operation",
                "candidateHandles",
                "budget",
            }
        )
    ):
        raise McpSelectionToolInputError("selection fields are invalid")
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
        raise McpSelectionToolInputError("selection context is invalid")
    project_id = context.get("projectId")
    revision = context.get("expectedProjectRevision")
    key = context.get("idempotencyKey")
    locale = context.get("locale")
    if not isinstance(project_id, str) or not _PROJECT_RE.fullmatch(project_id):
        raise McpSelectionToolInputError("projectId is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise McpSelectionToolInputError("expectedProjectRevision is invalid")
    if not isinstance(key, str) or not _ID_RE.fullmatch(key):
        raise McpSelectionToolInputError("idempotencyKey is invalid")
    if locale is not None and (
        not isinstance(locale, str) or not 2 <= len(locale) <= 32
    ):
        raise McpSelectionToolInputError("locale is invalid")
    discovery = arguments.get("discoveryHandle")
    if not isinstance(discovery, str) or not _HANDLE_RE.fullmatch(discovery):
        raise McpSelectionToolInputError("discoveryHandle is invalid")
    operation = arguments.get("operation")
    if operation not in _OPERATIONS:
        raise McpSelectionToolInputError("selection operation is invalid")
    handles = arguments.get("candidateHandles")
    if handles is not None and (
        not isinstance(handles, list)
        or len(handles) > 1000
        or any(
            not isinstance(value, str) or not _HANDLE_RE.fullmatch(value)
            for value in handles
        )
        or len(handles) != len(set(handles))
    ):
        raise McpSelectionToolInputError("candidateHandles are invalid")
    if operation in {"add", "remove"} and not handles:
        raise McpSelectionToolInputError("this operation requires candidateHandles")
    if operation == "accept_recommended" and handles:
        raise McpSelectionToolInputError(
            "accept_recommended does not accept candidateHandles"
        )
    budget = arguments.get("budget")
    if budget is not None:
        if not isinstance(budget, dict) or not set(budget).issubset(
            {"maxNewCards", "targetDailyReviewMinutes"}
        ):
            raise McpSelectionToolInputError("selection budget is invalid")
        maximum = budget.get("maxNewCards")
        daily = budget.get("targetDailyReviewMinutes")
        if maximum is not None and (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or not 1 <= maximum <= 1000
        ):
            raise McpSelectionToolInputError("maxNewCards is invalid")
        if daily is not None and (
            isinstance(daily, bool)
            or not isinstance(daily, int)
            or not 1 <= daily <= 1440
        ):
            raise McpSelectionToolInputError("targetDailyReviewMinutes is invalid")
        budget = dict(budget)
    return project_id, revision, key, discovery, operation, handles, budget


def call_selection_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    if tool_name != SET_SELECTION_TOOL_NAME:
        raise McpSelectionToolInputError("Unknown selection tool")
    project, revision, key, discovery, operation, handles, budget = _arguments(
        arguments
    )
    structured = service.set_study_selection(
        audience=audience_session.audience,
        project_id=project,
        expected_project_revision=revision,
        idempotency_key=key,
        discovery_handle=discovery,
        operation=operation,
        candidate_handles=handles,
        budget=budget,
    )
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Saved {structured['selectedCount']} candidate(s) in a reliable "
                    "local learning portfolio."
                ),
            }
        ],
        "structuredContent": structured,
    }


__all__ = [
    "McpSelectionToolInputError",
    "SELECTION_TOOL_NAMES",
    "SET_SELECTION_TOOL_NAME",
    "call_selection_tool",
    "selection_tool_definitions",
]
