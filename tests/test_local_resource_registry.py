from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.local_resource_registry import (
    LocalResourceGrantRegistry,
    LocalResourceRegistryError,
)


AUTH_KEY = b"local-resource-registry-test-key-32-bytes"
OWNER = hashlib.sha256(b"local-resource-owner").hexdigest()


def audience(
    *,
    owner: str = OWNER,
    host: str = "codex-desktop",
    plugin: str = "speakright.study",
    session: str = "session-local-resource",
) -> ArtifactAudienceBinding:
    return ArtifactAudienceBinding(
        owner_digest=owner,
        host_id=host,
        plugin_id=plugin,
        session_id=session,
    )


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


class Gestures:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def __call__(self, audience_digest: str, request_digest: str, attestation: str, action: str) -> bool:
        self.calls.append((audience_digest, request_digest, attestation, action))
        return attestation == "trusted-gesture"


def file_constraints(*, maximum: int = 1024, actions=None):
    return {"actions": actions or ["read"], "maxBytes": maximum}


def directory_constraints(**overrides):
    value = {
        "actions": ["enumerate", "read"],
        "maxDepth": 4,
        "maxEntries": 200,
        "maxTotalBytes": 1024 * 1024,
    }
    value.update(overrides)
    return value


def output_constraints(**overrides):
    value = {
        "actions": ["create", "versioned"],
        "maxFiles": 100,
        "maxTotalBytes": 1024 * 1024,
    }
    value.update(overrides)
    return value


def make_registry(tmp_path: Path, *, gestures=None, clock=None) -> LocalResourceGrantRegistry:
    return LocalResourceGrantRegistry(
        (tmp_path / "registry").resolve(),
        authentication_key=AUTH_KEY,
        service_instance_id="card-service-local",
        gesture_verifier=gestures,
        clock=clock or Clock(),
    )


def issue_file(
    registry: LocalResourceGrantRegistry,
    source: Path,
    *,
    request_id: str = "grant-file-1",
    maximum: int = 1024,
    max_uses: int = 1,
    bound_audience: ArtifactAudienceBinding | None = None,
):
    return registry.issue_grant(
        audience=bound_audience or audience(),
        grant_request_id=request_id,
        raw_path=str(source.resolve()),
        kind="file",
        constraints=file_constraints(maximum=maximum),
        attestation_ref="trusted-gesture",
        max_uses=max_uses,
    )


def test_file_grant_is_opaque_session_bound_and_revalidates_before_use(tmp_path: Path) -> None:
    gestures = Gestures()
    registry = make_registry(tmp_path, gestures=gestures)
    source = tmp_path / "source.txt"
    source.write_text("reliable source", encoding="utf-8")

    summary = issue_file(registry, source, max_uses=2)
    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["kind"] == "file"
    assert summary["state"] == "active"
    assert summary["remainingUses"] == 2
    assert str(source.resolve()) not in serialized
    assert summary["resourceRef"].startswith("resource_")
    assert gestures.calls[-1][3] == "approve_local_resource"

    resolved = registry.consume(
        summary["resourceRef"],
        audience(),
        action="read",
        use_id="use-file-1",
        expected_resource_revision_digest=summary["resourceRevisionDigest"],
        expected_revocation_epoch=0,
    )
    assert resolved.path == source.resolve()
    assert resolved.kind == "file"
    assert registry.inspect(summary["resourceRef"], audience())["remainingUses"] == 1


def test_public_and_persisted_binding_do_not_expose_raw_handles_or_gesture_ids(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    source = tmp_path / "private-source.txt"
    source.write_text("safe", encoding="utf-8")
    summary = registry.issue_grant(
        audience=audience(),
        grant_request_id="private-request-canary",
        raw_path=str(source.resolve()),
        kind="file",
        constraints=file_constraints(),
        attestation_ref="trusted-gesture",
    )
    registry.consume(
        summary["resourceRef"],
        audience(),
        action="read",
        use_id="private-use-canary",
        expected_resource_revision_digest=summary["resourceRevisionDigest"],
        expected_revocation_epoch=0,
    )

    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "registry").rglob("*.json")
    )
    public = json.dumps(registry.inspect(summary["resourceRef"], audience()), ensure_ascii=False)
    assert summary["resourceRef"] not in persisted
    assert "private-request-canary" not in persisted
    assert "private-use-canary" not in persisted
    assert "trusted-gesture" not in persisted
    assert str(source.resolve()) not in public
    assert "rawPath" not in public


def test_gesture_verification_is_fail_closed_and_happens_before_persistence(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    registry = make_registry(tmp_path)
    with pytest.raises(LocalResourceRegistryError) as missing:
        issue_file(registry, source)
    assert missing.value.code == "RESOURCE_GESTURE_REQUIRED"
    assert not list((tmp_path / "registry" / "records").rglob("*.json"))

    registry = make_registry(tmp_path / "denied", gestures=lambda *_: False)
    with pytest.raises(LocalResourceRegistryError) as denied:
        issue_file(registry, source)
    assert denied.value.code == "RESOURCE_GESTURE_REQUIRED"


@pytest.mark.parametrize(
    "other",
    [
        audience(owner=hashlib.sha256(b"other-owner").hexdigest()),
        audience(host="other-host"),
        audience(plugin="other-plugin"),
        audience(session="other-session"),
    ],
)
def test_reference_cannot_cross_any_audience_boundary(tmp_path: Path, other: ArtifactAudienceBinding) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    summary = issue_file(registry, source)
    with pytest.raises(LocalResourceRegistryError) as error:
        registry.inspect(summary["resourceRef"], other)
    assert error.value.code == "RESOURCE_AUDIENCE_MISMATCH"


def test_service_instance_is_part_of_the_audience_binding(tmp_path: Path) -> None:
    gestures = Gestures()
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    registry = make_registry(tmp_path, gestures=gestures)
    summary = issue_file(registry, source)
    other = LocalResourceGrantRegistry(
        (tmp_path / "registry").resolve(),
        authentication_key=AUTH_KEY,
        service_instance_id="another-card-service",
        gesture_verifier=gestures,
        clock=Clock(),
    )
    with pytest.raises(LocalResourceRegistryError) as error:
        other.inspect(summary["resourceRef"], audience())
    assert error.value.code == "RESOURCE_AUDIENCE_MISMATCH"


def test_issue_and_use_are_idempotent_but_conflicting_replays_fail(tmp_path: Path) -> None:
    gestures = Gestures()
    registry = make_registry(tmp_path, gestures=gestures)
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    first = issue_file(registry, source, max_uses=1)
    replay = issue_file(registry, source, max_uses=1)
    assert replay == first
    assert len(gestures.calls) == 1

    with pytest.raises(LocalResourceRegistryError) as conflict:
        issue_file(registry, source, maximum=2048, max_uses=1)
    assert conflict.value.code == "RESOURCE_IDEMPOTENCY_CONFLICT"

    kwargs = dict(
        action="read",
        use_id="same-use",
        expected_resource_revision_digest=first["resourceRevisionDigest"],
        expected_revocation_epoch=0,
    )
    registry.consume(first["resourceRef"], audience(), **kwargs)
    registry.consume(first["resourceRef"], audience(), **kwargs)
    with pytest.raises(LocalResourceRegistryError) as exhausted:
        registry.consume(
            first["resourceRef"],
            audience(),
            action="read",
            use_id="another-use",
            expected_resource_revision_digest=first["resourceRevisionDigest"],
            expected_revocation_epoch=0,
        )
    assert exhausted.value.code == "RESOURCE_USES_EXHAUSTED"


def test_use_id_cannot_be_replayed_with_a_different_constraint_request(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    summary = issue_file(registry, source, maximum=1024, max_uses=2)
    base = dict(
        action="read",
        use_id="same-use",
        expected_resource_revision_digest=summary["resourceRevisionDigest"],
        expected_revocation_epoch=0,
    )
    registry.consume(
        summary["resourceRef"], audience(), requested_constraints=file_constraints(maximum=512), **base
    )
    with pytest.raises(LocalResourceRegistryError) as conflict:
        registry.consume(
            summary["resourceRef"], audience(), requested_constraints=file_constraints(maximum=256), **base
        )
    assert conflict.value.code == "RESOURCE_USE_ID_CONFLICT"


def test_file_content_replacement_invalidates_the_grant(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    source = tmp_path / "source.txt"
    source.write_text("first value", encoding="utf-8")
    summary = issue_file(registry, source)
    source.write_text("second value", encoding="utf-8")
    with pytest.raises(LocalResourceRegistryError) as changed:
        registry.consume(
            summary["resourceRef"],
            audience(),
            action="read",
            use_id="use-after-change",
            expected_resource_revision_digest=summary["resourceRevisionDigest"],
            expected_revocation_epoch=0,
        )
    assert changed.value.code == "RESOURCE_CHANGED"


def test_directory_and_output_constraints_cannot_be_widened(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    source_dir = tmp_path / "sources"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()
    directory = registry.issue_grant(
        audience=audience(),
        grant_request_id="directory-grant",
        raw_path=str(source_dir.resolve()),
        kind="directory",
        constraints=directory_constraints(),
        attestation_ref="trusted-gesture",
    )
    output = registry.issue_grant(
        audience=audience(),
        grant_request_id="output-grant",
        raw_path=str(output_dir.resolve()),
        kind="output_directory",
        constraints=output_constraints(),
        attestation_ref="trusted-gesture",
        max_uses=2,
    )
    assert directory["kind"] == "directory"
    assert output["kind"] == "output_directory"
    narrowed = directory_constraints(actions=["read"], maxDepth=2, maxEntries=10)
    resolved = registry.consume(
        directory["resourceRef"],
        audience(),
        action="read",
        use_id="directory-use",
        expected_resource_revision_digest=directory["resourceRevisionDigest"],
        expected_revocation_epoch=0,
        requested_constraints=narrowed,
    )
    assert resolved.constraints == narrowed

    with pytest.raises(LocalResourceRegistryError) as action:
        registry.consume(
            output["resourceRef"],
            audience(),
            action="replace",
            use_id="output-replace",
            expected_resource_revision_digest=output["resourceRevisionDigest"],
            expected_revocation_epoch=0,
        )
    assert action.value.code == "RESOURCE_ACTION_FORBIDDEN"
    registry.consume(
        output["resourceRef"],
        audience(),
        action="create",
        use_id="output-create",
        expected_resource_revision_digest=output["resourceRevisionDigest"],
        expected_revocation_epoch=0,
    )
    (output_dir / "first.apkg").write_bytes(b"first")
    registry.consume(
        output["resourceRef"],
        audience(),
        action="versioned",
        use_id="output-versioned",
        expected_resource_revision_digest=output["resourceRevisionDigest"],
        expected_revocation_epoch=0,
    )
    assert registry.inspect(output["resourceRef"], audience())["state"] == "exhausted"


def test_revoke_requires_a_new_gesture_and_is_idempotent(tmp_path: Path) -> None:
    gestures = Gestures()
    registry = make_registry(tmp_path, gestures=gestures)
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    summary = issue_file(registry, source, max_uses=2)
    revoked = registry.revoke(
        summary["resourceRef"],
        audience(),
        revocation_id="revoke-1",
        expected_revocation_epoch=0,
        attestation_ref="trusted-gesture",
    )
    assert revoked["state"] == "revoked"
    assert revoked["revocationEpoch"] == 1
    assert gestures.calls[-1][3] == "revoke_local_resource"
    assert registry.revoke(
        summary["resourceRef"],
        audience(),
        revocation_id="revoke-1",
        expected_revocation_epoch=0,
        attestation_ref="ignored-on-idempotent-replay",
    ) == revoked
    with pytest.raises(LocalResourceRegistryError) as consumed:
        registry.consume(
            summary["resourceRef"],
            audience(),
            action="read",
            use_id="after-revoke",
            expected_resource_revision_digest=summary["resourceRevisionDigest"],
            expected_revocation_epoch=0,
        )
    assert consumed.value.code == "RESOURCE_REVOKED"


def test_list_grants_is_bounded_audience_scoped_and_pathless(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    source = tmp_path / "private-source.txt"
    source.write_text("safe", encoding="utf-8")
    first = issue_file(registry, source)
    other = audience(session="session-other")
    other_source = tmp_path / "other-private-source.txt"
    other_source.write_text("safe", encoding="utf-8")
    registry.issue_grant(
        audience=other,
        grant_request_id="other-grant",
        raw_path=other_source,
        kind="file",
        constraints={"actions": ["read"], "maxBytes": 4},
        attestation_ref="trusted-gesture",
    )

    listed = registry.list_grants(audience())

    assert [item["resourceRef"] for item in listed] == [first["resourceRef"]]
    serialized = json.dumps(listed, sort_keys=True)
    assert str(source) not in serialized
    assert str(other_source) not in serialized
    assert "rawPath" not in serialized

    registry.revoke(
        first["resourceRef"],
        audience(),
        revocation_id="list-revoke",
        expected_revocation_epoch=0,
        attestation_ref="trusted-gesture",
    )
    assert registry.list_grants(audience()) == []
    assert registry.list_grants(audience(), include_terminal=True)[0]["state"] == "revoked"


def test_expired_grant_is_visible_but_cannot_be_consumed(tmp_path: Path) -> None:
    clock = Clock()
    registry = make_registry(tmp_path, gestures=Gestures(), clock=clock)
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    summary = registry.issue_grant(
        audience=audience(),
        grant_request_id="short-grant",
        raw_path=str(source.resolve()),
        kind="file",
        constraints=file_constraints(),
        attestation_ref="trusted-gesture",
        expires_at=clock.value + timedelta(seconds=1),
    )
    clock.advance(seconds=2)
    assert registry.inspect(summary["resourceRef"], audience())["state"] == "expired"
    assert registry.issue_grant(
        audience=audience(),
        grant_request_id="short-grant",
        raw_path=str(source.resolve()),
        kind="file",
        constraints=file_constraints(),
        attestation_ref="not-needed-for-an-exact-replay",
        expires_at=None,
    )["state"] == "expired"
    with pytest.raises(LocalResourceRegistryError) as expired:
        registry.consume(
            summary["resourceRef"],
            audience(),
            action="read",
            use_id="expired-use",
            expected_resource_revision_digest=summary["resourceRevisionDigest"],
            expected_revocation_epoch=0,
        )
    assert expired.value.code == "RESOURCE_EXPIRED"


def test_hardlinks_symlinks_and_unsafe_path_syntax_are_rejected(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    hardlink = tmp_path / "hardlink.txt"
    try:
        os.link(source, hardlink)
    except OSError:
        hardlink = None
    if hardlink is not None:
        with pytest.raises(LocalResourceRegistryError) as linked:
            issue_file(registry, source, request_id="hardlink-grant")
        assert linked.value.code == "RESOURCE_FILE_UNSAFE"
        hardlink.unlink()
    symlink = tmp_path / "symlink.txt"
    try:
        symlink.symlink_to(source)
    except OSError:
        symlink = None
    if symlink is not None:
        with pytest.raises(LocalResourceRegistryError) as linked:
            registry.issue_grant(
                audience=audience(), grant_request_id="symlink-grant",
                raw_path=str(symlink), kind="file", constraints=file_constraints(),
                attestation_ref="trusted-gesture",
            )
        assert linked.value.code == "RESOURCE_PATH_UNSAFE"

    with pytest.raises(LocalResourceRegistryError) as relative:
        registry.issue_grant(
            audience=audience(),
            grant_request_id="relative",
            raw_path="relative.txt",
            kind="file",
            constraints=file_constraints(),
            attestation_ref="trusted-gesture",
        )
    assert relative.value.code == "RESOURCE_PATH_INVALID"
    with pytest.raises(LocalResourceRegistryError) as unc:
        registry.issue_grant(
            audience=audience(),
            grant_request_id="unc",
            raw_path=r"\\server\share\source.txt",
            kind="file",
            constraints=file_constraints(),
            attestation_ref="trusted-gesture",
        )
    assert unc.value.code == "RESOURCE_PATH_INVALID"
    if os.name == "nt":
        with pytest.raises(LocalResourceRegistryError) as stream:
            registry.issue_grant(
                audience=audience(),
                grant_request_id="ads",
                raw_path=str(source.resolve()) + ":stream",
                kind="file",
                constraints=file_constraints(),
                attestation_ref="trusted-gesture",
            )
        assert stream.value.code == "RESOURCE_PATH_INVALID"


def test_secret_like_file_name_is_redacted_from_public_summary(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    source = tmp_path / ("sk-" + "A" * 24 + ".txt")
    source.write_text("safe", encoding="utf-8")
    summary = issue_file(registry, source)
    assert summary["displayName"] == "Selected file"
    assert source.name not in json.dumps(summary)


def test_record_and_binding_tampering_fail_closed_without_backup_rollback(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    summary = issue_file(registry, source, max_uses=2)
    registry.consume(
        summary["resourceRef"],
        audience(),
        action="read",
        use_id="make-backup",
        expected_resource_revision_digest=summary["resourceRevisionDigest"],
        expected_revocation_epoch=0,
    )
    record = next((tmp_path / "registry" / "records").rglob("*.json"))
    assert record.with_suffix(".json.bak").exists()
    value = json.loads(record.read_text(encoding="utf-8"))
    value["useCount"] = 0
    record.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(LocalResourceRegistryError) as corrupt:
        registry.inspect(summary["resourceRef"], audience())
    assert corrupt.value.code == "RESOURCE_RECORD_CORRUPT"

    other_root = tmp_path / "binding-tamper"
    other = make_registry(other_root, gestures=Gestures())
    source2 = tmp_path / "source-2.txt"
    source2.write_text("safe", encoding="utf-8")
    summary2 = issue_file(other, source2)
    binding = next((other_root / "registry" / "bindings").rglob("*.json"))
    binding.write_bytes(binding.read_bytes()[:-1] + b" ")
    with pytest.raises(LocalResourceRegistryError) as invalid:
        other.inspect(summary2["resourceRef"], audience())
    assert invalid.value.code == "RESOURCE_RECORD_INVALID"


def test_resolved_resource_produces_only_an_exact_legacy_binding(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    summary = issue_file(registry, source)
    resolved = registry.consume(
        summary["resourceRef"],
        audience(),
        action="read",
        use_id="legacy-use",
        expected_resource_revision_digest=summary["resourceRevisionDigest"],
        expected_revocation_epoch=0,
    )
    binding = resolved.legacy_binding(
        json_pointer="/video_path",
        raw_project_value=str(source.resolve()),
        legacy_kind="source_file",
    )
    assert binding.resource_revision_digest == summary["resourceRevisionDigest"]
    assert binding.internal_resource_binding_id == resolved.grant_id
    with pytest.raises(LocalResourceRegistryError) as wrong_path:
        resolved.legacy_binding(
            json_pointer="/video_path",
            raw_project_value=str((tmp_path / "other.txt").resolve()),
            legacy_kind="source_file",
        )
    assert wrong_path.value.code == "RESOURCE_PATH_MISMATCH"
    with pytest.raises(LocalResourceRegistryError) as wrong_kind:
        resolved.legacy_binding(
            json_pointer="/output_directory",
            raw_project_value=str(source.resolve()),
            legacy_kind="output_directory",
        )
    assert wrong_kind.value.code == "RESOURCE_KIND_MISMATCH"
