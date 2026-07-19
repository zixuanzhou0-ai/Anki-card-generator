"""Closed MCP adapter for read-only Anki import preparation."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


PREPARE_IMPORT_TOOL_NAME = "anki.prepare_import"
ANKI_TOOL_NAMES = frozenset({PREPARE_IMPORT_TOOL_NAME})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")


class McpAnkiToolInputError(ValueError):
    pass


def anki_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": PREPARE_IMPORT_TOOL_NAME,
            "title": "Prepare a verified Anki import",
            "description": (
                "Reverify the current authenticated PackageArtifact and inspect the "
                "currently open local Anki profile through fixed-loopback AnkiConnect. "
                "Publishes an immutable ImportPlan and verification contract. This tool "
                "is read-only with respect to Anki: it does not import, create media, "
                "change decks, or grant write approval."
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
                        },
                        "required": [
                            "projectId",
                            "expectedProjectRevision",
                            "idempotencyKey",
                        ],
                        "additionalProperties": False,
                    },
                    "packageArtifactHandle": {
                        "type": "string",
                        "pattern": r"^study_[A-Za-z0-9_-]{43}$",
                    },
                },
                "required": ["context", "packageArtifactHandle"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "importPlanHandle": {"type": "string"},
                    "artifactStage": {"type": "string", "const": "apkg_ready"},
                    "projectRevision": {"type": "integer"},
                    "package": {"type": "object"},
                    "target": {"type": "object"},
                    "duplicatePolicy": {"type": "string"},
                    "dataVerificationCheckCount": {"type": "integer"},
                    "runtimeVerification": {
                        "type": "string",
                        "const": "not_assessed",
                    },
                    "confirmationRequired": {"type": "boolean", "const": True},
                    "nextAction": {
                        "type": "string",
                        "const": "request_import_confirmation",
                    },
                },
                "required": [
                    "schemaVersion",
                    "importPlanHandle",
                    "artifactStage",
                    "projectRevision",
                    "package",
                    "target",
                    "duplicatePolicy",
                    "dataVerificationCheckCount",
                    "runtimeVerification",
                    "confirmationRequired",
                    "nextAction",
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


def _arguments(arguments: Any) -> tuple[str, int, str, str]:
    if not isinstance(arguments, dict) or set(arguments) != {
        "context",
        "packageArtifactHandle",
    }:
        raise McpAnkiToolInputError("Anki preparation fields are invalid")
    context = arguments.get("context")
    if not isinstance(context, dict) or set(context) != {
        "projectId",
        "expectedProjectRevision",
        "idempotencyKey",
    }:
        raise McpAnkiToolInputError("Anki preparation context is invalid")
    project = context.get("projectId")
    revision = context.get("expectedProjectRevision")
    key = context.get("idempotencyKey")
    handle = arguments.get("packageArtifactHandle")
    if not isinstance(project, str) or not _PROJECT_RE.fullmatch(project):
        raise McpAnkiToolInputError("projectId is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise McpAnkiToolInputError("expectedProjectRevision is invalid")
    if not isinstance(key, str) or not _ID_RE.fullmatch(key):
        raise McpAnkiToolInputError("idempotencyKey is invalid")
    if not isinstance(handle, str) or not _HANDLE_RE.fullmatch(handle):
        raise McpAnkiToolInputError("packageArtifactHandle is invalid")
    return project, revision, key, handle


def call_anki_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    if tool_name != PREPARE_IMPORT_TOOL_NAME:
        raise McpAnkiToolInputError("Unknown Anki tool")
    project, revision, key, handle = _arguments(arguments)
    structured = service.prepare_study_anki_import(
        audience=audience_session.audience,
        project_id=project,
        expected_project_revision=revision,
        idempotency_key=key,
        package_artifact_handle=handle,
    )
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "Anki import plan is ready. No Anki write has occurred; "
                    "trusted user confirmation is still required."
                ),
            }
        ],
        "structuredContent": structured,
    }


__all__ = [
    "ANKI_TOOL_NAMES",
    "McpAnkiToolInputError",
    "PREPARE_IMPORT_TOOL_NAME",
    "anki_tool_definitions",
    "call_anki_tool",
]
