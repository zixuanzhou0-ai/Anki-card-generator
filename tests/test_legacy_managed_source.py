from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from workers.acg import legacy_worker
from workers.acg.managed_source_broker import ManagedYouTubeSubtitles


VIDEO_ID = "dQw4w9WgXcQ"


def test_subtitle_only_url_uses_service_broker_and_writes_verified_local_srt(tmp_path: Path) -> None:
    download_dir = tmp_path / "url_cache"
    download_dir.mkdir()
    acquired = ManagedYouTubeSubtitles(
        video_id=VIDEO_ID,
        title="Brokered title",
        language_code="en-US",
        caption_kind="manual",
        vtt=b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello from broker\n",
    )
    with (
        patch.object(legacy_worker, "managed_source_broker_is_configured", return_value=True),
        patch.object(legacy_worker, "managed_source_operation_available", return_value=True),
        patch.object(legacy_worker, "managed_source_request_youtube_subtitles", return_value=acquired) as request,
        patch.object(legacy_worker, "run_yt_dlp", side_effect=AssertionError("yt-dlp direct network must not run")),
    ):
        result = legacy_worker.download_url_subtitles_only(
            {
                "source_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
                "language": "English",
            },
            download_dir,
            str(download_dir / "source.%(ext)s"),
            "en.*",
        )
    subtitle = Path(result["subtitle_path"])
    assert subtitle.is_file()
    assert "Hello from broker" in subtitle.read_text(encoding="utf-8")
    assert result["source_acquisition"] == "card_service_broker"
    assert result["transcript_only"] is True
    assert result["video_path"] == ""
    request.assert_called_once()


def test_managed_full_video_url_fails_closed_without_direct_ytdlp(tmp_path: Path) -> None:
    previous = os.environ.get("ACG_MANAGED_RUNTIME")
    os.environ["ACG_MANAGED_RUNTIME"] = "1"
    try:
        with (
            patch.object(legacy_worker.Path, "cwd", return_value=tmp_path),
            patch.object(legacy_worker, "run_yt_dlp", side_effect=AssertionError("direct yt-dlp must not run")),
            pytest.raises(SystemExit),
        ):
            legacy_worker.download_url_source(
                {
                    "source_mode": "url",
                    "source_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
                    "language": "English",
                    "url_import_mode": "video",
                }
            )
    finally:
        if previous is None:
            os.environ.pop("ACG_MANAGED_RUNTIME", None)
        else:
            os.environ["ACG_MANAGED_RUNTIME"] = previous


def test_managed_runtime_never_executes_direct_network_ytdlp() -> None:
    previous = os.environ.get("ACG_MANAGED_RUNTIME")
    os.environ["ACG_MANAGED_RUNTIME"] = "1"
    try:
        with (
            patch.object(legacy_worker.subprocess, "run", side_effect=AssertionError("subprocess must not start")),
            pytest.raises(SystemExit),
        ):
            legacy_worker.run_yt_dlp([f"https://www.youtube.com/watch?v={VIDEO_ID}"], check=False)
    finally:
        if previous is None:
            os.environ.pop("ACG_MANAGED_RUNTIME", None)
        else:
            os.environ["ACG_MANAGED_RUNTIME"] = previous
