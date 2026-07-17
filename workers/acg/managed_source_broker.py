from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

from .broker_client import WorkerBrokerClient, WorkerBrokerError, configured_broker_client


SOURCE_OPERATION = "source.youtube_subtitles"
MAX_SUBTITLE_BYTES = 600 * 1024
YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
WORK_UNIT_PART = re.compile(r"[^A-Za-z0-9._:-]+")
ALLOWED_RESPONSE_KEYS = frozenset(
    {
        "schemaVersion",
        "sourceKind",
        "videoId",
        "title",
        "languageCode",
        "captionKind",
        "mimeType",
        "contentBase64",
        "byteLength",
        "sha256",
    }
)


class ManagedSourceBrokerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManagedYouTubeSubtitles:
    video_id: str
    title: str
    language_code: str
    caption_kind: str
    vtt: bytes


def configured_client() -> WorkerBrokerClient | None:
    return configured_broker_client()


def is_configured() -> bool:
    return configured_client() is not None


def operation_available() -> bool:
    client = configured_client()
    return client is not None and SOURCE_OPERATION in client.allowed_operations


def youtube_video_id(source_url: str) -> str:
    raw = str(source_url or "").strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise ManagedSourceBrokerError("YouTube source URL is invalid") from error
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme != "https"
        or host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
    ):
        raise ManagedSourceBrokerError("YouTube source URL is outside the managed acquisition boundary")
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    candidate = ""
    if host == "youtu.be" and len(parts) == 1:
        candidate = parts[0]
    elif parsed.path.rstrip("/") == "/watch":
        values = urllib.parse.parse_qs(parsed.query, keep_blank_values=True).get("v") or []
        candidate = values[0] if len(values) == 1 else ""
    elif len(parts) == 2 and parts[0].casefold() in {"shorts", "embed"}:
        candidate = parts[1]
    if YOUTUBE_VIDEO_ID.fullmatch(candidate) is None:
        raise ManagedSourceBrokerError("YouTube video ID is invalid")
    return candidate


def _language_prefix(language: str) -> str:
    normalized = str(language or "").strip().casefold().replace("_", "-")
    aliases = {
        "english": "en",
        "chinese": "zh",
        "mandarin": "zh",
        "japanese": "ja",
        "korean": "ko",
        "spanish": "es",
        "french": "fr",
        "german": "de",
    }
    prefix = aliases.get(normalized, normalized.split("-", 1)[0])
    if re.fullmatch(r"[a-z]{2,8}", prefix) is None:
        raise ManagedSourceBrokerError("Subtitle language is invalid")
    return prefix


def _work_unit_id(base: str, request: dict[str, Any]) -> str:
    normalized = WORK_UNIT_PART.sub("-", str(base or "youtube-subtitles")).strip("-._:") or "youtube-subtitles"
    digest = hashlib.sha256(
        json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    prefix = f"source:{normalized}"[:136].rstrip("-._:")
    return f"{prefix}:{digest}"


def request_youtube_subtitles(
    source_url: str,
    *,
    language: str,
    work_unit_base: str = "youtube-subtitles",
) -> ManagedYouTubeSubtitles:
    client = configured_client()
    if client is None:
        raise ManagedSourceBrokerError("Managed source broker is not configured")
    if SOURCE_OPERATION not in client.allowed_operations:
        raise ManagedSourceBrokerError("Managed YouTube subtitle acquisition is not authorized")
    video_id = youtube_video_id(source_url)
    requested_language = _language_prefix(language)
    request = {"videoId": video_id, "language": requested_language, "format": "vtt"}
    try:
        result = client.request(
            SOURCE_OPERATION,
            {"workUnitId": _work_unit_id(work_unit_base, request), "request": request},
        )
    except WorkerBrokerError as error:
        raise ManagedSourceBrokerError(str(error)) from error
    if not isinstance(result, dict) or set(result) != ALLOWED_RESPONSE_KEYS:
        raise ManagedSourceBrokerError("Managed source broker returned an invalid response")
    if (
        result.get("schemaVersion") != 1
        or result.get("sourceKind") != "youtube_subtitles"
        or result.get("videoId") != video_id
        or result.get("mimeType") != "text/vtt"
        or result.get("captionKind") not in {"manual", "automatic"}
    ):
        raise ManagedSourceBrokerError("Managed source broker returned mismatched source evidence")
    language_code = str(result.get("languageCode") or "").casefold()
    if language_code.split("-", 1)[0] != requested_language:
        raise ManagedSourceBrokerError("Managed source broker returned another subtitle language")
    encoded = result.get("contentBase64")
    try:
        vtt = base64.b64decode(encoded, validate=True) if isinstance(encoded, str) else b""
    except (binascii.Error, ValueError, TypeError) as error:
        raise ManagedSourceBrokerError("Managed source broker returned invalid subtitle encoding") from error
    if (
        not vtt.startswith(b"WEBVTT")
        or len(vtt) > MAX_SUBTITLE_BYTES
        or result.get("byteLength") != len(vtt)
        or result.get("sha256") != hashlib.sha256(vtt).hexdigest()
    ):
        raise ManagedSourceBrokerError("Managed source broker returned invalid subtitle integrity evidence")
    title = str(result.get("title") or "").strip()
    if len(title) > 300 or "\x00" in title:
        raise ManagedSourceBrokerError("Managed source broker returned an invalid title")
    return ManagedYouTubeSubtitles(
        video_id=video_id,
        title=title,
        language_code=str(result["languageCode"]),
        caption_kind=str(result["captionKind"]),
        vtt=vtt,
    )
