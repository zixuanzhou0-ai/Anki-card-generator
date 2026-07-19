"""Closed MCP adapters for deterministic CardPlan creation and review."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


PLAN_CARDS_TOOL_NAME = "study.plan_cards"
LIST_CARD_PLANS_TOOL_NAME = "study.list_card_plans"
CARD_PLAN_TOOL_NAMES = frozenset({PLAN_CARDS_TOOL_NAME, LIST_CARD_PLANS_TOOL_NAME})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_CURSOR_RE = re.compile(r"^study_plan_cursor_[A-Za-z0-9_-]{80,1800}$")


class McpCardPlanToolInputError(ValueError):
    pass


def _handle_schema() -> dict[str, Any]:
    return {"type": "string", "pattern": r"^study_[A-Za-z0-9_-]{43}$"}


def card_plan_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": PLAN_CARDS_TOOL_NAME,
            "title": "Plan reliable study cards",
            "description": (
                "Create deterministic CardPlans from the exact current authenticated selection. "
                "The service revalidates eligibility and supports only production, chunk/collocation, "
                "and reading-recognition plans that need no translation, media, or new model inference. "
                "At most 100 plans run synchronously; larger selections require the future asynchronous planner. Unsupported routes fail closed instead of becoming generic question-answer cards."
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
                    "selectionHandle": _handle_schema(),
                },
                "required": ["context", "selectionHandle"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "projectId": {"type": "string"},
                    "projectRevision": {"type": "integer", "minimum": 1},
                    "artifactStage": {"type": "string", "const": "plans_ready"},
                    "taskId": {"type": "string"},
                    "planSetHandle": _handle_schema(),
                    "validationHandle": _handle_schema(),
                    "totalPlans": {"type": "integer", "minimum": 1, "maximum": 100},
                    "eligiblePlans": {"type": "integer", "minimum": 0},
                    "blockedPlans": {"type": "integer", "minimum": 0},
                    "issueCodes": {"type": "array", "items": {"type": "string"}},
                    "nextAction": {
                        "type": "string",
                        "enum": ["generate_cards", "review_card_plans"],
                    },
                },
                "required": [
                    "schemaVersion",
                    "projectId",
                    "projectRevision",
                    "artifactStage",
                    "taskId",
                    "planSetHandle",
                    "validationHandle",
                    "totalPlans",
                    "eligiblePlans",
                    "blockedPlans",
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
        },
        {
            "name": LIST_CARD_PLANS_TOOL_NAME,
            "title": "Review authenticated card plans",
            "description": (
                "Read a bounded page of learner-facing card plans and all eight deterministic "
                "validation states. The response omits source paths, internal ArtifactRefs, "
                "authorization records, model data, and credentials."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "planSetHandle": _handle_schema(),
                    "cursor": {
                        "type": "string",
                        "pattern": r"^study_plan_cursor_[A-Za-z0-9_-]+$",
                        "maxLength": 1818,
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["planSetHandle"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "projectId": {"type": "string"},
                    "projectRevision": {"type": "integer", "minimum": 1},
                    "artifactStage": {"type": "string"},
                    "planSetHandle": _handle_schema(),
                    "totalPlans": {"type": "integer", "minimum": 1},
                    "returnedPlans": {"type": "integer", "minimum": 0},
                    "eligiblePlans": {"type": "integer", "minimum": 0},
                    "blockedPlans": {"type": "integer", "minimum": 0},
                    "items": {"type": "array", "items": {"type": "object"}},
                    "nextCursor": {
                        "oneOf": [
                            {
                                "type": "string",
                                "pattern": r"^study_plan_cursor_[A-Za-z0-9_-]+$",
                            },
                            {"type": "null"},
                        ]
                    },
                    "nextAction": {
                        "type": "string",
                        "enum": ["generate_cards", "review_card_plans"],
                    },
                },
                "required": [
                    "schemaVersion",
                    "projectId",
                    "projectRevision",
                    "artifactStage",
                    "planSetHandle",
                    "totalPlans",
                    "returnedPlans",
                    "eligiblePlans",
                    "blockedPlans",
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


def _context(arguments: Any) -> tuple[str, int, str, str]:
    if not isinstance(arguments, dict) or set(arguments) != {
        "context",
        "selectionHandle",
    }:
        raise McpCardPlanToolInputError("card planning fields are invalid")
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
        raise McpCardPlanToolInputError("card planning context is invalid")
    project_id = context.get("projectId")
    revision = context.get("expectedProjectRevision")
    key = context.get("idempotencyKey")
    locale = context.get("locale")
    selection = arguments.get("selectionHandle")
    if not isinstance(project_id, str) or not _PROJECT_RE.fullmatch(project_id):
        raise McpCardPlanToolInputError("projectId is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise McpCardPlanToolInputError("expectedProjectRevision is invalid")
    if not isinstance(key, str) or not _ID_RE.fullmatch(key):
        raise McpCardPlanToolInputError("idempotencyKey is invalid")
    if locale is not None and (
        not isinstance(locale, str) or not 2 <= len(locale) <= 32
    ):
        raise McpCardPlanToolInputError("locale is invalid")
    if not isinstance(selection, str) or not _HANDLE_RE.fullmatch(selection):
        raise McpCardPlanToolInputError("selectionHandle is invalid")
    return project_id, revision, key, selection


def _list_arguments(arguments: Any) -> tuple[str, str | None, int]:
    if (
        not isinstance(arguments, dict)
        or "planSetHandle" not in arguments
        or not set(arguments).issubset({"planSetHandle", "cursor", "limit"})
    ):
        raise McpCardPlanToolInputError("card plan list fields are invalid")
    handle = arguments.get("planSetHandle")
    cursor = arguments.get("cursor")
    limit = arguments.get("limit", 20)
    if not isinstance(handle, str) or not _HANDLE_RE.fullmatch(handle):
        raise McpCardPlanToolInputError("planSetHandle is invalid")
    if cursor is not None and (
        not isinstance(cursor, str) or not _CURSOR_RE.fullmatch(cursor)
    ):
        raise McpCardPlanToolInputError("cursor is invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise McpCardPlanToolInputError("limit is invalid")
    return handle, cursor, limit


def call_card_plan_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    if tool_name == PLAN_CARDS_TOOL_NAME:
        project, revision, key, selection = _context(arguments)
        structured = service.plan_study_cards(
            audience=audience_session.audience,
            project_id=project,
            expected_project_revision=revision,
            idempotency_key=key,
            selection_handle=selection,
        )
        text = (
            f"Planned {structured['totalPlans']} card(s); "
            f"{structured['eligiblePlans']} passed every deterministic gate."
        )
    elif tool_name == LIST_CARD_PLANS_TOOL_NAME:
        plan_set, cursor, limit = _list_arguments(arguments)
        structured = service.list_study_card_plans(
            audience=audience_session.audience,
            plan_set_handle=plan_set,
            cursor=cursor,
            limit=limit,
        )
        text = (
            f"Loaded {structured['returnedPlans']} of "
            f"{structured['totalPlans']} authenticated card plan(s)."
        )
    else:
        raise McpCardPlanToolInputError("Unknown card plan tool")
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }


__all__ = [
    "CARD_PLAN_TOOL_NAMES",
    "LIST_CARD_PLANS_TOOL_NAME",
    "McpCardPlanToolInputError",
    "PLAN_CARDS_TOOL_NAME",
    "call_card_plan_tool",
    "card_plan_tool_definitions",
]
