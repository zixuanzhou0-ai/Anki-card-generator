"""Deterministic inspection of authenticated SourceAsset snapshots."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .project_registry import ProjectRegistry, ProjectRegistryError
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_MAX_SOURCES = 64
_MAX_TEXT_BYTES = 8 * 1024 * 1024
_MAX_DIRECTORY_TEXT_BYTES = 16 * 1024 * 1024
_MAX_DIRECTORY_MANIFEST_BYTES = 64 * 1024 * 1024
_MAX_DIRECTORY_FILES = 2_048
_MAX_CONTENT_NODES = 20_000
_MAX_NODE_CHARACTERS = 4_096
_SUPPORTED_TEXT_TYPES = frozenset({"text", "markdown", "code", "html", "subtitle"})
_SOURCE_INSPECTION_COMPONENTS = {
    "cardService": "2.0.0",
    "worker": "not-invoked",
    "sourceAdapterSetDigest": hashlib.sha256(
        b"speakright.study.source-inspection.deterministic-text-v1"
    ).hexdigest(),
    "gateRuleSetVersion": "source-inspection-v1",
}


class SourceInspectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _VisibleHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag.casefold() in {
            "br",
            "p",
            "div",
            "li",
            "section",
            "article",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            if self._ignored_depth:
                self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag.casefold() in {
            "p",
            "div",
            "li",
            "section",
            "article",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _completeness(
    state: str,
    *,
    expected_units: int | None,
    processed_units: int,
    reason_codes: Sequence[str] = (),
    omitted_locators: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "state": state,
        "processedUnits": processed_units,
        "omittedLocators": [_clone(value) for value in omitted_locators],
        "reasonCodes": sorted(set(reason_codes)),
    }
    if expected_units is not None:
        result["expectedUnits"] = expected_units
    return result


def _decode_text(data: bytes, *, truncated: bool) -> tuple[str | None, str | None]:
    encoding = "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    try:
        text = data.decode(encoding, errors="strict")
    except UnicodeDecodeError as error:
        if not truncated or error.end != len(data):
            return None, "SOURCE_TEXT_ENCODING_UNSUPPORTED"
        try:
            text = data[: error.start].decode(encoding, errors="strict")
        except UnicodeDecodeError:
            return None, "SOURCE_TEXT_ENCODING_UNSUPPORTED"
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if "\x00" in text:
        return None, "SOURCE_TEXT_BINARY_CONTENT"
    return text, None


def _paragraph_ranges(text: str, *, code: bool) -> list[tuple[int, int]]:
    if not text:
        return []
    if code:
        ranges: list[tuple[int, int]] = []
        start = 0
        line_count = 0
        for match in re.finditer(r".*(?:\n|$)", text):
            if match.end() == match.start():
                continue
            line_count += 1
            if line_count >= 40:
                ranges.append((start, match.end()))
                start = match.end()
                line_count = 0
        if start < len(text):
            ranges.append((start, len(text)))
        return ranges
    ranges = []
    start: int | None = None
    cursor = 0
    for line in text.splitlines(keepends=True):
        end = cursor + len(line)
        if line.strip():
            if start is None:
                start = cursor
        elif start is not None:
            ranges.append((start, cursor))
            start = None
        cursor = end
    if start is not None:
        ranges.append((start, len(text)))
    if not ranges and text.strip():
        ranges.append((0, len(text)))
    return ranges


def _split_range(text: str, start: int, end: int) -> list[tuple[int, int]]:
    result = []
    cursor = start
    while cursor < end:
        limit = min(end, cursor + _MAX_NODE_CHARACTERS)
        if limit < end:
            window = text[cursor:limit]
            boundary = max(window.rfind("\n"), window.rfind(". "), window.rfind("。"))
            if boundary >= _MAX_NODE_CHARACTERS // 2:
                limit = cursor + boundary + 1
        if limit <= cursor:
            limit = min(end, cursor + _MAX_NODE_CHARACTERS)
        result.append((cursor, limit))
        cursor = limit
    return result


def _text_nodes(
    text: str,
    *,
    source_id: str,
    source_type: str,
    member_ref: str | None = None,
    order_offset: int = 0,
) -> tuple[list[dict[str, Any]], bool]:
    nodes: list[dict[str, Any]] = []
    for start, end in _paragraph_ranges(text, code=source_type == "code"):
        for chunk_start, chunk_end in _split_range(text, start, end):
            if len(nodes) >= _MAX_CONTENT_NODES:
                return nodes, True
            order = order_offset + len(nodes)
            node_id = (
                "node_"
                + _sha(
                    f"{source_id}:{member_ref or ''}:{order}:{chunk_start}:{chunk_end}".encode(
                        "utf-8"
                    )
                )[:40]
            )
            attributes: dict[str, str | int | bool] = {
                "textStart": chunk_start,
                "textEnd": chunk_end,
            }
            if member_ref is not None:
                attributes["memberRef"] = member_ref
            nodes.append(
                {
                    "nodeId": node_id,
                    "sourceId": source_id,
                    "order": order,
                    "kind": "code_block" if source_type == "code" else "paragraph",
                    "locator": {
                        "kind": "text_span",
                        "nodeId": node_id,
                        "start": chunk_start,
                        "end": chunk_end,
                    },
                    "extractionConfidence": 1.0 if source_type != "html" else 0.9,
                    "attributes": attributes,
                }
            )
    return nodes, False


_TIMESTAMP_RE = re.compile(
    r"(?P<start>(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3})"
)


def _timestamp_ms(value: str) -> int:
    fields = value.replace(",", ".").split(":")
    if len(fields) == 2:
        hours = 0
        minutes, seconds = fields
    else:
        hours, minutes, seconds = fields
    second, millis = seconds.split(".", 1)
    return ((int(hours) * 60 + int(minutes)) * 60 + int(second)) * 1000 + int(millis)


def _subtitle_content(
    text: str, *, source_id: str, member_ref: str | None = None
) -> tuple[str, list[dict[str, Any]], list[str]]:
    cues: list[tuple[int, int, str]] = []
    invalid = 0
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip("\ufeff ") for line in block.splitlines() if line.strip()]
        if not lines or lines[0].upper().startswith("WEBVTT"):
            continue
        timestamp_index = 0 if _TIMESTAMP_RE.search(lines[0]) else 1
        if timestamp_index >= len(lines):
            invalid += 1
            continue
        match = _TIMESTAMP_RE.search(lines[timestamp_index])
        if match is None:
            invalid += 1
            continue
        cue_text = " ".join(lines[timestamp_index + 1 :]).strip()
        if not cue_text:
            invalid += 1
            continue
        start_ms = _timestamp_ms(match.group("start"))
        end_ms = _timestamp_ms(match.group("end"))
        if end_ms <= start_ms:
            invalid += 1
            continue
        cues.append((start_ms, end_ms, cue_text))
    plain_parts: list[str] = []
    nodes: list[dict[str, Any]] = []
    cursor = 0
    for index, (start_ms, end_ms, cue_text) in enumerate(cues[:_MAX_CONTENT_NODES]):
        if plain_parts:
            plain_parts.append("\n")
            cursor += 1
        text_start = cursor
        plain_parts.append(cue_text)
        cursor += len(cue_text)
        cue_id = (
            "cue_"
            + _sha(
                f"{source_id}:{member_ref or ''}:{index}:{start_ms}:{end_ms}".encode(
                    "utf-8"
                )
            )[:40]
        )
        attributes: dict[str, str | int | bool] = {
            "textStart": text_start,
            "textEnd": cursor,
        }
        if member_ref is not None:
            attributes["memberRef"] = member_ref
        nodes.append(
            {
                "nodeId": cue_id,
                "sourceId": source_id,
                "order": index,
                "kind": "subtitle_cue",
                "locator": {
                    "kind": "subtitle",
                    "cueIds": [cue_id],
                    "startMs": start_ms,
                    "endMs": end_ms,
                },
                "extractionConfidence": 1.0,
                "attributes": attributes,
            }
        )
    issues = []
    if invalid:
        issues.append("SOURCE_SUBTITLE_CUES_OMITTED")
    if len(cues) > _MAX_CONTENT_NODES:
        issues.append("SOURCE_NODE_LIMIT_REACHED")
    return "".join(plain_parts), nodes, issues


def _visible_html(text: str) -> str:
    parser = _VisibleHtmlParser()
    parser.feed(text)
    parser.close()
    visible = "".join(parser.parts)
    visible = re.sub(r"[ \t\f\v]+", " ", visible)
    visible = re.sub(r"\n\s*\n+", "\n\n", visible)
    return visible.strip()


def _source_type_for_member(member_ref: str) -> str:
    extension = PurePosixPath(member_ref).suffix.casefold()
    if extension in {".txt", ".text"}:
        return "text"
    if extension in {".md", ".markdown", ".mdx"}:
        return "markdown"
    if extension in {".srt", ".vtt", ".ass", ".ssa"}:
        return "subtitle"
    if extension in {".html", ".htm"}:
        return "html"
    if extension in {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".swift",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".sql",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
    }:
        return "code"
    return "unknown"


def _recommended_routes(source_type: str) -> list[str]:
    if source_type == "subtitle":
        return ["reading_recognition", "listening_recognition", "chunk_collocation"]
    if source_type == "code":
        return ["procedural_decision", "error_repair", "concept_discrimination"]
    return ["fact_recall", "concept_discrimination", "application_transfer"]


class SourceInspectionRuntime:
    """Inspect immutable source snapshots without model, network, or raw-path access."""

    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        tasks: StudyTaskCoordinator,
    ) -> None:
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._tasks = tasks

    @staticmethod
    def _operation_digest(
        project_id: str,
        expected_revision: int,
        source_refs: Sequence[Mapping[str, Any]],
    ) -> str:
        return _sha(
            canonical_json_bytes(
                {
                    "schema": "study.inspect-sources.request",
                    "schemaVersion": 1,
                    "projectId": project_id,
                    "expectedProjectRevision": expected_revision,
                    "sourceRefs": [dict(value) for value in source_refs],
                    "extractorPolicy": "deterministic-text-v1",
                }
            )
        )

    def _resolve_sources(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        source_handles: Sequence[str],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        if (
            not isinstance(source_handles, Sequence)
            or isinstance(source_handles, (str, bytes))
            or not 1 <= len(source_handles) <= _MAX_SOURCES
        ):
            raise SourceInspectionError(
                "SOURCE_INSPECTION_INVALID", "sourceHandles count is invalid"
            )
        resolved = []
        seen: set[str] = set()
        for handle in source_handles:
            if not isinstance(handle, str) or not _HANDLE_RE.fullmatch(handle):
                raise SourceInspectionError(
                    "SOURCE_INSPECTION_INVALID", "sourceHandle is invalid"
                )
            ref, envelope = self._artifacts.resolve_with_ref(handle, audience)
            if ref["artifactId"] in seen:
                raise SourceInspectionError(
                    "SOURCE_INSPECTION_DUPLICATE", "sourceHandles contain a duplicate"
                )
            seen.add(ref["artifactId"])
            if (
                ref["projectId"] != project_id
                or envelope.get("payloadSchema") != "study.source-asset"
                or envelope.get("payloadSchemaVersion") != 1
                or not isinstance(envelope.get("payload"), Mapping)
            ):
                raise SourceInspectionError(
                    "SOURCE_INSPECTION_INVALID",
                    "sourceHandle is not a project SourceAsset",
                )
            resolved.append((_clone(ref), _clone(envelope)))
        resolved.sort(key=lambda item: item[0]["artifactId"].encode("utf-8"))
        return resolved

    def _bundle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        source_refs: Sequence[Mapping[str, Any]],
        operation_digest: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        subject = {
            "kind": "project_task",
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "inputArtifacts": [
                {
                    "artifactId": value["artifactId"],
                    "artifactRevision": value["artifactRevision"],
                    "artifactDigest": value["artifactDigest"],
                }
                for value in source_refs
            ],
            "sourceSnapshotDigests": [
                str(value["artifactDigest"]) for value in source_refs
            ],
            "learningContractRevision": project["learningContract"]["contractRevision"],
        }
        work, work_digest = build_work_reuse_manifest(
            action_id="inspect_source",
            subject=subject,
            component_versions=_SOURCE_INSPECTION_COMPONENTS,
            service_configurations=[],
            work_partition_policy_digest=_sha(b"study.source-inspection.partition.v1"),
        )
        capability, capability_digest = build_capability_binding(
            [
                {
                    "kind": "fixed",
                    "capabilityId": "runtime.card_service",
                    "implementationVersionOrDigest": "2.0.0",
                    "compatibilityContractVersion": "source-inspection-v1",
                }
            ]
        )
        authorization, authorization_digest = build_authorization_binding(
            audience=audience,
            service_instance_id=self._service_instance_id,
            bindings=[],
        )
        task_input, input_fingerprint = build_task_input_manifest(
            action_id="inspect_source",
            work_reuse_manifest=work,
            work_reuse_digest=work_digest,
            subject=subject,
            authorization_binding_digest=authorization_digest,
            capability_binding_digest=capability_digest,
            component_versions=_SOURCE_INSPECTION_COMPONENTS,
            service_bindings=[],
            operation_intent_digest=operation_digest,
            batch_policy_digest=_sha(b"study.source-inspection.batch.v1"),
        )
        return work, task_input, capability, authorization, input_fingerprint

    def _read_text_source(
        self,
        *,
        source_id: str,
        source_type: str,
        blob_ref: Mapping[str, Any],
        member_ref: str | None = None,
        maximum_bytes: int = _MAX_TEXT_BYTES,
    ) -> dict[str, Any]:
        size_bytes = blob_ref.get("sizeBytes")
        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
        ):
            raise SourceInspectionError(
                "SOURCE_ASSET_CORRUPT", "Source Blob size is invalid"
            )
        if size_bytes > maximum_bytes:
            return {
                "text": "",
                "nodes": [],
                "supportTier": "C",
                "status": "blocked",
                "completeness": _completeness(
                    "blocked",
                    expected_units=None,
                    processed_units=0,
                    reason_codes=["SOURCE_ASYNC_INSPECTION_REQUIRED"],
                ),
                "issueRefs": ["SOURCE_ASYNC_INSPECTION_REQUIRED"],
            }
        data, truncated = self._artifacts.read_blob_prefix(
            blob_ref, maximum_prefix_bytes=maximum_bytes
        )
        text, decode_issue = _decode_text(data, truncated=truncated)
        if text is None:
            return {
                "text": "",
                "nodes": [],
                "supportTier": "C",
                "status": "blocked",
                "completeness": _completeness(
                    "blocked",
                    expected_units=None,
                    processed_units=0,
                    reason_codes=[str(decode_issue)],
                ),
                "issueRefs": [str(decode_issue)],
            }
        html_partial = source_type == "html"
        if source_type == "html":
            text = _visible_html(text)
        if source_type == "subtitle":
            plain, nodes, subtitle_issues = _subtitle_content(
                text, source_id=source_id, member_ref=member_ref
            )
            if not nodes:
                return {
                    "text": "",
                    "nodes": [],
                    "supportTier": "C",
                    "status": "blocked",
                    "completeness": _completeness(
                        "blocked",
                        expected_units=None,
                        processed_units=0,
                        reason_codes=["SOURCE_SUBTITLE_UNREADABLE"],
                    ),
                    "issueRefs": ["SOURCE_SUBTITLE_UNREADABLE"],
                }
            issues = list(subtitle_issues)
            if truncated:
                issues.append("SOURCE_TEXT_LIMIT_REACHED")
            partial = bool(issues)
            return {
                "text": plain,
                "nodes": nodes,
                "supportTier": "B" if partial else "A",
                "status": "conditional" if partial else "ready",
                "completeness": _completeness(
                    "partial_declared" if partial else "complete",
                    expected_units=len(nodes) if not truncated else None,
                    processed_units=len(nodes),
                    reason_codes=issues,
                ),
                "issueRefs": sorted(set(issues)),
            }
        nodes, node_limit = _text_nodes(
            text,
            source_id=source_id,
            source_type=source_type,
            member_ref=member_ref,
        )
        issues = []
        if truncated:
            issues.append("SOURCE_TEXT_LIMIT_REACHED")
        if node_limit:
            issues.append("SOURCE_NODE_LIMIT_REACHED")
        if html_partial:
            issues.append("SOURCE_HTML_STRUCTURE_PARTIAL")
        if not nodes and text.strip():
            issues.append("SOURCE_NODE_EXTRACTION_EMPTY")
        if not text.strip():
            issues.append("SOURCE_TEXT_EMPTY")
        blocked = not nodes
        partial = bool(issues)
        return {
            "text": text,
            "nodes": nodes,
            "supportTier": "C" if blocked else ("B" if partial else "A"),
            "status": "blocked" if blocked else ("conditional" if partial else "ready"),
            "completeness": _completeness(
                (
                    "blocked"
                    if blocked
                    else ("partial_declared" if partial else "complete")
                ),
                expected_units=len(nodes) if not truncated and not node_limit else None,
                processed_units=len(nodes),
                reason_codes=issues,
            ),
            "issueRefs": sorted(set(issues)),
        }

    def _inspect_directory(
        self, *, source_id: str, manifest_blob_ref: Mapping[str, Any]
    ) -> dict[str, Any]:
        manifest_size = manifest_blob_ref.get("sizeBytes")
        if (
            isinstance(manifest_size, bool)
            or not isinstance(manifest_size, int)
            or manifest_size < 0
        ):
            raise SourceInspectionError(
                "SOURCE_DIRECTORY_MANIFEST_CORRUPT",
                "Directory snapshot manifest size is invalid",
            )
        if manifest_size > _MAX_DIRECTORY_MANIFEST_BYTES:
            return {
                "text": "",
                "nodes": [],
                "supportTier": "C",
                "status": "blocked",
                "completeness": _completeness(
                    "blocked",
                    expected_units=None,
                    processed_units=0,
                    reason_codes=["SOURCE_ASYNC_INSPECTION_REQUIRED"],
                ),
                "issueRefs": ["SOURCE_ASYNC_INSPECTION_REQUIRED"],
            }
        manifest_bytes, truncated = self._artifacts.read_blob_prefix(
            manifest_blob_ref,
            maximum_prefix_bytes=_MAX_DIRECTORY_MANIFEST_BYTES,
        )
        if truncated:
            return {
                "text": "",
                "nodes": [],
                "supportTier": "C",
                "status": "blocked",
                "completeness": _completeness(
                    "blocked",
                    expected_units=None,
                    processed_units=0,
                    reason_codes=["SOURCE_DIRECTORY_MANIFEST_TOO_LARGE"],
                ),
                "issueRefs": ["SOURCE_DIRECTORY_MANIFEST_TOO_LARGE"],
            }
        try:
            manifest = json.loads(manifest_bytes)
        except (TypeError, ValueError) as error:
            raise SourceInspectionError(
                "SOURCE_DIRECTORY_MANIFEST_CORRUPT",
                "Directory snapshot manifest is not valid JSON",
            ) from error
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"schema", "schemaVersion", "entries"}
            or manifest.get("schema") != "study.directory-snapshot"
            or manifest.get("schemaVersion") != 1
            or not isinstance(manifest.get("entries"), list)
        ):
            raise SourceInspectionError(
                "SOURCE_DIRECTORY_MANIFEST_CORRUPT",
                "Directory snapshot manifest schema is invalid",
            )
        entries = manifest["entries"]
        relative_names: list[str] = []
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"relativeLocator", "blobRef"}
                or not isinstance(entry.get("relativeLocator"), str)
                or not isinstance(entry.get("blobRef"), dict)
            ):
                raise SourceInspectionError(
                    "SOURCE_DIRECTORY_MANIFEST_CORRUPT",
                    "Directory snapshot entry is invalid",
                )
            relative = PurePosixPath(entry["relativeLocator"])
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise SourceInspectionError(
                    "SOURCE_DIRECTORY_MANIFEST_CORRUPT",
                    "Directory snapshot entry escaped its root",
                )
            relative_names.append(entry["relativeLocator"])
        if relative_names != sorted(relative_names) or len(relative_names) != len(
            set(relative_names)
        ):
            raise SourceInspectionError(
                "SOURCE_DIRECTORY_MANIFEST_CORRUPT",
                "Directory snapshot entries are not canonical",
            )
        combined: list[str] = []
        nodes: list[dict[str, Any]] = []
        cursor = 0
        processed_files = 0
        issue_refs: list[str] = []
        omitted: list[dict[str, Any]] = []
        remaining_bytes = _MAX_DIRECTORY_TEXT_BYTES
        for index, entry in enumerate(entries):
            relative = entry["relativeLocator"]
            source_type = _source_type_for_member(relative)
            if (
                index >= _MAX_DIRECTORY_FILES
                or source_type not in _SUPPORTED_TEXT_TYPES
                or remaining_bytes <= 0
            ):
                if len(omitted) < 256:
                    omitted.append(
                        {
                            "kind": "code",
                            "pathRef": relative,
                            "startLine": 1,
                            "endLine": 1,
                        }
                    )
                if index >= _MAX_DIRECTORY_FILES:
                    issue_refs.append("SOURCE_DIRECTORY_FILE_LIMIT_REACHED")
                elif remaining_bytes <= 0:
                    issue_refs.append("SOURCE_DIRECTORY_TEXT_LIMIT_REACHED")
                else:
                    issue_refs.append("SOURCE_MEMBER_UNSUPPORTED")
                continue
            extracted = self._read_text_source(
                source_id=source_id,
                source_type=source_type,
                blob_ref=entry["blobRef"],
                member_ref=relative,
                maximum_bytes=min(_MAX_TEXT_BYTES, remaining_bytes),
            )
            issue_refs.extend(extracted["issueRefs"])
            if not extracted["nodes"]:
                if len(omitted) < 256:
                    omitted.append(
                        {
                            "kind": "code",
                            "pathRef": relative,
                            "startLine": 1,
                            "endLine": 1,
                        }
                    )
                continue
            text = extracted["text"]
            if combined:
                combined.append("\n\n")
                cursor += 2
            for node in extracted["nodes"]:
                adjusted = _clone(node)
                adjusted["order"] = len(nodes)
                attributes = adjusted["attributes"]
                attributes["textStart"] = int(attributes["textStart"]) + cursor
                attributes["textEnd"] = int(attributes["textEnd"]) + cursor
                if adjusted["locator"]["kind"] == "text_span":
                    adjusted["locator"]["start"] += cursor
                    adjusted["locator"]["end"] += cursor
                nodes.append(adjusted)
                if len(nodes) >= _MAX_CONTENT_NODES:
                    issue_refs.append("SOURCE_NODE_LIMIT_REACHED")
                    break
            combined.append(text)
            cursor += len(text)
            remaining_bytes -= len(text.encode("utf-8"))
            processed_files += 1
            if len(nodes) >= _MAX_CONTENT_NODES:
                break
        if processed_files < len(entries) and not issue_refs:
            issue_refs.append("SOURCE_DIRECTORY_PARTIAL")
        issue_refs = sorted(set(issue_refs))
        if not nodes:
            state, tier, status = "blocked", "C", "blocked"
        elif processed_files == len(entries) and not issue_refs:
            state, tier, status = "complete", "A", "ready"
        else:
            state, tier, status = "partial_declared", "B", "conditional"
        return {
            "text": "".join(combined),
            "nodes": nodes,
            "supportTier": tier,
            "status": status,
            "completeness": _completeness(
                state,
                expected_units=len(entries),
                processed_units=processed_files,
                reason_codes=issue_refs,
                omitted_locators=omitted,
            ),
            "issueRefs": issue_refs,
        }

    def _inspect_payload(self, source: Mapping[str, Any]) -> dict[str, Any]:
        source_id = source.get("sourceId")
        source_type = source.get("sourceType")
        representations = source.get("representations")
        if (
            not isinstance(source_id, str)
            or not isinstance(source_type, str)
            or not isinstance(representations, list)
            or len(representations) != 1
            or not isinstance(representations[0], dict)
            or not isinstance(representations[0].get("blobRef"), dict)
        ):
            raise SourceInspectionError(
                "SOURCE_ASSET_CORRUPT", "SourceAsset payload is invalid"
            )
        if source_type == "directory_manifest":
            return self._inspect_directory(
                source_id=source_id,
                manifest_blob_ref=representations[0]["blobRef"],
            )
        if source_type not in _SUPPORTED_TEXT_TYPES:
            return {
                "text": "",
                "nodes": [],
                "supportTier": "C",
                "status": "blocked",
                "completeness": _completeness(
                    "blocked",
                    expected_units=1,
                    processed_units=0,
                    reason_codes=["SOURCE_PARSER_NOT_AVAILABLE"],
                ),
                "issueRefs": ["SOURCE_PARSER_NOT_AVAILABLE"],
            }
        return self._read_text_source(
            source_id=source_id,
            source_type=source_type,
            blob_ref=representations[0]["blobRef"],
        )

    def _publish_source_inspection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        project_revision: int,
        source_ref: Mapping[str, Any],
        source_envelope: Mapping[str, Any],
        input_fingerprint: str,
        operation_digest: str,
        index: int,
    ) -> str:
        source = source_envelope["payload"]
        extracted = self._inspect_payload(source)
        representation_refs: list[dict[str, Any]] = []
        if extracted["nodes"]:
            text_blob = self._artifacts.put_blob(
                extracted["text"].encode("utf-8"),
                media_type="text/plain",
            )
            representation_id = (
                "representation_"
                + _sha(f"{operation_digest}:{index}:representation".encode("ascii"))[
                    :40
                ]
            )
            representation_payload = {
                "representationId": representation_id,
                "sourceId": source["sourceId"],
                "sourceRef": dict(source_ref),
                "kind": (
                    "subtitle_cues"
                    if source["sourceType"] == "subtitle"
                    else "plain_text"
                ),
                "plainTextBlobRef": text_blob,
                "contentNodes": extracted["nodes"],
                "extractor": {
                    "component": "source-inspection",
                    "version": "1.0.0",
                },
                "completeness": extracted["completeness"],
                "issueRefs": extracted["issueRefs"],
            }
            publication = self._artifacts.publish_idempotent(
                audience=audience,
                project_id=project_id,
                project_revision=project_revision,
                artifact_id=representation_id,
                artifact_revision=1,
                payload_schema="study.source-representation",
                payload_schema_version=1,
                payload=representation_payload,
                producer={"component": "source-inspection", "version": "1.0.0"},
                parents=[source_ref],
                input_fingerprint=input_fingerprint,
                completeness=extracted["completeness"],
                issue_refs=extracted["issueRefs"],
            )
            representation_refs.append(dict(publication.artifact_ref))
        detail_id = (
            "inspection_source_"
            + _sha(f"{operation_digest}:{index}:detail".encode("ascii"))[:40]
        )
        detail_payload = {
            "sourceId": source["sourceId"],
            "sourceRef": dict(source_ref),
            "sourceRevision": source["sourceRevision"],
            "sourceType": source["sourceType"],
            "contentSha256": source["contentSha256"],
            "sourceIdentity": source["sourceIdentity"],
            "status": extracted["status"],
            "supportTier": extracted["supportTier"],
            "completeness": extracted["completeness"],
            "representationRefs": representation_refs,
            "contentNodeCount": len(extracted["nodes"]),
            "recommendedRoutes": (
                _recommended_routes(str(source["sourceType"]))
                if extracted["nodes"]
                else []
            ),
            "issueRefs": extracted["issueRefs"],
        }
        detail = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=project_revision,
            artifact_id=detail_id,
            artifact_revision=1,
            payload_schema="study.source-inspection",
            payload_schema_version=1,
            payload=detail_payload,
            producer={"component": "source-inspection", "version": "1.0.0"},
            parents=[source_ref, *representation_refs],
            input_fingerprint=input_fingerprint,
            completeness=extracted["completeness"],
            issue_refs=extracted["issueRefs"],
        )
        return detail.handle

    def _publish_summary(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        project_revision: int,
        detail_handles: Sequence[str],
        input_fingerprint: str,
        operation_digest: str,
        task_id: str,
    ) -> str:
        detail_refs: list[dict[str, Any]] = []
        source_refs: list[dict[str, Any]] = []
        representation_refs: list[dict[str, Any]] = []
        support_tiers: dict[str, str] = {}
        issue_refs: list[str] = []
        processed = 0
        omitted: list[dict[str, Any]] = []
        for handle in detail_handles:
            ref, envelope = self._artifacts.resolve_with_ref(handle, audience)
            if envelope.get("payloadSchema") != "study.source-inspection":
                raise SourceInspectionError(
                    "SOURCE_INSPECTION_CORRUPT", "Task detail result is invalid"
                )
            payload = envelope["payload"]
            detail_refs.append(ref)
            source_refs.append(_clone(payload["sourceRef"]))
            representation_refs.extend(_clone(payload["representationRefs"]))
            support_tiers[str(payload["sourceId"])] = str(payload["supportTier"])
            issue_refs.extend(payload["issueRefs"])
            if payload["status"] != "blocked":
                processed += 1
            elif len(omitted) < 64:
                omitted.append(
                    {
                        "kind": "text_span",
                        "nodeId": str(payload["sourceId"]),
                        "start": 0,
                        "end": 0,
                    }
                )
        expected = len(detail_refs)
        if processed == expected and not issue_refs:
            state = "complete"
        elif processed == 0:
            state = "blocked"
        else:
            state = "partial_declared"
        completeness = _completeness(
            state,
            expected_units=expected,
            processed_units=processed,
            reason_codes=issue_refs,
            omitted_locators=omitted,
        )
        inspection_id = "inspection_" + operation_digest[:40]
        payload = {
            "inspectionId": inspection_id,
            "taskId": task_id,
            "resultingProjectRevision": project_revision + 1,
            "sourceRefs": source_refs,
            "completeness": completeness,
            "representationRefs": representation_refs,
            "sourceInspectionRefs": detail_refs,
            "supportTiers": support_tiers,
            "issueRefs": sorted(set(issue_refs)),
        }
        publication = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=project_revision,
            artifact_id=inspection_id,
            artifact_revision=1,
            payload_schema="study.inspection",
            payload_schema_version=1,
            payload=payload,
            producer={"component": "source-inspection", "version": "1.0.0"},
            parents=detail_refs,
            input_fingerprint=input_fingerprint,
            completeness=completeness,
            issue_refs=sorted(set(issue_refs)),
        )
        return publication.handle

    def _public_result(
        self,
        *,
        audience: ArtifactAudienceBinding,
        committed: Mapping[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        inspection_handle: str | None = None
        inspection_payload: Mapping[str, Any] | None = None
        source_rows = []
        for ref in committed["artifactRefs"]:
            envelope = self._artifacts.verify_ref(ref, audience)
            schema = envelope.get("payloadSchema")
            if schema == "study.inspection":
                inspection_handle = self._artifacts.issue_handle(ref, audience)
                inspection_payload = envelope["payload"]
            elif schema == "study.source-inspection":
                payload = envelope["payload"]
                source_rows.append(
                    {
                        "sourceId": payload["sourceId"],
                        "sourceRevision": payload["sourceRevision"],
                        "sourceType": payload["sourceType"],
                        "contentSha256": payload["contentSha256"],
                        "identity": {
                            "stable": bool(payload["sourceIdentity"]["stable"]),
                            "identityMethod": payload["sourceIdentity"][
                                "identityMethod"
                            ],
                        },
                        "status": payload["status"],
                        "supportTier": payload["supportTier"],
                        "representationCount": len(payload["representationRefs"]),
                        "contentNodeCount": payload["contentNodeCount"],
                        "completeness": {
                            "state": payload["completeness"]["state"],
                            "expectedUnits": payload["completeness"].get(
                                "expectedUnits"
                            ),
                            "processedUnits": payload["completeness"]["processedUnits"],
                            "omittedCount": len(
                                payload["completeness"]["omittedLocators"]
                            ),
                            "reasonCodes": payload["completeness"]["reasonCodes"],
                        },
                        "recommendedRoutes": payload["recommendedRoutes"],
                        "issueCodes": payload["issueRefs"],
                    }
                )
        if inspection_handle is None or inspection_payload is None:
            raise SourceInspectionError(
                "SOURCE_INSPECTION_CORRUPT", "Inspection result is missing its summary"
            )
        source_rows.sort(key=lambda value: value["sourceId"].encode("utf-8"))
        completeness = inspection_payload["completeness"]
        next_action = (
            "discover_candidates"
            if completeness["processedUnits"] > 0
            else "resolve_issue"
        )
        return {
            "schemaVersion": 1,
            "projectId": committed["projectId"],
            "projectRevision": committed["projectRevision"],
            "artifactStage": committed["artifactStage"],
            "taskId": task_id,
            "inspectionHandle": inspection_handle,
            "completeness": {
                "state": completeness["state"],
                "expectedSources": completeness.get("expectedUnits"),
                "processedSources": completeness["processedUnits"],
                "omittedSources": len(completeness["omittedLocators"]),
                "reasonCodes": completeness["reasonCodes"],
            },
            "sources": source_rows,
            "nextAction": next_action,
        }

    def start_inspection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        source_handles: Sequence[str],
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            raise SourceInspectionError(
                "SOURCE_INSPECTION_INVALID", "idempotencyKey is invalid"
            )
        if (
            isinstance(expected_project_revision, bool)
            or not isinstance(expected_project_revision, int)
            or expected_project_revision < 1
        ):
            raise SourceInspectionError(
                "SOURCE_INSPECTION_INVALID", "expectedProjectRevision is invalid"
            )
        resolved = self._resolve_sources(
            audience=audience,
            project_id=project_id,
            source_handles=source_handles,
        )
        source_refs = [item[0] for item in resolved]
        operation_digest = self._operation_digest(
            project_id, expected_project_revision, source_refs
        )
        operation_id = "inspect:" + idempotency_key
        prior = self._projects.get_operation_result(
            audience=audience,
            project_id=project_id,
            operation_id=operation_id,
            operation_digest=operation_digest,
        )
        if prior is not None:
            return self._public_result(
                audience=audience,
                committed=prior,
                task_id=str(prior["taskId"]),
            )
        project = self._projects.get_project(project_id, audience)
        if project["projectRevision"] != expected_project_revision:
            raise SourceInspectionError(
                "PROJECT_REVISION_CONFLICT",
                "Project revision changed before source inspection",
            )
        if project["workflow"]["artifactStage"] != "sources_ready":
            raise SourceInspectionError(
                "SOURCE_INSPECTION_STAGE_CONFLICT",
                "Project does not have registered sources ready for inspection",
            )
        work, task_input, capability, authorization, input_fingerprint = self._bundle(
            audience=audience,
            project=project,
            source_refs=source_refs,
            operation_digest=operation_digest,
        )
        task_id = "task_inspect_" + operation_digest[:40]
        work_units = [
            {"workUnitId": f"inspect-{index:04d}", "phase": "source_inspection"}
            for index in range(len(resolved))
        ]
        work_units.append(
            {"workUnitId": "inspection-summary", "phase": "source_inspection"}
        )
        try:
            task = self._tasks.create_task(
                audience=audience,
                work_reuse_manifest=work,
                task_input_manifest=task_input,
                capability_binding=capability,
                authorization_binding=authorization,
                work_units=work_units,
                _task_id=task_id,
            )
        except StudyTaskError as error:
            if error.code != "TASK_ALREADY_EXISTS":
                raise SourceInspectionError(error.code, error.message) from error
            task = self._tasks.get_task(task_id, audience)
            if task.get("inputFingerprint") != input_fingerprint:
                raise SourceInspectionError(
                    "TASK_INPUT_MISMATCH", "Recoverable inspection task input changed"
                )
        if task["state"] not in {"queued", "running", "succeeded"}:
            raise SourceInspectionError(
                "TASK_RECOVERY_REQUIRED",
                "Source inspection task requires explicit recovery",
            )
        try:
            if task["state"] != "succeeded":
                if task["state"] == "queued":
                    task = self._tasks.start_task(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="start-" + operation_digest[:40],
                    )
                detail_handles: list[str] = []
                for index, (source_ref, source_envelope) in enumerate(resolved):
                    unit_id = f"inspect-{index:04d}"
                    task = self._tasks.get_task(task_id, audience)
                    unit = next(
                        item
                        for item in task["workUnits"]
                        if item["workUnitId"] == unit_id
                    )
                    if unit["state"] == "completed":
                        detail_handles.extend(unit["resultHandles"])
                        continue
                    if unit["state"] in {"pending", "failed"}:
                        task = self._tasks.begin_work_unit(
                            task_id,
                            audience,
                            expected_revision=task["taskRevision"],
                            operation_id=f"begin-{operation_digest[:32]}-{index}",
                            work_unit_id=unit_id,
                        )
                    elif unit["state"] != "active":
                        raise SourceInspectionError(
                            "TASK_RECOVERY_REQUIRED",
                            "Source inspection work unit is not recoverable",
                        )
                    detail_handle = self._publish_source_inspection(
                        audience=audience,
                        project_id=project_id,
                        project_revision=expected_project_revision,
                        source_ref=source_ref,
                        source_envelope=source_envelope,
                        input_fingerprint=input_fingerprint,
                        operation_digest=operation_digest,
                        index=index,
                    )
                    task = self._tasks.get_task(task_id, audience)
                    self._tasks.complete_work_unit(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id=f"complete-{operation_digest[:29]}-{index}",
                        work_unit_id=unit_id,
                        result_handles=[detail_handle],
                    )
                    detail_handles.append(detail_handle)
                task = self._tasks.get_task(task_id, audience)
                summary_unit = next(
                    item
                    for item in task["workUnits"]
                    if item["workUnitId"] == "inspection-summary"
                )
                if summary_unit["state"] == "completed":
                    summary_handle = summary_unit["resultHandles"][0]
                else:
                    if summary_unit["state"] in {"pending", "failed"}:
                        task = self._tasks.begin_work_unit(
                            task_id,
                            audience,
                            expected_revision=task["taskRevision"],
                            operation_id="begin-summary-" + operation_digest[:32],
                            work_unit_id="inspection-summary",
                        )
                    elif summary_unit["state"] != "active":
                        raise SourceInspectionError(
                            "TASK_RECOVERY_REQUIRED",
                            "Inspection summary work unit is not recoverable",
                        )
                    summary_handle = self._publish_summary(
                        audience=audience,
                        project_id=project_id,
                        project_revision=expected_project_revision,
                        detail_handles=detail_handles,
                        input_fingerprint=input_fingerprint,
                        operation_digest=operation_digest,
                        task_id=task_id,
                    )
                    task = self._tasks.get_task(task_id, audience)
                    self._tasks.complete_work_unit(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="complete-summary-" + operation_digest[:29],
                        work_unit_id="inspection-summary",
                        result_handles=[summary_handle],
                    )
                task = self._tasks.get_task(task_id, audience)
                if task["state"] == "running":
                    task = self._tasks.succeed_task(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="succeed-" + operation_digest[:38],
                    )
            final_task = self._tasks.get_task(task_id, audience)
            result_handles = list(final_task["resultHandles"])
            artifact_refs: list[dict[str, Any]] = []
            artifact_handles: list[str] = []
            next_action = "resolve_issue"
            for handle in result_handles:
                ref, envelope = self._artifacts.resolve_with_ref(handle, audience)
                artifact_refs.append(ref)
                artifact_handles.append(handle)
                if envelope.get("payloadSchema") == "study.source-inspection":
                    for representation_ref in envelope["payload"]["representationRefs"]:
                        artifact_refs.append(_clone(representation_ref))
                        artifact_handles.append(
                            self._artifacts.issue_handle(representation_ref, audience)
                        )
                elif envelope.get("payloadSchema") == "study.inspection":
                    if envelope["payload"]["completeness"]["processedUnits"] > 0:
                        next_action = "discover_candidates"
            paired = sorted(
                zip(artifact_refs, artifact_handles, strict=True),
                key=lambda pair: pair[0]["artifactId"].encode("utf-8"),
            )
            committed = self._projects.commit_artifact_stage(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                operation_id=operation_id,
                operation_digest=operation_digest,
                task_id=task_id,
                artifact_stage="sources_ready",
                artifact_refs=[pair[0] for pair in paired],
                artifact_handles=[pair[1] for pair in paired],
                primary_action_id=next_action,
            )
            return self._public_result(
                audience=audience, committed=committed, task_id=task_id
            )
        except (
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskManifestError,
            SourceInspectionError,
        ) as error:
            try:
                current = self._tasks.get_task(task_id, audience)
                if current["state"] == "running":
                    preserved = [
                        handle
                        for unit in current["workUnits"]
                        if unit["state"] == "completed"
                        for handle in unit["resultHandles"]
                    ]
                    self._tasks.fail_task(
                        task_id,
                        audience,
                        expected_revision=current["taskRevision"],
                        operation_id="fail-" + operation_digest[:40],
                        code=(
                            "ARTIFACT_CORRUPT"
                            if isinstance(error, ArtifactRegistryError)
                            else "SOURCE_UNREADABLE"
                        ),
                        stage="source_inspection",
                        retryable=False,
                        remote_cost_state="none",
                        retry_scope="item",
                        authorization_state="not_required",
                        preserved_artifact_handles=preserved,
                        required_action="resolve_issue",
                    )
            except (ArtifactRegistryError, StudyTaskError):
                pass
            if isinstance(error, SourceInspectionError):
                raise
            raise SourceInspectionError(
                getattr(error, "code", "SOURCE_INSPECTION_FAILED"),
                getattr(error, "message", "Source inspection failed safely"),
            ) from error

    def get_inspection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        inspection_handle: str,
    ) -> dict[str, Any]:
        if not isinstance(inspection_handle, str) or not _HANDLE_RE.fullmatch(
            inspection_handle
        ):
            raise SourceInspectionError(
                "SOURCE_INSPECTION_INVALID", "inspectionHandle is invalid"
            )
        ref, envelope = self._artifacts.resolve_with_ref(inspection_handle, audience)
        if envelope.get("payloadSchema") != "study.inspection":
            raise SourceInspectionError(
                "SOURCE_INSPECTION_INVALID", "handle is not an InspectionArtifact"
            )
        committed = {
            "projectId": ref["projectId"],
            "projectRevision": envelope["payload"]["resultingProjectRevision"],
            "artifactStage": "sources_ready",
            "taskId": envelope["payload"]["taskId"],
            "artifactRefs": [
                *envelope["payload"]["sourceInspectionRefs"],
                ref,
            ],
            "artifactHandles": [],
        }
        return self._public_result(
            audience=audience,
            committed=committed,
            task_id=str(envelope["payload"]["taskId"]),
        )


__all__ = ["SourceInspectionError", "SourceInspectionRuntime"]
