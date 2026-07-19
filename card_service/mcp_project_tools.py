"""Closed public MCP adapters for Study project operations."""

from __future__ import annotations

import json
import re
from typing import Any

from .project_registry import EVIDENCE_POLICIES, LEARNING_ROUTES
from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


CREATE_PROJECT_TOOL_NAME = "study.create_project"
LIST_PROJECTS_TOOL_NAME = "study.list_projects"
GET_PROJECT_TOOL_NAME = "study.get_project"
PROJECT_TOOL_NAMES = frozenset(
    {CREATE_PROJECT_TOOL_NAME, LIST_PROJECTS_TOOL_NAME, GET_PROJECT_TOOL_NAME}
)
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROJECT_ID_RE = re.compile(r"^project_[0-9a-f]{48}$")
_CURSOR_RE = re.compile(
    r"^study_project_cursor_[A-Za-z0-9_-]{40,1700}\.[A-Za-z0-9_-]{40,80}$"
)


class McpProjectToolInputError(ValueError):
    pass


def project_tool_definitions() -> list[dict[str, Any]]:
    context_schema = {
        "type": "object",
        "properties": {
            "idempotencyKey": {"type": "string", "minLength": 1, "maxLength": 160},
            "locale": {"type": "string", "minLength": 2, "maxLength": 32},
        },
        "required": ["idempotencyKey"],
        "additionalProperties": False,
    }
    learning_contract_schema = {
        "type": "object",
        "properties": {
            "purpose": {"type": "string", "minLength": 1, "maxLength": 4000},
            "targetBehavior": {"type": "string", "minLength": 1, "maxLength": 4000},
            "learnerLevel": {"type": "string", "minLength": 1, "maxLength": 200},
            "routes": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(LEARNING_ROUTES)},
                "maxItems": 32,
                "uniqueItems": True,
            },
            "maxNewCards": {"type": "integer", "minimum": 1, "maximum": 10000},
            "targetDailyReviewMinutes": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1440,
            },
            "promptLanguage": {"type": "string", "minLength": 1, "maxLength": 200},
            "answerLanguage": {"type": "string", "minLength": 1, "maxLength": 200},
            "evidencePolicy": {
                "type": "string",
                "enum": sorted(EVIDENCE_POLICIES),
            },
            "exclusions": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
                "maxItems": 256,
                "uniqueItems": True,
            },
        },
        "required": ["purpose", "targetBehavior"],
        "additionalProperties": False,
    }
    return [
        {
            "name": CREATE_PROJECT_TOOL_NAME,
            "title": "Create a study project",
            "description": (
                "Create an idempotent local Study project and freeze its initial learning "
                "contract. This does not call a model, read a source, or modify Anki."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context": context_schema,
                    "title": {"type": "string", "minLength": 1, "maxLength": 240},
                    "learningContract": learning_contract_schema,
                },
                "required": ["context", "learningContract"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "projectId": {"type": "string"},
                    "projectRevision": {"type": "integer", "minimum": 1},
                    "learningContractRef": {"type": "string"},
                    "contractRevision": {"type": "integer", "minimum": 1},
                    "inferredDefaults": {"type": "array", "items": {"type": "object"}},
                    "workflow": {"type": "object"},
                },
                "required": [
                    "schemaVersion",
                    "projectId",
                    "projectRevision",
                    "learningContractRef",
                    "contractRevision",
                    "inferredDefaults",
                    "workflow",
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
            "name": LIST_PROJECTS_TOOL_NAME,
            "title": "List Study projects",
            "description": (
                "List a bounded page of local Study project summaries for the current "
                "trusted owner and host scope. Source text, paths, credentials, and "
                "internal registry references are never returned."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cursor": {
                        "type": "string",
                        "pattern": (
                            r"^study_project_cursor_[A-Za-z0-9_-]+\."
                            r"[A-Za-z0-9_-]+$"
                        ),
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "totalProjects": {"type": "integer", "minimum": 0},
                    "returnedProjects": {"type": "integer", "minimum": 0},
                    "items": {"type": "array", "items": {"type": "object"}},
                    "nextCursor": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "null"},
                        ]
                    },
                },
                "required": [
                    "schemaVersion",
                    "totalProjects",
                    "returnedProjects",
                    "items",
                    "nextCursor",
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
            "name": GET_PROJECT_TOOL_NAME,
            "title": "Get a Study project",
            "description": (
                "Read one local Study project and its authoritative workflow snapshot, "
                "current task summary, and opaque latest Artifact handles."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {
                        "type": "string",
                        "pattern": r"^project_[0-9a-f]{48}$",
                    }
                },
                "required": ["projectId"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "projectId": {"type": "string"},
                    "title": {"type": "string"},
                    "projectRevision": {"type": "integer", "minimum": 1},
                    "learningContract": {"type": "object"},
                    "inferredDefaults": {"type": "array", "items": {"type": "object"}},
                    "workflow": {"type": "object"},
                    "currentTask": {
                        "oneOf": [{"type": "object"}, {"type": "null"}]
                    },
                    "latestArtifacts": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "createdAt": {"type": "string"},
                    "updatedAt": {"type": "string"},
                },
                "required": [
                    "schemaVersion",
                    "projectId",
                    "title",
                    "projectRevision",
                    "learningContract",
                    "inferredDefaults",
                    "workflow",
                    "currentTask",
                    "latestArtifacts",
                    "createdAt",
                    "updatedAt",
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


def _validated_arguments(arguments: Any) -> tuple[str, str | None, dict[str, Any]]:
    if (
        not isinstance(arguments, dict)
        or not set(arguments).issubset({"context", "title", "learningContract"})
        or not {"context", "learningContract"}.issubset(arguments)
    ):
        raise McpProjectToolInputError("project tool fields are invalid")
    context = arguments.get("context")
    if (
        not isinstance(context, dict)
        or not set(context).issubset({"idempotencyKey", "locale"})
        or "idempotencyKey" not in context
        or not isinstance(context["idempotencyKey"], str)
        or not _IDEMPOTENCY_RE.fullmatch(context["idempotencyKey"])
        or (
            "locale" in context
            and (
                not isinstance(context["locale"], str)
                or not 2 <= len(context["locale"]) <= 32
            )
        )
    ):
        raise McpProjectToolInputError("request context is invalid")
    title = arguments.get("title")
    if title is not None and (
        not isinstance(title, str)
        or not title.strip()
        or len(title) > 240
        or any(ord(character) < 0x20 for character in title)
    ):
        raise McpProjectToolInputError("project title is invalid")
    learning_contract = arguments.get("learningContract")
    if not isinstance(learning_contract, dict):
        raise McpProjectToolInputError("learning contract is invalid")
    allowed_contract_fields = {
        "purpose",
        "targetBehavior",
        "learnerLevel",
        "routes",
        "maxNewCards",
        "targetDailyReviewMinutes",
        "promptLanguage",
        "answerLanguage",
        "evidencePolicy",
        "exclusions",
    }
    if (
        not {"purpose", "targetBehavior"}.issubset(learning_contract)
        or not set(learning_contract).issubset(allowed_contract_fields)
        or any(
            not isinstance(learning_contract[field], str)
            or not learning_contract[field].strip()
            for field in ("purpose", "targetBehavior")
        )
    ):
        raise McpProjectToolInputError("learning contract fields are invalid")
    for field in ("learnerLevel", "promptLanguage", "answerLanguage"):
        if field in learning_contract and (
            not isinstance(learning_contract[field], str)
            or not learning_contract[field].strip()
        ):
            raise McpProjectToolInputError("learning contract text is invalid")
    for field in ("maxNewCards", "targetDailyReviewMinutes"):
        if field in learning_contract and (
            isinstance(learning_contract[field], bool)
            or not isinstance(learning_contract[field], int)
        ):
            raise McpProjectToolInputError("learning contract budget is invalid")
    if "routes" in learning_contract and (
        not isinstance(learning_contract["routes"], list)
        or any(route not in LEARNING_ROUTES for route in learning_contract["routes"])
    ):
        raise McpProjectToolInputError("learning routes are invalid")
    if "exclusions" in learning_contract and not isinstance(
        learning_contract["exclusions"], list
    ):
        raise McpProjectToolInputError("learning exclusions are invalid")
    if learning_contract.get("evidencePolicy", "automatic") not in EVIDENCE_POLICIES:
        raise McpProjectToolInputError("evidence policy is invalid")
    return (
        context["idempotencyKey"],
        title,
        json.loads(json.dumps(learning_contract, ensure_ascii=False)),
    )


def _list_arguments(arguments: Any) -> tuple[str | None, int]:
    if not isinstance(arguments, dict) or not set(arguments).issubset(
        {"cursor", "limit"}
    ):
        raise McpProjectToolInputError("project list fields are invalid")
    cursor = arguments.get("cursor")
    if cursor is not None and (
        not isinstance(cursor, str) or not _CURSOR_RE.fullmatch(cursor)
    ):
        raise McpProjectToolInputError("project cursor is invalid")
    limit = arguments.get("limit", 20)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise McpProjectToolInputError("project list limit is invalid")
    return cursor, limit


def _project_id_argument(arguments: Any) -> str:
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"projectId"}
        or not isinstance(arguments.get("projectId"), str)
        or not _PROJECT_ID_RE.fullmatch(arguments["projectId"])
    ):
        raise McpProjectToolInputError("project identity is invalid")
    return arguments["projectId"]


def call_project_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    if tool_name == CREATE_PROJECT_TOOL_NAME:
        idempotency_key, title, learning_contract = _validated_arguments(arguments)
        project = service.create_study_project(
            audience=audience_session.audience,
            idempotency_key=idempotency_key,
            learning_contract=learning_contract,
            title=title,
        )
        contract = project["learningContract"]
        structured = {
            "schemaVersion": 1,
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "learningContractRef": contract["contractId"],
            "contractRevision": contract["contractRevision"],
            "inferredDefaults": project["inferredDefaults"],
            "workflow": project["workflow"],
        }
        text = (
            f"Study project created at revision {structured['projectRevision']}. "
            "No source has been read yet."
        )
    elif tool_name == LIST_PROJECTS_TOOL_NAME:
        cursor, limit = _list_arguments(arguments)
        structured = service.list_study_projects(
            audience=audience_session.audience,
            cursor=cursor,
            limit=limit,
        )
        text = (
            f"Loaded {structured['returnedProjects']} of "
            f"{structured['totalProjects']} Study project(s)."
        )
    elif tool_name == GET_PROJECT_TOOL_NAME:
        project_id = _project_id_argument(arguments)
        structured = service.get_study_project(
            audience=audience_session.audience,
            project_id=project_id,
        )
        text = (
            f"Study project is at {structured['workflow']['artifactStage']} "
            f"with operation state {structured['workflow']['operationState']}."
        )
    else:
        raise McpProjectToolInputError("Unknown project tool")
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }


__all__ = [
    "CREATE_PROJECT_TOOL_NAME",
    "GET_PROJECT_TOOL_NAME",
    "LIST_PROJECTS_TOOL_NAME",
    "McpProjectToolInputError",
    "PROJECT_TOOL_NAMES",
    "call_project_tool",
    "project_tool_definitions",
]
