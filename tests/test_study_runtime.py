from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.resource_runtime import ServiceResourceRuntime
from card_service.study_runtime import StudyRuntime, StudyRuntimeError


OWNER = hashlib.sha256(b"study-runtime-owner").hexdigest()


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
    return backend, resources, runtime


def contract(**changes):
    value = {
        "purpose": "Remember useful language",
        "targetBehavior": "Recall and use the idea without seeing the answer",
    }
    value.update(changes)
    return value


def test_study_runtime_composes_all_registries_under_one_service_identity(
    tmp_path: Path,
) -> None:
    backend, resources, runtime = environment(tmp_path)
    capabilities = runtime.capabilities()

    assert runtime.service_instance_id == resources.service_instance_id
    assert capabilities["projectRegistry"] is True
    assert capabilities["artifactRegistry"] is True
    assert capabilities["studyTaskCoordinator"] is True
    assert capabilities["taskSourceBinding"] is True
    assert capabilities["sourceAssetPublication"] is True
    assert capabilities["sourceInspection"] is True
    assert capabilities["publicInputRegistration"] is True
    assert capabilities["publicSourceInspection"] is True
    assert capabilities["publicProjectQueries"] is True
    assert capabilities["publicLearningContractUpdate"] is True
    assert capabilities["pathDisclosure"] is False
    assert len(backend.values) == 1
    serialized = json.dumps(capabilities, sort_keys=True)
    assert str(tmp_path) not in serialized
    persisted = b"".join(
        path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    )
    for secret in backend.values.values():
        assert secret.encode("ascii") not in persisted


def test_create_project_is_idempotent_and_scoped(tmp_path: Path) -> None:
    _, _, runtime = environment(tmp_path)
    first = runtime.create_project(
        audience=audience(),
        idempotency_key="create-1",
        learning_contract=contract(),
        title="My study project",
    )
    second = runtime.create_project(
        audience=audience(),
        idempotency_key="create-1",
        learning_contract=contract(),
        title="My study project",
    )

    assert second == first
    assert first["projectRevision"] == 1
    assert first["workflow"]["artifactStage"] == "empty"
    assert runtime.get_project(first["projectId"], audience()) == first
    assert runtime.list_projects(audience()) == [first]
    assert (
        runtime.list_projects(
            audience(owner_digest=hashlib.sha256(b"other").hexdigest())
        )
        == []
    )

    with pytest.raises(StudyRuntimeError) as conflict:
        runtime.create_project(
            audience=audience(),
            idempotency_key="create-1",
            learning_contract=contract(purpose="Different"),
            title="My study project",
        )
    assert conflict.value.code == "PROJECT_IDEMPOTENCY_CONFLICT"


def test_learning_contract_update_returns_only_opaque_preserved_artifacts(
    tmp_path: Path,
) -> None:
    _, _, runtime = environment(tmp_path)
    bound = audience()
    project = runtime.create_project(
        audience=bound,
        idempotency_key="create-for-update",
        learning_contract=contract(),
        title="Preservation boundary",
    )
    publication = runtime.artifacts.publish_idempotent(
        audience=bound,
        project_id=project["projectId"],
        project_revision=1,
        artifact_id="source-for-update",
        artifact_revision=1,
        payload_schema="study.source-asset",
        payload_schema_version=1,
        payload={"sourceId": "source-for-update", "status": "ready"},
        producer={"component": "test", "version": "1.0.0"},
        parents=[],
        input_fingerprint=hashlib.sha256(b"source-for-update").hexdigest(),
        completeness={
            "state": "complete",
            "omittedLocators": [],
            "reasonCodes": [],
        },
        issue_refs=[],
    )
    runtime.projects.commit_artifact_stage(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=1,
        operation_id="commit-source-for-update",
        operation_digest=hashlib.sha256(b"commit-source-for-update").hexdigest(),
        task_id="task-source-for-update",
        artifact_stage="sources_ready",
        artifact_refs=[publication.artifact_ref],
        artifact_handles=[publication.handle],
    )
    updated = runtime.update_learning_contract(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=2,
        expected_contract_revision=1,
        operation_id="change-purpose-for-update",
        operations=[{"op": "set_purpose", "purpose": "A changed purpose"}],
    )
    assert len(updated["preservedArtifacts"]) == 1
    preserved = updated["preservedArtifacts"][0]
    assert preserved["payloadSchema"] == "study.source-asset"
    assert preserved["artifactHandle"].startswith("study_")
    assert runtime.artifacts.resolve(preserved["artifactHandle"], bound)[
        "payload"
    ]["sourceId"] == "source-for-update"
    serialized = json.dumps(updated, sort_keys=True)
    assert "registryAuthRef" not in serialized
    assert "artifactDigest" not in serialized


def test_historical_contract_replay_cannot_resurface_later_invalidated_artifacts(
    tmp_path: Path,
) -> None:
    _, _, runtime = environment(tmp_path)
    bound = audience()
    project = runtime.create_project(
        audience=bound,
        idempotency_key="create-for-replay-filter",
        learning_contract=contract(),
        title="Replay filtering",
    )
    stages = [
        ("sources_ready", "study.source-asset"),
        ("candidates_ready", "study.discovery"),
        ("selection_ready", "study.portfolio-selection"),
    ]
    revision = 1
    for index, (stage, schema) in enumerate(stages):
        publication = runtime.artifacts.publish_idempotent(
            audience=bound,
            project_id=project["projectId"],
            project_revision=revision,
            artifact_id=f"replay-filter-{index}",
            artifact_revision=1,
            payload_schema=schema,
            payload_schema_version=1,
            payload={"schema": schema, "sequence": index},
            producer={"component": "test", "version": "1.0.0"},
            parents=[],
            input_fingerprint=hashlib.sha256(
                f"replay-filter-{index}".encode()
            ).hexdigest(),
            completeness={
                "state": "complete",
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=[],
        )
        runtime.projects.commit_artifact_stage(
            audience=bound,
            project_id=project["projectId"],
            expected_project_revision=revision,
            operation_id=f"commit-replay-filter-{index}",
            operation_digest=hashlib.sha256(
                f"commit-replay-filter-{index}".encode()
            ).hexdigest(),
            task_id=f"task-replay-filter-{index}",
            artifact_stage=stage,
            artifact_refs=[publication.artifact_ref],
            artifact_handles=[publication.handle],
        )
        revision += 1

    first_arguments = {
        "audience": bound,
        "project_id": project["projectId"],
        "expected_project_revision": 4,
        "expected_contract_revision": 1,
        "operation_id": "language-replay-filter",
        "operations": [
            {
                "op": "set_languages",
                "promptLanguage": "en",
                "answerLanguage": "zh-CN",
            }
        ],
    }
    first = runtime.update_learning_contract(**first_arguments)
    assert {item["payloadSchema"] for item in first["preservedArtifacts"]} == {
        "study.source-asset",
        "study.discovery",
        "study.portfolio-selection",
    }
    runtime.update_learning_contract(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=5,
        expected_contract_revision=2,
        operation_id="purpose-replay-filter",
        operations=[{"op": "set_purpose", "purpose": "A later purpose"}],
    )
    replayed = runtime.update_learning_contract(**first_arguments)
    assert replayed["projectRevision"] == 5
    assert replayed["contractRevision"] == 2
    assert {item["payloadSchema"] for item in replayed["preservedArtifacts"]} == {
        "study.source-asset"
    }


def test_study_runtime_rejects_relative_state_root(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    credentials = (tmp_path / "credentials").resolve()
    resources = ServiceResourceRuntime(
        state_dir=(tmp_path / "resources").resolve(),
        credential_store=CredentialStore(state_dir=credentials, backend=backend),
        gesture_verifier=lambda *_args: True,
        harden_callback=None,
        require_hardening=False,
    )
    with pytest.raises(StudyRuntimeError) as captured:
        StudyRuntime(
            state_dir=Path("relative-study-state"),
            credential_store=CredentialStore(state_dir=credentials, backend=backend),
            resource_runtime=resources,
        )
    assert captured.value.code == "STUDY_RUNTIME_STATE_INVALID"
