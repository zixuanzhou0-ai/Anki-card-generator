"""Bounded public projections over authenticated Study artifacts.

The Artifact Registry stores internal references and potentially large payloads.
This module deliberately exposes neither.  Callers receive integrity metadata and
small, schema-specific summaries only after the opaque handle has been verified
against the current trusted audience.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .artifact_registry import ArtifactAudienceBinding, ArtifactRegistry


_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,159}$")


class ArtifactQueryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _text(value: Any, *, default: str = "", maximum: int = 160) -> str:
    if not isinstance(value, str):
        return default[:maximum]
    return value[:maximum]


def _hex_digest(value: Any) -> str:
    return (
        value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else ""
    )


def _strings(value: Any, *, maximum: int = 64) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:160] for item in value[:maximum] if isinstance(item, str)]


def _count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _codes(value: Any, *, maximum: int = 64) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value[:maximum]
        if isinstance(item, str) and _CODE_RE.fullmatch(item)
    ]


def _public_producer(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "component": str(value.get("component") or "")[:128],
        "version": str(value.get("version") or "")[:128],
    }


def _public_completeness(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "state": str(value.get("state") or "unknown")[:32],
        "expectedUnits": _integer(value.get("expectedUnits")),
        "processedUnits": _integer(value.get("processedUnits")),
        "omittedCount": (
            _integer(value.get("omittedUnits"))
            if value.get("omittedUnits") is not None
            else _count(value.get("omittedLocators"))
        ),
        "reasonCodes": _codes(value.get("reasonCodes")),
    }


def _public_payload_summary(schema: str, payload: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return "metadata_only", {}
    value = payload
    if schema == "study.anki-verification":
        return "verification_summary", {
            "dataVerification": _text(value.get("dataVerification"), default="unknown"),
            "runtimeVerification": _text(
                value.get("runtimeVerification"), default="not_assessed"
            ),
            "importDisposition": _text(
                value.get("importDisposition"), default="unknown"
            ),
            "importAttempted": value.get("importAttempted") is True,
            "importSucceeded": value.get("importSucceeded") is True,
            "noteCount": _integer(value.get("noteCount")),
            "cardCount": _integer(value.get("cardCount")),
            "expectedCardCount": _integer(value.get("expectedCardCount")),
            "mediaCountExpected": _integer(value.get("mediaCountExpected")),
            "mediaCountChecked": _integer(value.get("mediaCountChecked")),
            "duplicateCardCount": _integer(value.get("duplicateCardCount")),
            "failedChecks": _codes(value.get("failedChecks")),
            "verificationContractVersion": _text(
                value.get("verificationContractVersion")
            ),
            "policyVersion": _text(value.get("policyVersion")),
        }
    if schema == "study.anki-import-receipt":
        return "import_receipt_summary", {
            "importDisposition": _text(
                value.get("importDisposition"), default="unknown"
            ),
            "importAttempted": value.get("importAttempted") is True,
            "importSucceeded": value.get("importSucceeded") is True,
            "writeBoundaryState": _text(
                value.get("writeBoundaryState"), default="unknown"
            ),
            "apkgSha256": _hex_digest(value.get("apkgSha256")),
            "targetDigest": _hex_digest(value.get("targetDigest")),
            "policyVersion": _text(value.get("policyVersion")),
        }
    if schema == "study.package-artifact":
        return "package_summary", {
            "fileName": _text(value.get("fileName"), maximum=240),
            "apkgSha256": _hex_digest(value.get("apkgSha256")),
            "sizeBytes": _integer(value.get("sizeBytes")),
            "deckNames": _strings(value.get("deckNames"), maximum=32),
            "noteCount": _integer(value.get("noteCount")),
            "cardCount": _integer(value.get("cardCount")),
            "mediaCount": _integer(value.get("mediaCount")),
            "templateFamily": _text(value.get("templateFamily")),
            "templateSchemaVersion": _text(value.get("templateSchemaVersion")),
            "noteModelId": _text(value.get("noteModelId")),
            "compatibilityContractVersion": _text(
                value.get("compatibilityContractVersion")
            ),
            "frontTemplateSha256": _hex_digest(value.get("frontTemplateSha256")),
            "backTemplateSha256": _hex_digest(value.get("backTemplateSha256")),
            "cssSha256": _hex_digest(value.get("cssSha256")),
        }
    if schema == "study.reliability-manifest":
        return "reliability_summary", {
            "decision": _text(value.get("decision"), default="unknown"),
            "accountingComplete": value.get("accounting_complete") is True,
            "selectedPointCount": _integer(value.get("selected_point_count")),
            "verifiedCount": _integer(value.get("verified_count")),
            "needsReviewCount": _integer(value.get("needs_review_count")),
            "hardFailedCount": _integer(value.get("hard_failed_count")),
            "blockerCodes": _codes(value.get("blocker_codes")),
            "verificationProfile": _text(value.get("verification_profile")),
            "ruleSetVersion": _text(value.get("ruleSetVersion")),
        }
    if schema == "study.card-plan-validation":
        records = value.get("records")
        eligible = value.get("eligibleCardPlanRefs")
        blocked = value.get("blockedCardPlanRefs")
        return "card_plan_validation_summary", {
            "validationId": _text(value.get("validationId")),
            "ruleSetVersion": _text(value.get("ruleSetVersion")),
            "recordCount": _count(records),
            "eligibleCount": _count(eligible),
            "blockedCount": _count(blocked),
        }
    if schema == "study.project-artifact":
        return "project_artifact_summary", {
            "cardCount": _count(value.get("cardIds")),
            "cardPlanCount": _count(value.get("cardPlanRefs")),
        }
    if schema == "study.media-ledger":
        return "media_summary", {
            "state": _text(value.get("state"), default="unknown"),
            "mediaCount": _integer(value.get("mediaCount")),
            "cardCount": _count(value.get("cards")),
            "policyVersion": _text(value.get("policyVersion")),
        }
    if schema in {"study.source-inspection", "study.inspection"}:
        return "source_inspection_summary", {
            "sourceCount": _count(value.get("sources")),
            "inspectionCount": _count(value.get("inspections")),
            "issueCount": _count(value.get("issues")),
            "state": _text(value.get("state"), default="complete", maximum=64),
        }
    return "metadata_only", {}


def _parent_summaries(envelope: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    parents = envelope.get("parents")
    if not isinstance(parents, list):
        raise ArtifactQueryError(
            "ARTIFACT_ENVELOPE_INVALID", "Artifact parent metadata is invalid"
        )
    result: list[dict[str, Any]] = []
    for parent in parents[:256]:
        if not isinstance(parent, Mapping):
            raise ArtifactQueryError(
                "ARTIFACT_ENVELOPE_INVALID", "Artifact parent metadata is invalid"
            )
        result.append(
            {
                "payloadSchema": str(parent.get("payloadSchema") or "")[:160],
                "projectRevision": _integer(parent.get("projectRevision")),
                "artifactRevision": _integer(parent.get("artifactRevision")),
                "artifactDigest": str(parent.get("artifactDigest") or "")[:64],
            }
        )
    return result, len(parents)


class ArtifactQueryRuntime:
    def __init__(self, *, artifacts: ArtifactRegistry) -> None:
        self._artifacts = artifacts

    def get_artifact(
        self, *, audience: ArtifactAudienceBinding, artifact_handle: str
    ) -> dict[str, Any]:
        envelope = self._artifacts.resolve(artifact_handle, audience)
        schema = str(envelope.get("payloadSchema") or "")
        content_kind, summary = _public_payload_summary(schema, envelope.get("payload"))
        return {
            "schemaVersion": 1,
            "artifactHandle": artifact_handle,
            "projectId": str(envelope.get("projectId") or ""),
            "projectRevision": _integer(envelope.get("projectRevision")),
            "artifactRevision": _integer(envelope.get("artifactRevision")),
            "payloadSchema": schema,
            "payloadSchemaVersion": _integer(envelope.get("payloadSchemaVersion")),
            "artifactDigest": str(envelope.get("artifactDigest") or ""),
            "payloadSha256": str(envelope.get("payloadSha256") or ""),
            "createdAt": str(envelope.get("createdAt") or ""),
            "contentKind": content_kind,
            "summary": summary,
            "parentCount": len(envelope.get("parents") or []),
            "issueCount": len(envelope.get("issueRefs") or []),
        }

    def get_audit(
        self, *, audience: ArtifactAudienceBinding, artifact_handle: str
    ) -> dict[str, Any]:
        envelope = self._artifacts.resolve(artifact_handle, audience)
        schema = str(envelope.get("payloadSchema") or "")
        content_kind, summary = _public_payload_summary(schema, envelope.get("payload"))
        completeness = envelope.get("completeness")
        producer = envelope.get("producer")
        issue_refs = envelope.get("issueRefs")
        if (
            not isinstance(completeness, Mapping)
            or not isinstance(producer, Mapping)
            or not isinstance(issue_refs, list)
            or any(not isinstance(value, str) for value in issue_refs)
        ):
            raise ArtifactQueryError(
                "ARTIFACT_ENVELOPE_INVALID", "Artifact audit metadata is invalid"
            )
        limitations = [
            "Authenticated artifact integrity does not by itself prove external semantic truth."
        ]
        if (
            schema == "study.anki-verification"
            and summary.get("runtimeVerification") != "fully_verified"
        ):
            limitations.append(
                "Anki reviewer rendering, playback, focus behavior, and restart-review persistence were not fully verified."
            )
        if content_kind == "metadata_only":
            limitations.append(
                "This schema exposes integrity metadata only; use its dedicated review tool for content."
            )
        parents, parent_count = _parent_summaries(envelope)
        return {
            "schemaVersion": 1,
            "artifactHandle": artifact_handle,
            "projectId": str(envelope.get("projectId") or ""),
            "payloadSchema": schema,
            "payloadSchemaVersion": _integer(envelope.get("payloadSchemaVersion")),
            "projectRevision": _integer(envelope.get("projectRevision")),
            "artifactRevision": _integer(envelope.get("artifactRevision")),
            "artifactDigest": str(envelope.get("artifactDigest") or ""),
            "payloadSha256": str(envelope.get("payloadSha256") or ""),
            "inputFingerprint": str(envelope.get("inputFingerprint") or ""),
            "createdAt": str(envelope.get("createdAt") or ""),
            "producer": _public_producer(producer),
            "completeness": _public_completeness(completeness),
            "issueRefs": _codes(issue_refs, maximum=256),
            "parents": parents,
            "parentCount": parent_count,
            "parentsTruncated": parent_count > len(parents),
            "certificateKind": content_kind,
            "certificateSummary": summary,
            "knownLimitations": limitations,
            "integrityVerified": True,
        }


__all__ = ["ArtifactQueryError", "ArtifactQueryRuntime"]
