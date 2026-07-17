from __future__ import annotations

import base64
import hashlib
import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .broker import BrokerBudget, BrokerCall, BrokerError, ModelTtsBroker, canonical_digest
from .broker_ipc import BrokerIpcError
from .broker_runtime import WORK_UNIT_PATTERN


YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_SOURCE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
YOUTUBE_FETCH_HOSTS = frozenset({"youtube.com", "www.youtube.com"})
MAX_WATCH_PAGE_BYTES = 3 * 1024 * 1024
MAX_SUBTITLE_BYTES = 600 * 1024
MAX_CAPTION_URL_CHARS = 16 * 1024
SOURCE_OPERATION = "source.youtube_subtitles"
SOURCE_PROFILE_REF = "source.youtube_subtitles"


class SourceAcquisitionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SourceFetchResponse:
    status: int
    url: str
    headers: Mapping[str, str]
    body: bytes
    peer_ip: str


SourceFetchTransport = Callable[[str, int, float], SourceFetchResponse]
AddressResolver = Callable[..., list[tuple[Any, ...]]]


def _normalized_host(parsed: urllib.parse.SplitResult) -> str:
    try:
        port = parsed.port
    except ValueError as error:
        raise SourceAcquisitionError("SOURCE_URL_INVALID", "Source URL port is invalid") from error
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise SourceAcquisitionError("SOURCE_URL_BLOCKED", "Source URL must use public HTTPS without credentials")
    return host


def youtube_video_id(source_url: str) -> str:
    raw = str(source_url or "").strip()
    if not raw or len(raw) > 4096 or "\x00" in raw:
        raise SourceAcquisitionError("SOURCE_URL_INVALID", "YouTube source URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError as error:
        raise SourceAcquisitionError("SOURCE_URL_INVALID", "YouTube source URL is invalid") from error
    host = _normalized_host(parsed)
    if host not in YOUTUBE_SOURCE_HOSTS or parsed.fragment:
        raise SourceAcquisitionError("SOURCE_HOST_BLOCKED", "Only a fixed public YouTube video URL is supported")
    path_parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    candidate = ""
    if host == "youtu.be":
        if len(path_parts) != 1:
            raise SourceAcquisitionError("SOURCE_URL_INVALID", "YouTube short URL path is invalid")
        candidate = path_parts[0]
    elif parsed.path.rstrip("/") == "/watch":
        values = urllib.parse.parse_qs(parsed.query, keep_blank_values=True).get("v") or []
        if len(values) != 1:
            raise SourceAcquisitionError("SOURCE_URL_INVALID", "YouTube watch URL must contain one video ID")
        candidate = values[0]
    elif len(path_parts) == 2 and path_parts[0].casefold() in {"shorts", "embed"}:
        candidate = path_parts[1]
    else:
        raise SourceAcquisitionError("SOURCE_URL_INVALID", "YouTube source URL path is unsupported")
    if YOUTUBE_VIDEO_ID.fullmatch(candidate) is None:
        raise SourceAcquisitionError("SOURCE_VIDEO_ID_INVALID", "YouTube video ID is invalid")
    return candidate


def canonical_youtube_watch_url(source_url: str) -> str:
    video_id = youtube_video_id(source_url)
    return "https://www.youtube.com/watch?" + urllib.parse.urlencode({"v": video_id, "hl": "en"})


def resolve_public_addresses(host: str, *, resolver: AddressResolver = socket.getaddrinfo) -> tuple[str, ...]:
    try:
        records = resolver(host, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise SourceAcquisitionError("SOURCE_DNS_FAILED", "Source host DNS lookup failed") from error
    addresses: set[str] = set()
    for record in records:
        try:
            value = str(record[4][0]).split("%", 1)[0]
            address = ipaddress.ip_address(value)
        except (IndexError, TypeError, ValueError) as error:
            raise SourceAcquisitionError("SOURCE_DNS_INVALID", "Source host returned an invalid address") from error
        if not address.is_global:
            raise SourceAcquisitionError("SOURCE_DNS_PRIVATE_BLOCKED", "Source host resolved to a non-public address")
        addresses.add(address.compressed)
    if not addresses:
        raise SourceAcquisitionError("SOURCE_DNS_FAILED", "Source host did not resolve to a public address")
    return tuple(sorted(addresses))


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, *, timeout: float, context: ssl.SSLContext) -> None:
        super().__init__(host, 443, timeout=timeout, context=context)
        self._address = address

    def connect(self) -> None:
        raw = socket.create_connection((self._address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


class PinnedHttpsFetcher:
    def __init__(
        self,
        *,
        resolver: AddressResolver = socket.getaddrinfo,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.resolver = resolver
        self.ssl_context = ssl_context or ssl.create_default_context()

    def fetch(self, url: str, maximum_bytes: int, timeout_seconds: float) -> SourceFetchResponse:
        try:
            parsed = urllib.parse.urlsplit(url)
        except ValueError as error:
            raise SourceAcquisitionError("SOURCE_FETCH_URL_INVALID", "Source fetch URL is invalid") from error
        host = _normalized_host(parsed)
        if host not in YOUTUBE_FETCH_HOSTS or parsed.fragment:
            raise SourceAcquisitionError("SOURCE_FETCH_HOST_BLOCKED", "Source fetch host is not allowed")
        addresses = resolve_public_addresses(host, resolver=self.resolver)
        target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        last_error: Exception | None = None
        for address in addresses:
            connection = _PinnedHttpsConnection(
                host,
                address,
                timeout=max(1.0, min(float(timeout_seconds), 60.0)),
                context=self.ssl_context,
            )
            try:
                connection.request(
                    "GET",
                    target,
                    headers={
                        "Accept": "text/html,text/plain,text/vtt,application/xml;q=0.9,*/*;q=0.1",
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                        "User-Agent": "CodexStudy/1.0 (+local source acquisition)",
                    },
                )
                response = connection.getresponse()
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise SourceAcquisitionError("SOURCE_RESPONSE_LIMIT", "Source response exceeded its byte limit")
                return SourceFetchResponse(
                    status=int(response.status),
                    url=url,
                    headers={name.casefold(): value for name, value in response.getheaders()},
                    body=body,
                    peer_ip=address,
                )
            except SourceAcquisitionError:
                raise
            except (OSError, ssl.SSLError, http.client.HTTPException) as error:
                last_error = error
            finally:
                connection.close()
        raise SourceAcquisitionError("SOURCE_FETCH_FAILED", "Source HTTPS request failed") from last_error


def _raw_json_after_marker(text: str, marker: str) -> Any | None:
    start = text.find(marker)
    if start < 0:
        return None
    start += len(marker)
    while start < len(text) and text[start] in " \t\r\n:=":
        start += 1
    try:
        return json.JSONDecoder().raw_decode(text, start)[0]
    except (ValueError, TypeError):
        return None


def _player_response(watch_page: bytes) -> dict[str, Any]:
    try:
        text = watch_page.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceAcquisitionError("SOURCE_WATCH_ENCODING_INVALID", "YouTube watch page is not UTF-8") from error
    for marker in ("ytInitialPlayerResponse =", '"ytInitialPlayerResponse":'):
        value = _raw_json_after_marker(text, marker)
        if isinstance(value, dict):
            return value
    raise SourceAcquisitionError("SOURCE_CAPTION_METADATA_MISSING", "YouTube caption metadata was not found")


def _requested_language_prefix(language: str) -> str:
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
    return aliases.get(normalized, normalized.split("-", 1)[0])


def requested_language_prefix(language: str) -> str:
    prefix = _requested_language_prefix(language)
    if not prefix or len(prefix) > 16 or re.fullmatch(r"[a-z]{2,8}", prefix) is None:
        raise SourceAcquisitionError("SOURCE_LANGUAGE_INVALID", "Requested subtitle language is invalid")
    return prefix


def _select_caption_track(player: dict[str, Any], language: str) -> dict[str, Any]:
    renderer = ((player.get("captions") or {}).get("playerCaptionsTracklistRenderer") or {})
    tracks = renderer.get("captionTracks") or []
    if not isinstance(tracks, list):
        tracks = []
    valid = [
        item
        for item in tracks
        if isinstance(item, dict)
        and isinstance(item.get("baseUrl"), str)
        and isinstance(item.get("languageCode"), str)
    ]
    prefix = requested_language_prefix(language)
    matching = [item for item in valid if str(item["languageCode"]).casefold().split("-", 1)[0] == prefix]
    if not matching:
        raise SourceAcquisitionError("SOURCE_CAPTION_LANGUAGE_UNAVAILABLE", "Requested YouTube caption language is unavailable")
    matching.sort(key=lambda item: (str(item.get("kind") or "").casefold() == "asr", str(item["languageCode"])))
    return matching[0]


def _caption_vtt_url(base_url: str) -> str:
    if not base_url or len(base_url) > MAX_CAPTION_URL_CHARS or "\x00" in base_url:
        raise SourceAcquisitionError("SOURCE_CAPTION_URL_INVALID", "YouTube caption URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(base_url)
    except ValueError as error:
        raise SourceAcquisitionError("SOURCE_CAPTION_URL_INVALID", "YouTube caption URL is invalid") from error
    host = _normalized_host(parsed)
    if host not in YOUTUBE_FETCH_HOSTS or parsed.path != "/api/timedtext" or parsed.fragment or not parsed.query:
        raise SourceAcquisitionError("SOURCE_CAPTION_URL_BLOCKED", "YouTube caption endpoint is not allowed")
    query_names = {name.casefold() for name, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)}
    suffix = "" if "fmt" in query_names else "&fmt=vtt"
    return urllib.parse.urlunsplit(("https", host, "/api/timedtext", parsed.query + suffix, ""))


def _timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{millis:03d}"


def _normalize_caption_body(body: bytes) -> bytes:
    if not body or len(body) > MAX_SUBTITLE_BYTES:
        raise SourceAcquisitionError("SOURCE_SUBTITLE_LIMIT", "YouTube subtitle response is empty or too large")
    stripped = body.lstrip(b"\xef\xbb\xbf\r\n\t ")
    if stripped.startswith(b"WEBVTT"):
        try:
            text = stripped.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError as error:
            raise SourceAcquisitionError("SOURCE_SUBTITLE_FORMAT_INVALID", "YouTube VTT is not UTF-8") from error
        if "\x00" in text or re.search(
            r"(?m)^\s*(?:\d{2,}:)?\d{2}:\d{2}\.\d{3}\s+-->\s+(?:\d{2,}:)?\d{2}:\d{2}\.\d{3}(?:\s|$)",
            text,
        ) is None:
            raise SourceAcquisitionError("SOURCE_SUBTITLE_EMPTY", "YouTube VTT contains no valid cues")
        encoded = ("WEBVTT\n\n" + text[len("WEBVTT") :].lstrip("\n")).encode("utf-8")
        if len(encoded) > MAX_SUBTITLE_BYTES:
            raise SourceAcquisitionError("SOURCE_SUBTITLE_LIMIT", "Normalized YouTube subtitles exceed the byte limit")
        return encoded
    try:
        root = ET.fromstring(body.decode("utf-8"))
    except (UnicodeDecodeError, ET.ParseError) as error:
        raise SourceAcquisitionError("SOURCE_SUBTITLE_FORMAT_INVALID", "YouTube subtitle format is invalid") from error
    lines = ["WEBVTT", ""]
    cue_count = 0
    for node in root.findall(".//text"):
        try:
            start = float(node.attrib["start"])
            duration = float(node.attrib.get("dur") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        text = html.unescape("".join(node.itertext())).replace("\r", " ").replace("\n", " ").strip()
        if not text:
            continue
        end = max(start + max(duration, 0.05), start + 0.05)
        lines.extend([f"{_timestamp(start)} --> {_timestamp(end)}", text, ""])
        cue_count += 1
    if cue_count == 0:
        raise SourceAcquisitionError("SOURCE_SUBTITLE_EMPTY", "YouTube subtitle response contains no cues")
    encoded = "\n".join(lines).encode("utf-8")
    if len(encoded) > MAX_SUBTITLE_BYTES:
        raise SourceAcquisitionError("SOURCE_SUBTITLE_LIMIT", "Normalized YouTube subtitles exceed the byte limit")
    return encoded


class YouTubeSubtitleAcquirer:
    def __init__(self, *, transport: SourceFetchTransport | None = None, timeout_seconds: float = 30.0) -> None:
        self.transport = transport or PinnedHttpsFetcher().fetch
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 60.0))

    def acquire(self, source_url: str, language: str) -> tuple[dict[str, Any], int]:
        video_id = youtube_video_id(source_url)
        watch_url = canonical_youtube_watch_url(source_url)
        watch = self.transport(watch_url, MAX_WATCH_PAGE_BYTES, self.timeout_seconds)
        if 300 <= watch.status < 400:
            raise SourceAcquisitionError("SOURCE_REDIRECT_BLOCKED", "YouTube watch redirect is blocked")
        if watch.status != 200:
            raise SourceAcquisitionError("SOURCE_WATCH_FAILED", "YouTube watch page request failed")
        if len(watch.body) > MAX_WATCH_PAGE_BYTES:
            raise SourceAcquisitionError("SOURCE_RESPONSE_LIMIT", "YouTube watch page exceeded its byte limit")
        player = _player_response(watch.body)
        track = _select_caption_track(player, language)
        caption_url = _caption_vtt_url(str(track["baseUrl"]))
        caption = self.transport(caption_url, MAX_SUBTITLE_BYTES, self.timeout_seconds)
        if 300 <= caption.status < 400:
            raise SourceAcquisitionError("SOURCE_REDIRECT_BLOCKED", "YouTube caption redirect is blocked")
        if caption.status != 200:
            raise SourceAcquisitionError("SOURCE_CAPTION_FETCH_FAILED", "YouTube caption request failed")
        vtt = _normalize_caption_body(caption.body)
        digest = hashlib.sha256(vtt).hexdigest()
        details = player.get("videoDetails") if isinstance(player.get("videoDetails"), dict) else {}
        title = str((details or {}).get("title") or "").strip()[:300]
        result = {
            "schemaVersion": 1,
            "sourceKind": "youtube_subtitles",
            "videoId": video_id,
            "title": title,
            "languageCode": str(track["languageCode"]),
            "captionKind": "automatic" if str(track.get("kind") or "").casefold() == "asr" else "manual",
            "mimeType": "text/vtt",
            "contentBase64": base64.b64encode(vtt).decode("ascii"),
            "byteLength": len(vtt),
            "sha256": digest,
        }
        return result, len(watch.body) + len(caption.body)


def authorized_youtube_sources(request: Mapping[str, Any]) -> dict[str, str]:
    candidates: list[tuple[Any, Any]] = []
    default_language = request.get("language") or "English"
    source_mode = str(request.get("source_mode") or "").strip().casefold()
    if source_mode == "url" or request.get("source_url"):
        candidates.append((request.get("source_url"), default_language))
    batch_items = request.get("batch_items")
    if isinstance(batch_items, list):
        for item in batch_items:
            if not isinstance(item, dict) or item.get("enabled") is False:
                continue
            item_mode = str(item.get("source_mode") or "").strip().casefold()
            if item_mode == "url" or item.get("source_url"):
                candidates.append((item.get("source_url"), item.get("language") or default_language))
    authorized: dict[str, str] = {}
    for raw_url, raw_language in candidates:
        if not str(raw_url or "").strip():
            continue
        video_id = youtube_video_id(str(raw_url))
        language = requested_language_prefix(str(raw_language or "English"))
        existing = authorized.get(video_id)
        if existing is not None and existing != language:
            raise SourceAcquisitionError(
                "SOURCE_LANGUAGE_CONFLICT",
                "One YouTube video was requested with conflicting subtitle languages",
            )
        authorized[video_id] = language
    return authorized


def _source_idempotency_key(task_id: str, work_unit_id: str) -> str:
    payload = f"study.source-acquisition.v1\x00{task_id}\x00{work_unit_id}\x00{SOURCE_OPERATION}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def make_source_acquisition_handler(
    *,
    task_id: str,
    task_request: Mapping[str, Any],
    operation_intent_ref: str,
    budget: BrokerBudget,
    broker: ModelTtsBroker,
    expires_at_unix_ms: int,
    transport: SourceFetchTransport | None = None,
    timeout_seconds: float = 30.0,
) -> Callable[[dict[str, Any]], Any]:
    authorized = authorized_youtube_sources(task_request)
    acquirer = YouTubeSubtitleAcquirer(transport=transport, timeout_seconds=timeout_seconds)

    def handle(payload: dict[str, Any]) -> Any:
        try:
            if int(time.time() * 1000) >= expires_at_unix_ms:
                raise SourceAcquisitionError("SOURCE_AUTHORIZATION_EXPIRED", "Source acquisition authorization expired")
            if set(payload) != {"workUnitId", "request"}:
                raise SourceAcquisitionError("SOURCE_PAYLOAD_INVALID", "Source acquisition payload shape is invalid")
            work_unit_id = str(payload.get("workUnitId") or "")
            request = payload.get("request")
            if not WORK_UNIT_PATTERN.fullmatch(work_unit_id) or not isinstance(request, dict):
                raise SourceAcquisitionError("SOURCE_PAYLOAD_INVALID", "Source acquisition work unit is invalid")
            if set(request) != {"videoId", "language", "format"} or request.get("format") != "vtt":
                raise SourceAcquisitionError("SOURCE_PAYLOAD_INVALID", "Source acquisition request is invalid")
            video_id = str(request.get("videoId") or "")
            language = requested_language_prefix(str(request.get("language") or ""))
            if YOUTUBE_VIDEO_ID.fullmatch(video_id) is None or authorized.get(video_id) != language:
                raise SourceAcquisitionError(
                    "SOURCE_NOT_AUTHORIZED",
                    "YouTube source or subtitle language is not authorized for this task",
                )
            provider_payload = {"videoId": video_id, "language": language, "format": "vtt"}
            request_bytes = len(
                json.dumps(provider_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            call = BrokerCall(
                task_id=task_id,
                work_unit_id=work_unit_id,
                capability="source",
                profile_ref=SOURCE_PROFILE_REF,
                credential_revision=0,
                operation_intent_ref=operation_intent_ref,
                idempotency_key=_source_idempotency_key(task_id, work_unit_id),
                request_payload_digest=canonical_digest(provider_payload),
                request_bytes=request_bytes,
                maximum_response_bytes=MAX_WATCH_PAGE_BYTES + MAX_SUBTITLE_BYTES,
                reserved_cost_minor_units=0,
                credential_required=False,
            )
            return broker.execute(
                call=call,
                budget=budget,
                provider_payload=provider_payload,
                sender=lambda body, _secret: (
                    *acquirer.acquire(
                        f"https://www.youtube.com/watch?v={body['videoId']}",
                        str(body["language"]),
                    ),
                    0,
                ),
            )
        except BrokerIpcError:
            raise
        except (BrokerError, SourceAcquisitionError) as error:
            raise BrokerIpcError(error.code, str(error)) from error

    return handle
