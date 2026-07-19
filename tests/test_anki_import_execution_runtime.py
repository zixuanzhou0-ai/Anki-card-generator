from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from card_service.anki_import_approval import AnkiImportApprovalLedger
from card_service.anki_import_execution import (
    AnkiImportExecutionError,
    AnkiImportExecutionRuntime,
)
from card_service.anki_import_preparation import (
    ANKI_DATA_VERIFICATION_CONTRACT_VERSION,
    ANKI_IMPORT_PLAN_POLICY_VERSION,
    REQUIRED_DATA_CHECKS,
    AnkiImportPreparationRuntime,
)
from card_service.artifact_registry import ArtifactRegistry, canonical_json_bytes
from card_service.project_registry import ProjectRegistry
from card_service.task_coordinator import StudyTaskCoordinator
from tests.test_candidate_discovery_runtime import audience
from tests.test_project_registry import contract


def _sha(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class _UnusedPackages:
    pass


class _TargetInspector:
    def __call__(self):
        return {
            "schemaVersion": 1,
            "profileRef": "anki_current_" + "a" * 32,
            "configurationFingerprint": "b" * 64,
            "credentialRevision": 0,
            "ankiConnectVersion": 6,
            "profileIdentityDigest": "c" * 64,
            "collectionIdentityDigest": "d" * 64,
            "deckInventoryDigest": "e" * 64,
            "deckCount": 2,
            "transportAuthentication": "none",
            "observedAt": 1_786_000_000_000,
        }


class _SuccessfulExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, bundle, progress, cancel_event):
        self.calls += 1
        assert set(bundle) == {
            "schemaVersion",
            "apkgBlobRef",
            "apkgSha256",
            "sizeBytes",
            "deckNames",
            "cardCount",
            "mediaCount",
            "templateFamily",
            "templateSchemaVersion",
            "cardIdentities",
            "mediaEntries",
        }
        assert not cancel_event.is_set()
        progress({"stage": "import", "percent": 50, "message": "importing"})
        return {
            "ok": True,
            "failed_checks": [],
            "import_attempted": True,
            "import_result": True,
            "import_skipped_existing": False,
            "card_count": 1,
            "media_count_expected": 0,
            "media_count_checked": 0,
            "duplicate_imported_card_count": 0,
        }


class _BlockingExecutor:
    def __init__(self) -> None:
        self.calls = 0
        self.started = threading.Event()

    def __call__(self, _bundle, _progress, cancel_event):
        self.calls += 1
        self.started.set()
        assert cancel_event.wait(2)
        raise AnkiImportExecutionError("TASK_CANCELLED", "cancelled")


class _VerificationFailureAfterImportExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _bundle, _progress, _cancel_event):
        self.calls += 1
        return {
            "ok": False,
            "failed_checks": ["media_hash_mismatch"],
            "import_attempted": True,
            "import_result": [12345],
            "import_skipped_existing": False,
            "card_count": 1,
            "media_count_expected": 0,
            "media_count_checked": 0,
            "duplicate_imported_card_count": 0,
        }


class _ImportFailureExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _bundle, _progress, _cancel_event):
        self.calls += 1
        return {
            "ok": False,
            "failed_checks": ["anki_import_failed"],
            "import_attempted": True,
            "import_result": False,
            "import_skipped_existing": False,
            "card_count": 0,
            "media_count_expected": 0,
            "media_count_checked": 0,
            "duplicate_imported_card_count": 0,
        }


class _AlreadyPresentExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _bundle, _progress, _cancel_event):
        self.calls += 1
        return {
            "ok": True,
            "failed_checks": [],
            "import_attempted": True,
            "import_result": None,
            "import_skipped_existing": True,
            "card_count": 1,
            "media_count_expected": 0,
            "media_count_checked": 0,
            "duplicate_imported_card_count": 0,
        }


def _publication(artifacts, project, schema, payload, suffix):
    return artifacts.publish_idempotent(
        audience=audience(),
        project_id=project["projectId"],
        project_revision=project["projectRevision"],
        artifact_id=f"test_{suffix}_{project['projectRevision']}",
        artifact_revision=1,
        payload_schema=schema,
        payload_schema_version=1,
        payload=payload,
        producer={"component": "test", "version": "1.0.0"},
        parents=[],
        input_fingerprint=_sha(
            {"schema": schema, "revision": project["projectRevision"]}
        ),
        completeness={
            "state": "complete",
            "omittedLocators": [],
            "reasonCodes": [],
        },
        issue_refs=[],
    )


def _advance(projects, artifacts, project, stage):
    publication = _publication(
        artifacts,
        project,
        f"study.test-{stage}",
        {"schemaVersion": 1, "stage": stage},
        stage,
    )
    projects.commit_artifact_stage(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=project["projectRevision"],
        operation_id=f"advance:{stage}",
        operation_digest=_sha({"stage": stage}),
        task_id=f"task_advance_{stage}",
        artifact_stage=stage,
        artifact_refs=[publication.artifact_ref],
        artifact_handles=[publication.handle],
    )
    return projects.get_project(project["projectId"], audience())


def _runtime(tmp_path: Path):
    service_id = "service-anki-execution-test"
    artifacts = ArtifactRegistry(
        tmp_path / "artifacts",
        authentication_key=b"a" * 32,
        service_instance_id=service_id,
    )
    projects = ProjectRegistry(
        tmp_path / "projects",
        authentication_key=b"p" * 32,
        service_instance_id=service_id,
    )
    tasks = StudyTaskCoordinator(
        tmp_path / "tasks",
        authentication_key=b"t" * 32,
        service_instance_id=service_id,
        artifact_registry=artifacts,
    )
    project = projects.create_project(
        audience=audience(),
        idempotency_key="create-import-runtime",
        title="Import runtime",
        learning_contract=contract(),
    )
    for stage in (
        "sources_ready",
        "candidates_ready",
        "selection_ready",
        "plans_ready",
        "cards_ready",
    ):
        project = _advance(projects, artifacts, project, stage)

    blob = artifacts.put_blob(
        b"authenticated-apkg",
        media_type="application/vnd.anki.apkg",
    )
    card_sha = "1" * 64
    file_artifact = _publication(
        artifacts,
        project,
        "study.apkg-file",
        {
            "schemaVersion": 1,
            "blobRef": blob,
            "fileName": "cards.apkg",
            "sha256": blob["sha256"],
            "sizeBytes": blob["sizeBytes"],
            "outputResourceRefDigest": "2" * 64,
            "deliveryPolicy": "versioned-no-replace-v1",
        },
        "apkg_file",
    )
    identity_artifact = _publication(
        artifacts,
        project,
        "study.card-identity-set",
        {
            "schemaVersion": 1,
            "cards": [
                {
                    "cardId": "card-1",
                    "sourceCardId": "source-card-1",
                    "noteContentSha256": card_sha,
                    "deckName": "Study",
                }
            ],
            "cardCount": 1,
            "identityPolicy": "card-id-note-content-sha256-v1",
        },
        "identities",
    )
    media_artifact = _publication(
        artifacts,
        project,
        "study.package-media-manifest",
        {"schemaVersion": 1, "entries": [], "mediaCount": 0},
        "media_manifest",
    )
    inventory_artifact = _publication(
        artifacts,
        project,
        "study.card-media-role-inventory",
        {
            "schemaVersion": 1,
            "cards": [{"cardId": "card-1", "mediaRoles": []}],
            "mediaCount": 0,
        },
        "media_inventory",
    )
    verification_core = {
        "schemaVersion": 1,
        "contractVersion": ANKI_DATA_VERIFICATION_CONTRACT_VERSION,
        "requiredDataChecks": list(REQUIRED_DATA_CHECKS),
        "duplicatePolicy": "detect_and_report",
        "runtimeVerification": "not_assessed",
    }
    verification_artifact = _publication(
        artifacts,
        project,
        "study.anki-verification-contract",
        {**verification_core, "contractDigest": _sha(verification_core)},
        "verification_contract",
    )
    package_artifact = _publication(
        artifacts,
        project,
        "study.package-artifact",
        {
            "apkgSha256": blob["sha256"],
            "cardCount": 1,
            "mediaCount": 0,
        },
        "package",
    )
    target = {
        "schemaVersion": 1,
        "profileRef": "anki_current_" + "a" * 32,
        "configurationFingerprint": "b" * 64,
        "credentialRevision": 0,
        "ankiConnectVersion": 6,
        "profileIdentityDigest": "c" * 64,
        "collectionIdentityDigest": "d" * 64,
        "deckInventoryDigest": "e" * 64,
        "deckCount": 2,
        "transportAuthentication": "none",
    }
    plan_payload = {
        "schemaVersion": 1,
        "projectRevision": project["projectRevision"],
        "resultingProjectRevision": project["projectRevision"] + 1,
        "packageArtifactRef": package_artifact.artifact_ref,
        "packageArtifactDigest": package_artifact.artifact_ref["artifactDigest"],
        "apkgFileRef": file_artifact.artifact_ref,
        "apkgSha256": blob["sha256"],
        "sizeBytes": blob["sizeBytes"],
        "fileName": "cards.apkg",
        "deckNames": ["Study"],
        "noteCount": 1,
        "cardCount": 1,
        "mediaCount": 0,
        "cardIdentitySetRef": identity_artifact.artifact_ref,
        "cardIdentitySetDigest": identity_artifact.artifact_ref["artifactDigest"],
        "mediaManifestRef": media_artifact.artifact_ref,
        "mediaManifestDigest": media_artifact.artifact_ref["artifactDigest"],
        "cardMediaRoleInventoryRef": inventory_artifact.artifact_ref,
        "cardMediaRoleInventoryDigest": inventory_artifact.artifact_ref[
            "artifactDigest"
        ],
        "templateFamily": "document-knowledge",
        "templateSchemaVersion": "v15",
        "noteModelId": "123",
        "compatibilityContractVersion": "1",
        "frontTemplateSha256": "3" * 64,
        "backTemplateSha256": "4" * 64,
        "cssSha256": "5" * 64,
        "target": target,
        "verificationContractRef": verification_artifact.artifact_ref,
        "verificationContractDigest": _sha(verification_core),
        "requiredDataChecks": list(REQUIRED_DATA_CHECKS),
        "duplicatePolicy": "detect_and_report",
        "writePolicy": "explicit-confirmation-required",
        "runtimeVerification": "not_assessed",
        "recoveryPolicy": "inspect-before-any-retry",
        "policyVersion": ANKI_IMPORT_PLAN_POLICY_VERSION,
    }
    plan_artifact = _publication(
        artifacts,
        project,
        "study.anki-import-plan",
        plan_payload,
        "import_plan",
    )
    projects.commit_artifact_stage(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=project["projectRevision"],
        operation_id="commit-import-plan",
        operation_digest=_sha({"commit": "import-plan"}),
        task_id="task_commit_import_plan",
        artifact_stage="apkg_ready",
        artifact_refs=[plan_artifact.artifact_ref],
        artifact_handles=[plan_artifact.handle],
    )
    project = projects.get_project(project["projectId"], audience())
    preparation = AnkiImportPreparationRuntime(
        service_instance_id=service_id,
        artifacts=artifacts,
        projects=projects,
        packages=_UnusedPackages(),  # type: ignore[arg-type]
        target_inspector=_TargetInspector(),
    )
    approvals = AnkiImportApprovalLedger(
        tmp_path / "approvals",
        authentication_key=b"i" * 32,
        service_instance_id=service_id,
        gesture_attestation_verifier=lambda *_args: True,
    )
    intent = approvals.create_intent(
        audience=audience(),
        project_id=project["projectId"],
        project_revision=project["projectRevision"],
        import_plan_ref=plan_artifact.artifact_ref,
        import_plan_digest=plan_artifact.artifact_ref["artifactDigest"],
        target_digest=_sha(target),
        apkg_sha256=blob["sha256"],
    )
    approvals.record_decision(
        audience=audience(),
        import_intent_id=intent["importIntentId"],
        decision="approved",
        gesture_attestation_ref="trusted-click-attestation",
    )
    executor = _SuccessfulExecutor()
    runtime = AnkiImportExecutionRuntime(
        service_instance_id=service_id,
        artifacts=artifacts,
        projects=projects,
        tasks=tasks,
        preparation=preparation,
        approvals=approvals,
        executor=executor,
    )
    return runtime, projects, project, intent, executor


def _await(runtime, task_id: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = runtime.get_task(task_id, audience())
        if task["state"] not in {"queued", "running", "cancelling"}:
            return task
        time.sleep(0.01)
    raise AssertionError("Anki import task did not finish")


def test_approved_import_is_single_use_idempotent_and_commits_two_stages(
    tmp_path: Path,
) -> None:
    runtime, projects, project, intent, executor = _runtime(tmp_path)
    arguments = {
        "audience": audience(),
        "import_intent_id": intent["importIntentId"],
        "idempotency_key": "import-once",
    }

    started = runtime.start(**arguments)
    completed = _await(runtime, started["taskId"])

    assert completed["state"] == "succeeded"
    assert completed["result"] == {
        **completed["result"],
        "artifactStage": "anki_data_verified",
        "projectRevision": project["projectRevision"] + 2,
        "importDisposition": "imported",
        "cardCount": 1,
        "expectedCardCount": 1,
        "mediaCountExpected": 0,
        "mediaCountChecked": 0,
        "duplicateCardCount": 0,
        "dataVerification": "passed",
        "runtimeVerification": "not_assessed",
        "nextAction": "open_anki",
    }
    assert (
        projects.get_project(project["projectId"], audience())["workflow"][
            "artifactStage"
        ]
        == "anki_data_verified"
    )
    assert executor.calls == 1

    assert runtime.start(**arguments) == completed
    assert (
        runtime.start(**{**arguments, "idempotency_key": "different-key-cannot-replay"})
        == completed
    )
    assert executor.calls == 1


def test_verification_failure_after_write_preserves_unverified_receipt(
    tmp_path: Path,
) -> None:
    runtime, projects, project, intent, _executor = _runtime(tmp_path)
    failed_executor = _VerificationFailureAfterImportExecutor()
    runtime._executor = failed_executor
    arguments = {
        "audience": audience(),
        "import_intent_id": intent["importIntentId"],
        "idempotency_key": "import-verification-fails",
    }

    started = runtime.start(**arguments)
    completed = _await(runtime, started["taskId"])

    assert completed["state"] == "failed"
    assert completed["error"]["code"] == "ANKI_VERIFY_FAILED"
    current = projects.get_project(project["projectId"], audience())
    assert current["workflow"]["artifactStage"] == "imported_unverified"
    receipts = [
        ref
        for ref in current["latestArtifactRefs"]
        if ref["payloadSchema"] == "study.anki-import-receipt"
    ]
    assert len(receipts) == 1
    receipt = runtime._artifacts.verify_ref(receipts[0], audience())["payload"]
    assert receipt["writeBoundaryState"] == "observed_complete"
    assert receipt["importSucceeded"] is True
    assert (
        runtime.start(
            **{**arguments, "idempotency_key": "import-verification-fails-again"}
        )
        == completed
    )
    assert failed_executor.calls == 1


def test_import_failure_does_not_claim_an_unverified_write(tmp_path: Path) -> None:
    runtime, projects, project, intent, _executor = _runtime(tmp_path)
    failed_executor = _ImportFailureExecutor()
    runtime._executor = failed_executor

    completed = _await(
        runtime,
        runtime.start(
            audience=audience(),
            import_intent_id=intent["importIntentId"],
            idempotency_key="import-write-fails",
        )["taskId"],
    )

    assert completed["state"] == "failed"
    current = projects.get_project(project["projectId"], audience())
    assert current["workflow"]["artifactStage"] == "apkg_ready"
    assert not any(
        ref["payloadSchema"] == "study.anki-import-receipt"
        for ref in current["latestArtifactRefs"]
    )
    assert failed_executor.calls == 1


def test_existing_import_is_a_successful_observed_write(tmp_path: Path) -> None:
    runtime, _projects, _project, intent, _executor = _runtime(tmp_path)
    existing_executor = _AlreadyPresentExecutor()
    runtime._executor = existing_executor

    completed = _await(
        runtime,
        runtime.start(
            audience=audience(),
            import_intent_id=intent["importIntentId"],
            idempotency_key="import-already-present",
        )["taskId"],
    )

    assert completed["state"] == "succeeded"
    assert completed["result"]["importDisposition"] == "already_present"
    assert completed["result"]["dataVerification"] == "passed"
    assert existing_executor.calls == 1

def test_cancellation_reaches_terminal_state_without_import_receipt(
    tmp_path: Path,
) -> None:
    runtime, projects, project, intent, _executor = _runtime(tmp_path)
    blocking = _BlockingExecutor()
    runtime._executor = blocking
    started = runtime.start(
        audience=audience(),
        import_intent_id=intent["importIntentId"],
        idempotency_key="cancel-before-import-completes",
    )
    assert blocking.started.wait(2)

    cancelling = runtime.cancel_task(started["taskId"], audience())
    completed = _await(runtime, started["taskId"])

    assert cancelling["state"] == "cancelling"
    assert completed["state"] == "interrupted"
    assert completed["nextAction"] == "inspect_before_retry"
    assert projects.get_project(project["projectId"], audience())["workflow"][
        "artifactStage"
    ] == "apkg_ready"
    assert blocking.calls == 1