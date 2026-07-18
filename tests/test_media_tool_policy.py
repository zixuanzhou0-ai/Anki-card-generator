from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from workers.acg.media_tool_policy import (
    FFMPEG_FORMAT_WHITELIST,
    FFMPEG_PROTOCOL_BLACKLIST,
    FFMPEG_PROTOCOL_WHITELIST,
    MAX_MEDIA_OUTPUT_BYTES,
    MAX_MEDIA_STREAMS,
    MediaToolPolicyError,
    ffmpeg_command,
    ffprobe_command,
    managed_tool_path,
    run_ffmpeg,
    run_ffprobe,
)


class MediaToolPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="media_tool_policy_")
        self.root = Path(self.temporary.name).resolve()
        self.ffmpeg = self.root / "ffmpeg.exe"
        self.ffprobe = self.root / "ffprobe.exe"
        self.source = self.root / "source.mp4"
        self.output = self.root / "output.mp3"
        for path in (self.ffmpeg, self.ffprobe, self.source):
            path.write_bytes(b"fixture")
        self.environment = {
            "ACG_MANAGED_RUNTIME": "1",
            "ACG_MANAGED_FFMPEG": str(self.ffmpeg),
            "ACG_MANAGED_FFPROBE": str(self.ffprobe),
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_commands_bind_absolute_tools_and_fixed_protocol_format_policy(self) -> None:
        with patch.dict(os.environ, self.environment, clear=False):
            ffmpeg = ffmpeg_command(["-i", str(self.source), "-vn", str(self.output)])
            ffprobe = ffprobe_command(["-show_streams", "-of", "json"], self.source)
        self.assertEqual(ffmpeg[0], str(self.ffmpeg))
        self.assertEqual(ffprobe[0], str(self.ffprobe))
        for command in (ffmpeg, ffprobe):
            self.assertIn(FFMPEG_PROTOCOL_WHITELIST, command)
            self.assertIn(FFMPEG_PROTOCOL_BLACKLIST, command)
            self.assertIn(FFMPEG_FORMAT_WHITELIST, command)
            self.assertIn("-max_alloc", command)
            self.assertIn("-probesize", command)
            self.assertIn("-analyzeduration", command)
        self.assertIn("-nostdin", ffmpeg)
        self.assertIn("-max_streams", ffmpeg)
        self.assertIn(str(MAX_MEDIA_STREAMS), ffmpeg)
        self.assertEqual(ffmpeg[-3:], ["-fs", str(MAX_MEDIA_OUTPUT_BYTES), str(self.output)])
        self.assertEqual(ffmpeg.count("-protocol_whitelist"), 1)
        self.assertEqual(ffmpeg.count("-format_whitelist"), 1)

    def test_playlist_protocol_and_policy_override_inputs_fail_closed(self) -> None:
        playlist = self.root / "attack.ffconcat"
        playlist.write_text("ffconcat version 1.0\nfile 'C:/Windows/win.ini'\n", encoding="utf-8")
        cases = [
            (["-i", "concat:C:/one.mp4|C:/two.mp4", str(self.output)], "MEDIA_INPUT_PROTOCOL_BLOCKED"),
            (["-i", "subfile,,start,0,end,10,,:C:/one.mp4", str(self.output)], "MEDIA_INPUT_PROTOCOL_BLOCKED"),
            (["-i", "https://example.test/video.mp4", str(self.output)], "MEDIA_INPUT_PROTOCOL_BLOCKED"),
            (["-i", str(playlist), str(self.output)], "MEDIA_INPUT_DEMUXER_BLOCKED"),
            (["-f", "concat", "-i", str(self.source), str(self.output)], "MEDIA_INPUT_DEMUXER_BLOCKED"),
            (
                ["-protocol_whitelist", "file,http", "-i", str(self.source), str(self.output)],
                "MEDIA_ARGUMENT_OVERRIDE_BLOCKED",
            ),
            (["-filter_script", "C:/filter.txt", "-i", str(self.source), str(self.output)], "MEDIA_ARGUMENT_OVERRIDE_BLOCKED"),
        ]
        with patch.dict(os.environ, self.environment, clear=False):
            for arguments, code in cases:
                with self.subTest(arguments=arguments):
                    with self.assertRaises(MediaToolPolicyError) as caught:
                        ffmpeg_command(arguments)
                    self.assertEqual(caught.exception.code, code)

    def test_packaged_mode_never_falls_back_to_path(self) -> None:
        with patch.dict(os.environ, {"ACG_MANAGED_RUNTIME": "1", "ACG_MANAGED_FFMPEG": ""}, clear=True):
            with patch("workers.acg.media_tool_policy.shutil.which", return_value=str(self.ffmpeg)):
                with self.assertRaises(MediaToolPolicyError) as caught:
                    managed_tool_path("ffmpeg")
        self.assertEqual(caught.exception.code, "MANAGED_MEDIA_TOOL_MISSING")

    def test_subprocess_policy_forces_no_shell_no_stdin_and_bounded_timeout(self) -> None:
        completed = subprocess.CompletedProcess([str(self.ffmpeg)], 0, stdout="", stderr="")
        with patch.dict(os.environ, self.environment, clear=False):
            with (
                patch("workers.acg.media_tool_policy.validate_media_resource_limits"),
                patch("workers.acg.media_tool_policy.subprocess.run", return_value=completed) as run,
            ):
                result = run_ffmpeg(
                    ["-i", str(self.source), "-vn", str(self.output)],
                    timeout=10_000,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
        self.assertIs(result, completed)
        _, kwargs = run.call_args
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 300.0)

    def test_managed_run_rejects_resource_bombs_before_ffmpeg_launch(self) -> None:
        base_stream = {
            "index": 0,
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "duration": "10",
            "nb_frames": "300",
            "avg_frame_rate": "30/1",
            "r_frame_rate": "30/1",
            "bit_rate": "1000000",
        }
        cases = [
            ({"streams": [{**base_stream, "width": 9000}], "format": {"duration": "10"}}, "MEDIA_DIMENSION_LIMIT_EXCEEDED"),
            ({"streams": [{**base_stream, "avg_frame_rate": "300/1"}], "format": {"duration": "10"}}, "MEDIA_FRAME_RATE_LIMIT_EXCEEDED"),
            ({"streams": [{**base_stream, "duration": "50000"}], "format": {"duration": "50000"}}, "MEDIA_DURATION_LIMIT_EXCEEDED"),
            (
                {
                    "streams": [
                        {
                            "index": 0,
                            "codec_type": "audio",
                            "duration": "10",
                            "sample_rate": "384000",
                            "channels": 2,
                        }
                    ],
                    "format": {"duration": "10"},
                },
                "MEDIA_SAMPLE_RATE_LIMIT_EXCEEDED",
            ),
            ({"streams": [{**base_stream, "index": index} for index in range(33)], "format": {"duration": "10"}}, "MEDIA_STREAM_LIMIT_EXCEEDED"),
            ({"streams": [{"index": 0, "codec_type": "attachment"}], "format": {}}, "MEDIA_ATTACHMENT_BLOCKED"),
        ]
        with patch.dict(os.environ, self.environment, clear=False):
            for evidence, expected_code in cases:
                with self.subTest(expected_code=expected_code):
                    from workers.acg import media_tool_policy

                    media_tool_policy._RESOURCE_PROBE_CACHE.clear()
                    probe = subprocess.CompletedProcess(
                        [str(self.ffprobe)],
                        0,
                        stdout=json.dumps(evidence),
                        stderr="",
                    )
                    with patch("workers.acg.media_tool_policy.subprocess.run", return_value=probe) as run:
                        with self.assertRaises(MediaToolPolicyError) as caught:
                            run_ffmpeg(["-i", str(self.source), "-vn", str(self.output)])
                    self.assertEqual(caught.exception.code, expected_code)
                    self.assertEqual(run.call_count, 1)

    def test_raw_pcm_limits_are_derived_without_untrusted_probe(self) -> None:
        pcm = self.root / "speech.pcm"
        pcm.write_bytes(b"\x00\x00" * 16_000)
        completed = subprocess.CompletedProcess([str(self.ffmpeg)], 0, stdout="", stderr="")
        with patch.dict(os.environ, self.environment, clear=False):
            with patch("workers.acg.media_tool_policy.subprocess.run", return_value=completed) as run:
                result = run_ffmpeg(
                    [
                        "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", str(pcm),
                        "-acodec", "libmp3lame", str(self.output),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
        self.assertIs(result, completed)
        self.assertEqual(run.call_count, 1)

    def test_output_at_hard_limit_is_removed_and_fails_closed(self) -> None:
        pcm = self.root / "short.pcm"
        pcm.write_bytes(b"\x00\x00" * 16)

        def writes_limit(*_args, **_kwargs):
            self.output.write_bytes(b"1234")
            return subprocess.CompletedProcess([str(self.ffmpeg)], 0, stdout="", stderr="")

        with patch.dict(os.environ, self.environment, clear=False):
            with (
                patch("workers.acg.media_tool_policy.MAX_MEDIA_OUTPUT_BYTES", 4),
                patch("workers.acg.media_tool_policy.subprocess.run", side_effect=writes_limit),
            ):
                with self.assertRaises(MediaToolPolicyError) as caught:
                    run_ffmpeg(
                        ["-f", "s16le", "-ar", "16000", "-ac", "1", "-i", str(pcm), str(self.output)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
        self.assertEqual(caught.exception.code, "MEDIA_OUTPUT_SIZE_LIMIT_EXCEEDED")
        self.assertFalse(self.output.exists())

    def test_relative_missing_and_reparse_inputs_are_rejected_before_launch(self) -> None:
        with patch.dict(os.environ, self.environment, clear=False):
            for value, code in (
                ("relative.mp4", "MEDIA_INPUT_PATH_INVALID"),
                (str(self.root / "missing.mp4"), "MEDIA_INPUT_MISSING"),
            ):
                with self.subTest(value=value):
                    with self.assertRaises(MediaToolPolicyError) as caught:
                        ffmpeg_command(["-i", value, str(self.output)])
                    self.assertEqual(caught.exception.code, code)

    def test_real_local_transcode_and_malformed_probe_remain_bounded(self) -> None:
        real_ffmpeg = shutil.which("ffmpeg")
        real_ffprobe = shutil.which("ffprobe")
        if not real_ffmpeg or not real_ffprobe:
            self.skipTest("managed FFmpeg fixture is unavailable")
        wav_path = self.root / "silence.wav"
        mp3_path = self.root / "silence.mp3"
        with wave.open(str(wav_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16_000)
            output.writeframes(b"\x00\x00" * 3_200)
        environment = {
            "ACG_MANAGED_RUNTIME": "1",
            "ACG_MANAGED_FFMPEG": str(Path(real_ffmpeg).resolve()),
            "ACG_MANAGED_FFPROBE": str(Path(real_ffprobe).resolve()),
        }
        with patch.dict(os.environ, environment, clear=False):
            transcoded = run_ffmpeg(
                ["-i", str(wav_path), "-acodec", "libmp3lame", "-q:a", "7", str(mp3_path)],
                timeout=30,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(transcoded.returncode, 0, transcoded.stderr)
            self.assertTrue(mp3_path.is_file())
            self.assertGreater(mp3_path.stat().st_size, 0)

            malformed = self.root / "malformed.mp4"
            malformed.write_bytes(b"not-a-media-container")
            probed = run_ffprobe(
                ["-show_format", "-of", "json"],
                malformed,
                timeout=5,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertNotEqual(probed.returncode, 0)

    def test_real_mp4_slice_uses_product_profile_under_fixed_policy(self) -> None:
        real_ffmpeg = shutil.which("ffmpeg")
        real_ffprobe = shutil.which("ffprobe")
        if not real_ffmpeg or not real_ffprobe:
            self.skipTest("managed FFmpeg fixture is unavailable")
        source = self.root / "fixture-source.mp4"
        sliced = self.root / "fixture-slice.mp4"
        fixture = subprocess.run(
            [
                str(Path(real_ffmpeg).resolve()),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=320x240:d=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-y",
                str(source),
            ],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        self.assertEqual(fixture.returncode, 0, fixture.stderr)
        environment = {
            "ACG_MANAGED_RUNTIME": "1",
            "ACG_MANAGED_FFMPEG": str(Path(real_ffmpeg).resolve()),
            "ACG_MANAGED_FFPROBE": str(Path(real_ffprobe).resolve()),
        }
        with patch.dict(os.environ, environment, clear=False):
            result = run_ffmpeg(
                [
                    "-ss",
                    "0.1",
                    "-t",
                    "0.5",
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0?",
                    "-map",
                    "0:a:0?",
                    "-c:v",
                    "libx264",
                    "-profile:v",
                    "baseline",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(sliced),
                ],
                timeout=30,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            probe = run_ffprobe(
                ["-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height", "-of", "json"],
                sliced,
                timeout=10,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertIn("h264", probe.stdout)


if __name__ == "__main__":
    unittest.main()
