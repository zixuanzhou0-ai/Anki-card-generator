"""Closed MCP adapter for authenticated deterministic CardArtifact generation."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


GENERATE_CARDS_TOOL_NAME = "cards.generate"
LIST_CARDS_TOOL_NAME = "cards.list"
CARD_TOOL_NAMES = frozenset({GENERATE_CARDS_TOOL_NAME, LIST_CARDS_TOOL_NAME})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_CARD_CURSOR_RE = re.compile(r"^study_card_cursor_[A-Za-z0-9_.-]{80,1800}$")


class McpCardToolInputError(ValueError):
    pass


def _handle_schema() -> dict[str, Any]:
    return {"type": "string", "pattern": r"^study_[A-Za-z0-9_-]{43}$"}


def card_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": GENERATE_CARDS_TOOL_NAME,
            "title": "Generate verified study cards",
            "description": (
                "Convert the exact current authenticated CardPlan set into immutable, "
                "reviewable CardArtifacts and an export-compatible ProjectArtifact. Every "
                "plan must pass all eight gates. The current route is deterministic and "
                "text-only: it makes no model, TTS, media, network, or Anki call and fails "
                "closed when any unsupported request or review debt remains."
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
                    "planSetHandle": _handle_schema(),
                },
                "required": ["context", "planSetHandle"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "projectId": {"type": "string"},
                    "projectRevision": {"type": "integer", "minimum": 1},
                    "artifactStage": {"type": "string", "const": "cards_ready"},
                    "taskId": {"type": "string"},
                    "projectArtifactHandle": _handle_schema(),
                    "generatedCards": {"type": "integer", "minimum": 1, "maximum": 100},
                    "verifiedCards": {"type": "integer", "minimum": 1, "maximum": 100},
                    "needsReviewCards": {"type": "integer", "const": 0},
                    "hardFailedCards": {"type": "integer", "const": 0},
                    "mediaCount": {"type": "integer", "const": 0},
                    "generationMode": {
                        "type": "string",
                        "const": "deterministic_projection",
                    },
                    "nextAction": {"type": "string", "const": "export_apkg"},
                },
                "required": [
                    "schemaVersion",
                    "projectId",
                    "projectRevision",
                    "artifactStage",
                    "taskId",
                    "projectArtifactHandle",
                    "generatedCards",
                    "verifiedCards",
                    "needsReviewCards",
                    "hardFailedCards",
                    "mediaCount",
                    "generationMode",
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
        },
        {
            "name": LIST_CARDS_TOOL_NAME,
            "title": "Review generated study cards",
            "description": (
                "Read a bounded authenticated page of generated card fronts, answers, "
                "feedback, scoring boundaries, and verification state before APKG export. "
                "No source path, evidence locator, internal ArtifactRef, model data, or secret is returned."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectArtifactHandle": _handle_schema(),
                    "cursor": {
                        "type": "string",
                        "pattern": r"^study_card_cursor_[A-Za-z0-9_.-]{80,1800}$",
                        "maxLength": 1818,
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["projectArtifactHandle"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "projectId": {"type": "string"},
                    "projectRevision": {"type": "integer", "minimum": 1},
                    "artifactStage": {"type": "string"},
                    "projectArtifactHandle": _handle_schema(),
                    "totalCards": {"type": "integer", "minimum": 1},
                    "returnedCards": {"type": "integer", "minimum": 0},
                    "items": {"type": "array", "items": {"type": "object"}},
                    "nextCursor": {
                        "oneOf": [
                            {
                                "type": "string",
                                "pattern": r"^study_card_cursor_[A-Za-z0-9_.-]{80,1800}$",
                            },
                            {"type": "null"},
                        ]
                    },
                    "nextAction": {"type": "string", "const": "export_apkg"},
                },
                "required": [
                    "schemaVersion",
                    "projectId",
                    "projectRevision",
                    "artifactStage",
                    "projectArtifactHandle",
                    "totalCards",
                    "returnedCards",
                    "items",
                    "nextCursor",
                    "nextAction",
                ],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
    ]


def _arguments(value: Any) -> tuple[str, int, str, str]:
    if not isinstance(value, dict) or set(value) != {"context", "planSetHandle"}:
        raise McpCardToolInputError("card generation fields are invalid")
    context = value.get("context")
    if (
        not isinstance(context, dict)
        or not {"projectId", "expectedProjectRevision", "idempotencyKey"}.issubset(
            context
        )
        or not set(context).issubset(
            {"projectId", "expectedProjectRevision", "idempotencyKey", "locale"}
        )
    ):
        raise McpCardToolInputError("card generation context is invalid")
    project = context.get("projectId")
    revision = context.get("expectedProjectRevision")
    key = context.get("idempotencyKey")
    locale = context.get("locale")
    plan_set = value.get("planSetHandle")
    if not isinstance(project, str) or not _PROJECT_RE.fullmatch(project):
        raise McpCardToolInputError("projectId is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise McpCardToolInputError("expectedProjectRevision is invalid")
    if not isinstance(key, str) or not _ID_RE.fullmatch(key):
        raise McpCardToolInputError("idempotencyKey is invalid")
    if locale is not None and (
        not isinstance(locale, str) or not 2 <= len(locale) <= 32
    ):
        raise McpCardToolInputError("locale is invalid")
    if not isinstance(plan_set, str) or not _HANDLE_RE.fullmatch(plan_set):
        raise McpCardToolInputError("planSetHandle is invalid")
    return project, revision, key, plan_set


def _list_arguments(value: Any) -> tuple[str, str | None, int]:
    if (
        not isinstance(value, dict)
        or "projectArtifactHandle" not in value
        or not set(value).issubset({"projectArtifactHandle", "cursor", "limit"})
    ):
        raise McpCardToolInputError("card list fields are invalid")
    handle = value.get("projectArtifactHandle")
    cursor = value.get("cursor")
    limit = value.get("limit", 20)
    if not isinstance(handle, str) or not _HANDLE_RE.fullmatch(handle):
        raise McpCardToolInputError("projectArtifactHandle is invalid")
    if cursor is not None and (
        not isinstance(cursor, str) or not _CARD_CURSOR_RE.fullmatch(cursor)
    ):
        raise McpCardToolInputError("cursor is invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise McpCardToolInputError("limit is invalid")
    return handle, cursor, limit


def call_card_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    if tool_name == GENERATE_CARDS_TOOL_NAME:
        project, revision, key, plan_set = _arguments(arguments)
        structured = service.generate_study_cards(
            audience=audience_session.audience,
            project_id=project,
            expected_project_revision=revision,
            idempotency_key=key,
            plan_set_handle=plan_set,
        )
        text = (
            f"Generated and verified {structured['verifiedCards']} "
            "deterministic text card(s)."
        )
    elif tool_name == LIST_CARDS_TOOL_NAME:
        project_artifact, cursor, limit = _list_arguments(arguments)
        structured = service.list_study_generated_cards(
            audience=audience_session.audience,
            project_artifact_handle=project_artifact,
            cursor=cursor,
            limit=limit,
        )
        text = (
            f"Loaded {structured['returnedCards']} of "
            f"{structured['totalCards']} verified card(s)."
        )
    else:
        raise McpCardToolInputError("Unknown card tool")
    return {
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ],
        "structuredContent": structured,
    }


__all__ = [
    "CARD_TOOL_NAMES",
    "GENERATE_CARDS_TOOL_NAME",
    "LIST_CARDS_TOOL_NAME",
    "McpCardToolInputError",
    "call_card_tool",
    "card_tool_definitions",
]
