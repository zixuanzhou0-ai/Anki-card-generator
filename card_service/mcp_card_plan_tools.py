"""Closed MCP adapters for deterministic CardPlan creation and review."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


PLAN_CARDS_TOOL_NAME = "study.plan_cards"
LIST_CARD_PLANS_TOOL_NAME = "study.list_card_plans"
EDIT_CARD_PLAN_TOOL_NAME = "study.edit_card_plan"
VALIDATE_CARD_PLANS_TOOL_NAME = "study.validate_card_plans"
CARD_PLAN_TOOL_NAMES = frozenset(
    {
        PLAN_CARDS_TOOL_NAME,
        LIST_CARD_PLANS_TOOL_NAME,
        EDIT_CARD_PLAN_TOOL_NAME,
        VALIDATE_CARD_PLANS_TOOL_NAME,
    }
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_CURSOR_RE = re.compile(r"^study_plan_cursor_[A-Za-z0-9_-]{80,1800}$")


class McpCardPlanToolInputError(ValueError):
    pass


def _handle_schema() -> dict[str, Any]:
    return {"type": "string", "pattern": r"^study_[A-Za-z0-9_-]{43}$"}


def _request_context_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "projectId": {"type": "string", "minLength": 1, "maxLength": 256},
            "expectedProjectRevision": {"type": "integer", "minimum": 1},
            "idempotencyKey": {"type": "string", "minLength": 1, "maxLength": 160},
            "locale": {"type": "string", "minLength": 2, "maxLength": 32},
        },
        "required": ["projectId", "expectedProjectRevision", "idempotencyKey"],
        "additionalProperties": False,
    }


def _revision_output_schema(*, edited: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "schemaVersion": {"type": "integer", "const": 1},
        "projectId": {"type": "string"},
        "projectRevision": {"type": "integer", "minimum": 1},
        "artifactStage": {"type": "string", "const": "plans_ready"},
        "taskId": {"type": "string"},
        "planSetHandle": _handle_schema(),
        "validationHandle": _handle_schema(),
        "totalPlans": {"type": "integer", "minimum": 1, "maximum": 1000},
        "eligiblePlans": {"type": "integer", "minimum": 0},
        "blockedPlans": {"type": "integer", "minimum": 0},
        "issueCodes": {"type": "array", "items": {"type": "string"}},
        "nextAction": {
            "type": "string",
            "enum": ["generate_cards", "review_card_plans"],
        },
    }
    required = list(properties)
    if edited:
        properties["cardPlanHandle"] = _handle_schema()
        properties["cardPlanId"] = {"type": "string"}
        required.extend(["cardPlanHandle", "cardPlanId"])
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _text_schema(*, maximum: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _text_list_schema(*, maximum_items: int, maximum_text: int) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": maximum_items,
        "uniqueItems": True,
        "items": _text_schema(maximum=maximum_text),
    }


def _card_plan_edit_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "const": "edit_card_cue"},
                    "cue": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "const": "text"},
                            "content": _text_schema(maximum=1000),
                        },
                        "required": ["kind", "content"],
                        "additionalProperties": False,
                    },
                },
                "required": ["kind", "cue"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "const": "edit_card_answer"},
                    "expectedResponse": {
                        "type": "object",
                        "properties": {
                            "modality": {"type": "string", "const": "text"},
                            "coreAnswer": _text_schema(maximum=500),
                            "scoringPoints": {
                                **_text_list_schema(maximum_items=8, maximum_text=500),
                                "minItems": 1,
                            },
                            "acceptedVariants": _text_list_schema(
                                maximum_items=20, maximum_text=500
                            ),
                        },
                        "required": [
                            "modality",
                            "coreAnswer",
                            "scoringPoints",
                            "acceptedVariants",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": ["kind", "expectedResponse"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "const": "edit_card_feedback"},
                    "feedback": {
                        "type": "object",
                        "properties": {
                            "explanation": _text_schema(maximum=2000),
                            "examples": _text_list_schema(
                                maximum_items=10, maximum_text=2000
                            ),
                            "nonexamples": _text_list_schema(
                                maximum_items=10, maximum_text=2000
                            ),
                        },
                        "required": ["explanation", "examples", "nonexamples"],
                        "additionalProperties": False,
                    },
                },
                "required": ["kind", "feedback"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "const": "edit_media_policy"},
                    "mediaPolicy": {
                        "type": "object",
                        "properties": {
                            "sourceAudio": {"type": "boolean"},
                            "sourceVideo": {"type": "boolean"},
                            "sentenceTts": {"type": "boolean"},
                            "expressionTts": {"type": "boolean"},
                        },
                        "required": [
                            "sourceAudio",
                            "sourceVideo",
                            "sentenceTts",
                            "expressionTts",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": ["kind", "mediaPolicy"],
                "additionalProperties": False,
            },
        ]
    }


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
        {
            "name": EDIT_CARD_PLAN_TOOL_NAME,
            "title": "Edit one authenticated card plan",
            "description": (
                "Apply one bounded agent edit to the exact current CardPlan. The service "
                "preserves evidence references and user locks, records agent provenance, "
                "republishes the PlanSet, and reruns all eight gates. Unsupported semantic "
                "claims or media requests remain saved but blocked from generation."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context": _request_context_schema(),
                    "planSetHandle": _handle_schema(),
                    "cardPlanHandle": _handle_schema(),
                    "operation": _card_plan_edit_schema(),
                },
                "required": ["context", "planSetHandle", "cardPlanHandle", "operation"],
                "additionalProperties": False,
            },
            "outputSchema": _revision_output_schema(edited=True),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": VALIDATE_CARD_PLANS_TOOL_NAME,
            "title": "Revalidate authenticated card plans",
            "description": (
                "Replay all eight deterministic gates over the exact current PlanSet, publish "
                "a new authenticated validation revision, and fail closed on stale or corrupt graphs."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context": _request_context_schema(),
                    "planSetHandle": _handle_schema(),
                },
                "required": ["context", "planSetHandle"],
                "additionalProperties": False,
            },
            "outputSchema": _revision_output_schema(edited=False),
            "annotations": {
                "readOnlyHint": False,
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


def _revision_context(
    arguments: Any, *, edited: bool
) -> tuple[str, int, str, str, str | None, dict[str, Any] | None]:
    required = {"context", "planSetHandle"}
    if edited:
        required.update({"cardPlanHandle", "operation"})
    if not isinstance(arguments, dict) or set(arguments) != required:
        raise McpCardPlanToolInputError("card plan revision fields are invalid")
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
        raise McpCardPlanToolInputError("card plan revision context is invalid")
    project = context.get("projectId")
    revision = context.get("expectedProjectRevision")
    key = context.get("idempotencyKey")
    locale = context.get("locale")
    plan_set = arguments.get("planSetHandle")
    plan = arguments.get("cardPlanHandle")
    operation = arguments.get("operation")
    if not isinstance(project, str) or not _PROJECT_RE.fullmatch(project):
        raise McpCardPlanToolInputError("projectId is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise McpCardPlanToolInputError("expectedProjectRevision is invalid")
    if not isinstance(key, str) or not _ID_RE.fullmatch(key):
        raise McpCardPlanToolInputError("idempotencyKey is invalid")
    if locale is not None and (
        not isinstance(locale, str) or not 2 <= len(locale) <= 32
    ):
        raise McpCardPlanToolInputError("locale is invalid")
    if not isinstance(plan_set, str) or not _HANDLE_RE.fullmatch(plan_set):
        raise McpCardPlanToolInputError("planSetHandle is invalid")
    if edited:
        if not isinstance(plan, str) or not _HANDLE_RE.fullmatch(plan):
            raise McpCardPlanToolInputError("cardPlanHandle is invalid")
        _validate_edit_operation(operation)
    return project, revision, key, plan_set, plan, operation


def _bounded_text(value: Any, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _bounded_text_list(value: Any, maximum_items: int, maximum_text: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= maximum_items
        and all(_bounded_text(item, maximum_text) for item in value)
    )


def _validate_edit_operation(value: Any) -> None:
    if not isinstance(value, dict):
        raise McpCardPlanToolInputError("card plan edit operation is invalid")
    kind = value.get("kind")
    if kind == "edit_card_cue" and set(value) == {"kind", "cue"}:
        cue = value.get("cue")
        valid = (
            isinstance(cue, dict)
            and set(cue) == {"kind", "content"}
            and cue.get("kind") == "text"
            and _bounded_text(cue.get("content"), 1000)
        )
    elif kind == "edit_card_answer" and set(value) == {"kind", "expectedResponse"}:
        response = value.get("expectedResponse")
        valid = (
            isinstance(response, dict)
            and set(response)
            == {"modality", "coreAnswer", "scoringPoints", "acceptedVariants"}
            and response.get("modality") == "text"
            and _bounded_text(response.get("coreAnswer"), 500)
            and isinstance(response.get("scoringPoints"), list)
            and 1 <= len(response["scoringPoints"]) <= 8
            and _bounded_text_list(response["scoringPoints"], 8, 500)
            and _bounded_text_list(response.get("acceptedVariants"), 20, 500)
        )
    elif kind == "edit_card_feedback" and set(value) == {"kind", "feedback"}:
        feedback = value.get("feedback")
        valid = (
            isinstance(feedback, dict)
            and set(feedback) == {"explanation", "examples", "nonexamples"}
            and _bounded_text(feedback.get("explanation"), 2000)
            and _bounded_text_list(feedback.get("examples"), 10, 2000)
            and _bounded_text_list(feedback.get("nonexamples"), 10, 2000)
        )
    elif kind == "edit_media_policy" and set(value) == {"kind", "mediaPolicy"}:
        media = value.get("mediaPolicy")
        fields = {"sourceAudio", "sourceVideo", "sentenceTts", "expressionTts"}
        valid = (
            isinstance(media, dict)
            and set(media) == fields
            and all(isinstance(media[field], bool) for field in fields)
        )
    else:
        valid = False
    if not valid:
        raise McpCardPlanToolInputError("card plan edit operation is invalid")


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
    elif tool_name == EDIT_CARD_PLAN_TOOL_NAME:
        project, revision, key, plan_set, plan, operation = _revision_context(
            arguments, edited=True
        )
        assert plan is not None and operation is not None
        structured = service.edit_study_card_plan(
            audience=audience_session.audience,
            project_id=project,
            expected_project_revision=revision,
            idempotency_key=key,
            plan_set_handle=plan_set,
            card_plan_handle=plan,
            operation=operation,
        )
        text = (
            f"Edited and revalidated one card plan; "
            f"{structured['eligiblePlans']} of {structured['totalPlans']} are eligible."
        )
    elif tool_name == VALIDATE_CARD_PLANS_TOOL_NAME:
        project, revision, key, plan_set, _plan, _operation = _revision_context(
            arguments, edited=False
        )
        structured = service.validate_study_card_plans(
            audience=audience_session.audience,
            project_id=project,
            expected_project_revision=revision,
            idempotency_key=key,
            plan_set_handle=plan_set,
        )
        text = (
            f"Revalidated {structured['totalPlans']} card plan(s); "
            f"{structured['eligiblePlans']} passed every gate."
        )
    else:
        raise McpCardPlanToolInputError("Unknown card plan tool")
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }


__all__ = [
    "CARD_PLAN_TOOL_NAMES",
    "EDIT_CARD_PLAN_TOOL_NAME",
    "LIST_CARD_PLANS_TOOL_NAME",
    "McpCardPlanToolInputError",
    "PLAN_CARDS_TOOL_NAME",
    "VALIDATE_CARD_PLANS_TOOL_NAME",
    "call_card_plan_tool",
    "card_plan_tool_definitions",
]
