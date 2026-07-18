from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.credentials import (
    CredentialStore,
    CredentialStoreError,
    InMemoryCredentialBackend,
)
from card_service.service import CardService, CardServiceError
from card_service.resource_runtime import (
    ServiceResourceRuntime,
    ServiceResourceRuntimeError,
)


OWNER = hashlib.sha256(b"resource-runtime-owner").hexdigest()


def audience() -> ArtifactAudienceBinding:
    return ArtifactAudienceBinding(
        owner_digest=OWNER,
        host_id="codex-desktop",
        plugin_id="speakright.study",
        session_id="resource-runtime-session",
    )


def constraints(size: int) -> dict[str, object]:
    return {"actions": ["read"], "maxBytes": size}


def test_credential_store_derives_domain_separated_service_keys_without_file_secrets(
    tmp_path: Path,
) -> None:
    backend = InMemoryCredentialBackend()
    state = (tmp_path / "credentials").resolve()
    first = CredentialStore(state_dir=state, backend=backend)
    key_a = first.derive_service_key("local-resource-registry-v1", context=b"state-a")
    key_b = first.derive_service_key("resource-staging-v1", context=b"state-a")
    second = CredentialStore(state_dir=state, backend=backend)

    assert len(key_a) == 32
    assert key_a == second.derive_service_key(
        "local-resource-registry-v1", context=b"state-a"
    )
    assert key_a != key_b
    assert key_a != first.derive_service_key(
        "local-resource-registry-v1", context=b"state-b"
    )
    persisted = b"".join(
        path.read_bytes() for path in state.iterdir() if path.is_file()
    )
    assert key_a.hex().encode("ascii") not in persisted
    assert key_b.hex().encode("ascii") not in persisted


@pytest.mark.parametrize(
    ("purpose", "context"),
    [
        ("", b"ok"),
        ("contains space", b"ok"),
        ("valid", "not-bytes"),
        ("valid", b"x" * 1025),
    ],
)
def test_credential_store_rejects_invalid_service_key_derivation(
    tmp_path: Path, purpose: str, context: object
) -> None:
    store = CredentialStore(
        state_dir=(tmp_path / "credentials").resolve(),
        backend=InMemoryCredentialBackend(),
    )
    with pytest.raises(CredentialStoreError):
        store.derive_service_key(purpose, context=context)  # type: ignore[arg-type]


def test_service_resource_runtime_uses_ephemeral_instance_and_never_discloses_paths(
    tmp_path: Path,
) -> None:
    backend = InMemoryCredentialBackend()
    credential_state = (tmp_path / "credentials").resolve()
    state = (tmp_path / "resource-runtime").resolve()
    gestures = (
        lambda _audience, _request, attestation, _action: attestation == "gesture-1"
    )
    first = ServiceResourceRuntime(
        state_dir=state,
        credential_store=CredentialStore(state_dir=credential_state, backend=backend),
        gesture_verifier=gestures,
        harden_callback=None,
        require_hardening=False,
    )
    second = ServiceResourceRuntime(
        state_dir=state,
        credential_store=CredentialStore(state_dir=credential_state, backend=backend),
        gesture_verifier=gestures,
        harden_callback=None,
        require_hardening=False,
    )
    assert first.service_instance_id != second.service_instance_id
    summary = first.capabilities()
    serialized = json.dumps(summary, sort_keys=True)
    assert summary["authenticationKeyPersistedInFiles"] is False
    assert summary["sourcePathDisclosure"] is False
    assert str(state) not in serialized
    assert str(credential_state) not in serialized

    source = (tmp_path / "restart-bound.txt").resolve()
    source.write_text("restart-bound", encoding="utf-8")
    grant = first.issue_local_grant(
        audience=audience(),
        grant_request_id="restart-grant",
        raw_path=source,
        kind="file",
        constraints=constraints(source.stat().st_size),
        attestation_ref="gesture-1",
    )
    with pytest.raises(ServiceResourceRuntimeError):
        second.consume_local_grant(
            resource_ref=grant["resourceRef"],
            audience=audience(),
            use_id="restart-use",
            action="read",
            expected_resource_revision_digest=grant["resourceRevisionDigest"],
            expected_revocation_epoch=grant["revocationEpoch"],
        )


def test_service_resource_runtime_issues_consumes_and_stages_with_official_hardener(
    tmp_path: Path,
) -> None:
    backend = InMemoryCredentialBackend()
    source = (tmp_path / "source.txt").resolve()
    source.write_text("reliable staging", encoding="utf-8")
    hardening_calls: list[tuple[Path, str]] = []

    def harden(path: Path, sandbox_id: str) -> None:
        hardening_calls.append((path, sandbox_id))

    runtime = ServiceResourceRuntime(
        state_dir=(tmp_path / "resource-runtime").resolve(),
        credential_store=CredentialStore(
            state_dir=(tmp_path / "credentials").resolve(), backend=backend
        ),
        gesture_verifier=lambda _audience, _request, attestation, action: (
            attestation == "gesture-1" and action == "approve_local_resource"
        ),
        harden_callback=harden,
        require_hardening=True,
    )
    grant = runtime.issue_local_grant(
        audience=audience(),
        grant_request_id="grant-1",
        raw_path=source,
        kind="file",
        constraints=constraints(source.stat().st_size),
        attestation_ref="gesture-1",
    )
    resolved = runtime.consume_local_grant(
        resource_ref=grant["resourceRef"],
        audience=audience(),
        use_id="use-1",
        action="read",
        expected_resource_revision_digest=grant["resourceRevisionDigest"],
        expected_revocation_epoch=grant["revocationEpoch"],
        requested_constraints=constraints(source.stat().st_size),
    )
    task_id = str(uuid.uuid4())
    workspace = (tmp_path / "tasks" / task_id).resolve()
    workspace.mkdir(parents=True)
    staged = runtime.stage_local_resource(
        resolved,
        audience=audience(),
        task_id=task_id,
        task_workspace=workspace,
        staging_request_id="stage-1",
        task_sandbox_id="sandbox-1",
    )

    assert hardening_calls == [
        (
            workspace
            / staged.workspace_relative_path.split("/")[0]
            / staged.workspace_relative_path.split("/")[1],
            "sandbox-1",
        )
    ]
    assert staged.hardening_applied is True
    locator = staged.worker_locator()
    assert not Path(locator["workspaceRelativePath"]).is_absolute()
    assert str(source) not in json.dumps(locator, sort_keys=True)


def test_production_staging_fails_closed_without_hardener(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    source = (tmp_path / "source.txt").resolve()
    source.write_text("content", encoding="utf-8")
    runtime = ServiceResourceRuntime(
        state_dir=(tmp_path / "resource-runtime").resolve(),
        credential_store=CredentialStore(
            state_dir=(tmp_path / "credentials").resolve(), backend=backend
        ),
        gesture_verifier=lambda *_args: True,
        harden_callback=None,
        require_hardening=True,
    )
    grant = runtime.issue_local_grant(
        audience=audience(),
        grant_request_id="grant-1",
        raw_path=source,
        kind="file",
        constraints=constraints(source.stat().st_size),
        attestation_ref="gesture-1",
    )
    resolved = runtime.consume_local_grant(
        resource_ref=grant["resourceRef"],
        audience=audience(),
        use_id="use-1",
        action="read",
        expected_resource_revision_digest=grant["resourceRevisionDigest"],
        expected_revocation_epoch=0,
        requested_constraints=constraints(source.stat().st_size),
    )
    task_id = str(uuid.uuid4())
    workspace = (tmp_path / "tasks" / task_id).resolve()
    workspace.mkdir(parents=True)
    with pytest.raises(ServiceResourceRuntimeError) as failure:
        runtime.stage_local_resource(
            resolved,
            audience=audience(),
            task_id=task_id,
            task_workspace=workspace,
            staging_request_id="stage-1",
            task_sandbox_id=None,
        )
    assert failure.value.code == "STAGING_HARDENING_REQUIRED"


def test_card_service_lazily_owns_one_resource_runtime_without_public_write_tools(
    tmp_path: Path,
) -> None:
    backend = InMemoryCredentialBackend()
    service = CardService(
        state_dir=(tmp_path / "service-state").resolve(),
        credential_backend=backend,
        resource_gesture_verifier=lambda _audience, _request, attestation, _action: (
            attestation == "trusted-gesture"
        ),
        use_restricted_launcher=False,
    )

    before = service.capabilities()["localResourceRuntime"]
    assert before["initialized"] is False
    assert before["trustedGrantIssuance"] is True
    assert backend.values == {}
    assert "system.request_source_grant" not in service.capabilities()["systemMethods"]

    initialized = service.initialize_local_resource_runtime()
    again = service.initialize_local_resource_runtime()
    assert initialized == again
    assert initialized["initialized"] is True
    assert initialized["taskStaging"] is True
    assert initialized["productionHardeningRequired"] is False
    assert initialized["productionHardeningAvailable"] is False
    assert initialized["sourcePathDisclosure"] is False
    assert len(backend.values) == 1

    serialized_state = b"".join(
        path.read_bytes()
        for path in (tmp_path / "service-state").rglob("*")
        if path.is_file()
    )
    for secret in backend.values.values():
        assert secret.encode("ascii") not in serialized_state


def test_packaged_card_service_rejects_injected_resource_gesture_verifier(
    tmp_path: Path,
) -> None:
    with pytest.raises(CardServiceError) as failure:
        CardService(
            state_dir=(tmp_path / "service-state").resolve(),
            runtime_package=(tmp_path / "untrusted-package").resolve(),
            resource_gesture_verifier=lambda *_args: True,
            use_restricted_launcher=False,
        )
    assert failure.value.code == "RESOURCE_GESTURE_VERIFIER_INJECTION_FORBIDDEN"
