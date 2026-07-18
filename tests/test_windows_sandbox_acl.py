from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

import card_service.windows_sandbox_acl as windows_sandbox_acl_module

from card_service.windows_sandbox_acl import (
    FILE_FULL_CONTROL,
    FILE_GENERIC_READ_EXECUTE,
    FILE_MODIFY,
    WindowsSandboxAclError,
    apply_exact_dacl,
    create_task_workspace,
    current_user_sid,
    harden_runtime_tree,
    harden_staged_path,
    read_dacl,
    runtime_sandbox_sid,
    task_sandbox_sid,
    verify_runtime_tree_dacl,
)


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows DACL contract")


def test_runtime_and_task_sids_are_stable_and_task_bound() -> None:
    runtime_sid = runtime_sandbox_sid()
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    assert runtime_sid == runtime_sandbox_sid()
    assert runtime_sid.startswith("S-1-15-2-")
    assert task_sandbox_sid(first) == task_sandbox_sid(first)
    assert task_sandbox_sid(first) != task_sandbox_sid(second)
    assert task_sandbox_sid(first).startswith("S-1-15-3-")
    with pytest.raises(WindowsSandboxAclError) as invalid:
        task_sandbox_sid("not-a-task")
    assert invalid.value.code == "WINDOWS_TASK_ID_INVALID"


def test_runtime_sid_derivation_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_profile_creation(name: str) -> str:
        raise AssertionError(f"verification attempted to create AppContainer profile {name}")

    monkeypatch.setattr(
        windows_sandbox_acl_module,
        "_ensure_appcontainer_profile",
        unexpected_profile_creation,
    )
    assert runtime_sandbox_sid("read-only-verification-fixture").startswith("S-1-15-2-")


def test_runtime_tree_receives_only_recovery_and_sandbox_read_execute_aces(tmp_path: Path) -> None:
    root = (tmp_path / "managed-runtime").resolve()
    nested = root / "python" / "Lib"
    nested.mkdir(parents=True)
    executable = root / "python" / "python.exe"
    executable.write_bytes(b"runtime")
    module = nested / "module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    sandbox_sid = runtime_sandbox_sid()

    harden_runtime_tree(root, sandbox_sid)
    verify_runtime_tree_dacl(root, sandbox_sid)
    assert executable.read_bytes() == b"runtime"
    file_entries = read_dacl(executable)
    assert any(entry.sid == sandbox_sid and entry.access_mask == FILE_GENERIC_READ_EXECUTE for entry in file_entries)
    assert all(entry.sid not in {"S-1-1-0", "S-1-5-11", "S-1-5-32-545"} for entry in file_entries)

    apply_exact_dacl(
        root,
        [
            (current_user_sid(), FILE_FULL_CONTROL),
            ("S-1-1-0", FILE_GENERIC_READ_EXECUTE),
        ],
        inherit_to_children=True,
    )
    with pytest.raises(WindowsSandboxAclError) as mismatch:
        verify_runtime_tree_dacl(root, sandbox_sid)
    assert mismatch.value.code == "WINDOWS_RUNTIME_DACL_MISMATCH"


def test_task_workspace_uses_task_sid_and_staged_files_are_rehardened(tmp_path: Path) -> None:
    task_id = str(uuid.uuid4())
    workspace, task_sid = create_task_workspace((tmp_path / "tasks").resolve(), task_id)
    assert task_sid == task_sandbox_sid(task_id)
    directory_entries = read_dacl(workspace)
    assert any(entry.sid == task_sid and entry.access_mask == FILE_MODIFY for entry in directory_entries)
    assert all(entry.sid not in {"S-1-1-0", "S-1-5-11", "S-1-5-32-545"} for entry in directory_entries)
    assert all(
        entry.sid not in {"S-1-1-0", "S-1-5-11", "S-1-5-32-545"}
        for entry in read_dacl(workspace.parent)
    )

    staged_root = workspace / "staged"
    staged_root.mkdir()
    staged = staged_root / "nested" / "source.bin"
    staged.parent.mkdir()
    staged.write_bytes(b"source")
    apply_exact_dacl(
        staged,
        [(current_user_sid(), FILE_FULL_CONTROL), ("S-1-1-0", FILE_GENERIC_READ_EXECUTE)],
        inherit_to_children=False,
    )
    harden_staged_path(staged_root, task_sid)
    file_entries = read_dacl(staged)
    assert any(entry.sid == task_sid and entry.access_mask == FILE_GENERIC_READ_EXECUTE for entry in file_entries)
    assert all(entry.sid != "S-1-1-0" for entry in file_entries)


def test_acl_target_rejects_reparse_point_escape_before_resolution(tmp_path: Path) -> None:
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("unchanged", encoding="utf-8")
    link = tmp_path / "linked"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(WindowsSandboxAclError) as blocked:
        apply_exact_dacl(
            link / secret.name,
            [(current_user_sid(), FILE_FULL_CONTROL)],
            inherit_to_children=False,
        )
    assert blocked.value.code == "WINDOWS_ACL_REPARSE_BLOCKED"
    assert secret.read_text(encoding="utf-8") == "unchanged"
