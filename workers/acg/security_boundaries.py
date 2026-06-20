from __future__ import annotations

import ipaddress
import urllib.parse
from typing import Any

from acg.protocol import fail


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
BLOCKED_URL_HOSTS = {"localhost", "localhost.localdomain"}
SENSITIVE_WINDOWS_ROOTS = {
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
}
SUPPORTED_INPUT_SUFFIXES = {
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".m4v",
    ".srt",
    ".vtt",
    ".txt",
    ".md",
    ".markdown",
    ".docx",
    ".epub",
    ".pdf",
    ".azw",
    ".azw3",
    ".mobi",
}


def parsed_url_host(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    return (parsed.hostname or "").strip().lower()


def ip_address_for_host(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def host_is_loopback(host: str) -> bool:
    lower = host.strip().strip("[]").lower()
    if lower in LOOPBACK_HOSTS:
        return True
    address = ip_address_for_host(lower)
    return bool(address and address.is_loopback)


def host_is_private_or_local(host: str) -> bool:
    lower = host.strip().strip("[]").lower().rstrip(".")
    if not lower or lower in BLOCKED_URL_HOSTS or lower.endswith(".local"):
        return True
    address = ip_address_for_host(lower)
    if not address:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def validate_anki_connect_url(url: str) -> None:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    host = parsed_url_host(url)
    if parsed.scheme not in {"http", "https"} or not host:
        fail(
            "AnkiConnect 地址必须是 http(s) loopback URL。",
            error_code="REMOTE_ANKI_CONNECT_BLOCKED",
            stage="anki_verify",
        )
    if parsed.username or parsed.password or not host_is_loopback(host):
        fail(
            "AnkiConnect 只允许连接本机 localhost / 127.0.0.1 / ::1，已阻止远程地址。",
            error_code="REMOTE_ANKI_CONNECT_BLOCKED",
            stage="anki_verify",
            details={"anki_connect_url": str(url or "")},
        )


def validate_source_url_for_import(payload: dict[str, Any]) -> str:
    url = str(payload.get("source_url") or "").strip()
    if not url:
        fail("请输入 YouTube / 视频 URL。")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        fail("URL 需要以 http:// 或 https:// 开头。")
    host = parsed.hostname or ""
    if host_is_private_or_local(host) and not bool(payload.get("allow_private_network_url")):
        fail(
            "出于安全考虑，URL 视频导入默认不访问 localhost、私网、link-local 或系统保留地址。"
            "如果这是你明确选择的本机/内网素材，请在确认面板里允许本机/内网 URL 后重试。",
            error_code="PRIVATE_NETWORK_URL_BLOCKED",
            stage="download_video",
            retryable=False,
            details={"source_url": url, "host": host},
        )
    return url


def require_confirmed_local_path_access(payload: dict[str, Any], *, stage: str) -> None:
    if "local_path_access_confirmed" in payload and not bool(payload.get("local_path_access_confirmed")):
        fail(
            "读取本地视频、字幕或文档前需要用户在本轮确认路径来源。",
            error_code="LOCAL_PATH_ACCESS_CONFIRMATION_REQUIRED",
            stage=stage,
            retryable=False,
        )
