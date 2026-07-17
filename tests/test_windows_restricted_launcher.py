from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from card_service.process_isolation import TaskOwnedProcessGroup
from card_service.windows_restricted_launcher import SANDBOX_ATTESTATION_PREFIX
from card_service.windows_sandbox_acl import create_task_workspace, runtime_sandbox_sid


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows restricted token contract")


def test_restricted_sid_child_starts_inside_exact_task_workspace_without_sid_disclosure(tmp_path: Path) -> None:
    task_id = str(uuid.uuid4())
    workspace, task_sid = create_task_workspace((tmp_path / "tasks").resolve(), task_id)
    proof = workspace / "proof.txt"
    runtime_sid = runtime_sandbox_sid()
    launcher = Path(__file__).resolve().parents[1] / "card_service" / "windows_restricted_launcher.py"
    command = [
        sys.executable,
        str(launcher),
        "--task-id",
        task_id,
        "--cwd",
        str(workspace),
        "--runtime-sid",
        runtime_sid,
        "--task-sid",
        task_sid,
        "--",
        str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"),
        "/d",
        "/c",
        f"echo sandbox-ok>{proof.name}",
    ]
    process = subprocess.Popen(
        command,
        cwd=str(launcher.parent),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    group = TaskOwnedProcessGroup(memory_limit_bytes=256 * 1024 * 1024, active_process_limit=4)
    try:
        group.assign(process)
        key = b"a" * 32
        key_text = base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")
        stdout, stderr = process.communicate(f"START {key_text}\n", timeout=10)
    finally:
        group.close()
    assert process.returncode == 0, stderr
    assert stdout == ""
    assert proof.read_text(encoding="utf-8").strip() == "sandbox-ok"
    attestation_lines = [
        line for line in stderr.splitlines() if line.startswith(SANDBOX_ATTESTATION_PREFIX)
    ]
    assert len(attestation_lines) == 1
    attestation = json.loads(attestation_lines[0][len(SANDBOX_ATTESTATION_PREFIX) :])
    assert attestation["filesystemRestrictedByDedicatedSidDacl"] is True
    assert attestation["appContainerToken"] is True
    assert attestation["taskCapabilityPresent"] is True
    assert attestation["networkRestricted"] is True
    assert attestation["restrictedPrimaryToken"] is True
    assert attestation["jobInheritedBeforeResume"] is True
    assert len(attestation["runtimeAppContainerSidDigest"]) == 64
    assert len(attestation["taskCapabilitySidDigest"]) == 64
    assert runtime_sid not in stderr
    assert task_sid not in stderr


def test_appcontainer_cannot_read_sibling_service_state(tmp_path: Path) -> None:
    task_id = str(uuid.uuid4())
    workspace, task_sid = create_task_workspace((tmp_path / "tasks").resolve(), task_id)
    outside_secret = workspace.parent / "outside-secret.txt"
    outside_secret.write_text("must-not-be-readable", encoding="utf-8")
    runtime_sid = runtime_sandbox_sid()
    launcher = Path(__file__).resolve().parents[1] / "card_service" / "windows_restricted_launcher.py"
    command = [
        sys.executable,
        str(launcher),
        "--task-id",
        task_id,
        "--cwd",
        str(workspace),
        "--runtime-sid",
        runtime_sid,
        "--task-sid",
        task_sid,
        "--",
        str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"),
        "/d",
        "/c",
        f'type "{outside_secret}"',
    ]
    process = subprocess.Popen(
        command,
        cwd=str(launcher.parent),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    group = TaskOwnedProcessGroup(memory_limit_bytes=256 * 1024 * 1024, active_process_limit=4)
    try:
        group.assign(process)
        key_text = base64.urlsafe_b64encode(b"c" * 32).decode("ascii").rstrip("=")
        stdout, stderr = process.communicate(f"START {key_text}\n", timeout=10)
    finally:
        group.close()
    assert process.returncode != 0
    assert "must-not-be-readable" not in stdout
    attestation_lines = [
        line for line in stderr.splitlines() if line.startswith(SANDBOX_ATTESTATION_PREFIX)
    ]
    assert len(attestation_lines) == 1
    attestation = json.loads(attestation_lines[0][len(SANDBOX_ATTESTATION_PREFIX) :])
    assert attestation["appContainerToken"] is True
    assert attestation["taskCapabilityPresent"] is True


def test_appcontainer_without_network_capability_cannot_reach_loopback(tmp_path: Path) -> None:
    curl = Path(os.environ["SystemRoot"]) / "System32" / "curl.exe"
    if not curl.is_file():
        pytest.skip("Windows curl is unavailable")
    task_id = str(uuid.uuid4())
    workspace, task_sid = create_task_workspace((tmp_path / "tasks").resolve(), task_id)
    runtime_sid = runtime_sandbox_sid()
    launcher = Path(__file__).resolve().parents[1] / "card_service" / "windows_restricted_launcher.py"
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(0.5)
    port = int(server.getsockname()[1])
    command = [
        sys.executable,
        str(launcher),
        "--task-id",
        task_id,
        "--cwd",
        str(workspace),
        "--runtime-sid",
        runtime_sid,
        "--task-sid",
        task_sid,
        "--",
        str(curl),
        "--silent",
        "--show-error",
        "--max-time",
        "1",
        f"http://127.0.0.1:{port}/",
    ]
    process = subprocess.Popen(
        command,
        cwd=str(launcher.parent),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    group = TaskOwnedProcessGroup(memory_limit_bytes=256 * 1024 * 1024, active_process_limit=4)
    try:
        group.assign(process)
        key_text = base64.urlsafe_b64encode(b"b" * 32).decode("ascii").rstrip("=")
        stdout, stderr = process.communicate(f"START {key_text}\n", timeout=10)
        with pytest.raises(socket.timeout):
            server.accept()
    finally:
        server.close()
        group.close()
    assert process.returncode != 0
    assert stdout == ""
    attestation_lines = [
        line for line in stderr.splitlines() if line.startswith(SANDBOX_ATTESTATION_PREFIX)
    ]
    assert len(attestation_lines) == 1
    attestation = json.loads(attestation_lines[0][len(SANDBOX_ATTESTATION_PREFIX) :])
    assert attestation["appContainerToken"] is True
    assert attestation["networkRestricted"] is True
