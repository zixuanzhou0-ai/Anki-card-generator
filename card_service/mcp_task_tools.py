"""Public polling, cancellation, listing, and recovery tools for Study tasks."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


GET_TASK_TOOL_NAME = "study.get_task"
CANCEL_TASK_TOOL_NAME = "study.cancel_task"
LIST_RECOVERABLE_TASKS_TOOL_NAME = "study.list_recoverable_tasks"
RESUME_TASK_TOOL_NAME = "study.resume_task"
TASK_TOOL_NAMES = frozenset(
    {
        GET_TASK_TOOL_NAME,
        CANCEL_TASK_TOOL_NAME,
        LIST_RECOVERABLE_TASKS_TOOL_NAME,
        RESUME_TASK_TOOL_NAME,
    }
)
_TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class McpTaskToolInputError(ValueError):
    pass


def _task_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "taskId": {"type": "string"},
            "intent": {"type": "string"},
            "state": {"type": "string"},
            "cancellable": {"type": "boolean"},
            "resumability": {"type": "string"},
            "progress": {"type": "object"},
            "result": {"type": "object"},
            "error": {"type": "object"},
            "nextAction": {"type": "string"},
        },
        "required": [
            "schemaVersion",
            "taskId",
            "intent",
            "state",
            "cancellable",
            "resumability",
            "progress",
            "nextAction",
        ],
        "additionalProperties": False,
    }


def task_tool_definitions() -> list[dict[str, Any]]:
    input_schema = {
        "type": "object",
        "properties": {"taskId": {"type": "string", "minLength": 1, "maxLength": 256}},
        "required": ["taskId"],
        "additionalProperties": False,
    }
    list_input_schema = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "cursor": {"type": "string", "minLength": 1, "maxLength": 1800},
        },
        "additionalProperties": False,
    }
    resume_input_schema = {
        "type": "object",
        "properties": {
            "taskId": {"type": "string", "minLength": 1, "maxLength": 256},
            "idempotencyKey": {"type": "string", "minLength": 1, "maxLength": 160},
        },
        "required": ["taskId", "idempotencyKey"],
        "additionalProperties": False,
    }
    recoverable_list_schema = {
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "tasks": {"type": "array", "items": _task_schema()},
            "returnedTasks": {"type": "integer", "minimum": 0},
            "nextCursor": {"type": ["string", "null"]},
            "nextAction": {"type": "string", "enum": ["resume_task", "none"]},
        },
        "required": [
            "schemaVersion",
            "tasks",
            "returnedTasks",
            "nextCursor",
            "nextAction",
        ],
        "additionalProperties": False,
    }
    return [
        {
            "name": GET_TASK_TOOL_NAME,
            "title": "Get Study task status",
            "description": (
                "Poll one authenticated recoverable Study task. Returns bounded progress "
                "and a public result projection; never returns Worker output, local paths, "
                "credentials, internal ArtifactRefs, or input fingerprints."
            ),
            "inputSchema": input_schema,
            "outputSchema": _task_schema(),
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": CANCEL_TASK_TOOL_NAME,
            "title": "Cancel a Study task",
            "description": (
                "Request cancellation of one authenticated Study task and return its current "
                "state. Cancellation preserves the last safe artifact stage."
            ),
            "inputSchema": input_schema,
            "outputSchema": _task_schema(),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": LIST_RECOVERABLE_TASKS_TOOL_NAME,
            "title": "List recoverable Study tasks",
            "description": (
                "List authenticated candidate-discovery tasks that can be resumed. "
                "Export and Anki-import task recovery is not publicly supported."
            ),
            "inputSchema": list_input_schema,
            "outputSchema": recoverable_list_schema,
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": RESUME_TASK_TOOL_NAME,
            "title": "Resume a Study task",
            "description": (
                "Create or poll an idempotent successor for a failed, cancelled, or "
                "interrupted candidate-discovery task. Export and Anki-import recovery "
                "fails closed."
            ),
            "inputSchema": resume_input_schema,
            "outputSchema": _task_schema(),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        },
    ]


def _task_id(arguments: Any) -> str:
    if not isinstance(arguments, dict) or set(arguments) != {"taskId"}:
        raise McpTaskToolInputError("task fields are invalid")
    value = arguments.get("taskId")
    if not isinstance(value, str) or not _TASK_RE.fullmatch(value):
        raise McpTaskToolInputError("taskId is invalid")
    return value


def _list_arguments(arguments: Any) -> tuple[int, str | None]:
    if not isinstance(arguments, dict) or not set(arguments).issubset(
        {"limit", "cursor"}
    ):
        raise McpTaskToolInputError("recoverable task list fields are invalid")
    limit = arguments.get("limit", 20)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise McpTaskToolInputError("limit is invalid")
    cursor = arguments.get("cursor")
    if cursor is not None and (
        not isinstance(cursor, str) or not 1 <= len(cursor) <= 1800
    ):
        raise McpTaskToolInputError("cursor is invalid")
    return limit, cursor


def _resume_arguments(arguments: Any) -> tuple[str, str]:
    if not isinstance(arguments, dict) or set(arguments) != {
        "taskId",
        "idempotencyKey",
    }:
        raise McpTaskToolInputError("task recovery fields are invalid")
    task_id = _task_id({"taskId": arguments.get("taskId")})
    idempotency_key = arguments.get("idempotencyKey")
    if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
        idempotency_key
    ):
        raise McpTaskToolInputError("idempotencyKey is invalid")
    return task_id, idempotency_key


def call_task_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    if tool_name == GET_TASK_TOOL_NAME:
        task_id = _task_id(arguments)
        structured = service.get_public_study_task(
            audience=audience_session.audience, task_id=task_id
        )
        text = f"Study task state: {structured['state']}."
    elif tool_name == CANCEL_TASK_TOOL_NAME:
        task_id = _task_id(arguments)
        structured = service.cancel_public_study_task(
            audience=audience_session.audience, task_id=task_id
        )
        text = f"Study task cancellation state: {structured['state']}."
    elif tool_name == LIST_RECOVERABLE_TASKS_TOOL_NAME:
        limit, cursor = _list_arguments(arguments)
        structured = service.list_public_recoverable_study_tasks(
            audience=audience_session.audience, limit=limit, cursor=cursor
        )
        text = f"Recoverable Study tasks: {structured['returnedTasks']}."
    elif tool_name == RESUME_TASK_TOOL_NAME:
        task_id, idempotency_key = _resume_arguments(arguments)
        structured = service.resume_public_study_task(
            audience=audience_session.audience,
            task_id=task_id,
            idempotency_key=idempotency_key,
        )
        text = f"Study task recovery state: {structured['state']}."
    else:
        raise McpTaskToolInputError("Unknown task tool")
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }


__all__ = [
    "CANCEL_TASK_TOOL_NAME",
    "GET_TASK_TOOL_NAME",
    "LIST_RECOVERABLE_TASKS_TOOL_NAME",
    "McpTaskToolInputError",
    "RESUME_TASK_TOOL_NAME",
    "TASK_TOOL_NAMES",
    "call_task_tool",
    "task_tool_definitions",
]
