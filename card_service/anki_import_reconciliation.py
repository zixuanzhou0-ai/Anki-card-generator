"""Read-only reconciliation of an authenticated Anki ImportPlan.

This runtime never calls ``importPackage``.  It classifies the current Anki
state as present, absent, partial, or unknown and only promotes a project when
the existing data passes the complete verification contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Protocol

from .anki_import_execution import (
    AnkiImportExecutionError,
    AnkiImportExecutionRuntime,
)
from .anki_import_preparation import (
    ANKI_DATA_VERIFICATION_CONTRACT_VERSION,
    AnkiImportPreparationError,
    AnkiImportPreparationRuntime,
)
from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .project_registry import ProjectRegistry, ProjectRegistryError
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


ANKI_IMPORT_RECONCILIATION_POLICY_VERSION = "anki-import-reconciliation-v1"
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PRODUCER = {
    "component": "card-service.anki-import-reconciliation",
    "version": "1.0.0",
    "policyVersion": ANKI_IMPORT_RECONCILIATION_POLICY_VERSION,
}
_COMPONENTS = {
    "cardService": "2.0.0",
    "worker": "managed-worker",
    "sourceAdapterSetDigest": hashlib.sha256(
        b"study.anki-import-reconciliation.source-adapters.v1"
    ).hexdigest(),
    "gateRuleSetVersion": ANKI_IMPORT_RECONCILIATION_POLICY_VERSION,
    "compatibilityContractVersion": ANKI_DATA_VERIFICATION_CONTRACT_VERSION,
}
_UNKNOWN_CHECKS = frozenset(
    {
        "anki_connect",
        "apkg_integrity_changed_before_import",
        "apkg_export_contract_invalid",
    }
)


class AnkiImportReconciliationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AnkiImportInspector(Protocol):
    def __call__(self, bundle: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _reason_codes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["inspection_result_invalid"]
    result: list[str] = []
    for item in value:
        if (
            isinstance(item, str)
            and re.fullmatch(r"[a-z][a-z0-9_]{0,95}", item)
            and item not in result
        ):
            result.append(item)
        if len(result) >= 32:
            break
    return result


class AnkiImportReconciliationRuntime:
    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        tasks: StudyTaskCoordinator,
        preparation: AnkiImportPreparationRuntime,
        execution: AnkiImportExecutionRuntime,
        inspector: AnkiImportInspector,
    ) -> None:
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._tasks = tasks
        self._preparation = preparation
        self._execution = execution
        self._inspector = inspector

    @staticmethod
    def _classification(
        result: Mapping[str, Any], plan: Mapping[str, Any]
    ) -> dict[str, Any]:
        failed = _reason_codes(result.get("failed_checks"))
        expected_cards = int(plan["cardCount"])
        expected_media = int(plan["mediaCount"])
        verified_cards = _integer(result.get("card_count"))
        imported_cards = _integer(result.get("imported_card_count"))
        media_expected = _integer(result.get("media_count_expected"))
        media_checked = _integer(result.get("media_count_checked"))
        query_observed = bool(str(result.get("query") or "").strip())
        complete = (
            result.get("ok") is True
            and not failed
            and verified_cards == expected_cards
            and imported_cards == expected_cards
            and media_expected == expected_media
            and media_checked is not None
            and 0 <= media_checked <= expected_media
            and query_observed
        )
        if complete:
            state = "present"
            reasons: list[str] = []
        elif (
            query_observed
            and "no_imported_cards" in failed
            and (verified_cards or 0) == 0
            and (imported_cards or 0) == 0
            and not (_UNKNOWN_CHECKS & set(failed))
        ):
            state = "absent"
            reasons = ["no_imported_cards"]
        elif (verified_cards or 0) > 0 or (imported_cards or 0) > 0:
            state = "partial"
            reasons = failed or ["incomplete_authenticated_card_set"]
        else:
            state = "unknown"
            reasons = failed or ["inspection_inconclusive"]
        return {
            "state": state,
            "reasonCodes": reasons,
            "expectedCardCount": expected_cards,
            "observedCardCount": max(verified_cards or 0, imported_cards or 0),
            "expectedMediaCount": expected_media,
            "checkedMediaCount": media_checked if media_checked is not None else 0,
        }

    def _current_receipt(
        self,
        *,
        audience: ArtifactAudienceBinding,
        resolved: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        project = resolved["project"]
        plan_ref = resolved["importPlanRef"]
        plan = resolved["importPlanPayload"]
        target_digest = _digest(plan["target"])
        matches: list[dict[str, Any]] = []
        for ref in project.get("latestArtifactRefs", []):
            if not isinstance(ref, Mapping) or ref.get("payloadSchema") not in {
                "study.anki-import-receipt",
                "study.anki-reconciliation-receipt",
            }:
                continue
            envelope = self._artifacts.verify_ref(ref, audience)
            payload = envelope.get("payload")
            if not isinstance(payload, Mapping):
                raise AnkiImportReconciliationError(
                    "ARTIFACT_CORRUPT", "Anki receipt payload is invalid"
                )
            if (
                payload.get("importPlanDigest") == plan_ref["artifactDigest"]
                and payload.get("apkgSha256") == plan["apkgSha256"]
            ):
                schema = str(ref.get("payloadSchema") or "")
                if payload.get("targetDigest") != target_digest:
                    raise AnkiImportReconciliationError(
                        "ARTIFACT_CORRUPT", "Anki receipt target digest is invalid"
                    )
                if schema == "study.anki-import-receipt" and not (
                    payload.get("writeBoundaryState") == "observed_complete"
                    and payload.get("importSucceeded") is True
                ):
                    raise AnkiImportReconciliationError(
                        "ARTIFACT_CORRUPT", "Anki import receipt is incomplete"
                    )
                if schema == "study.anki-reconciliation-receipt" and not (
                    payload.get("writeBoundaryState") == "observed_existing"
                    and payload.get("presenceState") == "present"
                ):
                    raise AnkiImportReconciliationError(
                        "ARTIFACT_CORRUPT", "Anki reconciliation receipt is incomplete"
                    )
                matches.append({"ref": dict(ref), "payload": dict(payload)})
        stage = project.get("workflow", {}).get("artifactStage")
        if stage == "imported_unverified" and len(matches) != 1:
            raise AnkiImportReconciliationError(
                "ARTIFACT_CORRUPT",
                "Imported-unverified state requires one authenticated receipt",
            )
        if len(matches) > 1:
            raise AnkiImportReconciliationError(
                "ARTIFACT_CORRUPT", "Anki receipt lineage is ambiguous"
            )
        return matches[0] if matches else None

    def _fail_active_task(
        self,
        *,
        audience: ArtifactAudienceBinding,
        task_id: str | None,
        operation_digest: str | None,
        code: str,
    ) -> None:
        if task_id is None:
            return
        safe_code = code if code in {
            "ANKI_OFFLINE",
            "ANKI_VERIFY_FAILED",
            "ARTIFACT_CORRUPT",
            "INPUT_REVISION_MISMATCH",
            "IMPORT_CONFLICT",
            "PACKAGE_VERIFY_FAILED",
        } else "INTERNAL_UNCLASSIFIED"
        try:
            task = self._tasks.get_task(task_id, audience)
            if task.get("state") not in {"running", "cancelling"}:
                return
            suffix = (operation_digest or _digest({"taskId": task_id}))[:40]
            self._tasks.fail_task(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="fail-" + suffix,
                code=safe_code,
                stage="anki_data_verification",
                retryable=safe_code in {"ANKI_OFFLINE", "ANKI_VERIFY_FAILED"},
                remote_cost_state="none",
                retry_scope="whole_task",
                authorization_state="not_required",
                required_action="resolve_issue",
            )
        except (StudyTaskError, ArtifactRegistryError):
            # Preserve the original failure. A later recovery scan can still
            # quarantine an unfinishable task record.
            return

    def _manifests(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        plan_ref: Mapping[str, Any],
        target_digest: str,
        operation_digest: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        subject = {
            "kind": "project_task",
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "inputArtifacts": [
                {
                    "artifactId": plan_ref["artifactId"],
                    "artifactRevision": plan_ref["artifactRevision"],
                    "artifactDigest": plan_ref["artifactDigest"],
                }
            ],
            "sourceSnapshotDigests": [],
            "learningContractRevision": project["learningContract"][
                "contractRevision"
            ],
        }
        work, work_digest = build_work_reuse_manifest(
            action_id="resolve_anki_conflict",
            subject=subject,
            component_versions=_COMPONENTS,
            service_configurations=[],
            work_partition_policy_digest=operation_digest,
        )
        capability, capability_digest = build_capability_binding(
            [
                {
                    "kind": "fixed",
                    "capabilityId": "runtime.card_service",
                    "implementationVersionOrDigest": "2.0.0",
                    "compatibilityContractVersion": ANKI_IMPORT_RECONCILIATION_POLICY_VERSION,
                },
                {
                    "kind": "fixed",
                    "capabilityId": "runtime.worker",
                    "implementationVersionOrDigest": "managed-worker",
                    "compatibilityContractVersion": ANKI_DATA_VERIFICATION_CONTRACT_VERSION,
                },
                {
                    "kind": "fixed",
                    "capabilityId": "service.anki",
                    "implementationVersionOrDigest": target_digest,
                    "compatibilityContractVersion": "ankiconnect-v6-read-only",
                },
            ]
        )
        authorization, authorization_digest = build_authorization_binding(
            audience=audience,
            service_instance_id=self._service_instance_id,
            bindings=[],
        )
        task_input, fingerprint = build_task_input_manifest(
            action_id="resolve_anki_conflict",
            work_reuse_manifest=work,
            work_reuse_digest=work_digest,
            subject=subject,
            authorization_binding_digest=authorization_digest,
            capability_binding_digest=capability_digest,
            component_versions=_COMPONENTS,
            service_bindings=[],
            operation_intent_digest=operation_digest,
            batch_policy_digest=_digest(
                {"policy": ANKI_IMPORT_RECONCILIATION_POLICY_VERSION}
            ),
        )
        return work, task_input, capability, authorization, fingerprint

    def _publish_observation(
        self,
        *,
        audience: ArtifactAudienceBinding,
        resolved: Mapping[str, Any],
        operation_digest: str,
        classification: Mapping[str, Any],
        target_digest: str,
        receipt: Mapping[str, Any] | None,
    ):
        project = resolved["project"]
        plan_ref = resolved["importPlanRef"]
        plan = resolved["importPlanPayload"]
        payload = {
            "schemaVersion": 1,
            "projectRevision": project["projectRevision"],
            "importPlanRef": _clone(plan_ref),
            "importPlanDigest": plan_ref["artifactDigest"],
            "apkgSha256": plan["apkgSha256"],
            "targetDigest": target_digest,
            "reconciliationState": classification["state"],
            "reasonCodes": list(classification["reasonCodes"]),
            "expectedCardCount": classification["expectedCardCount"],
            "observedCardCount": classification["observedCardCount"],
            "expectedMediaCount": classification["expectedMediaCount"],
            "checkedMediaCount": classification["checkedMediaCount"],
            "receiptObserved": receipt is not None,
            "dataVerification": "not_verified",
            "runtimeVerification": "not_assessed",
            "policyVersion": ANKI_IMPORT_RECONCILIATION_POLICY_VERSION,
        }
        parents = [plan_ref]
        if receipt is not None:
            parents.append(receipt["ref"])
        return self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project["projectId"],
            project_revision=project["projectRevision"],
            artifact_id="anki_reconciliation_" + operation_digest[:40],
            artifact_revision=1,
            payload_schema="study.anki-reconciliation",
            payload_schema_version=1,
            payload=payload,
            producer=_PRODUCER,
            parents=parents,
            input_fingerprint=operation_digest,
            completeness={
                "state": (
                    "unknown"
                    if classification["state"] == "unknown"
                    else "partial_declared"
                ),
                "expectedUnits": classification["expectedCardCount"],
                "processedUnits": classification["observedCardCount"],
                "omittedLocators": [],
                "reasonCodes": list(classification["reasonCodes"]),
            },
            issue_refs=[],
        )

    def _promote_present(
        self,
        *,
        audience: ArtifactAudienceBinding,
        resolved: Mapping[str, Any],
        task_id: str,
        operation_id: str,
        operation_digest: str,
        classification: Mapping[str, Any],
        target_digest: str,
        receipt: Mapping[str, Any] | None,
    ):
        current = resolved
        project = current["project"]
        plan_ref = current["importPlanRef"]
        plan = current["importPlanPayload"]
        stage = project.get("workflow", {}).get("artifactStage")
        if stage == "apkg_ready":
            receipt_payload = {
                "schemaVersion": 1,
                "projectRevision": project["projectRevision"],
                "resultingProjectRevision": project["projectRevision"] + 1,
                "importPlanRef": _clone(plan_ref),
                "importPlanDigest": plan_ref["artifactDigest"],
                "apkgSha256": plan["apkgSha256"],
                "targetDigest": target_digest,
                "presenceState": "present",
                "writeBoundaryState": "observed_existing",
                "policyVersion": ANKI_IMPORT_RECONCILIATION_POLICY_VERSION,
            }
            receipt_publication = self._artifacts.publish_idempotent(
                audience=audience,
                project_id=project["projectId"],
                project_revision=project["projectRevision"],
                artifact_id="anki_reconciliation_receipt_" + operation_digest[:40],
                artifact_revision=1,
                payload_schema="study.anki-reconciliation-receipt",
                payload_schema_version=1,
                payload=receipt_payload,
                producer=_PRODUCER,
                parents=[plan_ref],
                input_fingerprint=operation_digest,
                completeness={
                    "state": "complete",
                    "expectedUnits": classification["expectedCardCount"],
                    "processedUnits": classification["observedCardCount"],
                    "omittedLocators": [],
                    "reasonCodes": [],
                },
                issue_refs=[],
            )
            self._projects.commit_artifact_stage(
                audience=audience,
                project_id=project["projectId"],
                expected_project_revision=project["projectRevision"],
                operation_id=operation_id + ":receipt",
                operation_digest=_digest(
                    {"operationDigest": operation_digest, "stage": "present"}
                ),
                task_id=task_id,
                artifact_stage="imported_unverified",
                artifact_refs=[receipt_publication.artifact_ref],
                artifact_handles=[receipt_publication.handle],
            )
            current = self._preparation.resolve_current_import_plan_ref(
                audience=audience, import_plan_ref=plan_ref
            )
            project = current["project"]
            receipt = {
                "ref": receipt_publication.artifact_ref,
                "payload": receipt_payload,
            }
        elif stage not in {"imported_unverified", "anki_data_verified", "anki_verified"}:
            raise AnkiImportReconciliationError(
                "IMPORT_PLAN_STAGE_CONFLICT", "Anki reconciliation stage is invalid"
            )

        if stage in {"anki_data_verified", "anki_verified"}:
            return self._publish_observation(
                audience=audience,
                resolved=current,
                operation_digest=operation_digest,
                classification=classification,
                target_digest=target_digest,
                receipt=receipt,
            )

        verification_payload = {
            "schemaVersion": 1,
            "projectRevision": project["projectRevision"],
            "resultingProjectRevision": project["projectRevision"] + 1,
            "importPlanRef": _clone(plan_ref),
            "importPlanDigest": plan_ref["artifactDigest"],
            "apkgSha256": plan["apkgSha256"],
            "targetDigest": target_digest,
            "operationDigest": operation_digest,
            "importDisposition": "already_present",
            "importAttempted": False,
            "importSucceeded": True,
            "noteCount": plan["noteCount"],
            "cardCount": classification["observedCardCount"],
            "expectedCardCount": classification["expectedCardCount"],
            "mediaCountExpected": classification["expectedMediaCount"],
            "mediaCountChecked": classification["checkedMediaCount"],
            "duplicateCardCount": 0,
            "failedChecks": [],
            "dataVerification": "passed",
            "runtimeVerification": "not_assessed",
            "verificationContractVersion": ANKI_DATA_VERIFICATION_CONTRACT_VERSION,
            "policyVersion": ANKI_IMPORT_RECONCILIATION_POLICY_VERSION,
        }
        parents = [plan_ref]
        if receipt is not None:
            parents.append(receipt["ref"])
        publication = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project["projectId"],
            project_revision=project["projectRevision"],
            artifact_id="anki_verification_reconciled_" + operation_digest[:40],
            artifact_revision=1,
            payload_schema="study.anki-verification",
            payload_schema_version=1,
            payload=verification_payload,
            producer=_PRODUCER,
            parents=parents,
            input_fingerprint=operation_digest,
            completeness={
                "state": "complete",
                "expectedUnits": classification["expectedCardCount"],
                "processedUnits": classification["observedCardCount"],
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=[],
        )
        self._projects.commit_artifact_stage(
            audience=audience,
            project_id=project["projectId"],
            expected_project_revision=project["projectRevision"],
            operation_id=operation_id,
            operation_digest=operation_digest,
            task_id=task_id,
            artifact_stage="anki_data_verified",
            artifact_refs=[publication.artifact_ref],
            artifact_handles=[publication.handle],
        )
        return publication

    def _public_task(
        self, task: Mapping[str, Any], audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        progress = task.get("progress") if isinstance(task.get("progress"), Mapping) else {}
        public: dict[str, Any] = {
            "schemaVersion": 1,
            "taskId": str(task.get("taskId") or ""),
            "intent": "inspect_anki_import",
            "state": str(task.get("state") or ""),
            "cancellable": False,
            "resumability": str(task.get("resumability") or "none"),
            "progress": {
                "phase": str(progress.get("phase") or "anki_reconciliation"),
                "phasePercent": progress.get("phasePercent"),
                "overallPercent": progress.get("overallPercent"),
                "lastProgressAt": str(progress.get("lastProgressAt") or ""),
            },
        }
        if public["state"] == "succeeded":
            handles = task.get("resultHandles")
            if not isinstance(handles, list) or len(handles) != 1:
                raise AnkiImportReconciliationError(
                    "ANKI_RECONCILIATION_INVALID", "Reconciliation result is invalid"
                )
            ref, envelope = self._artifacts.resolve_with_ref(handles[0], audience)
            payload = envelope.get("payload")
            if not isinstance(payload, Mapping):
                raise AnkiImportReconciliationError(
                    "ANKI_RECONCILIATION_INVALID", "Reconciliation artifact is invalid"
                )
            if envelope.get("payloadSchema") == "study.anki-verification":
                project = self._projects.get_project(ref["projectId"], audience)
                committed = project.get("workflow", {}).get("artifactStage") in {
                    "anki_data_verified",
                    "anki_verified",
                }
                state = "present" if committed else "unknown"
                public["result"] = {
                    "reconciliationState": state,
                    "artifactStage": project.get("workflow", {}).get("artifactStage"),
                    "projectRevision": project["projectRevision"],
                    "expectedCardCount": payload["expectedCardCount"],
                    "observedCardCount": payload["cardCount"],
                    "expectedMediaCount": payload["mediaCountExpected"],
                    "checkedMediaCount": payload["mediaCountChecked"],
                    "receiptObserved": len(envelope.get("parents", [])) > 1,
                    "dataVerification": "passed" if committed else "not_verified",
                    "runtimeVerification": "not_assessed",
                    "reasonCodes": [] if committed else ["project_commit_incomplete"],
                    "nextAction": "open_anki" if committed else "inspect_anki_import",
                }
            elif envelope.get("payloadSchema") == "study.anki-reconciliation":
                public["result"] = {
                    "reconciliationState": payload["reconciliationState"],
                    "artifactStage": self._projects.get_project(
                        ref["projectId"], audience
                    )["workflow"]["artifactStage"],
                    "projectRevision": payload["projectRevision"],
                    "expectedCardCount": payload["expectedCardCount"],
                    "observedCardCount": payload["observedCardCount"],
                    "expectedMediaCount": payload["expectedMediaCount"],
                    "checkedMediaCount": payload["checkedMediaCount"],
                    "receiptObserved": payload["receiptObserved"],
                    "dataVerification": "not_verified",
                    "runtimeVerification": "not_assessed",
                    "reasonCodes": list(payload["reasonCodes"]),
                    "nextAction": (
                        "request_import_confirmation"
                        if payload["reconciliationState"] == "absent"
                        else "resolve_issue"
                    ),
                }
            else:
                raise AnkiImportReconciliationError(
                    "ANKI_RECONCILIATION_INVALID", "Reconciliation schema is invalid"
                )
            public["nextAction"] = public["result"]["nextAction"]
        elif public["state"] in {"failed", "cancelled", "interrupted"}:
            failure = task.get("failure")
            public["error"] = {
                "code": str(
                    failure.get("code")
                    if isinstance(failure, Mapping)
                    else "ANKI_RECONCILIATION_FAILED"
                ),
                "retryable": bool(
                    failure.get("retryable") if isinstance(failure, Mapping) else False
                ),
                "stage": "anki_reconciliation",
            }
            public["nextAction"] = "inspect_anki_import"
        else:
            public["nextAction"] = "poll_task"
        return public

    def start(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        import_plan_handle: str,
    ) -> dict[str, Any]:
        task_id: str | None = None
        operation_digest: str | None = None
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            raise AnkiImportReconciliationError(
                "SCHEMA_INVALID", "idempotencyKey is invalid"
            )
        try:
            resolved = self._preparation.resolve_current_import_plan(
                audience=audience, import_plan_handle=import_plan_handle
            )
            project = resolved["project"]
            plan_ref = resolved["importPlanRef"]
            plan = resolved["importPlanPayload"]
            if project["projectId"] != project_id:
                raise AnkiImportReconciliationError(
                    "PROJECT_SCOPE_MISMATCH", "ImportPlan belongs to another project"
                )
            if project["projectRevision"] != expected_project_revision:
                raise AnkiImportReconciliationError(
                    "PROJECT_REVISION_CONFLICT",
                    "Project changed before Anki reconciliation",
                )
            receipt = self._current_receipt(audience=audience, resolved=resolved)
            target_digest = _digest(plan["target"])
            operation_digest = _digest(
                {
                    "schema": "study.anki-import-reconciliation.request",
                    "schemaVersion": 1,
                    "projectId": project_id,
                    "projectRevision": expected_project_revision,
                    "importPlanDigest": plan_ref["artifactDigest"],
                    "targetDigest": target_digest,
                    "apkgSha256": plan["apkgSha256"],
                    "policyVersion": ANKI_IMPORT_RECONCILIATION_POLICY_VERSION,
                }
            )
            operation_id = "anki-reconcile:" + idempotency_key
            task_id = "task_anki_reconcile_" + operation_digest[:40]
            try:
                existing = self._tasks.get_task(task_id, audience)
            except StudyTaskError as error:
                if error.code != "TASK_NOT_FOUND":
                    raise
            else:
                if existing.get("intent") != "resolve_anki_conflict":
                    raise AnkiImportReconciliationError(
                        "TASK_ID_CONFLICT",
                        "Anki reconciliation task identity conflicts",
                    )
                return self._public_task(existing, audience)

            work, task_input, capability, authorization, fingerprint = self._manifests(
                audience=audience,
                project=project,
                plan_ref=plan_ref,
                target_digest=target_digest,
                operation_digest=operation_digest,
            )
            try:
                task = self._tasks.create_task(
                    audience=audience,
                    work_reuse_manifest=work,
                    task_input_manifest=task_input,
                    capability_binding=capability,
                    authorization_binding=authorization,
                    work_units=[
                        {
                            "workUnitId": "inspect-anki-import",
                            "phase": "anki_data_verification",
                        }
                    ],
                    cancellable=False,
                    resumability="none",
                    _task_id=task_id,
                )
            except StudyTaskError as error:
                if error.code != "TASK_ALREADY_EXISTS":
                    raise
                task = self._tasks.get_task(task_id, audience)
                if task.get("inputFingerprint") != fingerprint:
                    raise AnkiImportReconciliationError(
                        "INPUT_REVISION_MISMATCH",
                        "Anki reconciliation input changed",
                    ) from error
            if task["state"] != "queued":
                return self._public_task(task, audience)
            task = self._tasks.start_task(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="start-" + operation_digest[:40],
            )
            task = self._tasks.begin_work_unit(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="begin-" + operation_digest[:40],
                work_unit_id="inspect-anki-import",
            )

            try:
                current_target = self._preparation.inspect_current_target()
                if _digest(current_target) != target_digest:
                    classification = {
                        "state": "unknown",
                        "reasonCodes": ["anki_target_changed"],
                        "expectedCardCount": plan["cardCount"],
                        "observedCardCount": 0,
                        "expectedMediaCount": plan["mediaCount"],
                        "checkedMediaCount": 0,
                    }
                else:
                    bundle = self._execution.authenticated_bundle(
                        audience=audience, resolved=resolved
                    )
                    try:
                        raw_result = self._inspector(bundle)
                    except Exception as error:
                        code = str(getattr(error, "code", "inspection_unavailable")).lower()
                        safe_code = (
                            code
                            if re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code)
                            else "inspection_unavailable"
                        )
                        classification = {
                            "state": "unknown",
                            "reasonCodes": [safe_code],
                            "expectedCardCount": plan["cardCount"],
                            "observedCardCount": 0,
                            "expectedMediaCount": plan["mediaCount"],
                            "checkedMediaCount": 0,
                        }
                    else:
                        classification = self._classification(raw_result, plan)
            except AnkiImportPreparationError as error:
                classification = {
                    "state": "unknown",
                    "reasonCodes": [error.code.lower()],
                    "expectedCardCount": plan["cardCount"],
                    "observedCardCount": 0,
                    "expectedMediaCount": plan["mediaCount"],
                    "checkedMediaCount": 0,
                }

            if classification["state"] == "present":
                publication = self._promote_present(
                    audience=audience,
                    resolved=resolved,
                    task_id=task_id,
                    operation_id=operation_id,
                    operation_digest=operation_digest,
                    classification=classification,
                    target_digest=target_digest,
                    receipt=receipt,
                )
            else:
                publication = self._publish_observation(
                    audience=audience,
                    resolved=resolved,
                    operation_digest=operation_digest,
                    classification=classification,
                    target_digest=target_digest,
                    receipt=receipt,
                )
            task = self._tasks.get_task(task_id, audience)
            task = self._tasks.complete_work_unit(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="complete-" + operation_digest[:37],
                work_unit_id="inspect-anki-import",
                result_handles=[publication.handle],
            )
            task = self._tasks.succeed_task(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="succeed-" + operation_digest[:38],
            )
            return self._public_task(task, audience)
        except AnkiImportReconciliationError as error:
            self._fail_active_task(
                audience=audience,
                task_id=task_id,
                operation_digest=operation_digest,
                code=error.code,
            )
            raise
        except (
            AnkiImportExecutionError,
            AnkiImportPreparationError,
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskManifestError,
        ) as error:
            code = getattr(error, "code", "ANKI_RECONCILIATION_FAILED")
            self._fail_active_task(
                audience=audience,
                task_id=task_id,
                operation_digest=operation_digest,
                code=code,
            )
            raise AnkiImportReconciliationError(
                code,
                getattr(error, "message", str(error)),
            ) from error

    def get_task(
        self, task_id: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        task = self._tasks.get_task(task_id, audience)
        if task.get("intent") != "resolve_anki_conflict":
            raise AnkiImportReconciliationError(
                "TASK_RUNTIME_UNAVAILABLE", "Task is not an Anki reconciliation"
            )
        return self._public_task(task, audience)


__all__ = [
    "ANKI_IMPORT_RECONCILIATION_POLICY_VERSION",
    "AnkiImportInspector",
    "AnkiImportReconciliationError",
    "AnkiImportReconciliationRuntime",
]
