from __future__ import annotations

from pathlib import Path

from tests.test_artifact_registry import audience, publish, registry


def test_shared_parent_dag_is_verified_once_per_unique_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    store = registry(tmp_path / "registry")
    root = publish(store, artifact_id="root", project_revision=1)
    left = publish(
        store,
        artifact_id="left",
        project_revision=2,
        parents=[dict(root.artifact_ref)],
    )
    right = publish(
        store,
        artifact_id="right",
        project_revision=2,
        parents=[dict(root.artifact_ref)],
    )
    top = publish(
        store,
        artifact_id="top",
        project_revision=3,
        parents=[dict(left.artifact_ref), dict(right.artifact_ref)],
    )

    original_json = store._json
    artifact_reads: dict[Path, int] = {}

    def counted_json(path: Path, maximum_bytes: int):
        if path.is_relative_to(store._root / "artifacts"):
            artifact_reads[path] = artifact_reads.get(path, 0) + 1
        return original_json(path, maximum_bytes)

    monkeypatch.setattr(store, "_json", counted_json)

    verified = store.verify_ref(top.artifact_ref, audience())

    assert verified["artifactId"] == "top"
    assert len(artifact_reads) == 4
    assert max(artifact_reads.values()) == 1
