from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from card_service.process_isolation import TaskOwnedProcessGroup
from card_service.windows_restricted_launcher import SANDBOX_ATTESTATION_PREFIX
from card_service.windows_sandbox_acl import create_task_workspace, harden_runtime_tree, runtime_sandbox_sid
from workers.acg.media_tool_policy import (
    FFMPEG_FORMAT_WHITELIST,
    FFMPEG_PROTOCOL_BLACKLIST,
    FFMPEG_PROTOCOL_WHITELIST,
)


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


def test_malformed_media_probe_is_contained_inside_appcontainer_and_job(tmp_path: Path) -> None:
    source_ffprobe = shutil.which("ffprobe")
    if not source_ffprobe:
        pytest.skip("FFprobe is unavailable")
    task_id = str(uuid.uuid4())
    workspace, task_sid = create_task_workspace((tmp_path / "tasks").resolve(), task_id)
    malformed = workspace / "malformed.mp4"
    malformed.write_bytes(b"not-a-media-container")
    sibling = workspace.parent / "sibling-state.txt"
    sibling.write_text("unchanged", encoding="utf-8")
    runtime_root = (tmp_path / "runtime").resolve()
    runtime_root.mkdir(parents=True)
    ffprobe = runtime_root / "ffprobe.exe"
    shutil.copy2(source_ffprobe, ffprobe)
    runtime_sid = runtime_sandbox_sid()
    harden_runtime_tree(runtime_root, runtime_sid)
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
        str(ffprobe),
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        FFMPEG_PROTOCOL_WHITELIST,
        "-protocol_blacklist",
        FFMPEG_PROTOCOL_BLACKLIST,
        "-format_whitelist",
        FFMPEG_FORMAT_WHITELIST,
        "-max_alloc",
        "268435456",
        "-show_format",
        "-of",
        "json",
        str(malformed),
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
    group = TaskOwnedProcessGroup(memory_limit_bytes=512 * 1024 * 1024, active_process_limit=3)
    try:
        group.assign(process)
        key_text = base64.urlsafe_b64encode(b"d" * 32).decode("ascii").rstrip("=")
        stdout, stderr = process.communicate(f"START {key_text}\n", timeout=15)
    finally:
        group.close()
    assert process.returncode != 0
    assert len(stdout.encode("utf-8")) < 4096
    assert sibling.read_text(encoding="utf-8") == "unchanged"
    attestation_lines = [
        line for line in stderr.splitlines() if line.startswith(SANDBOX_ATTESTATION_PREFIX)
    ]
    assert len(attestation_lines) == 1
    attestation = json.loads(attestation_lines[0][len(SANDBOX_ATTESTATION_PREFIX) :])
    assert attestation["appContainerToken"] is True
    assert attestation["networkRestricted"] is True
    assert attestation["filesystemRestrictedByDedicatedSidDacl"] is True


def test_real_resource_bomb_probes_are_contained_inside_appcontainer_and_job(tmp_path: Path) -> None:
    source_ffmpeg = shutil.which("ffmpeg")
    source_ffprobe = shutil.which("ffprobe")
    if not source_ffmpeg or not source_ffprobe:
        pytest.skip("FFmpeg fixtures are unavailable")
    task_id = str(uuid.uuid4())
    workspace, task_sid = create_task_workspace((tmp_path / "tasks").resolve(), task_id)
    logical_decode_bomb = workspace / "logical-decode-bomb.mkv"
    sparse_duration = workspace / "sparse-duration.mkv"
    fixture_commands = [
        [
            source_ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=8192x4320:r=240:d=0.00834",
            "-vf",
            "setpts=PTS*144000",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "ffv1",
            "-y",
            str(logical_decode_bomb),
        ],
        [
            source_ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:r=1:d=2",
            "-vf",
            "setpts=PTS*50000",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "ffv1",
            "-y",
            str(sparse_duration),
        ],
    ]
    for fixture_command in fixture_commands:
        built = subprocess.run(
            fixture_command,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        assert built.returncode == 0, built.stderr
    assert logical_decode_bomb.stat().st_size < 1024 * 1024
    assert sparse_duration.stat().st_size < 1024 * 1024

    sibling = workspace.parent / "sibling-state.txt"
    sibling.write_text("unchanged", encoding="utf-8")
    runtime_root = (tmp_path / "runtime").resolve()
    runtime_root.mkdir(parents=True)
    ffprobe = runtime_root / "ffprobe.exe"
    shutil.copy2(source_ffprobe, ffprobe)
    runtime_sid = runtime_sandbox_sid()
    harden_runtime_tree(runtime_root, runtime_sid)
    launcher = Path(__file__).resolve().parents[1] / "card_service" / "windows_restricted_launcher.py"

    observed = {}
    for index, source in enumerate((logical_decode_bomb, sparse_duration), start=1):
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
            str(ffprobe),
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            FFMPEG_PROTOCOL_WHITELIST,
            "-protocol_blacklist",
            FFMPEG_PROTOCOL_BLACKLIST,
            "-format_whitelist",
            FFMPEG_FORMAT_WHITELIST,
            "-max_alloc",
            "268435456",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(source),
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
        group = TaskOwnedProcessGroup(memory_limit_bytes=512 * 1024 * 1024, active_process_limit=3)
        try:
            group.assign(process)
            key_text = base64.urlsafe_b64encode(bytes([100 + index]) * 32).decode("ascii").rstrip("=")
            stdout, stderr = process.communicate(f"START {key_text}\n", timeout=15)
        finally:
            group.close()
        assert process.returncode == 0, stderr
        observed[source.name] = json.loads(stdout)
        attestation_lines = [
            line for line in stderr.splitlines() if line.startswith(SANDBOX_ATTESTATION_PREFIX)
        ]
        assert len(attestation_lines) == 1
        attestation = json.loads(attestation_lines[0][len(SANDBOX_ATTESTATION_PREFIX) :])
        assert attestation["appContainerToken"] is True
        assert attestation["networkRestricted"] is True
        assert attestation["filesystemRestrictedByDedicatedSidDacl"] is True

    decode_stream = observed["logical-decode-bomb.mkv"]["streams"][0]
    assert decode_stream["width"] == 8192
    assert decode_stream["height"] == 4320
    assert decode_stream["avg_frame_rate"] == "240/1"
    assert float(observed["logical-decode-bomb.mkv"]["format"]["duration"]) > 1_200
    assert float(observed["sparse-duration.mkv"]["format"]["duration"]) > 50_000
    assert sibling.read_text(encoding="utf-8") == "unchanged"
