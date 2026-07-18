from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from card_service import worker_bootstrap


def test_runtime_path_validation_does_not_require_strict_realpath(tmp_path: Path) -> None:
    root = (tmp_path / "runtime").resolve()
    target = root / "workers" / "anki_worker.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('ok')\n", encoding="utf-8")

    with patch.object(Path, "resolve", side_effect=PermissionError("strict realpath denied")):
        validated = worker_bootstrap._lexical_runtime_path(
            target,
            runtime_root=root,
            expect_directory=False,
            checked_components=set(),
        )

    assert validated == target


def test_runtime_path_validation_rejects_escape_and_wrong_kind(tmp_path: Path) -> None:
    root = (tmp_path / "runtime").resolve()
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="escaped its root"):
        worker_bootstrap._lexical_runtime_path(
            outside,
            runtime_root=root,
            expect_directory=False,
            checked_components=set(),
        )
    with pytest.raises(SystemExit, match="file is invalid"):
        worker_bootstrap._lexical_runtime_path(
            root,
            runtime_root=root,
            expect_directory=False,
            checked_components=set(),
        )


def test_runtime_path_validation_rejects_reparse_metadata(tmp_path: Path) -> None:
    root = (tmp_path / "runtime").resolve()
    target = root / "worker.py"
    root.mkdir()
    target.write_text("pass\n", encoding="utf-8")

    with patch.object(worker_bootstrap, "_has_reparse_attribute", return_value=True):
        with pytest.raises(SystemExit, match="reparse point"):
            worker_bootstrap._lexical_runtime_path(
                target,
                runtime_root=root,
                expect_directory=False,
                checked_components=set(),
            )


def test_development_manifest_path_can_be_verified_outside_package_root(tmp_path: Path) -> None:
    tool = (tmp_path / "managed-tool.exe").resolve()
    tool.write_bytes(b"tool")

    validated = worker_bootstrap._lexical_runtime_path(
        tool,
        runtime_root=None,
        expect_directory=False,
        checked_components=set(),
    )

    assert validated == tool
