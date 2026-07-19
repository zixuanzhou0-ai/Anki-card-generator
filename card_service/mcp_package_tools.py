"""Closed MCP adapter for authenticated APKG package export."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


EXPORT_APKG_TOOL_NAME = "cards.export_apkg"
PACKAGE_TOOL_NAMES = frozenset({EXPORT_APKG_TOOL_NAME})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_RESOURCE_RE = re.compile(r"^resource_[A-Za-z0-9_-]{43}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class McpPackageToolInputError(ValueError):
    pass


def _task_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "taskId": {"type": "string"},
            "intent": {"type": "string", "const": "export_apkg"},
            "state": {
                "type": "string",
                "enum": [
                    "queued",
                    "running",
                    "cancelling",
                    "succeeded",
                    "failed",
                    "cancelled",
                    "interrupted",
                ],
            },
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


def package_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": EXPORT_APKG_TOOL_NAME,
            "title": "Export a verified Anki package",
            "description": (
                "Start a recoverable APKG export from the exact current authenticated "
                "ProjectArtifact into a trusted output-folder grant. The Worker writes "
                "only inside its isolated workspace; Card Service independently validates "
                "the complete package contract, publishes a content-addressed PackageArtifact, "
                "and performs a versioned no-replace delivery. Returns immediately with a taskId."
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
                    "projectArtifactHandle": {
                        "type": "string",
                        "pattern": r"^study_[A-Za-z0-9_-]{43}$",
                    },
                    "outputRef": {
                        "type": "object",
                        "properties": {
                            "schemaVersion": {"type": "integer", "const": 1},
                            "displayName": {"type": "string"},
                            "resourceRevisionDigest": {
                                "type": "string",
                                "pattern": r"^[0-9a-f]{64}$",
                            },
                            "constraints": {"type": "object"},
                            "expiresAt": {"type": "string"},
                            "kind": {"type": "string", "const": "output_directory"},
                            "outputResourceRef": {
                                "type": "string",
                                "pattern": r"^resource_[A-Za-z0-9_-]{43}$",
                            },
                        },
                        "required": [
                            "schemaVersion",
                            "displayName",
                            "resourceRevisionDigest",
                            "constraints",
                            "expiresAt",
                            "kind",
                            "outputResourceRef",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": ["context", "projectArtifactHandle", "outputRef"],
                "additionalProperties": False,
            },
            "outputSchema": _task_schema(),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        }
    ]


def _arguments(value: Any) -> tuple[str, int, str, str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {
        "context",
        "projectArtifactHandle",
        "outputRef",
    }:
        raise McpPackageToolInputError("package export fields are invalid")
    context = value.get("context")
    if not isinstance(context, dict) or set(context) != {
        "projectId",
        "expectedProjectRevision",
        "idempotencyKey",
    }:
        raise McpPackageToolInputError("package export context is invalid")
    project = context.get("projectId")
    revision = context.get("expectedProjectRevision")
    key = context.get("idempotencyKey")
    handle = value.get("projectArtifactHandle")
    output = value.get("outputRef")
    if not isinstance(project, str) or not _PROJECT_RE.fullmatch(project):
        raise McpPackageToolInputError("projectId is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise McpPackageToolInputError("expectedProjectRevision is invalid")
    if not isinstance(key, str) or not _ID_RE.fullmatch(key):
        raise McpPackageToolInputError("idempotencyKey is invalid")
    if not isinstance(handle, str) or not _HANDLE_RE.fullmatch(handle):
        raise McpPackageToolInputError("projectArtifactHandle is invalid")
    if not isinstance(output, Mapping) or set(output) != {
        "schemaVersion",
        "displayName",
        "resourceRevisionDigest",
        "constraints",
        "expiresAt",
        "kind",
        "outputResourceRef",
    }:
        raise McpPackageToolInputError("outputRef fields are invalid")
    constraints = output.get("constraints")
    if (
        output.get("schemaVersion") != 1
        or output.get("kind") != "output_directory"
        or not isinstance(output.get("displayName"), str)
        or not isinstance(output.get("expiresAt"), str)
        or not isinstance(output.get("resourceRevisionDigest"), str)
        or not _SHA256_RE.fullmatch(output["resourceRevisionDigest"])
        or not isinstance(output.get("outputResourceRef"), str)
        or not _RESOURCE_RE.fullmatch(output["outputResourceRef"])
        or not isinstance(constraints, dict)
        or set(constraints) != {"actions", "maxFiles", "maxTotalBytes"}
        or constraints.get("actions") != ["create", "versioned"]
        or isinstance(constraints.get("maxFiles"), bool)
        or not isinstance(constraints.get("maxFiles"), int)
        or isinstance(constraints.get("maxTotalBytes"), bool)
        or not isinstance(constraints.get("maxTotalBytes"), int)
    ):
        raise McpPackageToolInputError("outputRef is invalid")
    return project, revision, key, handle, dict(output)


def call_package_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    if tool_name != EXPORT_APKG_TOOL_NAME:
        raise McpPackageToolInputError("Unknown package tool")
    project, revision, key, handle, output = _arguments(arguments)
    structured = service.start_study_apkg_export(
        audience=audience_session.audience,
        project_id=project,
        expected_project_revision=revision,
        idempotency_key=key,
        project_artifact_handle=handle,
        output_ref=output,
    )
    return {
        "content": [
            {
                "type": "text",
                "text": "Started verified APKG export. Poll the returned taskId.",
            }
        ],
        "structuredContent": structured,
    }


__all__ = [
    "EXPORT_APKG_TOOL_NAME",
    "McpPackageToolInputError",
    "PACKAGE_TOOL_NAMES",
    "call_package_tool",
    "package_tool_definitions",
]
