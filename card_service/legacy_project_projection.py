from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactPublication,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
    validate_persistable_json,
)


MAX_PROJECTION_BYTES = 16 * 1024 * 1024
MAX_PROJECTION_NODES = 200_000
MAX_PROJECTION_DEPTH = 64
MAX_RESOURCE_SLOTS = 4_096
MAX_REMOVED_FIELDS = 4_096
MAX_SUPPORT_REFS = 4_096
MAX_SAFE_INTEGER = 9_007_199_254_740_991

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//)")
_WINDOWS_DRIVE_RELATIVE_RE = re.compile(r"^[A-Za-z]:")
_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_EMBEDDED_URL_RE = re.compile(r"(?:https?://|file://|(?<!:)//)[^\s<>]+", re.IGNORECASE)
_UNSUPPORTED_RESOURCE_SCHEMES = frozenset(
    {"blob", "data", "file", "ftp", "ftps", "gs", "mailto", "s3", "scp", "ssh"}
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}\b", re.IGNORECASE),
)

_RESOURCE_KINDS = frozenset(
    {"source_file", "source_directory", "output_directory", "media_file", "source_network"}
)
_LOCAL_RESOURCE_KINDS = _RESOURCE_KINDS - {"source_network"}
_SUPPORT_SCHEMAS = {
    "sourceAssetRefs": "study.source-asset",
    "mediaLedgerRef": "study.media-ledger",
    "reliabilityManifestRef": "study.reliability-manifest",
    "learningPointInventoryRef": "study.learning-point-inventory",
    "generationDiagnosticsRef": "study.generation-diagnostics",
}

_PROJECT_REQUIRED_FIELDS = frozenset(
    {"id", "title", "video_path", "subtitle_path", "language", "level", "content_toggles", "card_types", "segments", "created_at"}
)
_PROJECT_ALLOWED_FIELDS = frozenset(
    {
        "schema_version", "id", "title", "source_mode", "source_url", "source_info",
        "video_path", "subtitle_path", "document_path", "language", "level_mode", "level",
        "collection_levels", "template_id", "card_style", "review_density", "content_toggles",
        "language_focus", "document_focus", "document_study_mode", "document_answer_language",
        "document_depth", "document_answer_length", "study_depth", "selection_strategy",
        "material_context", "card_types", "max_segments", "auto_max_segments",
        "skip_video_slicing", "batch_enabled", "batch_items", "quality_funnel",
        "card_generation_diagnostics", "reliability_manifest", "learning_point_inventory",
        "generated_learning_point_ids", "generated_document_point_ids", "source_fingerprint",
        "tts_semantic_verification", "segments", "warnings", "error_code", "model_error_code",
        "model_stage", "model_retryable", "stage", "retryable", "fallbacks", "warning",
        "created_at", "url_import_mode", "batch_summary", "review_basis",
        "ai_reviewed_source_count", "ai_reviewed_candidate_count", "local_candidate_count",
    }
)
_REMOVED_CONFIGURATION_KEYS = frozenset(
    {"apiconfig", "ttsconfig", "aimodelprovider", "aimodelname", "servicebindings", "credentialref", "profileref"}
)
_SECRET_KEY_PARTS = (
    "apikey", "authorization", "accesstoken", "refreshtoken", "password", "secret",
    "credential", "cookie", "oauth", "bearertoken", "clientsecret",
)
_SECRET_EXACT_KEYS = frozenset({"apikey", "authorization", "cookie", "password", "secret", "token"})


class LegacyProjectProjectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LegacyResourceBinding:
    """Trusted binding supplied by the resource broker; raw value digest is never persisted."""

    slot_id: str
    json_pointer: str
    kind: str
    internal_resource_binding_id: str
    resource_revision_digest: str
    resource_value_digest: str
    canonical_request_digest: str | None = None
    display_origin: str | None = None
    query_redaction_digest: str | None = None


LEGACY_PROJECT_PROJECTION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:speakright:schema:legacy.project.nonsecret.v1",
    "title": "Sanitized legacy Project projection",
    "type": "object",
    "additionalProperties": False,
    "required": ["projectionSchema", "projectionSchemaVersion", "project", "resourceSlots"],
    "properties": {
        "projectionSchema": {"const": "legacy.project.nonsecret.v1"},
        "projectionSchemaVersion": {"const": 1},
        "project": {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(_PROJECT_REQUIRED_FIELDS),
            "properties": {key: {} for key in sorted(_PROJECT_ALLOWED_FIELDS)},
        },
        "resourceSlots": {"type": "array", "maxItems": MAX_RESOURCE_SLOTS},
    },
}
LEGACY_PROJECT_PROJECTION_SCHEMA_SHA256 = hashlib.sha256(
    canonical_json_bytes(LEGACY_PROJECT_PROJECTION_SCHEMA)
).hexdigest()


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _pointer(parts: tuple[str, ...]) -> str:
    escaped = [part.replace("~", "~0").replace("/", "~1") for part in parts]
    return "#/" + "/".join(escaped)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", f"{label} is invalid")
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", f"{label} must be a lowercase SHA-256 digest")
    return value


def _looks_like_network_location(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith("//") and not stripped.startswith("\\\\"):
        return True
    try:
        parsed = urllib.parse.urlsplit(stripped)
    except ValueError:
        return False
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)


def _is_redacted_display_origin(value: Any) -> bool:
    if not isinstance(value, str) or not value or any(
        character.isspace() or ord(character) < 0x20 for character in value
    ):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    host = parsed.hostname
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and isinstance(host, str)
        and bool(host)
        and not any(character.isspace() or ord(character) < 0x20 for character in host)
        and parsed.username is None
        and parsed.password is None
        and parsed.query == ""
        and parsed.fragment == ""
        and parsed.path in {"", "/"}
        and (port is None or 1 <= port <= 65_535)
    )


def _looks_like_absolute_path(value: str) -> bool:
    stripped = value.strip()
    return (
        stripped.startswith("/")
        or stripped.casefold().startswith("file://")
        or bool(_WINDOWS_ABSOLUTE_RE.match(stripped))
        or stripped.startswith("../")
        or stripped.startswith("..\\")
        or bool(_WINDOWS_DRIVE_RELATIVE_RE.match(stripped))
    )


def _looks_like_unsupported_resource_location(value: str) -> bool:
    stripped = value.strip()
    match = _URL_SCHEME_RE.match(stripped)
    if match is None:
        return bool(_EMBEDDED_URL_RE.search(value))
    scheme = match.group(0)[:-1].casefold()
    remainder = stripped[match.end():]
    return scheme in _UNSUPPORTED_RESOURCE_SCHEMES or remainder.startswith("//")


def _resource_marker(slot_id: str) -> dict[str, str]:
    return {"$resourceSlot": slot_id}


def _normalize_service_bindings(values: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or len(values) > 2:
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", "serviceBindings must be a list")
    result: list[dict[str, str]] = []
    capabilities: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, Mapping) or set(value) != {"capability", "profileRef", "configurationFingerprint"}:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", f"serviceBindings[{index}] fields are invalid")
        capability = value.get("capability")
        if capability not in {"model", "tts"} or capability in capabilities:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", "service binding capability is invalid or duplicated")
        profile_ref = _require_id(value.get("profileRef"), "profileRef")
        fingerprint = _require_digest(value.get("configurationFingerprint"), "configurationFingerprint")
        capabilities.add(capability)
        result.append({"capability": capability, "profileRef": profile_ref, "configurationFingerprint": fingerprint})
    return sorted(result, key=lambda item: item["capability"])


def _normalize_resource_bindings(
    values: Sequence[LegacyResourceBinding],
) -> dict[str, LegacyResourceBinding]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise LegacyProjectProjectionError("LEGACY_RESOURCE_BINDING_INVALID", "resource bindings must be a list")
    if len(values) > MAX_RESOURCE_SLOTS:
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_LIMIT_EXCEEDED", "too many resource bindings")
    by_pointer: dict[str, LegacyResourceBinding] = {}
    slot_ids: set[str] = set()
    internal_ids: set[str] = set()
    for binding in values:
        if not isinstance(binding, LegacyResourceBinding):
            raise LegacyProjectProjectionError("LEGACY_RESOURCE_BINDING_INVALID", "resource binding type is invalid")
        slot_id = _require_id(binding.slot_id, "resource slot id")
        internal_id = _require_id(binding.internal_resource_binding_id, "internal resource binding id")
        if not isinstance(binding.json_pointer, str) or not binding.json_pointer.startswith("#/"):
            raise LegacyProjectProjectionError("LEGACY_RESOURCE_BINDING_INVALID", "resource binding JSON pointer is invalid")
        if binding.kind not in _RESOURCE_KINDS:
            raise LegacyProjectProjectionError("LEGACY_RESOURCE_BINDING_INVALID", "resource binding kind is invalid")
        _require_digest(binding.resource_revision_digest, "resource revision digest")
        _require_digest(binding.resource_value_digest, "resource value digest")
        if binding.kind == "source_network":
            _require_digest(binding.canonical_request_digest, "canonical request digest")
            _require_digest(binding.query_redaction_digest, "query redaction digest")
            if not _is_redacted_display_origin(binding.display_origin):
                raise LegacyProjectProjectionError(
                    "LEGACY_RESOURCE_BINDING_INVALID",
                    "network display origin must contain only a valid scheme and authority",
                )
        elif any(
            value is not None
            for value in (binding.canonical_request_digest, binding.display_origin, binding.query_redaction_digest)
        ):
            raise LegacyProjectProjectionError("LEGACY_RESOURCE_BINDING_INVALID", "local binding cannot contain network metadata")
        if binding.json_pointer in by_pointer or slot_id in slot_ids or internal_id in internal_ids:
            raise LegacyProjectProjectionError("LEGACY_RESOURCE_BINDING_INVALID", "resource binding identity is duplicated")
        by_pointer[binding.json_pointer] = binding
        slot_ids.add(slot_id)
        internal_ids.add(internal_id)
    return by_pointer


def _resource_slot_record(binding: LegacyResourceBinding) -> dict[str, str]:
    base = {
        "slotId": binding.slot_id,
        "jsonPointer": binding.json_pointer,
        "kind": binding.kind,
        "internalResourceBindingId": binding.internal_resource_binding_id,
        "resourceRevisionDigest": binding.resource_revision_digest,
    }
    if binding.kind == "source_network":
        return {
            **base,
            "canonicalRequestDigest": str(binding.canonical_request_digest),
            "displayOrigin": str(binding.display_origin),
            "queryRedactionDigest": str(binding.query_redaction_digest),
        }
    return base


class _ProjectSanitizer:
    def __init__(
        self,
        resource_bindings: Sequence[LegacyResourceBinding],
        *,
        forbidden_canaries: Sequence[str],
    ) -> None:
        self._bindings = _normalize_resource_bindings(resource_bindings)
        self._used_pointers: set[str] = set()
        self._removed: list[str] = []
        self._nodes = 0
        if isinstance(forbidden_canaries, (str, bytes)) or not isinstance(forbidden_canaries, Sequence):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", "forbidden canaries must be a list")
        self._canaries: list[str] = []
        for value in forbidden_canaries:
            if not isinstance(value, str) or not value or len(value) > 4_096:
                raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", "forbidden canary is invalid")
            self._canaries.append(value)

    def sanitize(self, project: Mapping[str, Any]) -> tuple[dict[str, Any], list[str], list[dict[str, str]]]:
        if not isinstance(project, Mapping):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", "legacy Project must be an object")
        sanitized = self._walk(dict(project), (), 0)
        if not isinstance(sanitized, dict):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", "legacy Project must remain an object")
        unknown = set(sanitized) - _PROJECT_ALLOWED_FIELDS
        missing = _PROJECT_REQUIRED_FIELDS - set(sanitized)
        if unknown or missing:
            raise LegacyProjectProjectionError(
                "LEGACY_PROJECTION_SCHEMA_INVALID",
                f"legacy Project fields are invalid; unknown={sorted(unknown)}, missing={sorted(missing)}",
            )
        unused = set(self._bindings) - self._used_pointers
        if unused:
            raise LegacyProjectProjectionError(
                "LEGACY_RESOURCE_BINDING_UNUSED",
                f"resource bindings were not consumed: {sorted(unused)}",
            )
        if len(self._removed) > MAX_REMOVED_FIELDS:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_LIMIT_EXCEEDED", "too many removed fields")
        slots = [_resource_slot_record(self._bindings[pointer]) for pointer in sorted(self._used_pointers)]
        projection = {
            "projectionSchema": "legacy.project.nonsecret.v1",
            "projectionSchemaVersion": 1,
            "project": sanitized,
            "resourceSlots": slots,
        }
        encoded = canonical_json_bytes(projection)
        if len(encoded) > MAX_PROJECTION_BYTES:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_LIMIT_EXCEEDED", "legacy Project projection is too large")
        self._scan_for_forbidden_content(encoded)
        try:
            validate_persistable_json(projection)
        except ArtifactRegistryError as error:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_PERSISTENCE_FORBIDDEN", error.message) from error
        return projection, sorted(self._removed), slots

    def _walk(self, value: Any, parts: tuple[str, ...], depth: int) -> Any:
        self._nodes += 1
        if self._nodes > MAX_PROJECTION_NODES or depth > MAX_PROJECTION_DEPTH:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_LIMIT_EXCEEDED", "legacy Project exceeds traversal limits")
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for key, child in value.items():
                if not isinstance(key, str) or not key:
                    raise LegacyProjectProjectionError(
                        "LEGACY_PROJECTION_SCHEMA_INVALID", "legacy Project keys must be non-empty text"
                    )
                child_parts = parts + (key,)
                normalized = _normalized_key(key)
                if normalized in _REMOVED_CONFIGURATION_KEYS or normalized in _SECRET_EXACT_KEYS or any(part in normalized for part in _SECRET_KEY_PARTS):
                    self._removed.append(_pointer(child_parts))
                    continue
                if key == "$resourceSlot":
                    raise LegacyProjectProjectionError(
                        "LEGACY_RESOURCE_MARKER_FORGED", "legacy Project cannot inject resource markers"
                    )
                result[key] = self._walk(child, child_parts, depth + 1)
            return result
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [self._walk(child, parts + (str(index),), depth + 1) for index, child in enumerate(value)]
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            if abs(value) > MAX_SAFE_INTEGER:
                raise LegacyProjectProjectionError(
                    "LEGACY_PROJECTION_SCHEMA_INVALID", "legacy Project contains an unsafe integer"
                )
            return value
        if isinstance(value, float):
            try:
                canonical_json_bytes(value)
            except ArtifactRegistryError as error:
                raise LegacyProjectProjectionError(
                    "LEGACY_PROJECTION_SCHEMA_INVALID", "legacy Project contains a non-finite number"
                ) from error
            return value
        if isinstance(value, str):
            return self._sanitize_string(value, parts)
        raise LegacyProjectProjectionError(
            "LEGACY_PROJECTION_SCHEMA_INVALID", f"unsupported legacy Project value: {type(value).__name__}"
        )

    def _sanitize_string(self, value: str, parts: tuple[str, ...]) -> Any:
        pointer = _pointer(parts)
        network = _looks_like_network_location(value)
        local = not network and _looks_like_absolute_path(value)
        if network or local:
            binding = self._bindings.get(pointer)
            if binding is None:
                raise LegacyProjectProjectionError(
                    "LEGACY_RESOURCE_BINDING_MISSING", f"resource value at {pointer} has no trusted binding"
                )
            if network and binding.kind != "source_network":
                raise LegacyProjectProjectionError(
                    "LEGACY_RESOURCE_BINDING_MISMATCH", f"resource kind at {pointer} does not match"
                )
            if local and binding.kind not in _LOCAL_RESOURCE_KINDS:
                raise LegacyProjectProjectionError(
                    "LEGACY_RESOURCE_BINDING_MISMATCH", f"resource kind at {pointer} does not match"
                )
            if _sha256_text(value) != binding.resource_value_digest:
                raise LegacyProjectProjectionError(
                    "LEGACY_RESOURCE_BINDING_MISMATCH", f"resource value at {pointer} does not match its binding"
                )
            self._used_pointers.add(pointer)
            return _resource_marker(binding.slot_id)
        if _looks_like_unsupported_resource_location(value):
            raise LegacyProjectProjectionError(
                "LEGACY_RESOURCE_VALUE_FORBIDDEN", f"unrecognized or embedded resource locator at {pointer}"
            )
        for pattern in _SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                raise LegacyProjectProjectionError(
                    "LEGACY_SECRET_CANARY_DETECTED", f"credential-like content remains at {pointer}"
                )
        return value

    def _scan_for_forbidden_content(self, encoded: bytes) -> None:
        for canary in self._canaries:
            if canary.encode("utf-8") in encoded:
                raise LegacyProjectProjectionError(
                    "LEGACY_SECRET_CANARY_DETECTED", "a forbidden canary remains after sanitization"
                )


def sanitize_legacy_project(
    project: Mapping[str, Any],
    *,
    resource_bindings: Sequence[LegacyResourceBinding],
    forbidden_canaries: Sequence[str] = (),
) -> tuple[dict[str, Any], list[str], list[dict[str, str]]]:
    """Sanitize a legacy Project completely in memory before any persistence call."""

    return _ProjectSanitizer(resource_bindings, forbidden_canaries=forbidden_canaries).sanitize(project)


def _validate_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "projectionSchema", "projectionSchemaVersion", "project", "resourceSlots"
    }:
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection fields are invalid")
    if (
        value.get("projectionSchema") != "legacy.project.nonsecret.v1"
        or value.get("projectionSchemaVersion") != 1
    ):
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection schema is invalid")
    project = value.get("project")
    if not isinstance(project, Mapping):
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection project is invalid")
    if set(project) - _PROJECT_ALLOWED_FIELDS or not _PROJECT_REQUIRED_FIELDS.issubset(project):
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection project fields are invalid")
    slots_value = value.get("resourceSlots")
    if not isinstance(slots_value, list) or len(slots_value) > MAX_RESOURCE_SLOTS:
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection resource slots are invalid")
    slots: dict[str, dict[str, Any]] = {}
    pointers: set[str] = set()
    internal_ids: set[str] = set()
    for item in slots_value:
        if not isinstance(item, Mapping):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection resource slot is invalid")
        kind = item.get("kind")
        required = {
            "slotId", "jsonPointer", "kind", "internalResourceBindingId", "resourceRevisionDigest"
        }
        if kind == "source_network":
            required |= {"canonicalRequestDigest", "displayOrigin", "queryRedactionDigest"}
        if set(item) != required or kind not in _RESOURCE_KINDS:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection resource slot fields are invalid")
        slot_id = _require_id(item.get("slotId"), "resource slot id")
        internal_id = _require_id(item.get("internalResourceBindingId"), "internal resource binding id")
        pointer = item.get("jsonPointer")
        if not isinstance(pointer, str) or not pointer.startswith("#/"):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "resource slot pointer is invalid")
        _require_digest(item.get("resourceRevisionDigest"), "resource revision digest")
        if kind == "source_network":
            _require_digest(item.get("canonicalRequestDigest"), "canonical request digest")
            _require_digest(item.get("queryRedactionDigest"), "query redaction digest")
            display = item.get("displayOrigin")
            if not _is_redacted_display_origin(display):
                raise LegacyProjectProjectionError(
                    "LEGACY_PROJECTION_BLOB_INVALID", "resource display origin is invalid or not redacted"
                )
        if slot_id in slots or pointer in pointers or internal_id in internal_ids:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection resource slot is duplicated")
        slots[slot_id] = dict(item)
        pointers.add(pointer)
        internal_ids.add(internal_id)

    used: set[str] = set()

    def walk(node: Any, parts: tuple[str, ...], depth: int) -> None:
        if depth > MAX_PROJECTION_DEPTH:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection depth is invalid")
        if isinstance(node, Mapping):
            if "$resourceSlot" in node:
                if set(node) != {"$resourceSlot"} or not isinstance(node["$resourceSlot"], str):
                    raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "resource marker is invalid")
                slot = slots.get(node["$resourceSlot"])
                if slot is None or slot["jsonPointer"] != _pointer(parts):
                    raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "resource marker does not match its slot")
                used.add(node["$resourceSlot"])
                return
            for key, child in node.items():
                if not isinstance(key, str):
                    raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection key is invalid")
                walk(child, parts + (key,), depth + 1)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, parts + (str(index),), depth + 1)
        elif isinstance(node, str):
            if _looks_like_network_location(node) or _looks_like_absolute_path(node):
                raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "raw resource locator remains in projection")
            if _looks_like_unsupported_resource_location(node):
                raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "unrecognized resource locator remains in projection")
            if any(pattern.search(node) for pattern in _SECRET_VALUE_PATTERNS):
                raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "credential-like content remains in projection")

    walk(project, (), 0)
    if used != set(slots):
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection contains unused resource slots")
    try:
        validate_persistable_json(dict(value))
    except ArtifactRegistryError as error:
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", error.message) from error
    return dict(value)


def _artifact_ref_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        value.get("projectId"), value.get("artifactId"), value.get("artifactRevision"),
        value.get("artifactDigest"),
    )


def _verify_support_ref(
    registry: ArtifactRegistry,
    artifact_ref: Mapping[str, Any],
    audience: ArtifactAudienceBinding,
    *,
    project_id: str,
    expected_schema: str,
) -> dict[str, Any]:
    try:
        envelope = registry.verify_ref(artifact_ref, audience)
    except ArtifactRegistryError as error:
        raise LegacyProjectProjectionError("LEGACY_SUPPORT_ARTIFACT_INVALID", error.message) from error
    if envelope.get("projectId") != project_id or envelope.get("payloadSchema") != expected_schema:
        raise LegacyProjectProjectionError(
            "LEGACY_SUPPORT_ARTIFACT_INVALID",
            f"support artifact must use {expected_schema} in the same project",
        )
    return dict(artifact_ref)


def _require_ref_list(value: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise LegacyProjectProjectionError("LEGACY_SUPPORT_ARTIFACT_INVALID", f"{label} must be a list")
    if not value or len(value) > MAX_SUPPORT_REFS or any(not isinstance(item, Mapping) for item in value):
        raise LegacyProjectProjectionError("LEGACY_SUPPORT_ARTIFACT_INVALID", f"{label} is invalid")
    copied = [dict(item) for item in value]
    if len({_artifact_ref_key(item) for item in copied}) != len(copied):
        raise LegacyProjectProjectionError("LEGACY_SUPPORT_ARTIFACT_INVALID", f"{label} contains duplicates")
    return copied


def _require_optional_ref(value: Any, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise LegacyProjectProjectionError("LEGACY_SUPPORT_ARTIFACT_INVALID", f"{label} is invalid")
    return dict(value)


def _validate_pointer_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_REMOVED_FIELDS:
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", f"{label} is invalid")
    if any(not isinstance(item, str) or not item.startswith("#/") for item in value):
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", f"{label} is invalid")
    if value != sorted(set(value)):
        raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", f"{label} must be sorted and unique")
    return list(value)


class LegacyProjectProjectionPublisher:
    """Internal-only bridge from the mutable legacy Project to immutable non-secret artifacts."""

    PAYLOAD_SCHEMA = "study.legacy.sanitized"
    PAYLOAD_SCHEMA_VERSION = 1

    def __init__(self, registry: ArtifactRegistry) -> None:
        if not isinstance(registry, ArtifactRegistry):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", "artifact registry is invalid")
        self._registry = registry

    def publish(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        project_revision: int,
        artifact_id: str,
        artifact_revision: int,
        legacy_project: Mapping[str, Any],
        resource_bindings: Sequence[LegacyResourceBinding],
        source_asset_refs: Sequence[Mapping[str, Any]],
        media_ledger_ref: Mapping[str, Any],
        service_bindings: Sequence[Mapping[str, Any]] = (),
        reliability_manifest_ref: Mapping[str, Any] | None = None,
        learning_point_inventory_ref: Mapping[str, Any] | None = None,
        generation_diagnostics_ref: Mapping[str, Any] | None = None,
        prior_projection_ref: Mapping[str, Any] | None = None,
        input_fingerprint: str,
        original_schema: str = "legacy.Project",
        producer: Mapping[str, Any] | None = None,
        forbidden_canaries: Sequence[str] = (),
    ) -> ArtifactPublication:
        # The complete legacy object is sanitized before the first persistence call.
        projection, removed_paths, resource_slots = sanitize_legacy_project(
            legacy_project,
            resource_bindings=resource_bindings,
            forbidden_canaries=forbidden_canaries,
        )
        normalized_services = _normalize_service_bindings(service_bindings)
        sources = _require_ref_list(source_asset_refs, "sourceAssetRefs")
        media = _require_optional_ref(media_ledger_ref, "mediaLedgerRef")
        if media is None:
            raise LegacyProjectProjectionError("LEGACY_SUPPORT_ARTIFACT_INVALID", "mediaLedgerRef is required")
        reliability = _require_optional_ref(reliability_manifest_ref, "reliabilityManifestRef")
        inventory = _require_optional_ref(learning_point_inventory_ref, "learningPointInventoryRef")
        diagnostics = _require_optional_ref(generation_diagnostics_ref, "generationDiagnosticsRef")
        prior = _require_optional_ref(prior_projection_ref, "priorProjectionRef")
        expected_optional = {
            "reliabilityManifestRef": ("reliability_manifest" in projection["project"], reliability),
            "learningPointInventoryRef": ("learning_point_inventory" in projection["project"], inventory),
            "generationDiagnosticsRef": ("card_generation_diagnostics" in projection["project"], diagnostics),
        }
        for label, (present, reference) in expected_optional.items():
            if present != (reference is not None):
                raise LegacyProjectProjectionError(
                    "LEGACY_SUPPORT_ARTIFACT_INVALID",
                    f"{label} must be present exactly when its legacy Project field is present",
                )
        if not isinstance(original_schema, str) or not _ID_RE.fullmatch(original_schema):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_SCHEMA_INVALID", "original schema is invalid")
        schema_version = projection["project"].get("schema_version", 1)
        if (
            isinstance(schema_version, bool) or not isinstance(schema_version, int)
            or not 1 <= schema_version <= MAX_SAFE_INTEGER
        ):
            raise LegacyProjectProjectionError(
                "LEGACY_PROJECTION_SCHEMA_INVALID", "legacy Project schema version is invalid"
            )

        verified_sources = [
            _verify_support_ref(
                self._registry, ref, audience, project_id=project_id,
                expected_schema=_SUPPORT_SCHEMAS["sourceAssetRefs"],
            )
            for ref in sources
        ]
        verified_media = _verify_support_ref(
            self._registry, media, audience, project_id=project_id,
            expected_schema=_SUPPORT_SCHEMAS["mediaLedgerRef"],
        )
        verified_optional: dict[str, dict[str, Any]] = {}
        for label, reference in (
            ("reliabilityManifestRef", reliability),
            ("learningPointInventoryRef", inventory),
            ("generationDiagnosticsRef", diagnostics),
        ):
            if reference is not None:
                verified_optional[label] = _verify_support_ref(
                    self._registry,
                    reference,
                    audience,
                    project_id=project_id,
                    expected_schema=_SUPPORT_SCHEMAS[label],
                )
        verified_prior: dict[str, Any] | None = None
        if prior is not None:
            verified_prior = _verify_support_ref(
                self._registry,
                prior,
                audience,
                project_id=project_id,
                expected_schema=self.PAYLOAD_SCHEMA,
            )

        projection_bytes = canonical_json_bytes(projection)
        projection_sha256 = hashlib.sha256(projection_bytes).hexdigest()
        blob_ref = self._registry.put_blob(
            projection_bytes,
            media_type="application/vnd.speakright.legacy-project+json",
        )
        payload_body: dict[str, Any] = {
            "legacyProjectSchema": original_schema,
            "legacyProjectSchemaVersion": schema_version,
            "projectionSchema": "legacy.project.nonsecret.v1",
            "projectionSchemaSha256": LEGACY_PROJECT_PROJECTION_SCHEMA_SHA256,
            "projectProjection": blob_ref,
            "projectProjectionSha256": projection_sha256,
            "resourceSlots": resource_slots,
            "sourceAssetRefs": verified_sources,
            "mediaLedgerRef": verified_media,
            "serviceBindings": normalized_services,
            **verified_optional,
        }
        sanitized_payload = {
            "sanitizerSchema": "study.legacy.sanitized",
            "sanitizerVersion": 1,
            "originalSchema": original_schema,
            "removedFieldPaths": removed_paths,
            "replacedResourcePaths": sorted(slot["jsonPointer"] for slot in resource_slots),
            "payload": payload_body,
        }
        try:
            validate_persistable_json(sanitized_payload)
        except ArtifactRegistryError as error:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_PERSISTENCE_FORBIDDEN", error.message) from error
        parents = [
            *verified_sources,
            verified_media,
            *verified_optional.values(),
            *([verified_prior] if verified_prior is not None else []),
        ]
        if len({_artifact_ref_key(parent) for parent in parents}) != len(parents):
            raise LegacyProjectProjectionError(
                "LEGACY_SUPPORT_ARTIFACT_INVALID", "support and prior artifact references must be unique"
            )
        try:
            return self._registry.publish(
                audience=audience,
                project_id=project_id,
                project_revision=project_revision,
                artifact_id=artifact_id,
                artifact_revision=artifact_revision,
                payload_schema=self.PAYLOAD_SCHEMA,
                payload_schema_version=self.PAYLOAD_SCHEMA_VERSION,
                payload=sanitized_payload,
                producer=dict(producer or {"component": "legacy-project-projector", "version": "1.0.0"}),
                parents=parents,
                input_fingerprint=input_fingerprint,
                completeness={"state": "complete", "omittedLocators": [], "reasonCodes": []},
                issue_refs=[],
            )
        except ArtifactRegistryError as error:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_PUBLISH_FAILED", error.message) from error

    def resolve_internal(
        self,
        handle: str,
        audience: ArtifactAudienceBinding,
    ) -> dict[str, Any]:
        try:
            artifact_ref, envelope = self._registry.resolve_with_ref(handle, audience)
        except ArtifactRegistryError as error:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RESOLVE_FAILED", error.message) from error
        if (
            envelope.get("payloadSchema") != self.PAYLOAD_SCHEMA
            or envelope.get("payloadSchemaVersion") != self.PAYLOAD_SCHEMA_VERSION
        ):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "artifact is not a legacy projection")
        record = envelope.get("payload")
        required_record = {
            "sanitizerSchema", "sanitizerVersion", "originalSchema", "removedFieldPaths",
            "replacedResourcePaths", "payload",
        }
        if not isinstance(record, Mapping) or set(record) != required_record:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "sanitized record fields are invalid")
        if record.get("sanitizerSchema") != "study.legacy.sanitized" or record.get("sanitizerVersion") != 1:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "sanitizer schema is invalid")
        if not isinstance(record.get("originalSchema"), str) or not _ID_RE.fullmatch(record["originalSchema"]):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "original schema is invalid")
        removed_paths = _validate_pointer_list(record.get("removedFieldPaths"), "removedFieldPaths")
        replaced_paths = _validate_pointer_list(record.get("replacedResourcePaths"), "replacedResourcePaths")
        body = record.get("payload")
        required_body = {
            "legacyProjectSchema", "legacyProjectSchemaVersion", "projectionSchema",
            "projectionSchemaSha256", "projectProjection", "projectProjectionSha256",
            "resourceSlots", "sourceAssetRefs", "mediaLedgerRef", "serviceBindings",
        }
        optional_body = {
            "reliabilityManifestRef", "learningPointInventoryRef", "generationDiagnosticsRef"
        }
        if (
            not isinstance(body, Mapping)
            or not required_body.issubset(body)
            or not set(body).issubset(required_body | optional_body)
        ):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "projection payload fields are invalid")
        if body.get("legacyProjectSchema") != record["originalSchema"]:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "legacy schema identity is inconsistent")
        version = body.get("legacyProjectSchemaVersion")
        if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= MAX_SAFE_INTEGER:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "legacy schema version is invalid")
        if (
            body.get("projectionSchema") != "legacy.project.nonsecret.v1"
            or body.get("projectionSchemaSha256") != LEGACY_PROJECT_PROJECTION_SCHEMA_SHA256
        ):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "projection schema binding is invalid")
        _require_digest(body.get("projectProjectionSha256"), "project projection digest")
        _normalize_service_bindings(body.get("serviceBindings"))
        sources = _require_ref_list(body.get("sourceAssetRefs"), "sourceAssetRefs")
        support = [
            *sources,
            _require_optional_ref(body.get("mediaLedgerRef"), "mediaLedgerRef"),
            *[
                _require_optional_ref(body.get(label), label)
                for label in optional_body if label in body
            ],
        ]
        if any(reference is None for reference in support):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "support artifact reference is missing")
        parent_keys = {_artifact_ref_key(parent) for parent in envelope.get("parents", [])}
        if any(_artifact_ref_key(reference) not in parent_keys for reference in support if reference is not None):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "support artifact is not bound as a parent")
        try:
            projection_bytes = self._registry.read_blob(body.get("projectProjection"))
        except (ArtifactRegistryError, AttributeError) as error:
            message = getattr(error, "message", str(error))
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", message) from error
        if hashlib.sha256(projection_bytes).hexdigest() != body["projectProjectionSha256"]:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection blob digest is inconsistent")
        try:
            parsed = json.loads(projection_bytes.decode("utf-8"))
            if canonical_json_bytes(parsed) != projection_bytes:
                raise ValueError("projection blob is not canonical JSON")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ArtifactRegistryError) as error:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_BLOB_INVALID", "projection blob is not canonical JSON") from error
        projection = _validate_projection(parsed)
        if body.get("resourceSlots") != projection["resourceSlots"]:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "resource slots differ from projection")
        expected_replaced = sorted(slot["jsonPointer"] for slot in projection["resourceSlots"])
        if replaced_paths != expected_replaced:
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "replaced resource paths are inconsistent")
        if removed_paths != sorted(removed_paths):
            raise LegacyProjectProjectionError("LEGACY_PROJECTION_RECORD_INVALID", "removed paths are inconsistent")
        return {
            "artifactRef": artifact_ref,
            "record": dict(record),
            "projection": projection,
        }

    def public_summary(self, handle: str, audience: ArtifactAudienceBinding) -> dict[str, Any]:
        internal = self.resolve_internal(handle, audience)
        artifact_ref = internal["artifactRef"]
        record = internal["record"]
        body = record["payload"]
        return {
            "artifactId": artifact_ref["artifactId"],
            "projectId": artifact_ref["projectId"],
            "projectRevision": artifact_ref["projectRevision"],
            "artifactRevision": artifact_ref["artifactRevision"],
            "payloadSchema": artifact_ref["payloadSchema"],
            "sanitizerSchema": record["sanitizerSchema"],
            "legacyProjectSchema": body["legacyProjectSchema"],
            "resourceSlotCount": len(body["resourceSlots"]),
            "sourceAssetCount": len(body["sourceAssetRefs"]),
            "serviceCapabilities": [item["capability"] for item in body["serviceBindings"]],
            "hasReliabilityManifest": "reliabilityManifestRef" in body,
            "hasLearningPointInventory": "learningPointInventoryRef" in body,
            "hasGenerationDiagnostics": "generationDiagnosticsRef" in body,
        }
