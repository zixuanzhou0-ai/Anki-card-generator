from __future__ import annotations

import os
from pathlib import Path

import pytest

from workers.acg import legacy_worker


@pytest.mark.skipif(os.name != "nt", reason="Python 3.13 Windows directory ACL behavior")
def test_managed_export_directory_avoids_tempfile_private_acl_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACG_MANAGED_RUNTIME", "1")

    def unexpected_mkdtemp(*_args, **_kwargs):
        raise AssertionError("managed export directory used tempfile.mkdtemp")

    monkeypatch.setattr(legacy_worker.tempfile, "mkdtemp", unexpected_mkdtemp)

    export_root = legacy_worker.create_export_run_directory(tmp_path, prefix="AnkiCard-proof-")
    media_dir = export_root / "media"
    media_dir.mkdir()
    proof = media_dir / "proof.txt"
    proof.write_text("reopenable", encoding="utf-8")

    assert export_root.parent == tmp_path
    assert export_root.name.startswith("AnkiCard-proof-")
    assert proof.read_text(encoding="utf-8") == "reopenable"


def test_managed_audio_duration_audit_does_not_silently_skip_policy_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = tmp_path / "proof.mp3"
    audio.write_bytes(b"ID3fixture")
    monkeypatch.setenv("ACG_MANAGED_RUNTIME", "1")

    def denied(*_args, **_kwargs):
        raise legacy_worker.MediaToolPolicyError("MANAGED_MEDIA_TOOL_MISSING", "probe unavailable")

    monkeypatch.setattr(legacy_worker, "media_policy_run_ffprobe", denied)

    with pytest.raises(RuntimeError, match=r"AUDIO_DURATION_AUDIT_UNAVAILABLE\[MANAGED_MEDIA_TOOL_MISSING\]"):
        legacy_worker.audio_duration_seconds(audio)

    assert not legacy_worker.tts_generation_retryable(
        "AUDIO_DURATION_AUDIT_UNAVAILABLE[MANAGED_MEDIA_TOOL_MISSING]"
    )
    assert legacy_worker.tts_generation_retryable("temporary provider error")
