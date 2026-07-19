from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from card_service.artifact_registry import (
    ArtifactRegistry,
    ArtifactRegistryError,
)


def _registry(tmp_path: Path) -> ArtifactRegistry:
    return ArtifactRegistry(
        tmp_path / "registry",
        authentication_key=b"m" * 32,
        service_instance_id="service-materialize-test",
    )


def test_materialize_blob_streams_verified_bytes_to_new_file(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    data = (b"verified-apkg-chunk" * 131_072) + b"tail"
    blob = registry.put_blob(data, media_type="application/vnd.anki.apkg")
    destination = (tmp_path / "task" / "cards.apkg").resolve()
    destination.parent.mkdir()

    result = registry.materialize_blob(blob, destination)

    assert result == {
        "sha256": hashlib.sha256(data).hexdigest(),
        "sizeBytes": len(data),
        "path": str(destination),
    }
    assert destination.read_bytes() == data


def test_materialize_blob_never_overwrites_existing_destination(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    blob = registry.put_blob(b"new", media_type="application/octet-stream")
    destination = (tmp_path / "task" / "blob.bin").resolve()
    destination.parent.mkdir()
    destination.write_bytes(b"keep")

    with pytest.raises(ArtifactRegistryError) as captured:
        registry.materialize_blob(blob, destination)

    assert captured.value.code == "ARTIFACT_BLOB_DESTINATION_EXISTS"
    assert destination.read_bytes() == b"keep"


def test_materialize_blob_rejects_tampered_identity_without_partial_file(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    blob = registry.put_blob(b"original", media_type="application/octet-stream")
    destination = (tmp_path / "task" / "blob.bin").resolve()
    destination.parent.mkdir()
    forged = {**blob, "sizeBytes": blob["sizeBytes"] + 1}

    with pytest.raises(ArtifactRegistryError) as captured:
        registry.materialize_blob(forged, destination)

    assert captured.value.code in {
        "ARTIFACT_STORAGE_UNSAFE",
        "ARTIFACT_BLOB_MISMATCH",
    }
    assert not destination.exists()


def test_materialize_blob_rejects_relative_destination(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    blob = registry.put_blob(b"original", media_type="application/octet-stream")

    with pytest.raises(ArtifactRegistryError) as captured:
        registry.materialize_blob(blob, Path("relative.bin"))

    assert captured.value.code == "ARTIFACT_BLOB_DESTINATION_INVALID"
