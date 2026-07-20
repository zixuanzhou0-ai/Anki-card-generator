from __future__ import annotations

import json
import math
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any


COMMAND = "parse_source_document"
SCHEMA = "study.source-parser-result"
SCHEMA_VERSION = 1
MAX_REQUEST_BYTES = 64 * 1024
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_PAGES = 512
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_PAGE_TEXT_BYTES = 1024 * 1024
MAX_OMITTED_PAGES = 256
MAX_MEDIA_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEDIA_STREAMS = 32
MAX_MEDIA_STREAM_INDEX = 65_535
MAX_MEDIA_DURATION_MS = 12 * 60 * 60 * 1000
MAX_PROBE_OUTPUT_BYTES = 1024 * 1024
SUPPORTED_SUBTITLE_CODECS = frozenset(
    {"ass", "mov_text", "ssa", "srt", "subrip", "text", "webvtt"}
)


def _failure(code: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "kind": "pdf",
        "status": "blocked",
        "parser": {"name": "pypdf", "version": "unavailable"},
        "pageCount": 0,
        "pages": [],
        "omittedPageCount": 0,
        "omittedPages": [],
        "issueCodes": [code],
    }


def _media_failure(kind: str, code: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "kind": kind,
        "status": "blocked",
        "parser": {"name": "ffmpeg-suite", "version": "sha256-bound"},
        "media": {
            "durationMs": None,
            "audioStreamCount": 0,
            "videoStreamCount": 0,
            "subtitleStreamCount": 0,
        },
        "transcript": None,
        "issueCodes": [code],
    }


def _safe_input_path(workspace: Path, input_name: str, *, kind: str) -> Path:
    expected_name = "source.pdf" if kind == "pdf" else "source.media"
    maximum_bytes = MAX_INPUT_BYTES if kind == "pdf" else MAX_MEDIA_BYTES
    if input_name != expected_name:
        raise ValueError("input name is not allowed")
    candidate = workspace / input_name
    if not candidate.is_absolute() or candidate.parent != workspace:
        raise ValueError("input escaped the task workspace")
    before = candidate.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or getattr(before, "st_file_attributes", 0) & 0x400
        or before.st_nlink != 1
        or before.st_size <= 0
        or before.st_size > maximum_bytes
    ):
        raise ValueError("input is not a bounded regular file")
    return candidate


def _media_duration_ms(probe: dict[str, Any]) -> int | None:
    values: list[Any] = []
    format_value = probe.get("format")
    if isinstance(format_value, dict):
        values.append(format_value.get("duration"))
    streams = probe.get("streams")
    if isinstance(streams, list):
        values.extend(
            value.get("duration") for value in streams if isinstance(value, dict)
        )
    for value in values:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(seconds) and 0 < seconds <= MAX_MEDIA_DURATION_MS / 1000:
            return int(round(seconds * 1000))
    return None


def parse_media(
    path: Path,
    *,
    kind: str,
    maximum_text_bytes: int,
) -> dict[str, Any]:
    try:
        if __package__:
            from .media_tool_policy import (
                MediaToolPolicyError,
                run_ffmpeg,
                run_ffprobe_bounded,
            )
        else:
            from acg.media_tool_policy import (
                MediaToolPolicyError,
                run_ffmpeg,
                run_ffprobe_bounded,
            )
    except Exception:
        return _media_failure(kind, "SOURCE_MEDIA_PARSER_UNAVAILABLE")

    try:
        completed = run_ffprobe_bounded(
            [
                "-show_entries",
                "stream=index,codec_type,codec_name,duration:stream_disposition=default:stream_tags=language:format=duration",
                "-of",
                "json",
            ],
            path,
            timeout=45,
            maximum_stdout_bytes=MAX_PROBE_OUTPUT_BYTES,
            maximum_stderr_bytes=256 * 1024,
        )
    except (MediaToolPolicyError, OSError, subprocess.TimeoutExpired):
        return _media_failure(kind, "SOURCE_MEDIA_PROBE_FAILED")
    if (
        completed.returncode != 0
        or len((completed.stdout or "").encode("utf-8")) > MAX_PROBE_OUTPUT_BYTES
        or len((completed.stderr or "").encode("utf-8")) > MAX_PROBE_OUTPUT_BYTES
    ):
        return _media_failure(kind, "SOURCE_MEDIA_PROBE_FAILED")
    try:
        probe = json.loads(completed.stdout or "{}")
    except (ValueError, RecursionError):
        return _media_failure(kind, "SOURCE_MEDIA_PROBE_FAILED")
    streams = probe.get("streams") if isinstance(probe, dict) else None
    if not isinstance(streams, list) or len(streams) > MAX_MEDIA_STREAMS:
        return _media_failure(kind, "SOURCE_MEDIA_STREAMS_INVALID")
    audio_count = 0
    video_count = 0
    subtitle_count = 0
    stream_indices: set[int] = set()
    subtitle_candidates: list[tuple[int, int, str]] = []
    for value in streams:
        if not isinstance(value, dict):
            return _media_failure(kind, "SOURCE_MEDIA_STREAMS_INVALID")
        index = value.get("index")
        stream_type = value.get("codec_type")
        codec = value.get("codec_name")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index <= MAX_MEDIA_STREAM_INDEX
            or index in stream_indices
            or stream_type not in {"audio", "video", "subtitle", "data", "attachment"}
            or (codec is not None and not isinstance(codec, str))
        ):
            return _media_failure(kind, "SOURCE_MEDIA_STREAMS_INVALID")
        stream_indices.add(index)
        if stream_type == "audio":
            audio_count += 1
        elif stream_type == "video":
            video_count += 1
        elif stream_type == "subtitle":
            subtitle_count += 1
            disposition = value.get("disposition")
            default = (
                int(disposition.get("default") == 1)
                if isinstance(disposition, dict)
                else 0
            )
            tags = value.get("tags")
            language = (
                str(tags.get("language") or "").strip().casefold()[:32]
                if isinstance(tags, dict)
                else ""
            )
            if language and any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
                for character in language
            ):
                language = ""
            if str(codec or "").casefold() in SUPPORTED_SUBTITLE_CODECS:
                english = int(language in {"en", "eng", "english"})
                subtitle_candidates.append((english * 2 + default, index, language))
    if (kind == "video" and video_count == 0) or (
        kind == "audio" and audio_count == 0
    ):
        return _media_failure(kind, "SOURCE_MEDIA_KIND_MISMATCH")
    duration_ms = _media_duration_ms(probe)
    media = {
        "durationMs": duration_ms,
        "audioStreamCount": audio_count,
        "videoStreamCount": video_count,
        "subtitleStreamCount": subtitle_count,
    }
    if not subtitle_candidates:
        result = _media_failure(
            kind,
            (
                "SOURCE_MEDIA_SUBTITLE_CODEC_UNSUPPORTED"
                if subtitle_count
                else "SOURCE_MEDIA_TRANSCRIPT_NOT_AVAILABLE"
            ),
        )
        result["media"] = media
        if duration_ms is None:
            result["issueCodes"].append("SOURCE_MEDIA_DURATION_UNKNOWN")
            result["issueCodes"] = sorted(set(result["issueCodes"]))
        return result
    _score, stream_index, language = sorted(
        subtitle_candidates,
        key=lambda value: (-value[0], value[1]),
    )[0]
    output_path = path.parent / "subtitle.vtt"
    try:
        extracted = run_ffmpeg(
            [
                "-i",
                str(path),
                "-map",
                f"0:{stream_index}",
                "-c:s",
                "webvtt",
                str(output_path),
            ],
            timeout=120,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if extracted.returncode != 0:
            return {**_media_failure(kind, "SOURCE_MEDIA_TRANSCRIPT_EXTRACTION_FAILED"), "media": media}
        before = output_path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or getattr(before, "st_file_attributes", 0) & 0x400
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > maximum_text_bytes
        ):
            return {**_media_failure(kind, "SOURCE_MEDIA_TRANSCRIPT_INVALID"), "media": media}
        raw = output_path.read_bytes()
        if len(raw) != before.st_size:
            return {**_media_failure(kind, "SOURCE_MEDIA_TRANSCRIPT_INVALID"), "media": media}
        try:
            decoded = raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            return {**_media_failure(kind, "SOURCE_MEDIA_TRANSCRIPT_INVALID"), "media": media}
        text, truncated, anomalies = _bounded_text(decoded, maximum_text_bytes)
        if truncated or anomalies or not text.strip():
            return {**_media_failure(kind, "SOURCE_MEDIA_TRANSCRIPT_INVALID"), "media": media}
        issues = ["SOURCE_MEDIA_EMBEDDED_TRANSCRIPT_EXTRACTED"]
        if duration_ms is None:
            issues.append("SOURCE_MEDIA_DURATION_UNKNOWN")
        return {
            "schema": SCHEMA,
            "schemaVersion": SCHEMA_VERSION,
            "kind": kind,
            "status": "conditional",
            "parser": {"name": "ffmpeg-suite", "version": "sha256-bound"},
            "media": media,
            "transcript": {
                "format": "webvtt",
                "text": text,
                "language": language or None,
                "streamIndex": stream_index,
            },
            "issueCodes": sorted(issues),
        }
    except (MediaToolPolicyError, OSError, subprocess.TimeoutExpired):
        return {**_media_failure(kind, "SOURCE_MEDIA_TRANSCRIPT_EXTRACTION_FAILED"), "media": media}
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass


def _bounded_text(value: str, maximum_bytes: int) -> tuple[str, bool, int]:
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    parts: list[str] = []
    anomalies = 0
    for character in normalized:
        category = unicodedata.category(character)
        if character == "\ufffd" or (
            category in {"Cc", "Cs", "Co", "Cn"} and character not in {"\n", "\t"}
        ):
            anomalies += 1
            parts.append("\ufffd")
        else:
            parts.append(character)
    cleaned = "".join(parts)
    encoded = cleaned.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return cleaned, False, anomalies
    prefix = encoded[:maximum_bytes]
    while prefix:
        try:
            return prefix.decode("utf-8"), True, anomalies
        except UnicodeDecodeError as error:
            prefix = prefix[: error.start]
    return "", True, anomalies


def _image_object_count(page: Any) -> tuple[int, bool]:
    try:
        resources = page.get("/Resources")
        if resources is None:
            return 0, False
        resources = resources.get_object()
        xobjects = resources.get("/XObject")
        if xobjects is None:
            return 0, False
        xobjects = xobjects.get_object()
        count = 0
        for index, value in enumerate(xobjects.values()):
            if index >= 4096:
                return count, True
            candidate = value.get_object()
            if candidate.get("/Subtype") == "/Image":
                count += 1
        return count, False
    except Exception:
        return 0, True


def parse_pdf(path: Path, *, maximum_pages: int, maximum_text_bytes: int) -> dict[str, Any]:
    try:
        from pypdf import PdfReader, __version__ as pypdf_version
    except Exception:
        return _failure("SOURCE_PDF_PARSER_UNAVAILABLE")

    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                if reader.decrypt("") == 0:
                    result = _failure("SOURCE_PDF_ENCRYPTED")
                    result["parser"]["version"] = str(pypdf_version)
                    return result
            except Exception:
                result = _failure("SOURCE_PDF_ENCRYPTED")
                result["parser"]["version"] = str(pypdf_version)
                return result
        page_count = len(reader.pages)
    except Exception:
        result = _failure("SOURCE_PDF_UNREADABLE")
        result["parser"]["version"] = str(pypdf_version)
        return result

    pages: list[dict[str, Any]] = []
    omitted_pages: list[int] = []
    omitted_page_count = 0
    issue_codes = {"SOURCE_PDF_LAYOUT_PARTIAL"}
    remaining = maximum_text_bytes
    inspect_count = min(page_count, maximum_pages)
    for page_index in range(inspect_count):
        page_number = page_index + 1
        if remaining <= 0:
            omitted_page_count += 1
            if len(omitted_pages) < MAX_OMITTED_PAGES:
                omitted_pages.append(page_number)
            issue_codes.add("SOURCE_PDF_TEXT_LIMIT_REACHED")
            continue
        try:
            raw_text = reader.pages[page_index].extract_text() or ""
        except Exception:
            omitted_page_count += 1
            if len(omitted_pages) < MAX_OMITTED_PAGES:
                omitted_pages.append(page_number)
            issue_codes.add("SOURCE_PDF_PAGE_UNREADABLE")
            continue
        text, truncated, anomalies = _bounded_text(
            raw_text,
            min(MAX_PAGE_TEXT_BYTES, remaining),
        )
        image_count, image_scan_partial = _image_object_count(reader.pages[page_index])
        if image_count:
            issue_codes.add("SOURCE_PDF_IMAGES_OMITTED")
        if image_scan_partial:
            issue_codes.add("SOURCE_PDF_IMAGE_SCAN_PARTIAL")
        if anomalies:
            issue_codes.add("SOURCE_PDF_CHARACTER_ANOMALIES")
        if truncated:
            issue_codes.add("SOURCE_PDF_TEXT_LIMIT_REACHED")
        pages.append(
            {
                "pageNumber": page_number,
                "text": text,
                "characterAnomalyCount": anomalies,
                "imageObjectCount": image_count,
                "textTruncated": truncated,
            }
        )
        remaining -= len(text.encode("utf-8"))
    if page_count > maximum_pages:
        issue_codes.add("SOURCE_PDF_PAGE_LIMIT_REACHED")
        omitted_page_count += page_count - maximum_pages
        remaining_samples = MAX_OMITTED_PAGES - len(omitted_pages)
        omitted_pages.extend(
            range(
                maximum_pages + 1,
                min(page_count, maximum_pages + remaining_samples) + 1,
            )
        )
    if not any(page["text"].strip() for page in pages):
        issue_codes.add("SOURCE_PDF_TEXT_LAYER_EMPTY")
        status = "blocked"
    else:
        status = "conditional"
    return {
        "schema": SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "kind": "pdf",
        "status": status,
        "parser": {"name": "pypdf", "version": str(pypdf_version)},
        "pageCount": page_count,
        "pages": pages,
        "omittedPageCount": omitted_page_count,
        "omittedPages": omitted_pages,
        "issueCodes": sorted(issue_codes),
    }


def _read_request() -> dict[str, Any]:
    source = sys.stdin.read(MAX_REQUEST_BYTES + 1)
    if not source or len(source.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError("request is missing or too large")
    value = json.loads(source)
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "kind",
        "inputName",
        "limits",
    }:
        raise ValueError("request schema is invalid")
    limits = value.get("limits")
    kind = value.get("kind")
    if (
        value.get("schemaVersion") != 1
        or kind not in {"pdf", "video", "audio"}
        or value.get("inputName") != ("source.pdf" if kind == "pdf" else "source.media")
        or not isinstance(limits, dict)
        or set(limits)
        != ({"maximumPages", "maximumTextBytes"} if kind == "pdf" else {"maximumTextBytes"})
        or (
            kind == "pdf"
            and (
                isinstance(limits.get("maximumPages"), bool)
                or not isinstance(limits.get("maximumPages"), int)
                or not 1 <= limits["maximumPages"] <= MAX_PAGES
            )
        )
        or isinstance(limits.get("maximumTextBytes"), bool)
        or not isinstance(limits.get("maximumTextBytes"), int)
        or not 1 <= limits["maximumTextBytes"] <= MAX_TEXT_BYTES
    ):
        raise ValueError("request values are invalid")
    return value


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] != COMMAND:
        raise SystemExit("source parser command is not allowed")
    try:
        request = _read_request()
        workspace = Path.cwd().absolute()
        path = _safe_input_path(workspace, request["inputName"], kind=request["kind"])
        if request["kind"] == "pdf":
            result = parse_pdf(
                path,
                maximum_pages=request["limits"]["maximumPages"],
                maximum_text_bytes=request["limits"]["maximumTextBytes"],
            )
        else:
            result = parse_media(
                path,
                kind=request["kind"],
                maximum_text_bytes=request["limits"]["maximumTextBytes"],
            )
    except Exception:
        result = (
            _failure("SOURCE_PARSER_REQUEST_FAILED")
            if "request" not in locals() or request.get("kind") == "pdf"
            else _media_failure(str(request["kind"]), "SOURCE_PARSER_REQUEST_FAILED")
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
