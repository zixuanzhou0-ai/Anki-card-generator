from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import card_service.resource_staging as staging_module
from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.local_resource_registry import LocalResourceGrantRegistry
from card_service.resource_staging import (
    ResourceStagingError,
    StagedResource,
    TaskResourceStager,
)


AUTH_KEY = b"resource-staging-tests-authentication-key-v1"
TASK_ID = "task-12345678"
SANDBOX_ID = "S-1-15-3-123456789"


def audience(**overrides) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": "a" * 64,
        "host_id": "host-main",
        "plugin_id": "plugin-study",
        "session_id": "session-current",
    }
    values.update(overrides)
    return ArtifactAudienceBinding(**values)


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, *, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class Gestures:
    def __call__(self, audience_digest, request_digest, attestation, action) -> bool:
        return (
            len(audience_digest) == 64
            and len(request_digest) == 64
            and attestation == "trusted-gesture"
            and action in {"approve_local_resource", "revoke_local_resource"}
        )


class Hardener:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[Path, str]] = []

    def __call__(self, path: Path, sandbox_id: str) -> None:
        self.calls.append((path, sandbox_id))
        if self.fail:
            raise RuntimeError("hardening failed")


def file_constraints(maximum: int = 1024 * 1024) -> dict:
    return {"actions": ["read"], "maxBytes": maximum}


def directory_constraints(**overrides) -> dict:
    value = {
        "actions": ["enumerate", "read"],
        "maxDepth": 4,
        "maxEntries": 100,
        "maxTotalBytes": 1024 * 1024,
    }
    value.update(overrides)
    return value


def make_registry(tmp_path: Path, *, clock=None) -> LocalResourceGrantRegistry:
    return LocalResourceGrantRegistry(
        tmp_path / "private-local-registry",
        authentication_key=AUTH_KEY,
        service_instance_id="service-main",
        gesture_verifier=Gestures(),
        clock=clock or Clock(),
    )


def make_stager(
    tmp_path: Path,
    *,
    hardener: Hardener | None = None,
    require_hardening: bool = True,
) -> TaskResourceStager:
    return TaskResourceStager(
        tmp_path / "private-staging-registry",
        authentication_key=AUTH_KEY,
        service_instance_id="service-main",
        harden_callback=hardener,
        require_hardening=require_hardening,
    )


def make_workspace(tmp_path: Path, task_id: str = TASK_ID) -> Path:
    workspace = tmp_path / "tasks" / task_id
    workspace.mkdir(parents=True)
    return workspace


def issue_and_consume(
    registry: LocalResourceGrantRegistry,
    path: Path,
    *,
    kind: str,
    constraints: dict,
    request_id: str = "source-grant",
    max_uses: int = 1,
):
    summary = registry.issue_grant(
        audience=audience(),
        grant_request_id=request_id,
        raw_path=str(path.resolve()),
        kind=kind,
        constraints=constraints,
        attestation_ref="trusted-gesture",
        max_uses=max_uses,
    )
    resolved = registry.consume(
        summary["resourceRef"],
        audience(),
        action="read",
        use_id=f"use-{request_id}",
        expected_resource_revision_digest=summary["resourceRevisionDigest"],
        expected_revocation_epoch=summary["revocationEpoch"],
        requested_constraints=constraints,
    )
    return summary, resolved


def stage(
    stager: TaskResourceStager,
    registry: LocalResourceGrantRegistry,
    resolved,
    workspace: Path,
    *,
    request_id: str = "stage-source",
) -> StagedResource:
    return stager.stage(
        resolved,
        registry=registry,
        audience=audience(),
        task_id=TASK_ID,
        task_workspace=workspace,
        staging_request_id=request_id,
        task_sandbox_id=SANDBOX_ID,
    )


def test_file_is_copied_to_an_opaque_relative_locator_and_rehydrates(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "private-source-name"
    source_root.mkdir()
    source = source_root / "lesson.MP4"
    source.write_bytes(b"video-bytes")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    hardener = Hardener()
    stager = make_stager(tmp_path, hardener=hardener)
    workspace = make_workspace(tmp_path)

    staged = stage(stager, registry, resolved, workspace)

    assert staged.kind == "file"
    assert staged.workspace_relative_path.endswith("/payload.mp4")
    assert not Path(staged.workspace_relative_path).is_absolute()
    assert str(source_root) not in json.dumps(staged.worker_locator())
    assert "stagingRef" not in staged.worker_locator()
    assert staged.total_bytes == len(b"video-bytes")
    assert staged.entry_count == 1
    assert staged.hardening_applied is True
    assert len(hardener.calls) == 1
    worker_path = stager.resolve_worker_path(
        staged,
        resource=resolved,
        registry=registry,
        audience=audience(),
        task_workspace=workspace,
    )
    assert worker_path.read_bytes() == b"video-bytes"
    assert worker_path.is_relative_to(workspace)


def test_directory_manifest_is_stable_sorted_and_preserves_empty_directories(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-directory"
    (source / "nested" / "empty").mkdir(parents=True)
    (source / "z.txt").write_text("z", encoding="utf-8")
    (source / "nested" / "a.txt").write_text("alpha", encoding="utf-8")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="directory", constraints=directory_constraints()
    )
    stager = make_stager(tmp_path, hardener=Hardener())
    workspace = make_workspace(tmp_path)

    staged = stage(stager, registry, resolved, workspace)
    path = stager.resolve_worker_path(
        staged,
        resource=resolved,
        registry=registry,
        audience=audience(),
        task_workspace=workspace,
    )

    assert staged.kind == "directory"
    assert staged.entry_count == 4
    assert staged.total_bytes == len(b"z") + len(b"alpha")
    assert (path / "nested" / "empty").is_dir()
    assert (path / "nested" / "a.txt").read_text(encoding="utf-8") == "alpha"


def test_empty_directory_is_a_valid_zero_entry_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "empty-source"
    source.mkdir()
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="directory", constraints=directory_constraints()
    )
    stager = make_stager(tmp_path, hardener=Hardener())
    staged = stage(stager, registry, resolved, make_workspace(tmp_path))
    assert staged.entry_count == 0
    assert staged.total_bytes == 0


def test_staging_is_idempotent_without_recopying_or_rehardening(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"same")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    hardener = Hardener()
    stager = make_stager(tmp_path, hardener=hardener)
    workspace = make_workspace(tmp_path)
    first = stage(stager, registry, resolved, workspace)
    second = stage(stager, registry, resolved, workspace)
    assert second == first
    assert len(hardener.calls) == 1


def test_staging_request_id_conflict_does_not_reuse_another_source(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    registry = make_registry(tmp_path)
    _, first_resolved = issue_and_consume(
        registry,
        first,
        kind="file",
        constraints=file_constraints(),
        request_id="first-grant",
    )
    _, second_resolved = issue_and_consume(
        registry,
        second,
        kind="file",
        constraints=file_constraints(),
        request_id="second-grant",
    )
    stager = make_stager(tmp_path, hardener=Hardener())
    workspace = make_workspace(tmp_path)
    stage(stager, registry, first_resolved, workspace, request_id="same-stage")
    with pytest.raises(ResourceStagingError) as conflict:
        stage(stager, registry, second_resolved, workspace, request_id="same-stage")
    assert conflict.value.code == "STAGING_IDEMPOTENCY_CONFLICT"


def test_tampered_resolved_resource_proof_is_rejected_before_copy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("trusted", encoding="utf-8")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    forged = dataclasses.replace(resolved, path=tmp_path / "other.txt")
    stager = make_stager(tmp_path, hardener=Hardener())
    with pytest.raises(ResourceStagingError) as blocked:
        stage(stager, registry, forged, make_workspace(tmp_path))
    assert blocked.value.code == "RESOURCE_RESOLUTION_INVALID"


def test_source_change_after_consume_is_rejected_before_staging(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    source.write_text("after-change", encoding="utf-8")
    with pytest.raises(ResourceStagingError) as changed:
        stage(
            make_stager(tmp_path, hardener=Hardener()),
            registry,
            resolved,
            make_workspace(tmp_path),
        )
    assert changed.value.code == "RESOURCE_CHANGED"


def test_source_change_during_directory_copy_is_rejected_and_partial_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source-directory"
    source.mkdir()
    (source / "one.txt").write_text("one", encoding="utf-8")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="directory", constraints=directory_constraints()
    )
    real_copy = staging_module._copy_file_snapshot

    def mutate_after_copy(source_file, target, *, maximum_bytes):
        result = real_copy(source_file, target, maximum_bytes=maximum_bytes)
        (source / "late.txt").write_text("late", encoding="utf-8")
        return result

    monkeypatch.setattr(staging_module, "_copy_file_snapshot", mutate_after_copy)
    workspace = make_workspace(tmp_path)
    with pytest.raises(ResourceStagingError) as changed:
        stage(
            make_stager(tmp_path, hardener=Hardener()),
            registry,
            resolved,
            workspace,
        )
    assert changed.value.code == "STAGING_SOURCE_CHANGED"
    inputs = workspace / "inputs"
    assert not inputs.exists() or list(inputs.iterdir()) == []


def test_staged_content_tamper_is_rejected_on_rehydration(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    stager = make_stager(tmp_path, hardener=Hardener())
    workspace = make_workspace(tmp_path)
    staged = stage(stager, registry, resolved, workspace)
    target = workspace.joinpath(*Path(staged.workspace_relative_path).parts)
    target.write_bytes(b"tampered")
    with pytest.raises(ResourceStagingError) as changed:
        stager.resolve_worker_path(
            staged,
            resource=resolved,
            registry=registry,
            audience=audience(),
            task_workspace=workspace,
        )
    assert changed.value.code == "STAGING_CONTENT_CHANGED"


def test_private_receipt_tamper_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    stager = make_stager(tmp_path, hardener=Hardener())
    workspace = make_workspace(tmp_path)
    staged = stage(stager, registry, resolved, workspace)
    record = next((tmp_path / "private-staging-registry" / "records").rglob("*.json"))
    value = json.loads(record.read_text(encoding="utf-8"))
    value["totalBytes"] += 1
    record.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(ResourceStagingError) as corrupt:
        stager.resolve_worker_path(
            staged,
            resource=resolved,
            registry=registry,
            audience=audience(),
            task_workspace=workspace,
        )
    assert corrupt.value.code == "STAGING_RECORD_CORRUPT"


def test_forged_public_staging_proof_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    stager = make_stager(tmp_path, hardener=Hardener())
    workspace = make_workspace(tmp_path)
    staged = stage(stager, registry, resolved, workspace)
    forged = dataclasses.replace(staged, total_bytes=staged.total_bytes + 1)
    with pytest.raises(ResourceStagingError) as invalid:
        stager.resolve_worker_path(
            forged,
            resource=resolved,
            registry=registry,
            audience=audience(),
            task_workspace=workspace,
        )
    assert invalid.value.code == "STAGING_RESOLUTION_INVALID"


def test_revoked_source_grant_invalidates_existing_staging(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    registry = make_registry(tmp_path)
    summary, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    stager = make_stager(tmp_path, hardener=Hardener())
    workspace = make_workspace(tmp_path)
    staged = stage(stager, registry, resolved, workspace)
    registry.revoke(
        summary["resourceRef"],
        audience(),
        revocation_id="revoke-source",
        expected_revocation_epoch=0,
        attestation_ref="trusted-gesture",
    )
    with pytest.raises(ResourceStagingError) as revoked:
        stager.resolve_worker_path(
            staged,
            resource=resolved,
            registry=registry,
            audience=audience(),
            task_workspace=workspace,
        )
    assert revoked.value.code == "RESOURCE_REVOCATION_CHANGED"


def test_expired_source_grant_invalidates_existing_staging(tmp_path: Path) -> None:
    clock = Clock()
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    registry = make_registry(tmp_path, clock=clock)
    summary = registry.issue_grant(
        audience=audience(),
        grant_request_id="short-grant",
        raw_path=str(source.resolve()),
        kind="file",
        constraints=file_constraints(),
        attestation_ref="trusted-gesture",
        expires_at=clock() + timedelta(seconds=1),
    )
    resolved = registry.consume(
        summary["resourceRef"],
        audience(),
        action="read",
        use_id="short-use",
        expected_resource_revision_digest=summary["resourceRevisionDigest"],
        expected_revocation_epoch=0,
    )
    stager = make_stager(tmp_path, hardener=Hardener())
    workspace = make_workspace(tmp_path)
    staged = stage(stager, registry, resolved, workspace)
    clock.advance(seconds=2)
    with pytest.raises(ResourceStagingError) as expired:
        stager.resolve_worker_path(
            staged,
            resource=resolved,
            registry=registry,
            audience=audience(),
            task_workspace=workspace,
        )
    assert expired.value.code == "RESOURCE_EXPIRED"


def test_workspace_replacement_invalidates_staging_receipt(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    stager = make_stager(tmp_path, hardener=Hardener())
    workspace = make_workspace(tmp_path)
    staged = stage(stager, registry, resolved, workspace)
    moved = workspace.with_name("old-task")
    workspace.rename(moved)
    workspace.mkdir()
    with pytest.raises(ResourceStagingError) as changed:
        stager.resolve_worker_path(
            staged,
            resource=resolved,
            registry=registry,
            audience=audience(),
            task_workspace=workspace,
        )
    assert changed.value.code == "STAGING_WORKSPACE_CHANGED"


def test_task_workspace_name_and_private_state_overlap_are_rejected(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    stager = make_stager(tmp_path, hardener=Hardener())
    wrong_workspace = make_workspace(tmp_path, task_id="different-task")
    with pytest.raises(ResourceStagingError) as mismatch:
        stage(stager, registry, resolved, wrong_workspace)
    assert mismatch.value.code == "STAGING_TASK_MISMATCH"

    overlapping_state = TaskResourceStager(
        wrong_workspace / "private-state",
        authentication_key=AUTH_KEY,
        service_instance_id="service-main",
        harden_callback=Hardener(),
    )
    with pytest.raises(ResourceStagingError) as overlap:
        overlapping_state.stage(
            resolved,
            registry=registry,
            audience=audience(),
            task_id="different-task",
            task_workspace=wrong_workspace,
            staging_request_id="stage-overlap",
            task_sandbox_id=SANDBOX_ID,
        )
    assert overlap.value.code == "STAGING_PATH_OVERLAP"


def test_production_hardening_is_required_and_failure_cleans_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    workspace = make_workspace(tmp_path)
    with pytest.raises(ResourceStagingError) as required:
        stage(make_stager(tmp_path, hardener=None), registry, resolved, workspace)
    assert required.value.code == "STAGING_HARDENING_REQUIRED"
    assert list((workspace / "inputs").iterdir()) == []

    failing = make_stager(tmp_path / "second", hardener=Hardener(fail=True))
    second_workspace = make_workspace(tmp_path / "second")
    with pytest.raises(RuntimeError, match="hardening failed"):
        stage(failing, registry, resolved, second_workspace)
    assert list((second_workspace / "inputs").iterdir()) == []


@pytest.mark.parametrize(
    ("constraints", "expected_code"),
    [
        (directory_constraints(maxDepth=0), "STAGING_DEPTH_LIMIT"),
        (directory_constraints(maxEntries=1), "STAGING_ENTRY_LIMIT"),
        (directory_constraints(maxTotalBytes=2), "STAGING_BYTE_LIMIT"),
    ],
)
def test_directory_depth_entry_and_byte_limits_fail_closed(
    tmp_path: Path, constraints: dict, expected_code: str
) -> None:
    source = tmp_path / expected_code
    (source / "nested").mkdir(parents=True)
    (source / "a.txt").write_text("abc", encoding="utf-8")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry,
        source,
        kind="directory",
        constraints=constraints,
        request_id=expected_code.casefold(),
    )
    with pytest.raises(ResourceStagingError) as limited:
        stage(
            make_stager(tmp_path, hardener=Hardener()),
            registry,
            resolved,
            make_workspace(tmp_path),
        )
    assert limited.value.code == expected_code


def test_directory_symlink_or_hardlink_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "unsafe-directory"
    source.mkdir()
    target = source / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = source / "link.txt"
    try:
        os.link(target, link)
    except OSError:
        pytest.skip("hardlink creation is unavailable")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="directory", constraints=directory_constraints()
    )
    with pytest.raises(ResourceStagingError) as unsafe:
        stage(
            make_stager(tmp_path, hardener=Hardener()),
            registry,
            resolved,
            make_workspace(tmp_path),
        )
    assert unsafe.value.code == "STAGING_SOURCE_UNSAFE"


def test_private_receipt_does_not_persist_the_absolute_source_path(
    tmp_path: Path,
) -> None:
    secret_parent = tmp_path / "sensitive-user-folder"
    secret_parent.mkdir()
    source = secret_parent / "source.bin"
    source.write_bytes(b"payload")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    stage(
        make_stager(tmp_path, hardener=Hardener()),
        registry,
        resolved,
        make_workspace(tmp_path),
    )
    records = b"".join(
        path.read_bytes()
        for path in (tmp_path / "private-staging-registry" / "records").rglob("*.json")
    )
    assert str(source.resolve()).encode("utf-8") not in records
    assert str(secret_parent.resolve()).encode("utf-8") not in records


def test_development_mode_is_explicitly_marked_unhardened(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    registry = make_registry(tmp_path)
    _, resolved = issue_and_consume(
        registry, source, kind="file", constraints=file_constraints()
    )
    stager = make_stager(tmp_path, hardener=None, require_hardening=False)
    staged = stage(stager, registry, resolved, make_workspace(tmp_path))
    assert staged.hardening_applied is False
    assert staged.worker_locator()["hardeningApplied"] is False
