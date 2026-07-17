from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any, Sequence


MANAGED_RUNTIME_ENV = "ACG_MANAGED_RUNTIME"
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
ALLOWED_EXPLICIT_FORMATS = frozenset(
    {
        "aac",
        "flac",
        "image2",
        "matroska",
        "mov",
        "mp3",
        "mp4",
        "null",
        "ogg",
        "opus",
        "s16le",
        "wav",
        "webm",
    }
)
BLOCKED_ARGUMENT_OPTIONS = frozenset(
    {
        "-attach",
        "-dump_attachment",
        "-filter_complex_script",
        "-filter_script",
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


class MediaToolPolicyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def managed_tool_path(name: str) -> Path:
    env_name = MANAGED_TOOL_ENV.get(name)
    if env_name is None:
        raise MediaToolPolicyError("MEDIA_TOOL_NOT_ALLOWED", "Media tool is not allowed")
    configured = str(os.environ.get(env_name) or "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            raise MediaToolPolicyError("MANAGED_MEDIA_TOOL_INVALID", "Managed media tool path must be absolute")
        if candidate.is_symlink() or (candidate.exists() and _has_reparse_attribute(candidate)):
            raise MediaToolPolicyError("MANAGED_MEDIA_TOOL_INVALID", "Managed media tool path contains a reparse point")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise MediaToolPolicyError("MANAGED_MEDIA_TOOL_MISSING", "Managed media tool is unavailable") from error
        if not resolved.is_file():
            raise MediaToolPolicyError("MANAGED_MEDIA_TOOL_MISSING", "Managed media tool is unavailable")
        return resolved
    if os.environ.get(MANAGED_RUNTIME_ENV) == "1":
        raise MediaToolPolicyError("MANAGED_MEDIA_TOOL_MISSING", "Packaged runtime is missing a managed media tool")
    discovered = shutil.which(name)
    if not discovered:
        raise MediaToolPolicyError("MANAGED_MEDIA_TOOL_MISSING", f"{name} is unavailable")
    return Path(discovered).resolve(strict=True)


def _local_input_path(value: str) -> Path:
    if not value or value == "-" or "\x00" in value:
        raise MediaToolPolicyError("MEDIA_INPUT_PROTOCOL_BLOCKED", "Media input must be a local file")
    lowered = value.casefold()
    if lowered.startswith(("concat", "concatf", "subfile", "http:", "https:", "tcp:", "udp:", "pipe:")):
        raise MediaToolPolicyError("MEDIA_INPUT_PROTOCOL_BLOCKED", "Media input protocol is blocked")
    if _SCHEME_RE.match(value) and not _WINDOWS_DRIVE_RE.match(value):
        raise MediaToolPolicyError("MEDIA_INPUT_PROTOCOL_BLOCKED", "Media input protocol is blocked")
    path = Path(value)
    if not path.is_absolute():
        raise MediaToolPolicyError("MEDIA_INPUT_PATH_INVALID", "Media input path must be absolute")
    if path.suffix.casefold() in BLOCKED_INPUT_SUFFIXES:
        raise MediaToolPolicyError("MEDIA_INPUT_DEMUXER_BLOCKED", "Playlist and concat media inputs are blocked")
    if path.is_symlink() or (path.exists() and _has_reparse_attribute(path)):
        raise MediaToolPolicyError("MEDIA_INPUT_REPARSE_BLOCKED", "Media input cannot be a reparse point")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise MediaToolPolicyError("MEDIA_INPUT_MISSING", "Media input file is unavailable") from error
    if not resolved.is_file():
        raise MediaToolPolicyError("MEDIA_INPUT_MISSING", "Media input file is unavailable")
    return resolved


def validate_media_arguments(arguments: Sequence[str]) -> list[str]:
    if not arguments or len(arguments) > _MAX_ARGUMENTS:
        raise MediaToolPolicyError("MEDIA_ARGUMENTS_INVALID", "Media tool arguments are empty or too numerous")
    normalized = [str(value) for value in arguments]
    if any("\x00" in value or len(value) > _MAX_ARGUMENT_LENGTH for value in normalized):
        raise MediaToolPolicyError("MEDIA_ARGUMENTS_INVALID", "Media tool argument is invalid")
    index = 0
    while index < len(normalized):
        value = normalized[index]
        lowered = value.casefold()
        if lowered in BLOCKED_ARGUMENT_OPTIONS:
            raise MediaToolPolicyError("MEDIA_ARGUMENT_OVERRIDE_BLOCKED", "Media tool policy override is blocked")
        if lowered == "-f":
            if index + 1 >= len(normalized) or normalized[index + 1].casefold() not in ALLOWED_EXPLICIT_FORMATS:
                raise MediaToolPolicyError("MEDIA_INPUT_DEMUXER_BLOCKED", "Explicit media format is blocked")
            index += 2
            continue
        if lowered == "-i":
            if index + 1 >= len(normalized):
                raise MediaToolPolicyError("MEDIA_ARGUMENTS_INVALID", "Media input argument is missing")
            normalized[index + 1] = str(_local_input_path(normalized[index + 1]))
            index += 2
            continue
        index += 1
    if "-i" not in [value.casefold() for value in normalized]:
        raise MediaToolPolicyError("MEDIA_ARGUMENTS_INVALID", "Media command must declare an input")
    return normalized


def ffmpeg_command(arguments: Sequence[str]) -> list[str]:
    validated = validate_media_arguments(arguments)
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
        "-filter_threads",
        "2",
        "-filter_complex_threads",
        "2",
        "-y",
        *validated,
    ]


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
        *normalized,
        str(resolved_input),
    ]


def _timeout(value: float | int | None) -> float:
    if value is None:
        return _MAX_TOOL_TIMEOUT_SECONDS
    return max(1.0, min(float(value), _MAX_TOOL_TIMEOUT_SECONDS))


def run_ffmpeg(
    arguments: Sequence[str],
    *,
    timeout: float | int | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    if "shell" in kwargs or "stdin" in kwargs or "timeout" in kwargs:
        raise MediaToolPolicyError("MEDIA_SUBPROCESS_OVERRIDE_BLOCKED", "Media subprocess policy override is blocked")
    return subprocess.run(
        ffmpeg_command(arguments),
        shell=False,
        stdin=subprocess.DEVNULL,
        timeout=_timeout(timeout),
        **kwargs,
    )


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
