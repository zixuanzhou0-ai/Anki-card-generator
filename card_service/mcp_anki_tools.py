"""Closed MCP adapters for Anki planning and model-external confirmation."""

from __future__ import annotations

import re
import time
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


PREPARE_IMPORT_TOOL_NAME = "anki.prepare_import"
REQUEST_IMPORT_CONFIRMATION_TOOL_NAME = "anki.request_import_confirmation"
IMPORT_AND_VERIFY_TOOL_NAME = "anki.import_and_verify"
ANKI_TOOL_NAMES = frozenset(
    {
        PREPARE_IMPORT_TOOL_NAME,
        REQUEST_IMPORT_CONFIRMATION_TOOL_NAME,
        IMPORT_AND_VERIFY_TOOL_NAME,
    }
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_IMPORT_INTENT_RE = re.compile(r"^anki_intent_[0-9a-f]{48}$")


class McpAnkiToolInputError(ValueError):
    pass


def anki_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": PREPARE_IMPORT_TOOL_NAME,
            "title": "Prepare a verified Anki import",
            "description": (
                "Reverify the authenticated PackageArtifact and inspect the current "
                "local Anki target through fixed-loopback AnkiConnect. Publishes an "
                "immutable ImportPlan and a session-bound importIntentId. This tool "
                "does not import into Anki and does not grant approval."
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
                    "importIntentId": {
                        "type": "string",
                        "pattern": r"^anki_intent_[0-9a-f]{48}$",
                    },
                    "approvalState": {"type": "string", "const": "pending"},
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
                    "importIntentId",
                    "approvalState",
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
        },
        {
            "name": REQUEST_IMPORT_CONFIRMATION_TOOL_NAME,
            "title": "Confirm an Anki import locally",
            "description": (
                "Open a digest-pinned local confirmation window for one current "
                "importIntentId. Only a real click in that window can update the "
                "server-side approval ledger. Chat text is never accepted as approval, "
                "and no execution bearer is returned."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "importIntentId": {
                        "type": "string",
                        "pattern": r"^anki_intent_[0-9a-f]{48}$",
                    }
                },
                "required": ["importIntentId"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "importIntentId": {"type": "string"},
                    "approvalState": {
                        "type": "string",
                        "enum": [
                            "pending",
                            "approved",
                            "declined",
                            "expired",
                            "cancelled",
                            "revoked",
                            "consumed",
                        ],
                    },
                    "expiresAt": {"type": "string"},
                },
                "required": [
                    "schemaVersion",
                    "importIntentId",
                    "approvalState",
                    "expiresAt",
                ],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": False,
            },
        },
        {
            "name": IMPORT_AND_VERIFY_TOOL_NAME,
            "title": "Import into Anki and verify",
            "description": (
                "Consume one approved, session-bound import intent and start the "
                "authenticated Anki import-and-data-verification task. The tool accepts "
                "no path, AnkiConnect URL, approval boolean, token, or raw ExportResult."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context": {
                        "type": "object",
                        "properties": {
                            "idempotencyKey": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 160,
                            }
                        },
                        "required": ["idempotencyKey"],
                        "additionalProperties": False,
                    },
                    "importIntentId": {
                        "type": "string",
                        "pattern": r"^anki_intent_[0-9a-f]{48}$",
                    },
                },
                "required": ["context", "importIntentId"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "taskId": {"type": "string"},
                    "intent": {"type": "string", "const": "import_and_verify"},
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
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        },
    ]


def _prepare_arguments(arguments: Any) -> tuple[str, int, str, str]:
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


def _confirmation_argument(arguments: Any) -> str:
    if not isinstance(arguments, dict) or set(arguments) != {"importIntentId"}:
        raise McpAnkiToolInputError("Anki confirmation fields are invalid")
    intent = arguments.get("importIntentId")
    if not isinstance(intent, str) or not _IMPORT_INTENT_RE.fullmatch(intent):
        raise McpAnkiToolInputError("importIntentId is invalid")
    return intent


def _import_arguments(arguments: Any) -> tuple[str, str]:
    if not isinstance(arguments, dict) or set(arguments) != {
        "context",
        "importIntentId",
    }:
        raise McpAnkiToolInputError("Anki import fields are invalid")
    context = arguments.get("context")
    if not isinstance(context, dict) or set(context) != {"idempotencyKey"}:
        raise McpAnkiToolInputError("Anki import context is invalid")
    key = context.get("idempotencyKey")
    intent = arguments.get("importIntentId")
    if not isinstance(key, str) or not _ID_RE.fullmatch(key):
        raise McpAnkiToolInputError("idempotencyKey is invalid")
    if not isinstance(intent, str) or not _IMPORT_INTENT_RE.fullmatch(intent):
        raise McpAnkiToolInputError("importIntentId is invalid")
    return key, intent

def call_anki_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
    user_action_timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    if tool_name == PREPARE_IMPORT_TOOL_NAME:
        project, revision, key, handle = _prepare_arguments(arguments)
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
                        "trusted local confirmation is still required."
                    ),
                }
            ],
            "structuredContent": structured,
        }
    if tool_name == REQUEST_IMPORT_CONFIRMATION_TOOL_NAME:
        intent = _confirmation_argument(arguments)
        deadline = time.monotonic() + max(0.0, float(user_action_timeout_seconds))
        structured = service.request_study_anki_import_confirmation(
            audience=audience_session.audience,
            import_intent_id=intent,
        )
        while (
            structured.get("approvalState") == "pending" and time.monotonic() < deadline
        ):
            time.sleep(0.05)
            structured = service.request_study_anki_import_confirmation(
                audience=audience_session.audience,
                import_intent_id=intent,
            )
        state = str(structured["approvalState"])
        text = {
            "pending": "The trusted local confirmation window is waiting for the user.",
            "approved": "The Anki import was approved for one server-side execution.",
            "declined": "The user declined the Anki import.",
            "expired": "The Anki import intent expired without execution.",
            "cancelled": "The user closed the trusted confirmation window.",
            "revoked": "The Anki import approval was revoked.",
            "consumed": "The Anki import approval has already been consumed.",
        }[state]
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": structured,
        }
    if tool_name == IMPORT_AND_VERIFY_TOOL_NAME:
        key, intent = _import_arguments(arguments)
        structured = service.start_study_anki_import(
            audience=audience_session.audience,
            import_intent_id=intent,
            idempotency_key=key,
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Authenticated Anki import and data verification started. "
                        "Poll the returned Study task for its terminal result."
                    ),
                }
            ],
            "structuredContent": structured,
        }
    raise McpAnkiToolInputError("Unknown Anki tool")


__all__ = [
    "ANKI_TOOL_NAMES",
    "McpAnkiToolInputError",
    "IMPORT_AND_VERIFY_TOOL_NAME",
    "PREPARE_IMPORT_TOOL_NAME",
    "REQUEST_IMPORT_CONFIRMATION_TOOL_NAME",
    "anki_tool_definitions",
    "call_anki_tool",
]
