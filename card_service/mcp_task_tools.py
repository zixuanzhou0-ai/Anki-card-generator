"""Public polling and cancellation tools for recoverable Study tasks."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


GET_TASK_TOOL_NAME = "study.get_task"
CANCEL_TASK_TOOL_NAME = "study.cancel_task"
TASK_TOOL_NAMES = frozenset({GET_TASK_TOOL_NAME, CANCEL_TASK_TOOL_NAME})
_TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


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
    ]


def _task_id(arguments: Any) -> str:
    if not isinstance(arguments, dict) or set(arguments) != {"taskId"}:
        raise McpTaskToolInputError("task fields are invalid")
    value = arguments.get("taskId")
    if not isinstance(value, str) or not _TASK_RE.fullmatch(value):
        raise McpTaskToolInputError("taskId is invalid")
    return value


def call_task_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    task_id = _task_id(arguments)
    if tool_name == GET_TASK_TOOL_NAME:
        structured = service.get_public_study_task(
            audience=audience_session.audience, task_id=task_id
        )
        text = f"Study task state: {structured['state']}."
    elif tool_name == CANCEL_TASK_TOOL_NAME:
        structured = service.cancel_public_study_task(
            audience=audience_session.audience, task_id=task_id
        )
        text = f"Study task cancellation state: {structured['state']}."
    else:
        raise McpTaskToolInputError("Unknown task tool")
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }


__all__ = [
    "CANCEL_TASK_TOOL_NAME",
    "GET_TASK_TOOL_NAME",
    "McpTaskToolInputError",
    "TASK_TOOL_NAMES",
    "call_task_tool",
    "task_tool_definitions",
]
