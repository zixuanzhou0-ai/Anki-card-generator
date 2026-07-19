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
