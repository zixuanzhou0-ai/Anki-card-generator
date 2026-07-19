from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

from card_service.artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)


AUTH_KEY = bytes(range(32))
OWNER = hashlib.sha256(b"owner-sid").hexdigest()
INPUT_FINGERPRINT = hashlib.sha256(b"input-manifest").hexdigest()


def audience(**changes: str) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


def registry(root: Path, *, service: str = "service-1", key: bytes = AUTH_KEY) -> ArtifactRegistry:
    return ArtifactRegistry(root, authentication_key=key, service_instance_id=service)


def publish(
    store: ArtifactRegistry,
    *,
    bound_audience: ArtifactAudienceBinding | None = None,
    project_id: str = "project-1",
    project_revision: int = 1,
    artifact_id: str = "artifact-1",
    artifact_revision: int = 1,
    payload: object | None = None,
    parents: list[dict[str, object]] | None = None,
    completeness: dict[str, object] | None = None,
):
    return store.publish(
        audience=bound_audience or audience(),
        project_id=project_id,
        project_revision=project_revision,
        artifact_id=artifact_id,
        artifact_revision=artifact_revision,
        payload_schema="study.test.payload",
        payload_schema_version=1,
        payload={"text": "hello", "count": 1} if payload is None else payload,
        producer={"component": "test-suite", "version": "1.0.0"},
        parents=parents or [],
        input_fingerprint=INPUT_FINGERPRINT,
        completeness=completeness
        or {"state": "complete", "omittedLocators": [], "reasonCodes": []},
        issue_refs=[],
    )


def rewrite_canonical(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))


def test_publish_resolve_restart_and_no_bearer_or_key_persistence(tmp_path: Path) -> None:
    store = registry(tmp_path / "registry")
    publication = publish(store)

    resolved = store.resolve(publication.handle, audience())
    assert resolved == publication.envelope
    assert resolved["payload"] == {"text": "hello", "count": 1}
    persisted = b"\n".join(path.read_bytes() for path in (tmp_path / "registry").rglob("*") if path.is_file())
    assert publication.handle.encode("ascii") not in persisted
    assert AUTH_KEY not in persisted

    restarted = registry(tmp_path / "registry", service="service-2")
    with pytest.raises(ArtifactRegistryError) as captured:
        restarted.resolve(publication.handle, audience())
    assert captured.value.code == "ARTIFACT_HANDLE_SCOPE_MISMATCH"

    replacement = restarted.issue_handle(publication.artifact_ref, audience())
    assert replacement != publication.handle
    assert restarted.resolve(replacement, audience())["artifactDigest"] == publication.artifact_ref["artifactDigest"]


@pytest.mark.parametrize(
    "changed",
    [
        {"owner_digest": hashlib.sha256(b"other-owner").hexdigest()},
        {"host_id": "other-host"},
        {"plugin_id": "other-plugin"},
        {"session_id": "other-session"},
    ],
)
def test_handle_is_bound_to_owner_host_plugin_and_session(tmp_path: Path, changed: dict[str, str]) -> None:
    store = registry(tmp_path / "registry")
    publication = publish(store)
    with pytest.raises(ArtifactRegistryError) as captured:
        store.resolve(publication.handle, audience(**changed))
    assert captured.value.code in {"ARTIFACT_HANDLE_SCOPE_MISMATCH", "ARTIFACT_AUTH_MISMATCH"}


def test_envelope_tamper_even_with_recomputed_digest_cannot_forge_registry_auth(tmp_path: Path) -> None:
    store = registry(tmp_path / "registry")
    publication = publish(store)
    path = store._artifact_path("project-1", "artifact-1", 1)
    forged = json.loads(path.read_text(encoding="utf-8"))
    forged["payload"] = {"text": "forged", "count": 1}
    forged["payloadSha256"] = hashlib.sha256(canonical_json_bytes(forged["payload"])).hexdigest()
    preimage = dict(forged)
    preimage.pop("artifactDigest")
    preimage.pop("registryAuthRef")
    forged["artifactDigest"] = hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()
    rewrite_canonical(path, forged)
    forged_ref = dict(publication.artifact_ref)
    forged_ref["artifactDigest"] = forged["artifactDigest"]

    with pytest.raises(ArtifactRegistryError) as captured:
        store.issue_handle(forged_ref, audience())
    assert captured.value.code == "ARTIFACT_AUTH_MISMATCH"


@pytest.mark.parametrize("target", ["record", "handle"])
def test_authenticated_registry_metadata_tamper_is_rejected(tmp_path: Path, target: str) -> None:
    store = registry(tmp_path / "registry")
    publication = publish(store)
    if target == "record":
        path = store._record_path(publication.artifact_ref["registryAuthRef"])
        value = json.loads(path.read_text(encoding="utf-8"))
        value["projectOwnerDigest"] = hashlib.sha256(b"attacker").hexdigest()
    else:
        path = store._handle_path(publication.handle)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["serviceInstanceId"] = "attacker-service"
    rewrite_canonical(path, value)

    with pytest.raises(ArtifactRegistryError) as captured:
        store.resolve(publication.handle, audience())
    assert captured.value.code in {"ARTIFACT_AUTH_INVALID", "ARTIFACT_HANDLE_AUTH_INVALID"}


def test_revision_chain_parent_and_project_scope_are_enforced(tmp_path: Path) -> None:
    store = registry(tmp_path / "registry")
    first = publish(store)
    second = publish(
        store,
        project_revision=2,
        artifact_revision=2,
        payload={"text": "second"},
        parents=[dict(first.artifact_ref)],
    )
    assert store.resolve(second.handle, audience())["artifactRevision"] == 2

    with pytest.raises(ArtifactRegistryError) as missing_parent:
        publish(store, project_revision=3, artifact_revision=3, payload={"text": "third"})
    assert missing_parent.value.code == "ARTIFACT_REVISION_CONFLICT"

    other = publish(store, project_id="project-2", artifact_id="other-artifact")
    with pytest.raises(ArtifactRegistryError) as transplant:
        publish(store, project_revision=3, artifact_revision=3, parents=[dict(second.artifact_ref), dict(other.artifact_ref)])
    assert transplant.value.code == "ARTIFACT_SCOPE_MISMATCH"


def test_revocation_is_authenticated_append_only_and_concurrently_idempotent(tmp_path: Path) -> None:
    store = registry(tmp_path / "registry")
    publication = publish(store)
    barrier = threading.Barrier(3)
    outcomes: list[bool] = []

    def attempt() -> None:
        barrier.wait()
        outcomes.append(store.revoke(publication.artifact_ref, audience(), reason_code="user_request"))

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == [False, True]
    with pytest.raises(ArtifactRegistryError) as captured:
        store.resolve(publication.handle, audience())
    assert captured.value.code == "ARTIFACT_REVOKED"

    revocation_path = store._revocation_path(publication.artifact_ref["registryAuthRef"])
    revocation = json.loads(revocation_path.read_text(encoding="utf-8"))
    revocation["reasonCode"] = "forged"
    rewrite_canonical(revocation_path, revocation)
    with pytest.raises(ArtifactRegistryError) as tampered:
        store.issue_handle(publication.artifact_ref, audience())
    assert tampered.value.code == "ARTIFACT_REVOCATION_INVALID"


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"apiKey": "canary"}, "ARTIFACT_SECRET_FORBIDDEN"),
        ({"nested": {"Authorization": "Bearer canary"}}, "ARTIFACT_SECRET_FORBIDDEN"),
        ({"path": r"C:\\Users\\person\\secret.mp4"}, "ARTIFACT_PATH_FORBIDDEN"),
        ({"path": r"\\server\share\file"}, "ARTIFACT_PATH_FORBIDDEN"),
        ({"path": "/home/person/file"}, "ARTIFACT_PATH_FORBIDDEN"),
        ({"path": "file:///C:/secret"}, "ARTIFACT_PATH_FORBIDDEN"),
    ],
)
def test_secret_and_absolute_path_values_never_persist(tmp_path: Path, payload: dict[str, object], code: str) -> None:
    store = registry(tmp_path / "registry")
    with pytest.raises(ArtifactRegistryError) as captured:
        publish(store, payload=payload)
    assert captured.value.code == code
    assert not any((tmp_path / "registry" / "artifacts").rglob("*.json"))


def test_canonical_json_uses_utf16_key_order_and_rfc8785_number_rendering() -> None:
    value = {"\ue000": 3, "\U00010000": 2, "plain": 1}
    assert canonical_json_bytes(value).decode("utf-8") == '{"plain":1,"𐀀":2,"":3}'
    assert canonical_json_bytes([333333333.33333329, 1e30, 4.50, 2e-3, 1e-27]).decode("ascii") == "[333333333.3333333,1e+30,4.5,0.002,1e-27]"
    assert canonical_json_bytes([-0.0, 1e20, 1e21, 1e-6, 1e-7]).decode("ascii") == "[0,100000000000000000000,1e+21,0.000001,1e-7]"
    with pytest.raises(ArtifactRegistryError) as unsafe:
        canonical_json_bytes({"number": 9_007_199_254_740_992})
    assert unsafe.value.code == "ARTIFACT_NUMBER_UNSAFE"
    with pytest.raises(ArtifactRegistryError) as surrogate:
        canonical_json_bytes({"text": "\ud800"})
    assert surrogate.value.code == "ARTIFACT_STRING_INVALID"


def test_completeness_invariant_and_blob_integrity(tmp_path: Path) -> None:
    store = registry(tmp_path / "registry")
    with pytest.raises(ArtifactRegistryError) as incomplete:
        publish(
            store,
            completeness={"state": "complete", "omittedLocators": [{"id": "missing"}], "reasonCodes": []},
        )
    assert incomplete.value.code == "ARTIFACT_COMPLETENESS_INVALID"

    blob = store.put_blob(b"artifact blob", media_type="application/octet-stream")
    assert store.read_blob(blob) == b"artifact blob"
    blob_path = store._blob_path(blob["sha256"])
    blob_path.write_bytes(b"tampered blob")
    with pytest.raises(ArtifactRegistryError) as tampered:
        store.read_blob(blob)
    assert tampered.value.code == "ARTIFACT_BLOB_MISMATCH"


def test_blob_path_streams_deduplicates_and_enforces_limits(tmp_path: Path, monkeypatch) -> None:
    store = registry(tmp_path / "registry")
    source = (tmp_path / "source.bin").resolve()
    source.write_bytes((b"streamed-source-" * 65536) + b"end")

    original_read_bytes = Path.read_bytes

    def forbid_source_read_bytes(path: Path) -> bytes:
        if path == source:
            raise AssertionError("streaming Blob ingestion must not call Path.read_bytes")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", forbid_source_read_bytes)
    first = store.put_blob_path(
        source,
        media_type="application/octet-stream",
        maximum_bytes=source.stat().st_size,
    )
    second = store.put_blob_path(
        source,
        media_type="application/octet-stream",
        maximum_bytes=source.stat().st_size,
    )
    assert second == first
    assert first["sizeBytes"] == source.stat().st_size
    assert first["sha256"] == hashlib.sha256(original_read_bytes(source)).hexdigest()

    with pytest.raises(ArtifactRegistryError) as too_large:
        store.put_blob_path(
            source,
            media_type="application/octet-stream",
            maximum_bytes=source.stat().st_size - 1,
        )
    assert too_large.value.code == "ARTIFACT_BLOB_TOO_LARGE"


def test_blob_path_preserves_windows_newlines_and_prefix_reader_verifies_full_blob(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path / "registry")
    source = (tmp_path / "windows-newlines.txt").resolve()
    original = b"first line\r\nsecond line\nthird line\r\n"
    source.write_bytes(original)

    blob = store.put_blob_path(source, media_type="text/plain")

    assert blob["sizeBytes"] == len(original)
    assert blob["sha256"] == hashlib.sha256(original).hexdigest()
    assert store.read_blob(blob) == original
    prefix, truncated = store.read_blob_prefix(blob, maximum_prefix_bytes=12)
    assert prefix == original[:12]
    assert truncated is True
    complete, truncated = store.read_blob_prefix(
        blob, maximum_prefix_bytes=len(original)
    )
    assert complete == original
    assert truncated is False

    store._blob_path(blob["sha256"]).write_bytes(b"tampered")
    with pytest.raises(ArtifactRegistryError) as corrupted:
        store.read_blob_prefix(blob, maximum_prefix_bytes=4)
    assert corrupted.value.code in {
        "ARTIFACT_STORAGE_UNSAFE",
        "ARTIFACT_BLOB_MISMATCH",
    }


def test_idempotent_publish_reissues_handle_and_repairs_missing_record(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path / "registry")
    arguments = {
        "audience": audience(),
        "project_id": "project-1",
        "project_revision": 1,
        "artifact_id": "source-stable-1",
        "artifact_revision": 1,
        "payload_schema": "study.source-asset",
        "payload_schema_version": 1,
        "payload": {"sourceId": "source-stable-1", "status": "ready"},
        "producer": {"component": "source-registration", "version": "1.0.0"},
        "parents": [],
        "input_fingerprint": INPUT_FINGERPRINT,
        "completeness": {
            "state": "complete",
            "omittedLocators": [],
            "reasonCodes": [],
        },
        "issue_refs": [],
    }
    first = store.publish_idempotent(**arguments)
    repeated = store.publish_idempotent(**arguments)
    assert repeated.envelope == first.envelope
    assert repeated.handle != first.handle
    assert store.resolve(repeated.handle, audience()) == first.envelope

    record_path = store._record_path(first.artifact_ref["registryAuthRef"])
    record_path.unlink()
    repaired = store.publish_idempotent(**arguments)
    assert store.resolve(repaired.handle, audience()) == first.envelope

    with pytest.raises(ArtifactRegistryError) as conflict:
        store.publish_idempotent(
            **{**arguments, "payload": {"sourceId": "source-stable-1", "status": "blocked"}}
        )
    assert conflict.value.code == "ARTIFACT_IDEMPOTENCY_CONFLICT"


def test_wrong_registry_key_cannot_read_authenticated_records(tmp_path: Path) -> None:
    first = registry(tmp_path / "registry")
    publication = publish(first)
    wrong = registry(tmp_path / "registry", service="service-2", key=b"x" * 32)
    with pytest.raises(ArtifactRegistryError) as captured:
        wrong.issue_handle(publication.artifact_ref, audience())
    assert captured.value.code == "ARTIFACT_AUTH_INVALID"


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point defense")
def test_replaced_storage_subdirectory_cannot_redirect_artifact_write(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    store = registry(root)
    artifacts = root / "artifacts"
    artifacts.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, artifacts, target_is_directory=True)
    except OSError:
        pytest.skip("Creating a directory symlink requires unavailable Windows privilege")
    with pytest.raises(ArtifactRegistryError) as captured:
        publish(store)
    assert captured.value.code == "ARTIFACT_STORAGE_UNSAFE"
    assert not any(outside.rglob("*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point defense")
def test_registry_root_reparse_point_is_rejected_on_windows(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        pytest.skip("Creating a directory symlink requires unavailable Windows privilege")
    with pytest.raises(ArtifactRegistryError) as captured:
        registry(link)
    assert captured.value.code == "ARTIFACT_STORAGE_UNSAFE"
