from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat
import subprocess
import threading
from pathlib import Path
from typing import Any, Sequence


MANAGED_RUNTIME_ENV = "ACG_MANAGED_RUNTIME"
MANAGED_RUNTIME_ROOT_ENV = "ACG_MANAGED_RUNTIME_ROOT"
TASK_WORKSPACE_ENV = "ACG_TASK_WORKSPACE"
MANAGED_TOOL_ENV = {
    "ffmpeg": "ACG_MANAGED_FFMPEG",
    "ffprobe": "ACG_MANAGED_FFPROBE",
    "yt-dlp": "ACG_MANAGED_YTDLP",
}
FFMPEG_PROTOCOL_WHITELIST = "file"
FFMPEG_PROTOCOL_BLACKLIST = (
    "async,bluray,cache,concat,concatf,crypto,data,fd,ftp,gopher,hls,http,httpproxy,https,"
    "ipfs,ipns,librist,libsrt,md5,mmsh,mmst,pipe,rtmp,rtmps,rtmpt,rtp,sctp,sftp,"
    "subfile,tcp,tls,udp,udplite,unix"
)
FFMPEG_FORMAT_WHITELIST = (
    "aac,ac3,aiff,asf,avi,caf,flac,flv,h264,hevc,image2,image2pipe,matroska,mjpeg,"
    "mov,mp3,mpeg,mpegts,ogg,opus,s16le,wav,webm,webvtt"
)
ALLOWED_EXPLICIT_INPUT_FORMATS = frozenset({"s16le"})
ALLOWED_FFMPEG_VALUE_OPTIONS = frozenset(
    {
        "-ac",
        "-acodec",
        "-af",
        "-ar",
        "-b:a",
        "-b:v",
        "-c:a",
        "-c:s",
        "-c:v",
        "-cpu-used",
        "-crf",
        "-deadline",
        "-frames:v",
        "-level",
        "-map",
        "-movflags",
        "-pix_fmt",
        "-preset",
        "-profile:v",
        "-q:a",
        "-q:v",
        "-row-mt",
        "-ss",
        "-t",
        "-vf",
    }
)
ALLOWED_FFMPEG_FLAG_OPTIONS = frozenset({"-vn"})
UNBOUNDED_FFMPEG_OPTIONS = frozenset(
    {
        "-loop",
        "-re",
        "-readrate",
        "-stream_loop",
    }
)
ALLOWED_VIDEO_FILTERS = frozenset(
    {
        "scale=-2:540",
        "scale='min(960,iw)':-2",
    }
)
_VOLUME_FILTER_RE = re.compile(r"^volume=(?:0\.[0-9]{3}|1\.000)$")
BLOCKED_ARGUMENT_OPTIONS = frozenset(
    {
        "-attach",
        "-dump_attachment",
        "-filter_complex_script",
        "-filter_script",
        "-fs",
        "-init_hw_device",
        "-protocol_blacklist",
        "-protocol_whitelist",
        "-format_whitelist",
        "-progress",
        "-safe",
    }
)
BLOCKED_INPUT_SUFFIXES = frozenset({".concat", ".ffconcat", ".m3u", ".m3u8", ".sdp"})
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_MAX_ARGUMENTS = 512
_MAX_ARGUMENT_LENGTH = 32_768
_MAX_TOOL_TIMEOUT_SECONDS = 300.0
MAX_MEDIA_INPUT_BYTES = 8 * 1024 * 1024 * 1024
MAX_MEDIA_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_MEDIA_STREAMS = 32
MAX_MEDIA_DURATION_SECONDS = 12 * 60 * 60
MAX_VIDEO_WIDTH = 8_192
MAX_VIDEO_HEIGHT = 8_192
MAX_VIDEO_PIXELS_PER_FRAME = 8_192 * 4_320
MAX_VIDEO_FRAME_RATE = 240.0
MAX_VIDEO_FRAMES = 3_000_000
MAX_DECODED_VIDEO_BYTES = 16 * 1024 * 1024 * 1024 * 1024
MAX_AUDIO_SAMPLE_RATE = 192_000
MAX_AUDIO_CHANNELS = 8
MAX_DECODED_AUDIO_BYTES = 64 * 1024 * 1024 * 1024
MAX_MEDIA_BIT_RATE = 500_000_000
MAX_RESOURCE_PROBE_STDOUT_BYTES = 1024 * 1024
MAX_RESOURCE_PROBE_STDERR_BYTES = 256 * 1024
_RESOURCE_PROBE_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
_RESOURCE_PROBE_LOCK = threading.RLock()


class MediaToolPolicyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _windows_path_form_blocked(value: str) -> bool:
    normalized = value.replace("/", "\\")
    if normalized.startswith("\\\\"):
        return True
    return bool(_WINDOWS_DRIVE_RE.match(value) and ":" in value[2:])


def _ensure_no_reparse_components(
    path: Path,
    code: str,
    message: str,
    *,
    boundary: Path | None = None,
) -> None:
    if boundary is None:
        current = Path(path.anchor)
        components = path.parts[1:]
    else:
        current = _lexical_absolute(boundary)
        try:
            components = path.relative_to(current).parts
        except ValueError as error:
            raise MediaToolPolicyError(code, message) from error
        try:
            if current.is_symlink() or (current.exists() and _has_reparse_attribute(current)):
                raise MediaToolPolicyError(code, message)
        except MediaToolPolicyError:
            raise
        except OSError as error:
            raise MediaToolPolicyError(code, message) from error
    for component in components:
        current /= component
        try:
            if current.is_symlink() or (current.exists() and _has_reparse_attribute(current)):
                raise MediaToolPolicyError(code, message)
        except MediaToolPolicyError:
            raise
        except OSError as error:
            raise MediaToolPolicyError(code, message) from error


def _lexical_absolute(path: Path) -> Path:
    """Normalize without opening a stronger realpath handle than AppContainer allows."""

    return Path(os.path.abspath(os.fspath(path)))


def _managed_boundary(env_name: str, path: Path, code: str, message: str) -> Path:
    configured = str(os.environ.get(env_name) or "").strip()
    if not configured:
        raise MediaToolPolicyError(code, message)
    raw_root = Path(configured)
    if not raw_root.is_absolute() or _windows_path_form_blocked(configured):
        raise MediaToolPolicyError(code, message)
    root = _lexical_absolute(raw_root)
    try:
        path.relative_to(root)
    except ValueError as error:
        raise MediaToolPolicyError(code, message) from error
    return root


def managed_tool_path(name: str) -> Path:
    env_name = MANAGED_TOOL_ENV.get(name)
    if env_name is None:
        raise MediaToolPolicyError("MEDIA_TOOL_NOT_ALLOWED", "Media tool is not allowed")
    configured = str(os.environ.get(env_name) or "").strip()
    if configured:
        raw_candidate = Path(configured)
        if not raw_candidate.is_absolute() or _windows_path_form_blocked(configured):
            raise MediaToolPolicyError("MANAGED_MEDIA_TOOL_INVALID", "Managed media tool path must be absolute")
        candidate = _lexical_absolute(raw_candidate)
        managed = os.environ.get(MANAGED_RUNTIME_ENV) == "1"
        boundary = (
            _managed_boundary(
                MANAGED_RUNTIME_ROOT_ENV,
                candidate,
                "MANAGED_MEDIA_TOOL_INVALID",
                "Managed media tool escaped its signed runtime boundary",
            )
            if managed
            else None
        )
        _ensure_no_reparse_components(
            candidate,
            "MANAGED_MEDIA_TOOL_INVALID",
            "Managed media tool path contains a reparse point",
            boundary=boundary,
        )
        if not candidate.is_file():
            raise MediaToolPolicyError("MANAGED_MEDIA_TOOL_MISSING", "Managed media tool is unavailable")
        return candidate
    if os.environ.get(MANAGED_RUNTIME_ENV) == "1":
        raise MediaToolPolicyError("MANAGED_MEDIA_TOOL_MISSING", "Packaged runtime is missing a managed media tool")
    discovered = shutil.which(name)
    if not discovered:
        raise MediaToolPolicyError("MANAGED_MEDIA_TOOL_MISSING", f"{name} is unavailable")
    return _lexical_absolute(Path(discovered))


def _local_input_path(value: str) -> Path:
    if not value or value == "-" or "\x00" in value:
        raise MediaToolPolicyError("MEDIA_INPUT_PROTOCOL_BLOCKED", "Media input must be a local file")
    lowered = value.casefold()
    if lowered.startswith(("concat", "concatf", "subfile", "http:", "https:", "tcp:", "udp:", "pipe:")):
        raise MediaToolPolicyError("MEDIA_INPUT_PROTOCOL_BLOCKED", "Media input protocol is blocked")
    if _SCHEME_RE.match(value) and not _WINDOWS_DRIVE_RE.match(value):
        raise MediaToolPolicyError("MEDIA_INPUT_PROTOCOL_BLOCKED", "Media input protocol is blocked")
    raw_path = Path(value)
    if not raw_path.is_absolute() or _windows_path_form_blocked(value):
        raise MediaToolPolicyError("MEDIA_INPUT_PATH_INVALID", "Media input path must be absolute")
    path = _lexical_absolute(raw_path)
    if path.suffix.casefold() in BLOCKED_INPUT_SUFFIXES:
        raise MediaToolPolicyError("MEDIA_INPUT_DEMUXER_BLOCKED", "Playlist and concat media inputs are blocked")
    boundary = (
        _managed_boundary(
            TASK_WORKSPACE_ENV,
            path,
            "MEDIA_INPUT_PATH_INVALID",
            "Managed media input escaped its task workspace",
        )
        if os.environ.get(MANAGED_RUNTIME_ENV) == "1"
        else None
    )
    _ensure_no_reparse_components(
        path,
        "MEDIA_INPUT_REPARSE_BLOCKED",
        "Media input path cannot contain a reparse point",
        boundary=boundary,
    )
    if not path.is_file():
        raise MediaToolPolicyError("MEDIA_INPUT_MISSING", "Media input file is unavailable")
    return path


def _local_output_path(value: str) -> Path:
    if (
        not value
        or value == "-"
        or "\x00" in value
        or (_SCHEME_RE.match(value) and not _WINDOWS_DRIVE_RE.match(value))
    ):
        raise MediaToolPolicyError("MEDIA_OUTPUT_PATH_INVALID", "Media output must be an absolute local file")
    raw_path = Path(value)
    if not raw_path.is_absolute() or _windows_path_form_blocked(value):
        raise MediaToolPolicyError("MEDIA_OUTPUT_PATH_INVALID", "Media output path must be absolute")
    path = _lexical_absolute(raw_path)
    if path.is_symlink() or (path.exists() and _has_reparse_attribute(path)):
        raise MediaToolPolicyError("MEDIA_OUTPUT_REPARSE_BLOCKED", "Media output cannot be a reparse point")
    if path.exists():
        raise MediaToolPolicyError("MEDIA_OUTPUT_ALREADY_EXISTS", "Media output must be a new file")
    raw_parent = path.parent
    boundary = (
        _managed_boundary(
            TASK_WORKSPACE_ENV,
            raw_parent,
            "MEDIA_OUTPUT_PATH_INVALID",
            "Managed media output escaped its task workspace",
        )
        if os.environ.get(MANAGED_RUNTIME_ENV) == "1"
        else None
    )
    _ensure_no_reparse_components(
        raw_parent,
        "MEDIA_OUTPUT_REPARSE_BLOCKED",
        "Media output directory path cannot contain a reparse point",
        boundary=boundary,
    )
    parent = _lexical_absolute(raw_parent)
    if not parent.is_dir() or _has_reparse_attribute(parent):
        raise MediaToolPolicyError("MEDIA_OUTPUT_REPARSE_BLOCKED", "Media output directory cannot be a reparse point")
    return parent / path.name


def _validate_ffmpeg_option_value(option: str, value: str) -> None:
    if option == "-vf" and value not in ALLOWED_VIDEO_FILTERS:
        raise MediaToolPolicyError("MEDIA_FILTER_BLOCKED", "Video filter is not allowed")
    if option == "-af" and _VOLUME_FILTER_RE.fullmatch(value) is None:
        raise MediaToolPolicyError("MEDIA_FILTER_BLOCKED", "Audio filter is not allowed")


def validate_media_arguments(arguments: Sequence[str]) -> list[str]:
    if not arguments or len(arguments) > _MAX_ARGUMENTS:
        raise MediaToolPolicyError("MEDIA_ARGUMENTS_INVALID", "Media tool arguments are empty or too numerous")
    normalized = [str(value) for value in arguments]
    if any("\x00" in value or len(value) > _MAX_ARGUMENT_LENGTH for value in normalized):
        raise MediaToolPolicyError("MEDIA_ARGUMENTS_INVALID", "Media tool argument is invalid")
    output_index = len(normalized) - 1
    normalized[output_index] = str(_local_output_path(normalized[output_index]))
    input_count = 0
    index = 0
    while index < output_index:
        value = normalized[index]
        lowered = value.casefold()
        if lowered in BLOCKED_ARGUMENT_OPTIONS:
            raise MediaToolPolicyError("MEDIA_ARGUMENT_OVERRIDE_BLOCKED", "Media tool policy override is blocked")
        if lowered in UNBOUNDED_FFMPEG_OPTIONS:
            raise MediaToolPolicyError(
                "MEDIA_UNBOUNDED_OPERATION_BLOCKED",
                "Looping and real-time media operations are blocked",
            )
        if lowered == "-f":
            if (
                input_count > 0
                or index + 1 >= output_index
                or normalized[index + 1].casefold() not in ALLOWED_EXPLICIT_INPUT_FORMATS
            ):
                raise MediaToolPolicyError("MEDIA_INPUT_DEMUXER_BLOCKED", "Explicit media format is blocked")
            index += 2
            continue
        if lowered == "-i":
            if index + 1 >= output_index:
                raise MediaToolPolicyError("MEDIA_ARGUMENTS_INVALID", "Media input argument is missing")
            input_count += 1
            if input_count > 1:
                raise MediaToolPolicyError("MEDIA_MULTIPLE_INPUTS_BLOCKED", "Media command must use one input")
            normalized[index + 1] = str(_local_input_path(normalized[index + 1]))
            index += 2
            continue
        if lowered in ALLOWED_FFMPEG_VALUE_OPTIONS:
            if index + 1 >= output_index:
                raise MediaToolPolicyError("MEDIA_ARGUMENTS_INVALID", "Media option value is missing")
            _validate_ffmpeg_option_value(lowered, normalized[index + 1])
            index += 2
            continue
        if lowered in ALLOWED_FFMPEG_FLAG_OPTIONS:
            index += 1
            continue
        if not value.startswith("-"):
            raise MediaToolPolicyError(
                "MEDIA_MULTIPLE_OUTPUTS_BLOCKED",
                "Media command must declare exactly one final output",
            )
        raise MediaToolPolicyError("MEDIA_ARGUMENT_OPTION_BLOCKED", "Media tool option is not allowed")
    if input_count != 1:
        raise MediaToolPolicyError("MEDIA_ARGUMENTS_INVALID", "Media command must declare an input")
    return normalized


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_integer(value: Any) -> int | None:
    number = _finite_number(value)
    if number is None or number <= 0 or not number.is_integer():
        return None
    return int(number)


def _frame_rate(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"0/0", "N/A"}:
        return None
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        top = _finite_number(numerator)
        bottom = _finite_number(denominator)
        if top is None or bottom is None or bottom == 0:
            return None
        return top / bottom
    return _finite_number(text)


def _probe_resource_evidence(path: Path) -> dict[str, Any]:
    stat_result = path.stat()
    cache_key = (str(path), int(stat_result.st_size), int(stat_result.st_mtime_ns))
    with _RESOURCE_PROBE_LOCK:
        cached = _RESOURCE_PROBE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        command = ffprobe_command(
            [
                "-show_entries",
                (
                    "format=duration,size,bit_rate:"
                    "stream=index,codec_type,width,height,duration,nb_frames,avg_frame_rate,r_frame_rate,"
                    "sample_rate,channels,bit_rate"
                ),
                "-of",
                "json",
            ],
            path,
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                command,
                shell=False,
                stdin=subprocess.DEVNULL,
                timeout=30,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as error:
            raise MediaToolPolicyError("MEDIA_RESOURCE_PROBE_TIMEOUT", "Media resource probe timed out") from error
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if (
            len(stdout.encode("utf-8", errors="replace")) > MAX_RESOURCE_PROBE_STDOUT_BYTES
            or len(stderr.encode("utf-8", errors="replace")) > MAX_RESOURCE_PROBE_STDERR_BYTES
        ):
            raise MediaToolPolicyError("MEDIA_RESOURCE_PROBE_OUTPUT_EXCEEDED", "Media resource probe output is too large")
        if completed.returncode != 0:
            raise MediaToolPolicyError("MEDIA_RESOURCE_PROBE_FAILED", "Media resource probe failed")
        try:
            evidence = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise MediaToolPolicyError("MEDIA_RESOURCE_PROBE_INVALID", "Media resource probe returned invalid JSON") from error
        if not isinstance(evidence, dict):
            raise MediaToolPolicyError("MEDIA_RESOURCE_PROBE_INVALID", "Media resource probe returned invalid evidence")
        final_stat = path.stat()
        if (
            int(final_stat.st_size) != cache_key[1]
            or int(final_stat.st_mtime_ns) != cache_key[2]
        ):
            raise MediaToolPolicyError("MEDIA_INPUT_CHANGED_DURING_PROBE", "Media input changed during resource probe")
        if len(_RESOURCE_PROBE_CACHE) >= 128:
            _RESOURCE_PROBE_CACHE.pop(next(iter(_RESOURCE_PROBE_CACHE)))
        _RESOURCE_PROBE_CACHE[cache_key] = evidence
        return evidence


def _validate_probed_resource(path: Path, evidence: dict[str, Any]) -> None:
    streams = evidence.get("streams")
    format_evidence = evidence.get("format")
    if not isinstance(streams, list) or not isinstance(format_evidence, dict):
        raise MediaToolPolicyError("MEDIA_RESOURCE_PROBE_INVALID", "Media resource evidence is incomplete")
    if not streams or len(streams) > MAX_MEDIA_STREAMS:
        raise MediaToolPolicyError("MEDIA_STREAM_LIMIT_EXCEEDED", "Media stream count is outside the allowed range")
    format_duration = _finite_number(format_evidence.get("duration"))
    format_bit_rate = _positive_integer(format_evidence.get("bit_rate"))
    if format_bit_rate is not None and format_bit_rate > MAX_MEDIA_BIT_RATE:
        raise MediaToolPolicyError("MEDIA_BIT_RATE_LIMIT_EXCEEDED", "Media bit rate exceeds the allowed limit")
    has_timed_stream = False
    for stream in streams:
        if not isinstance(stream, dict):
            raise MediaToolPolicyError("MEDIA_RESOURCE_PROBE_INVALID", "Media stream evidence is invalid")
        stream_type = str(stream.get("codec_type") or "")
        if stream_type == "attachment":
            raise MediaToolPolicyError("MEDIA_ATTACHMENT_BLOCKED", "Embedded media attachments are blocked")
        if stream_type not in {"video", "audio", "subtitle", "data"}:
            raise MediaToolPolicyError("MEDIA_STREAM_TYPE_BLOCKED", "Media stream type is not allowed")
        stream_duration = _finite_number(stream.get("duration"))
        duration_candidates = [
            value
            for value in (stream_duration, format_duration)
            if value is not None and value > 0
        ]
        duration = max(duration_candidates) if duration_candidates else None
        stream_bit_rate = _positive_integer(stream.get("bit_rate"))
        if stream_bit_rate is not None and stream_bit_rate > MAX_MEDIA_BIT_RATE:
            raise MediaToolPolicyError("MEDIA_BIT_RATE_LIMIT_EXCEEDED", "Media stream bit rate exceeds the allowed limit")
        if stream_type not in {"video", "audio"}:
            continue
        has_timed_stream = True
        if duration is None or duration <= 0 or duration > MAX_MEDIA_DURATION_SECONDS:
            raise MediaToolPolicyError("MEDIA_DURATION_LIMIT_EXCEEDED", "Media duration is unknown or exceeds the limit")
        if stream_type == "video":
            width = _positive_integer(stream.get("width"))
            height = _positive_integer(stream.get("height"))
            if width is None or height is None or width > MAX_VIDEO_WIDTH or height > MAX_VIDEO_HEIGHT:
                raise MediaToolPolicyError("MEDIA_DIMENSION_LIMIT_EXCEEDED", "Video dimensions exceed the allowed limit")
            pixels = width * height
            if pixels > MAX_VIDEO_PIXELS_PER_FRAME:
                raise MediaToolPolicyError("MEDIA_PIXEL_LIMIT_EXCEEDED", "Video pixels per frame exceed the allowed limit")
            rate = _frame_rate(stream.get("avg_frame_rate")) or _frame_rate(stream.get("r_frame_rate"))
            if rate is None or rate <= 0 or rate > MAX_VIDEO_FRAME_RATE:
                raise MediaToolPolicyError("MEDIA_FRAME_RATE_LIMIT_EXCEEDED", "Video frame rate is unknown or exceeds the limit")
            reported_frames = _positive_integer(stream.get("nb_frames")) or 0
            frames = max(reported_frames, int(math.ceil(duration * rate)))
            if frames > MAX_VIDEO_FRAMES or pixels * frames * 4 > MAX_DECODED_VIDEO_BYTES:
                raise MediaToolPolicyError("MEDIA_DECODE_LIMIT_EXCEEDED", "Video logical decode size exceeds the limit")
        elif stream_type == "audio":
            sample_rate = _positive_integer(stream.get("sample_rate"))
            channels = _positive_integer(stream.get("channels"))
            if sample_rate is None or sample_rate > MAX_AUDIO_SAMPLE_RATE:
                raise MediaToolPolicyError("MEDIA_SAMPLE_RATE_LIMIT_EXCEEDED", "Audio sample rate exceeds the allowed limit")
            if channels is None or channels > MAX_AUDIO_CHANNELS:
                raise MediaToolPolicyError("MEDIA_CHANNEL_LIMIT_EXCEEDED", "Audio channel count exceeds the allowed limit")
            if duration * sample_rate * channels * 4 > MAX_DECODED_AUDIO_BYTES:
                raise MediaToolPolicyError("MEDIA_DECODE_LIMIT_EXCEEDED", "Audio logical decode size exceeds the limit")
    if not has_timed_stream:
        raise MediaToolPolicyError("MEDIA_TIMED_STREAM_REQUIRED", "Media input has no timed audio or video stream")


def _input_specs(arguments: Sequence[str]) -> list[tuple[Path, str, int | None, int | None]]:
    specs: list[tuple[Path, str, int | None, int | None]] = []
    explicit_format = ""
    sample_rate: int | None = None
    channels: int | None = None
    index = 0
    while index < len(arguments):
        value = arguments[index].casefold()
        if value in {"-f", "-ar", "-ac"} and index + 1 < len(arguments):
            next_value = arguments[index + 1]
            if value == "-f":
                explicit_format = next_value.casefold()
            elif value == "-ar":
                sample_rate = _positive_integer(next_value)
            else:
                channels = _positive_integer(next_value)
            index += 2
            continue
        if value == "-i" and index + 1 < len(arguments):
            specs.append((Path(arguments[index + 1]), explicit_format, sample_rate, channels))
            explicit_format = ""
            sample_rate = None
            channels = None
            index += 2
            continue
        index += 1
    return specs


def validate_media_resource_limits(arguments: Sequence[str]) -> None:
    specs = _input_specs(arguments)
    total_bytes = sum(path.stat().st_size for path, *_ in specs)
    if total_bytes <= 0 or total_bytes > MAX_MEDIA_INPUT_BYTES:
        raise MediaToolPolicyError("MEDIA_INPUT_SIZE_LIMIT_EXCEEDED", "Media input bytes exceed the allowed limit")
    for path, explicit_format, sample_rate, channels in specs:
        if explicit_format == "s16le":
            if sample_rate is None or not 8_000 <= sample_rate <= MAX_AUDIO_SAMPLE_RATE:
                raise MediaToolPolicyError("MEDIA_SAMPLE_RATE_LIMIT_EXCEEDED", "Raw audio sample rate is invalid")
            if channels is None or channels > MAX_AUDIO_CHANNELS:
                raise MediaToolPolicyError("MEDIA_CHANNEL_LIMIT_EXCEEDED", "Raw audio channel count is invalid")
            decoded_bytes = path.stat().st_size
            duration = path.stat().st_size / (sample_rate * channels * 2)
            if duration <= 0 or duration > MAX_MEDIA_DURATION_SECONDS or decoded_bytes > MAX_DECODED_AUDIO_BYTES:
                raise MediaToolPolicyError("MEDIA_DECODE_LIMIT_EXCEEDED", "Raw audio logical decode size exceeds the limit")
            continue
        _validate_probed_resource(path, _probe_resource_evidence(path))


def _ffmpeg_command(validated: Sequence[str]) -> list[str]:
    return [
        str(managed_tool_path("ffmpeg")),
        "-nostdin",
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
        "-probesize",
        "50000000",
        "-analyzeduration",
        "30000000",
        "-max_streams",
        str(MAX_MEDIA_STREAMS),
        "-filter_threads",
        "2",
        "-filter_complex_threads",
        "2",
        "-y",
        *validated[:-1],
        "-fs",
        str(MAX_MEDIA_OUTPUT_BYTES),
        validated[-1],
    ]


def ffmpeg_command(arguments: Sequence[str]) -> list[str]:
    return _ffmpeg_command(validate_media_arguments(arguments))


def ffprobe_command(arguments: Sequence[str], input_path: str | Path) -> list[str]:
    normalized = [str(value) for value in arguments]
    if len(normalized) > _MAX_ARGUMENTS or any(
        "\x00" in value or len(value) > _MAX_ARGUMENT_LENGTH for value in normalized
    ):
        raise MediaToolPolicyError("MEDIA_ARGUMENTS_INVALID", "Media probe argument is invalid")
    if any(value.casefold() in BLOCKED_ARGUMENT_OPTIONS or value.casefold() == "-f" for value in normalized):
        raise MediaToolPolicyError("MEDIA_ARGUMENT_OVERRIDE_BLOCKED", "Media probe policy override is blocked")
    resolved_input = _local_input_path(str(input_path))
    return [
        str(managed_tool_path("ffprobe")),
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
        "-probesize",
        "50000000",
        "-analyzeduration",
        "30000000",
        "-max_streams",
        str(MAX_MEDIA_STREAMS),
        *normalized,
        str(resolved_input),
    ]


def _timeout(value: float | int | None) -> float:
    if value is None:
        return _MAX_TOOL_TIMEOUT_SECONDS
    return max(1.0, min(float(value), _MAX_TOOL_TIMEOUT_SECONDS))


def _remove_run_output(path: Path) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.exists():
            raise MediaToolPolicyError("MEDIA_OUTPUT_CLEANUP_FAILED", "Media output is not safe to remove")
    except MediaToolPolicyError:
        raise
    except OSError as error:
        raise MediaToolPolicyError("MEDIA_OUTPUT_CLEANUP_FAILED", "Media output cleanup failed") from error


def run_ffmpeg(
    arguments: Sequence[str],
    *,
    timeout: float | int | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    if "shell" in kwargs or "stdin" in kwargs or "timeout" in kwargs:
        raise MediaToolPolicyError("MEDIA_SUBPROCESS_OVERRIDE_BLOCKED", "Media subprocess policy override is blocked")
    validated = validate_media_arguments(arguments)
    if os.environ.get(MANAGED_RUNTIME_ENV) == "1":
        validate_media_resource_limits(validated)
    output_path = Path(validated[-1])
    try:
        completed = subprocess.run(
            _ffmpeg_command(validated),
            shell=False,
            stdin=subprocess.DEVNULL,
            timeout=_timeout(timeout),
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired):
        _remove_run_output(output_path)
        raise
    if completed.returncode != 0:
        _remove_run_output(output_path)
        return completed
    if output_path.is_symlink():
        _remove_run_output(output_path)
        raise MediaToolPolicyError("MEDIA_OUTPUT_REPARSE_BLOCKED", "Media output became a reparse point")
    if not output_path.exists():
        raise MediaToolPolicyError("MEDIA_OUTPUT_MISSING", "Media tool reported success without an output file")
    if _has_reparse_attribute(output_path):
        _remove_run_output(output_path)
        raise MediaToolPolicyError("MEDIA_OUTPUT_REPARSE_BLOCKED", "Media output became a reparse point")
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        _remove_run_output(output_path)
        raise MediaToolPolicyError("MEDIA_OUTPUT_INVALID", "Media output is not a non-empty regular file")
    if output_path.stat().st_size >= MAX_MEDIA_OUTPUT_BYTES:
        _remove_run_output(output_path)
        raise MediaToolPolicyError("MEDIA_OUTPUT_SIZE_LIMIT_EXCEEDED", "Media output reached the safety limit")
    return completed


def run_ffprobe(
    arguments: Sequence[str],
    input_path: str | Path,
    *,
    timeout: float | int | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    if "shell" in kwargs or "stdin" in kwargs or "timeout" in kwargs:
        raise MediaToolPolicyError("MEDIA_SUBPROCESS_OVERRIDE_BLOCKED", "Media subprocess policy override is blocked")
    return subprocess.run(
        ffprobe_command(arguments, input_path),
        shell=False,
        stdin=subprocess.DEVNULL,
        timeout=_timeout(timeout),
        **kwargs,
    )


def tool_version(name: str, *, timeout: float | int = 10) -> subprocess.CompletedProcess[str]:
    if name not in {"ffmpeg", "ffprobe"}:
        raise MediaToolPolicyError("MEDIA_TOOL_NOT_ALLOWED", "Media tool is not allowed")
    argument = "-version"
    return subprocess.run(
        [str(managed_tool_path(name)), argument],
        shell=False,
        stdin=subprocess.DEVNULL,
        timeout=_timeout(timeout),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
