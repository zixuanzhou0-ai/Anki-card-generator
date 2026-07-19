"""Authenticated, read-only Anki import planning from a verified PackageArtifact."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .anki_target_probe import AnkiTargetInspector, AnkiTargetProbeError
from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .package_artifact_runtime import (
    PackageArtifactRuntime,
    PackageArtifactRuntimeError,
)
from .project_registry import ProjectRegistry, ProjectRegistryError


ANKI_IMPORT_PLAN_POLICY_VERSION = "anki-import-plan-v1"
ANKI_DATA_VERIFICATION_CONTRACT_VERSION = "anki-data-v1"
REQUIRED_DATA_CHECKS = (
    "package_hash",
    "import_plan_binding",
    "profile_collection_identity",
    "deck_identity",
    "note_count",
    "card_count",
    "field_content",
    "template_hash",
    "media_manifest",
    "audio_media_evidence",
    "card_id_uniqueness",
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRODUCER = {
    "component": "card-service.anki-import-preparation",
    "version": "1.0.0",
}
_IMPORT_PLAN_FIELDS = {
    "schemaVersion",
    "projectRevision",
    "resultingProjectRevision",
    "packageArtifactRef",
    "packageArtifactDigest",
    "apkgFileRef",
    "apkgSha256",
    "sizeBytes",
    "fileName",
    "deckNames",
    "noteCount",
    "cardCount",
    "mediaCount",
    "cardIdentitySetRef",
    "cardIdentitySetDigest",
    "mediaManifestRef",
    "mediaManifestDigest",
    "cardMediaRoleInventoryRef",
    "cardMediaRoleInventoryDigest",
    "templateFamily",
    "templateSchemaVersion",
    "noteModelId",
    "compatibilityContractVersion",
    "frontTemplateSha256",
    "backTemplateSha256",
    "cssSha256",
    "target",
    "verificationContractRef",
    "verificationContractDigest",
    "requiredDataChecks",
    "duplicatePolicy",
    "writePolicy",
    "runtimeVerification",
    "recoveryPolicy",
    "policyVersion",
}


class AnkiImportPreparationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _identity(ref: Mapping[str, Any]) -> tuple[str, int, str]:
    return (
        str(ref.get("artifactId") or ""),
        int(ref.get("artifactRevision") or 0),
        str(ref.get("artifactDigest") or ""),
    )


def _target_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion",
        "profileRef",
        "configurationFingerprint",
        "credentialRevision",
        "ankiConnectVersion",
        "profileIdentityDigest",
        "collectionIdentityDigest",
        "deckInventoryDigest",
        "deckCount",
        "transportAuthentication",
        "observedAt",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise AnkiImportPreparationError(
            "ANKI_TARGET_INVALID", "Anki target snapshot fields are invalid"
        )
    for field in (
        "configurationFingerprint",
        "profileIdentityDigest",
        "collectionIdentityDigest",
        "deckInventoryDigest",
    ):
        if not isinstance(value[field], str) or not _SHA256_RE.fullmatch(value[field]):
            raise AnkiImportPreparationError(
                "ANKI_TARGET_INVALID", "Anki target snapshot digest is invalid"
            )
    if (
        value["schemaVersion"] != 1
        or not isinstance(value["profileRef"], str)
        or not re.fullmatch(r"anki_current_[0-9a-f]{32}", value["profileRef"])
        or isinstance(value["credentialRevision"], bool)
        or value["credentialRevision"] != 0
        or isinstance(value["ankiConnectVersion"], bool)
        or not isinstance(value["ankiConnectVersion"], int)
        or not 5 <= value["ankiConnectVersion"] <= 6
        or isinstance(value["deckCount"], bool)
        or not isinstance(value["deckCount"], int)
        or not 0 <= value["deckCount"] <= 100_000
        or value["transportAuthentication"] != "none"
        or isinstance(value["observedAt"], bool)
        or not isinstance(value["observedAt"], int)
        or value["observedAt"] <= 0
    ):
        raise AnkiImportPreparationError(
            "ANKI_TARGET_INVALID", "Anki target snapshot is invalid"
        )
    return {
        "schemaVersion": 1,
        "profileRef": value["profileRef"],
        "configurationFingerprint": value["configurationFingerprint"],
        "credentialRevision": 0,
        "ankiConnectVersion": value["ankiConnectVersion"],
        "profileIdentityDigest": value["profileIdentityDigest"],
        "collectionIdentityDigest": value["collectionIdentityDigest"],
        "deckInventoryDigest": value["deckInventoryDigest"],
        "deckCount": value["deckCount"],
        "transportAuthentication": "none",
    }


def _validated_plan_payload(value: Any, *, project_revision: int) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _IMPORT_PLAN_FIELDS:
        raise AnkiImportPreparationError(
            "IMPORT_PLAN_INVALID", "ImportPlan payload fields are invalid"
        )
    payload = dict(value)
    for field in (
        "packageArtifactDigest",
        "apkgSha256",
        "cardIdentitySetDigest",
        "mediaManifestDigest",
        "cardMediaRoleInventoryDigest",
        "frontTemplateSha256",
        "backTemplateSha256",
        "cssSha256",
        "verificationContractDigest",
    ):
        if not isinstance(payload[field], str) or not _SHA256_RE.fullmatch(
            payload[field]
        ):
            raise AnkiImportPreparationError(
                "IMPORT_PLAN_INVALID", "ImportPlan digest is invalid"
            )
    if any(
        isinstance(payload[field], bool)
        or not isinstance(payload[field], int)
        or payload[field]
        < (1 if field in {"sizeBytes", "noteCount", "cardCount"} else 0)
        for field in ("sizeBytes", "noteCount", "cardCount", "mediaCount")
    ):
        raise AnkiImportPreparationError(
            "IMPORT_PLAN_INVALID", "ImportPlan package counts are invalid"
        )
    decks = payload["deckNames"]
    if (
        payload["schemaVersion"] != 1
        or payload["projectRevision"] != project_revision
        or payload["resultingProjectRevision"] != project_revision + 1
        or not isinstance(payload["fileName"], str)
        or not payload["fileName"].endswith(".apkg")
        or "/" in payload["fileName"]
        or "\\" in payload["fileName"]
        or not isinstance(decks, list)
        or not decks
        or len(decks) > 256
        or any(not isinstance(deck, str) or not deck for deck in decks)
        or payload["requiredDataChecks"] != list(REQUIRED_DATA_CHECKS)
        or payload["duplicatePolicy"] != "detect_and_report"
        or payload["writePolicy"] != "explicit-confirmation-required"
        or payload["runtimeVerification"] != "not_assessed"
        or payload["recoveryPolicy"] != "inspect-before-any-retry"
        or payload["policyVersion"] != ANKI_IMPORT_PLAN_POLICY_VERSION
    ):
        raise AnkiImportPreparationError(
            "IMPORT_PLAN_INVALID", "ImportPlan contract is invalid"
        )
    target = payload["target"]
    if not isinstance(target, Mapping):
        raise AnkiImportPreparationError(
            "IMPORT_PLAN_INVALID", "ImportPlan target is invalid"
        )
    payload["target"] = _target_snapshot({**dict(target), "observedAt": 1})
    return payload


class AnkiImportPreparationRuntime:
    """Freeze an ImportPlan without performing any Anki write action."""

    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        packages: PackageArtifactRuntime,
        target_inspector: AnkiTargetInspector,
    ) -> None:
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._packages = packages
        self._target_inspector = target_inspector

    def _public_plan(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_plan_handle: str,
    ) -> dict[str, Any]:
        try:
            ref, envelope = self._artifacts.resolve_with_ref(
                import_plan_handle, audience
            )
            if envelope.get("payloadSchema") != "study.anki-import-plan":
                raise AnkiImportPreparationError(
                    "IMPORT_PLAN_INVALID", "ImportPlan handle has the wrong schema"
                )
            payload = _validated_plan_payload(
                envelope.get("payload"), project_revision=ref["projectRevision"]
            )
            project = self._projects.get_project(ref["projectId"], audience)
            current_plans = {
                _identity(value)
                for value in project.get("latestArtifactRefs", [])
                if isinstance(value, Mapping)
                and value.get("payloadSchema") == "study.anki-import-plan"
            }
            if (
                _identity(ref) not in current_plans
                or project.get("workflow", {}).get("artifactStage")
                not in {
                    "apkg_ready",
                    "imported_unverified",
                    "anki_data_verified",
                    "anki_verified",
                }
                or project.get("projectRevision", 0)
                < payload.get("resultingProjectRevision", 0)
            ):
                raise AnkiImportPreparationError(
                    "IMPORT_PLAN_STALE", "ImportPlan is not current"
                )
            target = payload["target"]
            return {
                "schemaVersion": 1,
                "importPlanHandle": import_plan_handle,
                "artifactStage": "apkg_ready",
                "projectRevision": payload["resultingProjectRevision"],
                "package": {
                    "apkgSha256": payload["apkgSha256"],
                    "sizeBytes": payload["sizeBytes"],
                    "fileName": payload["fileName"],
                    "deckNames": list(payload["deckNames"]),
                    "noteCount": payload["noteCount"],
                    "cardCount": payload["cardCount"],
                    "mediaCount": payload["mediaCount"],
                },
                "target": {
                    "profileRef": target["profileRef"],
                    "ankiConnectVersion": target["ankiConnectVersion"],
                    "deckCount": target["deckCount"],
                    "transportAuthentication": target["transportAuthentication"],
                },
                "duplicatePolicy": payload["duplicatePolicy"],
                "dataVerificationCheckCount": len(payload["requiredDataChecks"]),
                "runtimeVerification": "not_assessed",
                "confirmationRequired": True,
                "nextAction": "request_import_confirmation",
            }
        except (ArtifactRegistryError, ProjectRegistryError) as error:
            raise AnkiImportPreparationError(error.code, error.message) from error

    def prepare(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        package_artifact_handle: str,
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not _ID_RE.fullmatch(
            idempotency_key
        ):
            raise AnkiImportPreparationError(
                "IMPORT_PLAN_REQUEST_INVALID", "idempotencyKey is invalid"
            )
        try:
            resolved = self._packages.resolve_current_package_artifact(
                audience=audience,
                package_artifact_handle=package_artifact_handle,
            )
        except PackageArtifactRuntimeError as error:
            raise AnkiImportPreparationError(error.code, error.message) from error
        project = resolved["project"]
        package_ref = resolved["packageRef"]
        package = resolved["packagePayload"]
        if project.get("projectId") != project_id:
            raise AnkiImportPreparationError(
                "IMPORT_PLAN_PROJECT_MISMATCH",
                "PackageArtifact belongs to another project",
            )
        operation_id = "anki-prepare:" + idempotency_key
        operation_digest = _digest(
            {
                "schema": "study.anki-import-plan.request",
                "schemaVersion": 1,
                "projectId": project_id,
                "expectedProjectRevision": expected_project_revision,
                "packageArtifactDigest": package_ref["artifactDigest"],
                "policyVersion": ANKI_IMPORT_PLAN_POLICY_VERSION,
            }
        )
        try:
            prior = self._projects.get_operation_result(
                audience=audience,
                project_id=project_id,
                operation_id=operation_id,
                operation_digest=operation_digest,
            )
            if prior is not None:
                handles = prior.get("artifactHandles")
                if not isinstance(handles, list) or len(handles) != 1:
                    raise AnkiImportPreparationError(
                        "IMPORT_PLAN_INVALID", "Saved ImportPlan result is invalid"
                    )
                return self._public_plan(
                    audience=audience, import_plan_handle=handles[0]
                )
        except ProjectRegistryError as error:
            raise AnkiImportPreparationError(error.code, error.message) from error
        if project.get("projectRevision") != expected_project_revision:
            raise AnkiImportPreparationError(
                "PROJECT_REVISION_CONFLICT", "project changed before import planning"
            )
        if project.get("workflow", {}).get("artifactStage") != "apkg_ready":
            raise AnkiImportPreparationError(
                "IMPORT_PLAN_STAGE_CONFLICT", "Anki import planning is not current"
            )
        try:
            target = _target_snapshot(self._target_inspector())
        except AnkiTargetProbeError as error:
            raise AnkiImportPreparationError(error.code, error.message) from error
        contract_core = {
            "schemaVersion": 1,
            "contractVersion": ANKI_DATA_VERIFICATION_CONTRACT_VERSION,
            "requiredDataChecks": list(REQUIRED_DATA_CHECKS),
            "duplicatePolicy": "detect_and_report",
            "runtimeVerification": "not_assessed",
        }
        contract_payload = {
            **contract_core,
            "contractDigest": _digest(contract_core),
        }
        input_fingerprint = _digest(
            {
                "packageArtifactDigest": package_ref["artifactDigest"],
                "target": target,
                "contractDigest": contract_payload["contractDigest"],
                "policyVersion": ANKI_IMPORT_PLAN_POLICY_VERSION,
            }
        )
        try:
            contract_publication = self._artifacts.publish_idempotent(
                audience=audience,
                project_id=project_id,
                project_revision=expected_project_revision,
                artifact_id="anki_verification_contract_" + operation_digest[:40],
                artifact_revision=1,
                payload_schema="study.anki-verification-contract",
                payload_schema_version=1,
                payload=contract_payload,
                producer=_PRODUCER,
                parents=[package_ref],
                input_fingerprint=input_fingerprint,
                completeness={
                    "state": "complete",
                    "omittedLocators": [],
                    "reasonCodes": [],
                },
                issue_refs=[],
            )
            plan_payload = {
                "schemaVersion": 1,
                "projectRevision": expected_project_revision,
                "resultingProjectRevision": expected_project_revision + 1,
                "packageArtifactRef": _clone(package_ref),
                "packageArtifactDigest": package_ref["artifactDigest"],
                "apkgFileRef": _clone(resolved["fileRef"]),
                "apkgSha256": package["apkgSha256"],
                "sizeBytes": package["sizeBytes"],
                "fileName": package["fileName"],
                "deckNames": list(package["deckNames"]),
                "noteCount": package["noteCount"],
                "cardCount": package["cardCount"],
                "mediaCount": package["mediaCount"],
                "cardIdentitySetRef": _clone(package["cardIdentitySetRef"]),
                "cardIdentitySetDigest": package["cardIdentitySetDigest"],
                "mediaManifestRef": _clone(package["mediaManifestRef"]),
                "mediaManifestDigest": package["mediaManifestDigest"],
                "cardMediaRoleInventoryRef": _clone(
                    package["cardMediaRoleInventoryRef"]
                ),
                "cardMediaRoleInventoryDigest": package["cardMediaRoleInventoryDigest"],
                "templateFamily": package["templateFamily"],
                "templateSchemaVersion": package["templateSchemaVersion"],
                "noteModelId": package["noteModelId"],
                "compatibilityContractVersion": package["compatibilityContractVersion"],
                "frontTemplateSha256": package["frontTemplateSha256"],
                "backTemplateSha256": package["backTemplateSha256"],
                "cssSha256": package["cssSha256"],
                "target": target,
                "verificationContractRef": _clone(contract_publication.artifact_ref),
                "verificationContractDigest": contract_payload["contractDigest"],
                "requiredDataChecks": list(REQUIRED_DATA_CHECKS),
                "duplicatePolicy": "detect_and_report",
                "writePolicy": "explicit-confirmation-required",
                "runtimeVerification": "not_assessed",
                "recoveryPolicy": "inspect-before-any-retry",
                "policyVersion": ANKI_IMPORT_PLAN_POLICY_VERSION,
            }
            plan_publication = self._artifacts.publish_idempotent(
                audience=audience,
                project_id=project_id,
                project_revision=expected_project_revision,
                artifact_id="anki_import_plan_" + operation_digest[:40],
                artifact_revision=1,
                payload_schema="study.anki-import-plan",
                payload_schema_version=1,
                payload=plan_payload,
                producer=_PRODUCER,
                parents=[
                    package_ref,
                    resolved["fileRef"],
                    package["cardIdentitySetRef"],
                    package["mediaManifestRef"],
                    package["cardMediaRoleInventoryRef"],
                    contract_publication.artifact_ref,
                ],
                input_fingerprint=input_fingerprint,
                completeness={
                    "state": "complete",
                    "expectedUnits": package["cardCount"],
                    "processedUnits": package["cardCount"],
                    "omittedLocators": [],
                    "reasonCodes": [],
                },
                issue_refs=[],
            )
            committed = self._projects.commit_artifact_stage(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                operation_id=operation_id,
                operation_digest=operation_digest,
                task_id="task_anki_prepare_" + operation_digest[:40],
                artifact_stage="apkg_ready",
                artifact_refs=[plan_publication.artifact_ref],
                artifact_handles=[plan_publication.handle],
            )
            return self._public_plan(
                audience=audience,
                import_plan_handle=committed["artifactHandles"][0],
            )
        except (ArtifactRegistryError, ProjectRegistryError) as error:
            raise AnkiImportPreparationError(error.code, error.message) from error


__all__ = [
    "ANKI_DATA_VERIFICATION_CONTRACT_VERSION",
    "ANKI_IMPORT_PLAN_POLICY_VERSION",
    "REQUIRED_DATA_CHECKS",
    "AnkiImportPreparationError",
    "AnkiImportPreparationRuntime",
]
