"""Closed MCP adapters for authenticated artifact and audit projections."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


GET_ARTIFACT_TOOL_NAME = "study.get_artifact"
GET_AUDIT_TOOL_NAME = "study.get_audit"
ARTIFACT_TOOL_NAMES = frozenset({GET_ARTIFACT_TOOL_NAME, GET_AUDIT_TOOL_NAME})
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")


class McpArtifactToolInputError(ValueError):
    pass


def _input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "artifactHandle": {
                "type": "string",
                "pattern": r"^study_[A-Za-z0-9_-]{43}$",
            }
        },
        "required": ["artifactHandle"],
        "additionalProperties": False,
    }


def _closed(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _summary_schema() -> dict[str, Any]:
    text = {"type": "string", "maxLength": 240}
    count = {"type": "integer", "minimum": 0}
    code_list = {
        "type": "array",
        "maxItems": 64,
        "items": {
            "type": "string",
            "maxLength": 160,
            "pattern": r"^[A-Za-z][A-Za-z0-9._:-]{0,159}$",
        },
    }
    variants = [
        _closed({}, []),
        _closed(
            {
                "dataVerification": text,
                "runtimeVerification": text,
                "importDisposition": text,
                "importAttempted": {"type": "boolean"},
                "importSucceeded": {"type": "boolean"},
                "noteCount": count,
                "cardCount": count,
                "expectedCardCount": count,
                "mediaCountExpected": count,
                "mediaCountChecked": count,
                "duplicateCardCount": count,
                "failedChecks": code_list,
                "verificationContractVersion": text,
                "policyVersion": text,
            },
            [
                "dataVerification",
                "runtimeVerification",
                "importDisposition",
                "importAttempted",
                "importSucceeded",
                "noteCount",
                "cardCount",
                "expectedCardCount",
                "mediaCountExpected",
                "mediaCountChecked",
                "duplicateCardCount",
                "failedChecks",
                "verificationContractVersion",
                "policyVersion",
            ],
        ),
        _closed(
            {
                "importDisposition": text,
                "importAttempted": {"type": "boolean"},
                "importSucceeded": {"type": "boolean"},
                "writeBoundaryState": text,
                "apkgSha256": {"type": "string", "pattern": "^([0-9a-f]{64})?$"},
                "targetDigest": {"type": "string", "pattern": "^([0-9a-f]{64})?$"},
                "policyVersion": text,
            },
            [
                "importDisposition",
                "importAttempted",
                "importSucceeded",
                "writeBoundaryState",
                "apkgSha256",
                "targetDigest",
                "policyVersion",
            ],
        ),
        _closed(
            {
                "fileName": text,
                "apkgSha256": {"type": "string", "pattern": "^([0-9a-f]{64})?$"},
                "sizeBytes": count,
                "deckNames": {
                    "type": "array",
                    "maxItems": 32,
                    "items": {"type": "string", "maxLength": 160},
                },
                "noteCount": count,
                "cardCount": count,
                "mediaCount": count,
                "templateFamily": text,
                "templateSchemaVersion": text,
                "noteModelId": text,
                "compatibilityContractVersion": text,
                "frontTemplateSha256": {
                    "type": "string",
                    "pattern": "^([0-9a-f]{64})?$",
                },
                "backTemplateSha256": {
                    "type": "string",
                    "pattern": "^([0-9a-f]{64})?$",
                },
                "cssSha256": {"type": "string", "pattern": "^([0-9a-f]{64})?$"},
            },
            [
                "fileName",
                "apkgSha256",
                "sizeBytes",
                "deckNames",
                "noteCount",
                "cardCount",
                "mediaCount",
                "templateFamily",
                "templateSchemaVersion",
                "noteModelId",
                "compatibilityContractVersion",
                "frontTemplateSha256",
                "backTemplateSha256",
                "cssSha256",
            ],
        ),
        _closed(
            {
                "decision": text,
                "accountingComplete": {"type": "boolean"},
                "selectedPointCount": count,
                "verifiedCount": count,
                "needsReviewCount": count,
                "hardFailedCount": count,
                "blockerCodes": code_list,
                "verificationProfile": text,
                "ruleSetVersion": text,
            },
            [
                "decision",
                "accountingComplete",
                "selectedPointCount",
                "verifiedCount",
                "needsReviewCount",
                "hardFailedCount",
                "blockerCodes",
                "verificationProfile",
                "ruleSetVersion",
            ],
        ),
        _closed(
            {
                "validationId": text,
                "ruleSetVersion": text,
                "recordCount": count,
                "eligibleCount": count,
                "blockedCount": count,
            },
            [
                "validationId",
                "ruleSetVersion",
                "recordCount",
                "eligibleCount",
                "blockedCount",
            ],
        ),
        _closed(
            {"cardCount": count, "cardPlanCount": count},
            ["cardCount", "cardPlanCount"],
        ),
        _closed(
            {
                "state": text,
                "mediaCount": count,
                "cardCount": count,
                "policyVersion": text,
            },
            ["state", "mediaCount", "cardCount", "policyVersion"],
        ),
        _closed(
            {
                "sourceCount": count,
                "inspectionCount": count,
                "issueCount": count,
                "state": text,
            },
            ["sourceCount", "inspectionCount", "issueCount", "state"],
        ),
    ]
    return {"oneOf": variants}


def artifact_tool_definitions() -> list[dict[str, Any]]:
    annotations = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    return [
        {
            "name": GET_ARTIFACT_TOOL_NAME,
            "title": "Get Study artifact",
            "description": (
                "Verify a current-session opaque artifact handle and return bounded metadata "
                "plus an allowlisted schema-specific summary. Never returns internal references, "
                "local paths, arbitrary files, or full source/card payloads."
            ),
            "inputSchema": _input_schema(),
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "artifactHandle": {"type": "string"},
                    "projectId": {"type": "string"},
                    "projectRevision": {"type": "integer", "minimum": 1},
                    "artifactRevision": {"type": "integer", "minimum": 1},
                    "payloadSchema": {"type": "string"},
                    "payloadSchemaVersion": {"type": "integer", "minimum": 1},
                    "artifactDigest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "payloadSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "createdAt": {"type": "string"},
                    "contentKind": {
                        "type": "string",
                        "enum": [
                            "metadata_only",
                            "verification_summary",
                            "import_receipt_summary",
                            "package_summary",
                            "reliability_summary",
                            "card_plan_validation_summary",
                            "project_artifact_summary",
                            "media_summary",
                            "source_inspection_summary",
                        ],
                    },
                    "summary": _summary_schema(),
                    "parentCount": {"type": "integer", "minimum": 0},
                    "issueCount": {"type": "integer", "minimum": 0},
                },
                "required": [
                    "schemaVersion",
                    "artifactHandle",
                    "projectId",
                    "projectRevision",
                    "artifactRevision",
                    "payloadSchema",
                    "payloadSchemaVersion",
                    "artifactDigest",
                    "payloadSha256",
                    "createdAt",
                    "contentKind",
                    "summary",
                    "parentCount",
                    "issueCount",
                ],
                "additionalProperties": False,
            },
            "annotations": dict(annotations),
        },
        {
            "name": GET_AUDIT_TOOL_NAME,
            "title": "Get Study audit certificate",
            "description": (
                "Verify a current-session opaque artifact handle and return its bounded integrity, "
                "lineage, producer, gate, and known-limitation certificate."
            ),
            "inputSchema": _input_schema(),
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "artifactHandle": {"type": "string"},
                    "projectId": {"type": "string"},
                    "payloadSchema": {"type": "string"},
                    "payloadSchemaVersion": {"type": "integer", "minimum": 1},
                    "projectRevision": {"type": "integer", "minimum": 1},
                    "artifactRevision": {"type": "integer", "minimum": 1},
                    "artifactDigest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "payloadSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "inputFingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "createdAt": {"type": "string"},
                    "producer": _closed(
                        {
                            "component": {"type": "string", "maxLength": 128},
                            "version": {"type": "string", "maxLength": 128},
                        },
                        ["component", "version"],
                    ),
                    "completeness": _closed(
                        {
                            "state": {
                                "type": "string",
                                "enum": [
                                    "complete",
                                    "partial_declared",
                                    "unknown",
                                    "blocked",
                                ],
                            },
                            "expectedUnits": {"type": "integer", "minimum": 0},
                            "processedUnits": {"type": "integer", "minimum": 0},
                            "omittedCount": {"type": "integer", "minimum": 0},
                            "reasonCodes": {
                                "type": "array",
                                "maxItems": 64,
                                "items": {
                                    "type": "string",
                                    "maxLength": 160,
                                    "pattern": r"^[A-Za-z][A-Za-z0-9._:-]{0,159}$",
                                },
                            },
                        },
                        [
                            "state",
                            "expectedUnits",
                            "processedUnits",
                            "omittedCount",
                            "reasonCodes",
                        ],
                    ),
                    "issueRefs": {
                        "type": "array",
                        "maxItems": 256,
                        "items": {
                            "type": "string",
                            "maxLength": 160,
                            "pattern": r"^[A-Za-z][A-Za-z0-9._:-]{0,159}$",
                        },
                    },
                    "parents": {
                        "type": "array",
                        "maxItems": 256,
                        "items": _closed(
                            {
                                "payloadSchema": {"type": "string", "maxLength": 160},
                                "projectRevision": {"type": "integer", "minimum": 1},
                                "artifactRevision": {"type": "integer", "minimum": 1},
                                "artifactDigest": {
                                    "type": "string",
                                    "pattern": "^[0-9a-f]{64}$",
                                },
                            },
                            [
                                "payloadSchema",
                                "projectRevision",
                                "artifactRevision",
                                "artifactDigest",
                            ],
                        ),
                    },
                    "parentCount": {"type": "integer", "minimum": 0},
                    "parentsTruncated": {"type": "boolean"},
                    "certificateKind": {
                        "type": "string",
                        "enum": [
                            "metadata_only",
                            "verification_summary",
                            "import_receipt_summary",
                            "package_summary",
                            "reliability_summary",
                            "card_plan_validation_summary",
                            "project_artifact_summary",
                            "media_summary",
                            "source_inspection_summary",
                        ],
                    },
                    "certificateSummary": _summary_schema(),
                    "knownLimitations": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 3,
                        "items": {"type": "string", "maxLength": 240},
                    },
                    "integrityVerified": {"type": "boolean", "const": True},
                },
                "required": [
                    "schemaVersion",
                    "artifactHandle",
                    "projectId",
                    "payloadSchema",
                    "payloadSchemaVersion",
                    "projectRevision",
                    "artifactRevision",
                    "artifactDigest",
                    "payloadSha256",
                    "inputFingerprint",
                    "createdAt",
                    "producer",
                    "completeness",
                    "issueRefs",
                    "parents",
                    "parentCount",
                    "parentsTruncated",
                    "certificateKind",
                    "certificateSummary",
                    "knownLimitations",
                    "integrityVerified",
                ],
                "additionalProperties": False,
            },
            "annotations": dict(annotations),
        },
    ]


def _artifact_handle(arguments: Any) -> str:
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"artifactHandle"}
        or not isinstance(arguments.get("artifactHandle"), str)
        or not _HANDLE_RE.fullmatch(arguments["artifactHandle"])
    ):
        raise McpArtifactToolInputError("artifact handle is invalid")
    return arguments["artifactHandle"]


def call_artifact_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    handle = _artifact_handle(arguments)
    if tool_name == GET_ARTIFACT_TOOL_NAME:
        structured = service.get_study_artifact(
            audience=audience_session.audience, artifact_handle=handle
        )
        text = (
            f"Verified {structured['payloadSchema']} artifact metadata and "
            f"{structured['contentKind']} content projection."
        )
    elif tool_name == GET_AUDIT_TOOL_NAME:
        structured = service.get_study_audit(
            audience=audience_session.audience, artifact_handle=handle
        )
        text = (
            f"Verified the {structured['payloadSchema']} artifact integrity and "
            "lineage certificate."
        )
    else:
        raise McpArtifactToolInputError("unknown artifact tool")
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }


__all__ = [
    "ARTIFACT_TOOL_NAMES",
    "GET_ARTIFACT_TOOL_NAME",
    "GET_AUDIT_TOOL_NAME",
    "McpArtifactToolInputError",
    "artifact_tool_definitions",
    "call_artifact_tool",
]
