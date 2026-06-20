from __future__ import annotations

import subprocess
import shutil
from collections.abc import Callable
from typing import Any


YTDLP_REMOTE_COMPONENTS_ARGS = ["--remote-components", "ejs:github"]
YTDLP_NETWORK_BASE_ARGS = [
    "--force-ipv4",
    "--retries",
    "10",
    "--fragment-retries",
    "10",
    "--extractor-retries",
    "5",
    "--retry-sleep",
    "http:linear=3::20",
    "--sleep-requests",
    "0.75",
    "--sleep-subtitles",
    "1.5",
]


def yt_dlp_js_runtime_args(
    allow_remote_components: bool = False,
    *,
    which_func: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    if not allow_remote_components:
        return []
    for runtime in ("deno", "node", "bun"):
        if which_func(runtime):
            return ["--js-runtimes", runtime, *YTDLP_REMOTE_COMPONENTS_ARGS]
    return []


def yt_dlp_network_args(*, curl_cffi_available: bool = False) -> list[str]:
    args = list(YTDLP_NETWORK_BASE_ARGS)
    if curl_cffi_available:
        args.extend(["--impersonate", "chrome"])
    return args


def yt_dlp_needs_remote_components(detail: str) -> bool:
    lower = detail.lower()
    return "n challenge solving failed" in lower or "remote component challenge solver" in lower


def yt_dlp_failure_detail(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stderr or completed.stdout or "").strip()


def is_subtitle_rate_limited(detail: str) -> bool:
    lower = detail.lower()
    return "http error 429" in lower and "subtitles" in lower


def format_yt_dlp_failure(detail: str) -> str:
    tail = detail[-1800:]
    if "HTTP Error 429" in detail:
        return (
            "URL 下载失败：YouTube 返回 HTTP 429，说明当前网络/IP 被临时限流，尤其是字幕接口。"
            "我已经启用了 EJS、重试、降速和浏览器模拟；如果仍失败，请稍后重试、换网络/代理，"
            "或先下载/准备本地 SRT 后走“本地视频 + SRT”。\n\n"
            f"yt-dlp 原始信息：{tail}"
        )
    if yt_dlp_needs_remote_components(detail):
        return (
            "URL 下载失败：YouTube JS challenge 没有解开。出于安全考虑，本应用默认不自动启用 yt-dlp remote components。"
            "请确认你信任本次来源后再允许远程组件重试。\n\n"
            f"yt-dlp 原始信息：{tail}"
        )
    return f"URL 下载失败：{tail}"


def yt_dlp_failure_meta(detail: str) -> dict[str, Any]:
    if "HTTP Error 429" in detail:
        return {
            "error_code": "YOUTUBE_RATE_LIMIT",
            "stage": "download_subtitles" if "subtitles" in detail.lower() else "download_video",
            "retryable": True,
            "fallbacks": ["subtitle_only", "local_srt"],
        }
    if yt_dlp_needs_remote_components(detail):
        return {
            "error_code": "YTDLP_REMOTE_COMPONENTS_CONFIRMATION_REQUIRED",
            "stage": "download_video",
            "retryable": True,
            "fallbacks": ["allow_ytdlp_remote_components", "subtitle_only", "local_srt"],
        }
    return {
        "error_code": "YOUTUBE_SUBTITLE_UNAVAILABLE" if "subtitles" in detail.lower() else None,
        "stage": "download_subtitles" if "subtitles" in detail.lower() else "download_video",
        "retryable": True,
        "fallbacks": ["subtitle_only", "local_srt"],
    }
