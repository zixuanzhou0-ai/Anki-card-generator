from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest
import card_service.task_coordinator as task_coordinator_module

from card_service.artifact_registry import ArtifactAudienceBinding, ArtifactRegistry
from card_service.task_coordinator import StudyTaskCoordinator, StudyTaskError
from card_service.task_manifests import (
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


KEY = bytes(range(32))
OWNER = hashlib.sha256(b"owner").hexdigest()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bound_audience(**changes: str) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


def components():
    return {
        "cardService": "2.0.0",
        "worker": "1.4.0",
        "sourceAdapterSetDigest": digest("adapters"),
        "gateRuleSetVersion": "gates-v3",
    }


def bundle(
    audience: ArtifactAudienceBinding,
    *,
    service_id: str = "service-1",
    project_id: str = "project-1",
    credential_revision: int | None = None,
):
    subject = {
        "kind": "project_task",
        "projectId": project_id,
        "projectRevision": 1,
        "inputArtifacts": [],
        "sourceSnapshotDigests": [digest("source-snapshot")],
        "learningContractRevision": 1,
    }
    profile_configuration = {
        "capability": "model",
        "profileRef": "profile-model",
        "configurationFingerprint": digest("model-config"),
    }
    service_configurations = [profile_configuration] if credential_revision is not None else []
    work, work_digest = build_work_reuse_manifest(
        action_id="discover_candidates",
        subject=subject,
        component_versions=components(),
        service_configurations=service_configurations,
        work_partition_policy_digest=digest("partition"),
    )
    if credential_revision is None:
        required_capabilities = [{
            "kind": "fixed",
            "capabilityId": "runtime.card_service",
            "implementationVersionOrDigest": "2.0.0",
            "compatibilityContractVersion": "service-v1",
        }]
        service_bindings = []
    else:
        required_capabilities = [{
            "kind": "service_profile",
            **profile_configuration,
            "credentialRevision": credential_revision,
            "implementationVersionOrDigest": "model-provider-v1",
            "compatibilityContractVersion": "model-v1",
        }]
        service_bindings = [{**profile_configuration, "credentialRevision": credential_revision}]
    capability, capability_digest = build_capability_binding(required_capabilities)
    authorization, authorization_digest = build_authorization_binding(
        audience=audience,
        service_instance_id=service_id,
        bindings=[
            {
                "action": "read_source",
                "authorizationRecordDigest": digest("auth-record"),
                "constraintsDigest": digest("constraints"),
                "exactScopeDigest": digest("scope"),
                "expectedRevocationEpoch": 0,
            }
        ],
    )
    task_input, _ = build_task_input_manifest(
        action_id="discover_candidates",
        work_reuse_manifest=work,
        work_reuse_digest=work_digest,
        subject=subject,
        authorization_binding_digest=authorization_digest,
        capability_binding_digest=capability_digest,
        component_versions=components(),
        service_bindings=service_bindings,
        operation_intent_digest=digest("intent"),
        batch_policy_digest=digest("batch"),
    )
    return work, task_input, capability, authorization


def environment(tmp_path: Path, *, service_id: str = "service-1"):
    audience = bound_audience()
    artifacts = ArtifactRegistry(
        tmp_path / "artifacts", authentication_key=KEY, service_instance_id=service_id
    )
    tasks = StudyTaskCoordinator(
        tmp_path / "tasks",
        authentication_key=KEY,
        service_instance_id=service_id,
        artifact_registry=artifacts,
    )
    return audience, artifacts, tasks


def create(
    tasks: StudyTaskCoordinator,
    audience: ArtifactAudienceBinding,
    *,
    service_id: str = "service-1",
    credential_revision: int | None = None,
):
    work, task_input, capability, authorization = bundle(
        audience, service_id=service_id, credential_revision=credential_revision
    )
    return tasks.create_task(
        audience=audience,
        work_reuse_manifest=work,
        task_input_manifest=task_input,
        capability_binding=capability,
        authorization_binding=authorization,
        work_units=[
            {"workUnitId": "inspect", "phase": "source_inspection"},
            {"workUnitId": "discover", "phase": "discovery"},
        ],
    )


def publish_result(artifacts: ArtifactRegistry, audience: ArtifactAudienceBinding, *, project_id: str = "project-1", artifact_id: str = "result-1"):
    return artifacts.publish(
        audience=audience,
        project_id=project_id,
        project_revision=1,
        artifact_id=artifact_id,
        artifact_revision=1,
        payload_schema="study.test.result",
        payload_schema_version=1,
        payload={"items": ["one"]},
        producer={"component": "test-suite", "version": "1.0.0"},
        parents=[],
        input_fingerprint=digest("input"),
        completeness={"state": "complete", "omittedLocators": [], "reasonCodes": []},
        issue_refs=[],
    )


def start(tasks: StudyTaskCoordinator, audience: ArtifactAudienceBinding, task: dict):
    return tasks.start_task(task["taskId"], audience, expected_revision=task["taskRevision"], operation_id="start-1")


def test_create_read_and_checkpoint_are_authenticated_and_scoped(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    task = create(tasks, audience)
    assert task["state"] == "queued"
    assert task["taskRevision"] == 1
    assert task["resultHandles"] == []
    assert tasks.get_task(task["taskId"], audience) == task
    checkpoint = tasks.load_checkpoint("project-1", audience)
    assert checkpoint["task"]["taskId"] == task["taskId"]
    assert checkpoint["recoveredFromBackup"] is False
    assert checkpoint["taskAdvancedBeyondCheckpoint"] is False
    assert {"authKeyId", "authTag", "projectScopeDigest", "taskRecordDigest"}.isdisjoint(checkpoint["checkpoint"])
    with pytest.raises(StudyTaskError) as wrong_owner:
        tasks.get_task(task["taskId"], bound_audience(owner_digest=digest("other-owner")))
    assert wrong_owner.value.code == "TASK_SCOPE_MISMATCH"


def test_new_session_can_read_but_cannot_mutate_old_task(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    task = create(tasks, audience)
    next_session = bound_audience(session_id="session-2")
    assert tasks.get_task(task["taskId"], next_session)["taskId"] == task["taskId"]
    with pytest.raises(StudyTaskError) as captured:
        tasks.start_task(task["taskId"], next_session, expected_revision=1, operation_id="start-new-session")
    assert captured.value.code == "TASK_REAUTHORIZATION_REQUIRED"


def test_bundle_must_bind_current_trusted_audience(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    work, task_input, capability, authorization = bundle(bound_audience(session_id="other-session"))
    with pytest.raises(StudyTaskError) as captured:
        tasks.create_task(
            audience=audience,
            work_reuse_manifest=work,
            task_input_manifest=task_input,
            capability_binding=capability,
            authorization_binding=authorization,
            work_units=[],
        )
    assert captured.value.code == "TASK_AUDIENCE_MISMATCH"


def test_revision_cas_and_operation_idempotency(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    task = create(tasks, audience)
    running = start(tasks, audience, task)
    repeated = tasks.start_task(task["taskId"], audience, expected_revision=1, operation_id="start-1")
    assert repeated["taskRevision"] == running["taskRevision"] == 2
    with pytest.raises(StudyTaskError) as stale:
        tasks.update_progress(
            task["taskId"], audience, expected_revision=1, operation_id="progress-stale",
            phase="source_inspection", phase_percent=1, overall_percent=1,
        )
    assert stale.value.code == "TASK_REVISION_CONFLICT"
    progress = tasks.update_progress(
        task["taskId"], audience, expected_revision=2, operation_id="progress-1",
        phase="source_inspection", phase_percent=10, overall_percent=5,
    )
    with pytest.raises(StudyTaskError) as conflict:
        tasks.update_progress(
            task["taskId"], audience, expected_revision=progress["taskRevision"], operation_id="progress-1",
            phase="source_inspection", phase_percent=20, overall_percent=10,
        )
    assert conflict.value.code == "TASK_IDEMPOTENCY_CONFLICT"


def test_progress_is_monotonic_and_only_success_can_reach_overall_100(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    running = start(tasks, audience, create(tasks, audience))
    progress = tasks.update_progress(
        running["taskId"], audience, expected_revision=2, operation_id="progress-1",
        phase="source_inspection", phase_percent=50, overall_percent=20,
        completed_items=2, total_items=10,
    )
    with pytest.raises(StudyTaskError) as regression:
        tasks.update_progress(
            running["taskId"], audience, expected_revision=progress["taskRevision"], operation_id="progress-2",
            phase="source_inspection", phase_percent=40, overall_percent=19,
        )
    assert regression.value.code == "TASK_PROGRESS_REGRESSION"
    with pytest.raises(StudyTaskError) as premature:
        tasks.update_progress(
            running["taskId"], audience, expected_revision=progress["taskRevision"], operation_id="progress-3",
            phase="source_inspection", phase_percent=100, overall_percent=100,
        )
    assert premature.value.code == "TASK_PROGRESS_INVALID"


def test_work_unit_results_persist_internal_refs_not_raw_handles(tmp_path: Path) -> None:
    audience, artifacts, tasks = environment(tmp_path)
    running = start(tasks, audience, create(tasks, audience))
    active = tasks.begin_work_unit(
        running["taskId"], audience, expected_revision=2, operation_id="begin-inspect", work_unit_id="inspect"
    )
    publication = publish_result(artifacts, audience)
    completed = tasks.complete_work_unit(
        running["taskId"], audience, expected_revision=active["taskRevision"], operation_id="complete-inspect",
        work_unit_id="inspect", result_handles=[publication.handle],
    )
    assert completed["workUnits"][0]["state"] == "completed"
    assert len(completed["workUnits"][0]["resultHandles"]) == 1
    persisted = b"\n".join(path.read_bytes() for path in (tmp_path / "tasks").rglob("*") if path.is_file())
    assert publication.handle.encode("ascii") not in persisted
    assert b'"resultRefs"' in persisted


def test_cross_project_result_handle_is_rejected(tmp_path: Path) -> None:
    audience, artifacts, tasks = environment(tmp_path)
    running = start(tasks, audience, create(tasks, audience))
    active = tasks.begin_work_unit(
        running["taskId"], audience, expected_revision=2, operation_id="begin-inspect", work_unit_id="inspect"
    )
    other = publish_result(artifacts, audience, project_id="project-2", artifact_id="other-result")
    with pytest.raises(StudyTaskError) as captured:
        tasks.complete_work_unit(
            running["taskId"], audience, expected_revision=active["taskRevision"], operation_id="complete-other",
            work_unit_id="inspect", result_handles=[other.handle],
        )
    assert captured.value.code == "TASK_RESULT_SCOPE_MISMATCH"


def test_success_requires_all_units_and_is_the_only_overall_100_state(tmp_path: Path) -> None:
    audience, artifacts, tasks = environment(tmp_path)
    task = start(tasks, audience, create(tasks, audience))
    with pytest.raises(StudyTaskError) as incomplete:
        tasks.succeed_task(task["taskId"], audience, expected_revision=2, operation_id="succeed-early")
    assert incomplete.value.code == "TASK_WORK_INCOMPLETE"
    revision = 2
    for index, unit_id in enumerate(("inspect", "discover"), start=1):
        active = tasks.begin_work_unit(
            task["taskId"], audience, expected_revision=revision, operation_id=f"begin-{unit_id}", work_unit_id=unit_id
        )
        result = publish_result(artifacts, audience, artifact_id=f"result-{index}")
        done = tasks.complete_work_unit(
            task["taskId"], audience, expected_revision=active["taskRevision"], operation_id=f"complete-{unit_id}",
            work_unit_id=unit_id, result_handles=[result.handle],
        )
        revision = done["taskRevision"]
    succeeded = tasks.succeed_task(task["taskId"], audience, expected_revision=revision, operation_id="succeed")
    assert succeeded["state"] == "succeeded"
    assert succeeded["progress"]["overallPercent"] == 100
    assert len(succeeded["resultHandles"]) == 2


def test_failure_is_structured_and_preserves_verified_artifacts(tmp_path: Path) -> None:
    audience, artifacts, tasks = environment(tmp_path)
    running = start(tasks, audience, create(tasks, audience))
    result = publish_result(artifacts, audience)
    failed = tasks.fail_task(
        running["taskId"], audience, expected_revision=2, operation_id="fail-1",
        code="MODEL_OUTPUT_INVALID", stage="discovery", retryable=True,
        remote_cost_state="incurred", retry_scope="phase", authorization_state="valid",
        preserved_artifact_handles=[result.handle], required_action="retry",
    )
    assert failed["state"] == "failed"
    assert failed["failure"]["code"] == "MODEL_OUTPUT_INVALID"
    assert len(failed["failure"]["preservedArtifactHandles"]) == 1
    assert failed["progress"]["overallPercent"] is None


def test_cancel_reaches_cancelled_or_interrupted_never_sticks(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    queued = create(tasks, audience)
    cancelled = tasks.request_cancel(
        queued["taskId"], audience, expected_revision=1, operation_id="cancel-queued"
    )
    assert cancelled["state"] == "cancelled"

    running = start(tasks, audience, create(tasks, audience))
    cancelling = tasks.request_cancel(
        running["taskId"], audience, expected_revision=2, operation_id="cancel-running"
    )
    assert cancelling["state"] == "cancelling"
    interrupted = tasks.finish_cancellation(
        running["taskId"], audience, expected_revision=cancelling["taskRevision"],
        operation_id="finish-cancel", safe_checkpoint_proven=False,
    )
    assert interrupted["state"] == "interrupted"


def test_new_service_marks_stale_active_task_interrupted_and_lists_it(tmp_path: Path) -> None:
    audience, _, old_tasks = environment(tmp_path, service_id="service-1")
    running = start(old_tasks, audience, create(old_tasks, audience, service_id="service-1"))
    new_artifacts = ArtifactRegistry(tmp_path / "artifacts", authentication_key=KEY, service_instance_id="service-2")
    new_tasks = StudyTaskCoordinator(
        tmp_path / "tasks", authentication_key=KEY, service_instance_id="service-2", artifact_registry=new_artifacts
    )
    interrupted = new_tasks.interrupt_stale_task(
        running["taskId"], audience, expected_revision=2, operation_id="interrupt-after-restart"
    )
    assert interrupted["state"] == "interrupted"
    assert interrupted["failure"]["authorizationState"] == "required"
    recoverable = new_tasks.list_recoverable_tasks(audience, scope_id="project-1")
    assert [item["taskId"] for item in recoverable] == [running["taskId"]]


def test_checkpoint_backup_recovers_and_detects_task_advanced_beyond_it(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    task = create(tasks, audience)
    running = start(tasks, audience, task)
    checkpoint_path = tasks._checkpoint_path("project-1")
    backup_path = checkpoint_path.with_suffix(checkpoint_path.suffix + ".bak")
    checkpoint_path.write_bytes(backup_path.read_bytes())
    recovered = tasks.load_checkpoint("project-1", audience)
    assert recovered["task"]["taskRevision"] == running["taskRevision"]
    assert recovered["taskAdvancedBeyondCheckpoint"] is True


def test_tampered_task_and_backup_are_rejected(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    task = create(tasks, audience)
    start(tasks, audience, task)
    task_path = tasks._task_path(task["taskId"])
    backup_path = task_path.with_suffix(task_path.suffix + ".bak")
    for path in (task_path, backup_path):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["task"]["state"] = "succeeded"
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    with pytest.raises(StudyTaskError) as captured:
        tasks.get_task(task["taskId"], audience)
    assert captured.value.code == "TASK_RECORD_CORRUPT"


def test_valid_task_backup_is_not_used_as_a_rollback_source(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    task = create(tasks, audience)
    start(tasks, audience, task)
    task_path = tasks._task_path(task["taskId"])
    task_path.write_bytes(b"corrupt-current-record")
    with pytest.raises(StudyTaskError) as captured:
        tasks.get_task(task["taskId"], audience)
    assert captured.value.code == "TASK_RECORD_CORRUPT"


def test_wrong_task_authentication_key_is_rejected(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    task = create(tasks, audience)
    artifacts = ArtifactRegistry(tmp_path / "artifacts", authentication_key=KEY, service_instance_id="service-1")
    wrong = StudyTaskCoordinator(
        tmp_path / "tasks", authentication_key=b"x" * 32,
        service_instance_id="service-1", artifact_registry=artifacts,
    )
    with pytest.raises(StudyTaskError) as captured:
        wrong.get_task(task["taskId"], audience)
    assert captured.value.code == "TASK_RECORD_CORRUPT"


def test_concurrent_expected_revision_has_one_winner(tmp_path: Path) -> None:
    audience, _, first_tasks = environment(tmp_path)
    second_artifacts = ArtifactRegistry(
        tmp_path / "artifacts", authentication_key=KEY, service_instance_id="service-1"
    )
    second_tasks = StudyTaskCoordinator(
        tmp_path / "tasks", authentication_key=KEY,
        service_instance_id="service-1", artifact_registry=second_artifacts,
    )
    task = create(first_tasks, audience)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def attempt(number: int) -> None:
        barrier.wait()
        try:
            coordinator = first_tasks if number == 1 else second_tasks
            coordinator.start_task(task["taskId"], audience, expected_revision=1, operation_id=f"start-{number}")
            outcomes.append("ok")
        except StudyTaskError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=attempt, args=(number,)) for number in (1, 2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["TASK_REVISION_CONFLICT", "ok"]


@pytest.mark.parametrize("phase_percent,overall_percent", [(float("nan"), 1), (1, float("inf")), (1, float("-inf"))])
def test_nonfinite_progress_is_rejected(
    tmp_path: Path, phase_percent: float, overall_percent: float
) -> None:
    audience, _, tasks = environment(tmp_path)
    running = start(tasks, audience, create(tasks, audience))
    with pytest.raises(StudyTaskError) as captured:
        tasks.update_progress(
            running["taskId"], audience, expected_revision=running["taskRevision"],
            operation_id="invalid-progress", phase="source_inspection",
            phase_percent=phase_percent, overall_percent=overall_percent,
        )
    assert captured.value.code == "TASK_PROGRESS_INVALID"


def successor_bindings(
    audience: ArtifactAudienceBinding,
    service_id: str,
    *,
    capability_version: str = "2.0.0",
    credential_revision: int | None = None,
    extra_action: bool = False,
):
    if credential_revision is None:
        required_capabilities = [{
            "kind": "fixed",
            "capabilityId": "runtime.card_service",
            "implementationVersionOrDigest": capability_version,
            "compatibilityContractVersion": "service-v1",
        }]
    else:
        required_capabilities = [{
            "kind": "service_profile",
            "capability": "model",
            "profileRef": "profile-model",
            "configurationFingerprint": digest("model-config"),
            "credentialRevision": credential_revision,
            "implementationVersionOrDigest": "model-provider-v1",
            "compatibilityContractVersion": "model-v1",
        }]
    capability, _ = build_capability_binding(required_capabilities)
    bindings = [
        {
            "action": "read_source",
            "authorizationRecordDigest": digest(f"auth-record-{service_id}"),
            "constraintsDigest": digest("constraints"),
            "exactScopeDigest": digest("scope"),
            "expectedRevocationEpoch": 1,
        }
    ]
    if extra_action:
        bindings.append(
            {
                "action": "call_model",
                "authorizationRecordDigest": digest("model-auth"),
                "constraintsDigest": digest("model-constraints"),
                "exactScopeDigest": digest("model-scope"),
                "expectedRevocationEpoch": 0,
            }
        )
    authorization, _ = build_authorization_binding(
        audience=audience, service_instance_id=service_id, bindings=bindings
    )
    return capability, authorization


def interrupted_with_one_completed_unit(tmp_path: Path, *, credential_revision: int | None = None):
    old_audience, old_artifacts, old_tasks = environment(tmp_path, service_id="service-1")
    task = start(old_tasks, old_audience, create(
        old_tasks, old_audience, service_id="service-1", credential_revision=credential_revision
    ))
    first = old_tasks.begin_work_unit(
        task["taskId"], old_audience, expected_revision=2, operation_id="begin-inspect", work_unit_id="inspect"
    )
    result = publish_result(old_artifacts, old_audience)
    first_done = old_tasks.complete_work_unit(
        task["taskId"], old_audience, expected_revision=first["taskRevision"], operation_id="complete-inspect",
        work_unit_id="inspect", result_handles=[result.handle],
    )
    second = old_tasks.begin_work_unit(
        task["taskId"], old_audience, expected_revision=first_done["taskRevision"],
        operation_id="begin-discover", work_unit_id="discover",
    )
    new_audience = bound_audience(session_id="session-2")
    new_artifacts = ArtifactRegistry(tmp_path / "artifacts", authentication_key=KEY, service_instance_id="service-2")
    new_tasks = StudyTaskCoordinator(
        tmp_path / "tasks", authentication_key=KEY, service_instance_id="service-2", artifact_registry=new_artifacts
    )
    interrupted = new_tasks.interrupt_stale_task(
        task["taskId"], new_audience, expected_revision=second["taskRevision"], operation_id="interrupt-stale"
    )
    return new_audience, new_artifacts, new_tasks, interrupted, result


def test_successor_reuses_only_completed_verified_work_and_rebinds_session(tmp_path: Path) -> None:
    audience, _, tasks, predecessor, result = interrupted_with_one_completed_unit(tmp_path)
    capability, authorization = successor_bindings(audience, "service-2")
    successor = tasks.create_successor_task(
        predecessor["taskId"], audience,
        operation_id="resume-1",
        authorization_binding=authorization,
        capability_binding=capability,
        service_bindings=[],
        scope_relation="equivalent",
        predecessor_authorization_audit_ref="audit-old",
        successor_authorization_audit_ref="audit-new",
        operation_intent_digest=digest("new-intent"),
        batch_policy_digest=digest("new-batch"),
    )
    assert successor["taskId"] != predecessor["taskId"]
    assert successor["predecessorTaskId"] == predecessor["taskId"]
    assert successor["inputFingerprint"] != predecessor["inputFingerprint"]
    assert successor["workReuseDigest"] == predecessor["workReuseDigest"]
    assert successor["workUnits"][0]["state"] == "completed"
    assert len(successor["workUnits"][0]["resultHandles"]) == 1
    assert successor["workUnits"][1]["state"] == "pending"
    persisted = b"\n".join(path.read_bytes() for path in (tmp_path / "tasks").rglob("*") if path.is_file())
    assert result.handle.encode("ascii") not in persisted


def test_self_consistent_but_noncanonical_manifest_is_rejected(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    work, task_input, capability, authorization = bundle(audience)
    forged_capability = {**capability, "callerClaimedReady": True}
    forged_input = {**task_input, "capabilityBindingDigest": hashlib.sha256(
        json.dumps(forged_capability, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()}
    with pytest.raises(StudyTaskError) as captured:
        tasks.create_task(
            audience=audience, work_reuse_manifest=work, task_input_manifest=forged_input,
            capability_binding=forged_capability, authorization_binding=authorization, work_units=[],
        )
    assert captured.value.code in {"TASK_MANIFEST_INVALID", "TASK_MANIFEST_MISMATCH"}


def test_successor_operation_is_idempotent_and_conflicting_reuse_is_rejected(tmp_path: Path) -> None:
    audience, _, tasks, predecessor, _ = interrupted_with_one_completed_unit(tmp_path)
    capability, authorization = successor_bindings(audience, "service-2")
    arguments = {
        "operation_id": "resume-1",
        "authorization_binding": authorization,
        "capability_binding": capability,
        "service_bindings": [],
        "scope_relation": "equivalent",
        "predecessor_authorization_audit_ref": "audit-old",
        "successor_authorization_audit_ref": "audit-new",
        "operation_intent_digest": digest("new-intent"),
        "cost_budget_digest": digest("cost-1"),
    }
    first = tasks.create_successor_task(predecessor["taskId"], audience, **arguments)
    repeated = tasks.create_successor_task(predecessor["taskId"], audience, **arguments)
    assert repeated["taskId"] == first["taskId"]
    with pytest.raises(StudyTaskError) as conflict:
        tasks.create_successor_task(
            predecessor["taskId"], audience, **{**arguments, "cost_budget_digest": digest("cost-2")}
        )
    assert conflict.value.code == "TASK_IDEMPOTENCY_CONFLICT"


def test_successor_allows_revalidated_credential_revision_with_stable_configuration(tmp_path: Path) -> None:
    audience, _, tasks, predecessor, _ = interrupted_with_one_completed_unit(
        tmp_path, credential_revision=1
    )
    capability, authorization = successor_bindings(
        audience, "service-2", credential_revision=2
    )
    successor = tasks.create_successor_task(
        predecessor["taskId"], audience, operation_id="resume-credential-rotation",
        authorization_binding=authorization, capability_binding=capability,
        service_bindings=[{
            "capability": "model",
            "profileRef": "profile-model",
            "configurationFingerprint": digest("model-config"),
            "credentialRevision": 2,
        }],
        scope_relation="equivalent",
        predecessor_authorization_audit_ref="audit-old",
        successor_authorization_audit_ref="audit-new",
    )
    assert successor["workUnits"][0]["state"] == "completed"
    assert successor["workUnits"][1]["state"] == "pending"


def test_successor_rejects_tampered_reusable_artifact(tmp_path: Path) -> None:
    audience, artifacts, tasks, predecessor, result = interrupted_with_one_completed_unit(tmp_path)
    artifact_ref = result.artifact_ref
    artifacts._artifact_path(
        artifact_ref["projectId"], artifact_ref["artifactId"], artifact_ref["artifactRevision"]
    ).write_bytes(b"{}")
    capability, authorization = successor_bindings(audience, "service-2")
    with pytest.raises(StudyTaskError) as captured:
        tasks.create_successor_task(
            predecessor["taskId"], audience, operation_id="resume-tampered-result",
            authorization_binding=authorization, capability_binding=capability,
            service_bindings=[], scope_relation="equivalent",
            predecessor_authorization_audit_ref="audit-old",
            successor_authorization_audit_ref="audit-new",
        )
    assert captured.value.code == "TASK_RESULT_INVALID"


def test_successor_rejects_capability_change_and_authorization_expansion(tmp_path: Path) -> None:
    audience, _, tasks, predecessor, _ = interrupted_with_one_completed_unit(tmp_path)
    changed_capability, authorization = successor_bindings(audience, "service-2", capability_version="3.0.0")
    with pytest.raises(StudyTaskError) as incompatible:
        tasks.create_successor_task(
            predecessor["taskId"], audience, operation_id="resume-capability",
            authorization_binding=authorization, capability_binding=changed_capability,
            service_bindings=[], scope_relation="equivalent",
            predecessor_authorization_audit_ref="audit-old", successor_authorization_audit_ref="audit-new",
        )
    assert incompatible.value.code == "TASK_CAPABILITY_INCOMPATIBLE"

    capability, expanded = successor_bindings(audience, "service-2", extra_action=True)
    with pytest.raises(StudyTaskError) as expanded_scope:
        tasks.create_successor_task(
            predecessor["taskId"], audience, operation_id="resume-expanded",
            authorization_binding=expanded, capability_binding=capability,
            service_bindings=[], scope_relation="equivalent",
            predecessor_authorization_audit_ref="audit-old", successor_authorization_audit_ref="audit-new",
        )
    assert expanded_scope.value.code == "TASK_AUTHORIZATION_SCOPE_EXPANDED"

def test_recoverable_listing_isolates_a_corrupt_record(tmp_path: Path) -> None:
    audience, _, tasks = environment(tmp_path)
    running = start(tasks, audience, create(tasks, audience))
    failed = tasks.fail_task(
        running["taskId"],
        audience,
        expected_revision=running["taskRevision"],
        operation_id="fail-for-list",
        code="MODEL_OUTPUT_INVALID",
        stage="discovery",
        retryable=True,
        remote_cost_state="incurred",
        retry_scope="phase",
        authorization_state="valid",
        preserved_artifact_handles=[],
        required_action="retry",
    )
    corrupt_path = tasks._tasks_root / "corrupt-record" / "record.json"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_bytes(b"not-json")

    recoverable = tasks.list_recoverable_tasks(audience, limit=1)

    assert [item["taskId"] for item in recoverable] == [failed["taskId"]]


def test_recoverable_listing_fails_explicitly_at_scan_bound(
    tmp_path: Path, monkeypatch
) -> None:
    audience, _, tasks = environment(tmp_path)
    for name in ("one", "two"):
        path = tasks._tasks_root / name / "record.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not-json")
    monkeypatch.setattr(task_coordinator_module, "MAX_RECOVERY_SCAN_RECORDS", 1)

    with pytest.raises(StudyTaskError) as captured:
        tasks.list_recoverable_tasks(audience)

    assert captured.value.code == "TASK_LIST_SCAN_LIMIT"

def test_successor_lineage_scan_is_bounded_and_isolates_corrupt_records(
    tmp_path: Path, monkeypatch
) -> None:
    audience, _, tasks, predecessor, _ = interrupted_with_one_completed_unit(tmp_path)
    corrupt_path = tasks._tasks_root / "corrupt-record" / "record.json"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_bytes(b"not-json")
    capability, authorization = successor_bindings(audience, "service-2")

    successor = tasks.create_successor_task(
        predecessor["taskId"],
        audience,
        operation_id="resume-with-corrupt-neighbor",
        authorization_binding=authorization,
        capability_binding=capability,
        service_bindings=[],
        scope_relation="equivalent",
        predecessor_authorization_audit_ref="audit-old",
        successor_authorization_audit_ref="audit-new",
    )
    assert successor["predecessorTaskId"] == predecessor["taskId"]

    monkeypatch.setattr(task_coordinator_module, "MAX_RECOVERY_SCAN_RECORDS", 1)
    with pytest.raises(StudyTaskError) as captured:
        tasks.create_successor_task(
            predecessor["taskId"],
            audience,
            operation_id="resume-over-scan-bound",
            authorization_binding=authorization,
            capability_binding=capability,
            service_bindings=[],
            scope_relation="equivalent",
            predecessor_authorization_audit_ref="audit-old",
            successor_authorization_audit_ref="audit-new",
        )
    assert captured.value.code == "TASK_LIST_SCAN_LIMIT"

def test_concurrent_coordinators_allow_only_one_lineage_successor(
    tmp_path: Path,
) -> None:
    audience, _, first_tasks, predecessor, _ = interrupted_with_one_completed_unit(
        tmp_path
    )
    second_artifacts = ArtifactRegistry(
        tmp_path / "artifacts",
        authentication_key=KEY,
        service_instance_id="service-2",
    )
    second_tasks = StudyTaskCoordinator(
        tmp_path / "tasks",
        authentication_key=KEY,
        service_instance_id="service-2",
        artifact_registry=second_artifacts,
    )
    capability, authorization = successor_bindings(audience, "service-2")
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, str]] = []
    outcome_lock = threading.Lock()

    def create_successor(coordinator: StudyTaskCoordinator, operation_id: str) -> None:
        barrier.wait(timeout=5)
        try:
            created = coordinator.create_successor_task(
                predecessor["taskId"],
                audience,
                operation_id=operation_id,
                authorization_binding=authorization,
                capability_binding=capability,
                service_bindings=[],
                scope_relation="equivalent",
                predecessor_authorization_audit_ref="audit-old",
                successor_authorization_audit_ref="audit-new",
            )
            outcome = ("created", created["taskId"])
        except StudyTaskError as error:
            outcome = ("error", error.code)
        with outcome_lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(
            target=create_successor,
            args=(first_tasks, "resume-concurrent-one"),
        ),
        threading.Thread(
            target=create_successor,
            args=(second_tasks, "resume-concurrent-two"),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert len(outcomes) == 2
    assert [kind for kind, _ in outcomes].count("created") == 1
    assert ("error", "TASK_SUCCESSOR_ACTIVE") in outcomes
