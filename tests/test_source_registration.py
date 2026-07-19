from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.project_registry import ProjectRegistryError
from card_service.resource_runtime import ServiceResourceRuntime
from card_service.service import CardService
from card_service.study_runtime import StudyRuntime, StudyRuntimeError


OWNER = hashlib.sha256(b"source-registration-owner").hexdigest()


def audience(**changes: str) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


def environment(tmp_path: Path):
    backend = InMemoryCredentialBackend()
    credentials = (tmp_path / "credentials").resolve()
    resources = ServiceResourceRuntime(
        state_dir=(tmp_path / "resources").resolve(),
        credential_store=CredentialStore(state_dir=credentials, backend=backend),
        gesture_verifier=lambda *_args: True,
        harden_callback=None,
        require_hardening=False,
    )
    runtime = StudyRuntime(
        state_dir=(tmp_path / "study").resolve(),
        credential_store=CredentialStore(state_dir=credentials, backend=backend),
        resource_runtime=resources,
    )
    project = runtime.create_project(
        audience=audience(),
        idempotency_key="project-1",
        learning_contract={
            "purpose": "Remember useful material",
            "targetBehavior": "Recall it without seeing the answer",
        },
        title="Trusted sources",
    )
    return resources, runtime, project


def input_ref(
    resources: ServiceResourceRuntime,
    path: Path,
    *,
    request_id: str,
) -> dict:
    kind = "directory" if path.is_dir() else "file"
    constraints = (
        {
            "actions": ["enumerate", "read"],
            "maxDepth": 8,
            "maxEntries": 64,
            "maxTotalBytes": 1024 * 1024,
        }
        if kind == "directory"
        else {"actions": ["read"], "maxBytes": max(1, path.stat().st_size)}
    )
    grant = resources.issue_local_grant(
        audience=audience(),
        grant_request_id=request_id,
        raw_path=path.resolve(),
        kind=kind,
        constraints=constraints,
        attestation_ref="gesture-" + request_id,
    )
    field = "directoryResourceRef" if kind == "directory" else "fileResourceRef"
    return {
        "schemaVersion": 1,
        "kind": kind,
        field: grant["resourceRef"],
        "displayName": grant["displayName"],
        "resourceRevisionDigest": grant["resourceRevisionDigest"],
        "constraints": grant["constraints"],
        "expiresAt": grant["expiresAt"],
    }


def register(
    runtime: StudyRuntime, project: dict, ref: dict, *, key: str = "register-1"
):
    return runtime.register_inputs(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=project["projectRevision"],
        idempotency_key=key,
        input_refs=[ref],
    )


def test_register_file_freezes_source_without_disclosing_local_path(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("reliable source evidence", encoding="utf-8")
    ref = input_ref(resources, source, request_id="file-1")

    result = register(runtime, project, ref)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert result["projectRevision"] == 2
    assert result["artifactStage"] == "sources_ready"
    assert result["completeness"] == {
        "state": "complete",
        "registeredSources": 1,
        "omittedSources": 0,
    }
    assert result["sources"][0]["sourceType"] == "text"
    assert result["sources"][0]["status"] == "conditional"
    assert str(source) not in encoded
    assert ref["fileResourceRef"] not in encoded
    for forbidden in ("workspaceRelativePath", "stagingRef", "registryAuthRef"):
        assert forbidden not in encoded

    public_project = runtime.get_public_project(
        project_id=project["projectId"], audience=audience(session_id="session-2")
    )
    assert public_project["workflow"]["operationState"] == "succeeded"
    assert public_project["currentTask"]["taskId"] == result["taskId"]
    assert public_project["currentTask"]["state"] == "succeeded"
    assert public_project["currentTask"]["recoverable"] is False
    assert len(public_project["latestArtifacts"]) == 1
    public_artifact = public_project["latestArtifacts"][0]
    assert public_artifact["payloadSchema"] == "study.source-asset"
    assert runtime.artifacts.resolve(
        public_artifact["artifactHandle"], audience(session_id="session-2")
    )["payloadSchema"] == "study.source-asset"
    public_page = runtime.list_public_projects(
        audience=audience(session_id="session-2"), limit=1
    )
    assert public_page["items"][0]["latestTask"]["state"] == "succeeded"
    assert public_page["items"][0]["artifactStage"] == "sources_ready"
    public_encoded = json.dumps(public_project, ensure_ascii=False, sort_keys=True)
    for forbidden in ("registryAuthRef", "blobRef", "workspace", str(source)):
        assert forbidden not in public_encoded

    envelope = runtime.artifacts.resolve(
        result["sources"][0]["sourceHandle"], audience()
    )
    payload = envelope["payload"]
    assert payload["inputRefKind"] == "file"
    assert payload["sourceIdentity"]["stable"] is True
    assert (
        runtime.artifacts.read_blob(payload["representations"][0]["blobRef"])
        == source.read_bytes()
    )
    persisted = b"\n".join(
        path.read_bytes() for path in (tmp_path / "study").rglob("*") if path.is_file()
    )
    assert str(source).encode("utf-8") not in persisted


def test_register_directory_publishes_content_addressed_manifest(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "course").resolve()
    source.mkdir()
    (source / "part-1.md").write_text("first", encoding="utf-8")
    nested = source / "nested"
    nested.mkdir()
    (nested / "part-2.txt").write_text("second", encoding="utf-8")
    ref = input_ref(resources, source, request_id="directory-1")

    result = register(runtime, project, ref)
    envelope = runtime.artifacts.resolve(
        result["sources"][0]["sourceHandle"], audience()
    )
    payload = envelope["payload"]
    assert payload["sourceType"] == "directory_manifest"
    manifest = json.loads(
        runtime.artifacts.read_blob(payload["representations"][0]["blobRef"])
    )
    assert [entry["relativeLocator"] for entry in manifest["entries"]] == [
        "nested/part-2.txt",
        "part-1.md",
    ]
    assert all(
        not Path(entry["relativeLocator"]).is_absolute()
        for entry in manifest["entries"]
    )


def test_completed_registration_is_idempotent_and_reissues_session_handle(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.md").resolve()
    source.write_text("stable", encoding="utf-8")
    ref = input_ref(resources, source, request_id="file-idempotent")

    first = register(runtime, project, ref)
    second = register(runtime, project, ref)
    assert second["projectRevision"] == first["projectRevision"] == 2
    assert second["taskId"] == first["taskId"]
    assert second["sources"][0]["sourceId"] == first["sources"][0]["sourceId"]
    assert second["sources"][0]["sourceHandle"] != first["sources"][0]["sourceHandle"]
    first_envelope = runtime.artifacts.resolve(
        first["sources"][0]["sourceHandle"], audience()
    )
    second_envelope = runtime.artifacts.resolve(
        second["sources"][0]["sourceHandle"], audience()
    )
    assert second_envelope == first_envelope


def test_retry_after_task_success_commits_project_without_rereading_source(
    tmp_path: Path, monkeypatch
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("recoverable", encoding="utf-8")
    ref = input_ref(resources, source, request_id="file-recovery")
    original_commit = runtime.projects.commit_artifact_stage
    calls = 0

    def interrupt_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProjectRegistryError(
                "PROJECT_COMMIT_INTERRUPTED", "simulated interruption"
            )
        return original_commit(**kwargs)

    monkeypatch.setattr(runtime.projects, "commit_artifact_stage", interrupt_once)
    with pytest.raises(StudyRuntimeError) as interrupted:
        register(runtime, project, ref, key="register-recovery")
    assert interrupted.value.code == "PROJECT_COMMIT_INTERRUPTED"
    source.unlink()

    recovered = register(runtime, project, ref, key="register-recovery")
    assert recovered["projectRevision"] == 2
    assert recovered["completeness"]["registeredSources"] == 1


def test_registration_rejects_changed_source_and_cross_session_ref(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("before", encoding="utf-8")
    ref = input_ref(resources, source, request_id="file-change")
    source.write_text("after", encoding="utf-8")
    with pytest.raises(StudyRuntimeError) as changed:
        register(runtime, project, ref, key="changed")
    assert changed.value.code == "RESOURCE_CHANGED"

    with pytest.raises(StudyRuntimeError) as wrong_session:
        runtime.register_inputs(
            audience=audience(session_id="session-2"),
            project_id=project["projectId"],
            expected_project_revision=1,
            idempotency_key="wrong-session",
            input_refs=[ref],
        )
    assert wrong_session.value.code in {
        "PROJECT_SCOPE_MISMATCH",
        "RESOURCE_SCOPE_MISMATCH",
        "RESOURCE_AUDIENCE_MISMATCH",
    }


def test_card_service_uses_managed_workspace_and_releases_capacity_reservation(
    tmp_path: Path,
) -> None:
    service = CardService(
        state_dir=(tmp_path / "service").resolve(),
        credential_backend=InMemoryCredentialBackend(),
        resource_gesture_verifier=lambda *_args: True,
        use_restricted_launcher=False,
    )
    resources = service._ensure_resource_runtime()
    source = (tmp_path / "service-lesson.txt").resolve()
    source.write_text("managed workspace", encoding="utf-8")
    ref = input_ref(resources, source, request_id="service-file")
    project = service.create_study_project(
        audience=audience(),
        idempotency_key="service-project",
        learning_contract={
            "purpose": "Remember managed input",
            "targetBehavior": "Recall it later",
        },
    )

    result = service.register_study_inputs(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=1,
        idempotency_key="service-register",
        input_refs=[ref],
    )

    assert result["artifactStage"] == "sources_ready"
    assert result["taskId"] not in service._workspace_reservations
    workspace = service.store.root / "sandboxes" / result["taskId"]
    assert workspace.is_dir()
