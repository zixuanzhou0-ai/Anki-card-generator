from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding, ArtifactRegistry
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.resource_runtime import ServiceResourceRuntime
from card_service.task_coordinator import StudyTaskCoordinator
from card_service.task_manifests import (
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)
from card_service.task_source_binding import (
    TaskSourceBindingError,
    TaskSourceBindingRuntime,
)


KEY = bytes(range(32))
OWNER = hashlib.sha256(b"task-source-owner").hexdigest()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def audience(**changes: str) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


def components() -> dict[str, str]:
    return {
        "cardService": "2.0.0",
        "worker": "1.4.0",
        "sourceAdapterSetDigest": digest("adapters"),
        "gateRuleSetVersion": "gates-v3",
    }


def create_task(
    tasks: StudyTaskCoordinator,
    current_audience: ArtifactAudienceBinding,
    *,
    service_id: str,
    source_revision: str,
) -> dict:
    subject = {
        "kind": "project_task",
        "projectId": "project-1",
        "projectRevision": 1,
        "inputArtifacts": [],
        "sourceSnapshotDigests": [source_revision],
        "learningContractRevision": 1,
    }
    work, work_digest = build_work_reuse_manifest(
        action_id="discover_candidates",
        subject=subject,
        component_versions=components(),
        service_configurations=[],
        work_partition_policy_digest=digest("partition"),
    )
    capability, capability_digest = build_capability_binding(
        [
            {
                "kind": "fixed",
                "capabilityId": "runtime.card_service",
                "implementationVersionOrDigest": "2.0.0",
                "compatibilityContractVersion": "service-v1",
            }
        ]
    )
    authorization, authorization_digest = build_authorization_binding(
        audience=current_audience,
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
        service_bindings=[],
        operation_intent_digest=digest("intent"),
        batch_policy_digest=digest("batch"),
    )
    return tasks.create_task(
        audience=current_audience,
        work_reuse_manifest=work,
        task_input_manifest=task_input,
        capability_binding=capability,
        authorization_binding=authorization,
        work_units=[{"workUnitId": "inspect", "phase": "source_inspection"}],
    )


def setup_runtime(tmp_path: Path, *, directory: bool = False):
    current_audience = audience()
    source = (tmp_path / ("lesson" if directory else "lesson.txt")).resolve()
    if directory:
        source.mkdir()
        (source / "part-1.txt").write_text("first", encoding="utf-8")
        (source / "part-2.txt").write_text("second", encoding="utf-8")
        kind = "directory"
        constraints = {
            "actions": ["enumerate", "read"],
            "maxDepth": 8,
            "maxEntries": 64,
            "maxTotalBytes": 4096,
        }
    else:
        source.write_text("reliable source", encoding="utf-8")
        kind = "file"
        constraints = {"actions": ["read"], "maxBytes": source.stat().st_size}
    backend = InMemoryCredentialBackend()
    resources = ServiceResourceRuntime(
        state_dir=(tmp_path / "resource-runtime").resolve(),
        credential_store=CredentialStore(
            state_dir=(tmp_path / "credentials").resolve(), backend=backend
        ),
        gesture_verifier=lambda *_args: True,
        harden_callback=None,
        require_hardening=False,
    )
    grant = resources.issue_local_grant(
        audience=current_audience,
        grant_request_id="grant-1",
        raw_path=source,
        kind=kind,
        constraints=constraints,
        attestation_ref="gesture-1",
    )
    artifacts = ArtifactRegistry(
        tmp_path / "artifacts",
        authentication_key=KEY,
        service_instance_id=resources.service_instance_id,
    )
    tasks = StudyTaskCoordinator(
        tmp_path / "tasks",
        authentication_key=KEY,
        service_instance_id=resources.service_instance_id,
        artifact_registry=artifacts,
    )
    task = create_task(
        tasks,
        current_audience,
        service_id=resources.service_instance_id,
        source_revision=grant["resourceRevisionDigest"],
    )
    workspace = (tmp_path / "workspaces" / task["taskId"]).resolve()
    workspace.mkdir(parents=True)
    runtime = TaskSourceBindingRuntime(
        tmp_path / "source-bindings",
        authentication_key=KEY,
        service_instance_id=resources.service_instance_id,
        resource_runtime=resources,
        task_coordinator=tasks,
    )
    ref_field = "fileResourceRef" if kind == "file" else "directoryResourceRef"
    input_ref = {
        "schemaVersion": 1,
        "kind": kind,
        ref_field: grant["resourceRef"],
        "displayName": grant["displayName"],
        "resourceRevisionDigest": grant["resourceRevisionDigest"],
        "constraints": grant["constraints"],
        "expiresAt": grant["expiresAt"],
    }
    return (
        current_audience,
        source,
        resources,
        tasks,
        task,
        workspace,
        runtime,
        input_ref,
    )


def bind(values, *, registration_id: str = "register-1") -> dict:
    current_audience, _, _, _, task, workspace, runtime, input_ref = values
    return runtime.bind_local_input(
        audience=current_audience,
        task_id=task["taskId"],
        task_input_fingerprint=task["inputFingerprint"],
        task_workspace=workspace,
        task_sandbox_id=None,
        input_ref=input_ref,
        registration_id=registration_id,
    )


def test_binding_public_summary_discloses_no_path_grant_or_worker_receipt(
    tmp_path: Path,
) -> None:
    values = setup_runtime(tmp_path)
    current_audience, source, _, _, task, workspace, runtime, _ = values
    public = bind(values)
    serialized = json.dumps(public, sort_keys=True)

    assert public["state"] == "staged"
    assert public["taskId"] == task["taskId"]
    assert public["contentSnapshot"]["entryCount"] == 1
    assert str(source) not in serialized
    for forbidden in (
        "resourceRef",
        "stagingRef",
        "workspaceRelativePath",
        "resolutionProof",
        "inputs/",
    ):
        assert forbidden not in serialized

    worker = runtime.worker_input(
        public["sourceBindingRef"],
        audience=current_audience,
        task_id=task["taskId"],
        task_input_fingerprint=task["inputFingerprint"],
        task_workspace=workspace,
    )
    locator = worker["locator"]
    assert worker["adapterId"] == "source.local-file"
    assert not Path(locator["workspaceRelativePath"]).is_absolute()
    assert (workspace / Path(locator["workspaceRelativePath"])).read_text(
        encoding="utf-8"
    ) == "reliable source"
    worker_json = json.dumps(worker, sort_keys=True)
    assert str(source) not in worker_json
    assert public["sourceBindingRef"] not in worker_json


def test_directory_binding_yields_only_relative_manifest_backed_locator(
    tmp_path: Path,
) -> None:
    values = setup_runtime(tmp_path, directory=True)
    current_audience, source, _, _, task, workspace, runtime, _ = values
    public = bind(values)
    worker = runtime.worker_input(
        public["sourceBindingRef"],
        audience=current_audience,
        task_id=task["taskId"],
        task_input_fingerprint=task["inputFingerprint"],
        task_workspace=workspace,
    )

    assert public["contentSnapshot"]["entryCount"] == 2
    assert worker["adapterId"] == "source.directory"
    relative = worker["locator"]["workspaceRelativePath"]
    assert not Path(relative).is_absolute()
    assert sorted(path.name for path in (workspace / Path(relative)).iterdir()) == [
        "part-1.txt",
        "part-2.txt",
    ]
    assert str(source) not in json.dumps(worker, sort_keys=True)


def test_successful_binding_is_idempotent_after_single_use_grant_is_exhausted(
    tmp_path: Path,
) -> None:
    values = setup_runtime(tmp_path)
    _, _, resources, _, _, _, _, input_ref = values
    first = bind(values)
    inspected = resources.local_registry.inspect(
        input_ref["fileResourceRef"], audience()
    )
    assert inspected["state"] == "exhausted"
    assert bind(values) == first


def test_registration_id_cannot_be_reused_with_changed_public_input(
    tmp_path: Path,
) -> None:
    values = setup_runtime(tmp_path)
    bind(values)
    current_audience, _, _, _, task, workspace, runtime, input_ref = values
    altered = {**input_ref, "displayName": "another-name.txt"}
    with pytest.raises(TaskSourceBindingError) as captured:
        runtime.bind_local_input(
            audience=current_audience,
            task_id=task["taskId"],
            task_input_fingerprint=task["inputFingerprint"],
            task_workspace=workspace,
            task_sandbox_id=None,
            input_ref=altered,
            registration_id="register-1",
        )
    assert captured.value.code == "TASK_SOURCE_IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    "field", ["displayName", "resourceRevisionDigest", "constraints"]
)
def test_public_input_must_exactly_match_service_owned_grant(
    tmp_path: Path, field: str
) -> None:
    values = setup_runtime(tmp_path)
    current_audience, _, _, _, task, workspace, runtime, input_ref = values
    altered = dict(input_ref)
    if field == "displayName":
        altered[field] = "forged.txt"
    elif field == "resourceRevisionDigest":
        altered[field] = digest("forged")
    else:
        altered[field] = {**input_ref[field], "maxBytes": 1}
    with pytest.raises(TaskSourceBindingError) as captured:
        runtime.bind_local_input(
            audience=current_audience,
            task_id=task["taskId"],
            task_input_fingerprint=task["inputFingerprint"],
            task_workspace=workspace,
            task_sandbox_id=None,
            input_ref=altered,
            registration_id=f"tamper-{field}",
        )
    assert captured.value.code in {
        "TASK_INPUT_MISMATCH",
        "TASK_SOURCE_INPUT_REF_MISMATCH",
    }


def test_task_manifest_must_commit_exact_source_revision(tmp_path: Path) -> None:
    values = setup_runtime(tmp_path)
    current_audience, _, resources, tasks, _, _, runtime, input_ref = values
    other_task = create_task(
        tasks,
        current_audience,
        service_id=resources.service_instance_id,
        source_revision=digest("other-source"),
    )
    other_workspace = (tmp_path / "workspaces" / other_task["taskId"]).resolve()
    other_workspace.mkdir(parents=True)
    with pytest.raises(TaskSourceBindingError) as captured:
        runtime.bind_local_input(
            audience=current_audience,
            task_id=other_task["taskId"],
            task_input_fingerprint=other_task["inputFingerprint"],
            task_workspace=other_workspace,
            task_sandbox_id=None,
            input_ref=input_ref,
            registration_id="wrong-task",
        )
    assert captured.value.code == "TASK_INPUT_MISMATCH"


def test_binding_cannot_cross_session_or_task_state(tmp_path: Path) -> None:
    values = setup_runtime(tmp_path)
    current_audience, _, _, tasks, task, workspace, runtime, input_ref = values
    with pytest.raises(TaskSourceBindingError) as wrong_session:
        runtime.bind_local_input(
            audience=audience(session_id="session-2"),
            task_id=task["taskId"],
            task_input_fingerprint=task["inputFingerprint"],
            task_workspace=workspace,
            task_sandbox_id=None,
            input_ref=input_ref,
            registration_id="other-session",
        )
    assert wrong_session.value.code == "TASK_REAUTHORIZATION_REQUIRED"

    tasks.start_task(
        task["taskId"],
        current_audience,
        expected_revision=task["taskRevision"],
        operation_id="start-1",
    )
    with pytest.raises(TaskSourceBindingError) as late:
        runtime.bind_local_input(
            audience=current_audience,
            task_id=task["taskId"],
            task_input_fingerprint=task["inputFingerprint"],
            task_workspace=workspace,
            task_sandbox_id=None,
            input_ref=input_ref,
            registration_id="late-binding",
        )
    assert late.value.code == "TASK_STATE_CONFLICT"


def test_existing_binding_can_be_rehydrated_after_task_start(tmp_path: Path) -> None:
    values = setup_runtime(tmp_path)
    current_audience, _, _, tasks, task, _, _, _ = values
    first = bind(values)
    tasks.start_task(
        task["taskId"],
        current_audience,
        expected_revision=task["taskRevision"],
        operation_id="start-recovery",
    )

    assert bind(values) == first


def test_worker_resolution_rejects_another_audience_and_tampered_private_record(
    tmp_path: Path,
) -> None:
    values = setup_runtime(tmp_path)
    current_audience, _, _, _, task, workspace, runtime, _ = values
    public = bind(values)
    with pytest.raises(TaskSourceBindingError) as wrong_session:
        runtime.worker_input(
            public["sourceBindingRef"],
            audience=audience(session_id="session-2"),
            task_id=task["taskId"],
            task_input_fingerprint=task["inputFingerprint"],
            task_workspace=workspace,
        )
    assert wrong_session.value.code == "TASK_SOURCE_BINDING_SCOPE_MISMATCH"

    record_path = next((tmp_path / "source-bindings" / "records").rglob("*.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["displayName"] = "tampered.txt"
    record_path.write_bytes(
        json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    with pytest.raises(TaskSourceBindingError) as tampered:
        runtime.worker_input(
            public["sourceBindingRef"],
            audience=current_audience,
            task_id=task["taskId"],
            task_input_fingerprint=task["inputFingerprint"],
            task_workspace=workspace,
        )
    assert tampered.value.code == "TASK_SOURCE_BINDING_AUTH_FAILED"


def test_source_change_after_authorization_fails_before_staging(tmp_path: Path) -> None:
    values = setup_runtime(tmp_path)
    _, source, _, _, _, workspace, _, _ = values
    source.write_text("changed after approval", encoding="utf-8")
    with pytest.raises(TaskSourceBindingError) as captured:
        bind(values, registration_id="changed-source")
    assert captured.value.code == "RESOURCE_CHANGED"
    assert not (workspace / "inputs").exists()
