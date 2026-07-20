from __future__ import annotations

import json
import stat
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


def _safe_input_path(workspace: Path, input_name: str) -> Path:
    if input_name != "source.pdf":
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
        or before.st_size > MAX_INPUT_BYTES
    ):
        raise ValueError("input is not a bounded regular file")
    return candidate


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
    if (
        value.get("schemaVersion") != 1
        or value.get("kind") != "pdf"
        or value.get("inputName") != "source.pdf"
        or not isinstance(limits, dict)
        or set(limits) != {"maximumPages", "maximumTextBytes"}
        or isinstance(limits.get("maximumPages"), bool)
        or not isinstance(limits.get("maximumPages"), int)
        or not 1 <= limits["maximumPages"] <= MAX_PAGES
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
        path = _safe_input_path(workspace, request["inputName"])
        result = parse_pdf(
            path,
            maximum_pages=request["limits"]["maximumPages"],
            maximum_text_bytes=request["limits"]["maximumTextBytes"],
        )
    except Exception:
        result = _failure("SOURCE_PARSER_REQUEST_FAILED")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
