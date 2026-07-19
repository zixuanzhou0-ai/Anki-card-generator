from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//)")
_MEDIA_TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_RECORD_BYTES = 128 * 1024
_MAX_BLOB_BYTES = 2 * 1024 * 1024 * 1024

_FORBIDDEN_SECRET_KEYS = {
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "refreshtoken",
    "secret",
    "token",
}


class ArtifactRegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ArtifactAudienceBinding:
    owner_digest: str
    host_id: str
    plugin_id: str
    session_id: str

    def project_scope(self, project_id: str) -> dict[str, Any]:
        return {
            "schema": "study.artifact.project-scope",
            "schemaVersion": 1,
            "ownerDigest": self.owner_digest,
            "hostId": self.host_id,
            "pluginId": self.plugin_id,
            "projectId": project_id,
        }

    def audience(self, service_instance_id: str) -> dict[str, Any]:
        return {
            "schema": "study.artifact.audience-binding",
            "schemaVersion": 1,
            "ownerDigest": self.owner_digest,
            "hostId": self.host_id,
            "pluginId": self.plugin_id,
            "sessionId": self.session_id,
            "serviceInstanceId": service_instance_id,
        }


@dataclass(frozen=True)
class ArtifactPublication:
    handle: str
    artifact_ref: Mapping[str, Any]
    envelope: Mapping[str, Any]


def _utf16_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be", errors="surrogatepass")


def _canonicalize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ArtifactRegistryError("ARTIFACT_NUMBER_UNSAFE", "Integer is outside the interoperable JSON range")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ArtifactRegistryError("ARTIFACT_NUMBER_NONFINITE", "Non-finite JSON numbers are forbidden")
        return _canonical_float(value)
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ArtifactRegistryError("ARTIFACT_STRING_INVALID", "JSON strings cannot contain lone surrogates") from error
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_canonicalize(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ArtifactRegistryError("ARTIFACT_KEY_INVALID", "JSON object keys must be strings")
        keys = sorted(value, key=_utf16_sort_key)
        return "{" + ",".join(
            f"{json.dumps(key, ensure_ascii=False, separators=(',', ':'))}:{_canonicalize(value[key])}"
            for key in keys
        ) + "}"
    raise ArtifactRegistryError("ARTIFACT_VALUE_INVALID", f"Unsupported JSON value type: {type(value).__name__}")


def _canonical_float(value: float) -> str:
    """Render a finite IEEE-754 double using RFC 8785/ECMAScript thresholds."""
    if value == 0:
        return "0"
    negative = value < 0
    rendered = repr(abs(value)).lower()
    if "e" in rendered:
        mantissa, exponent_text = rendered.split("e", 1)
        exponent = int(exponent_text)
    else:
        mantissa = rendered
        exponent = 0
    if "." in mantissa:
        whole, fraction = mantissa.split(".", 1)
    else:
        whole, fraction = mantissa, ""
    digits = (whole + fraction).lstrip("0") or "0"
    scale = exponent - len(fraction)
    while len(digits) > 1 and digits.endswith("0"):
        digits = digits[:-1]
        scale += 1
    absolute = abs(value)
    if 1e-6 <= absolute < 1e21:
        point = len(digits) + scale
        if point <= 0:
            result = "0." + ("0" * -point) + digits
        elif point >= len(digits):
            result = digits + ("0" * (point - len(digits)))
        else:
            result = digits[:point] + "." + digits[point:]
    else:
        scientific_exponent = len(digits) + scale - 1
        coefficient = digits[0] + (("." + digits[1:]) if len(digits) > 1 else "")
        sign = "+" if scientific_exponent >= 0 else ""
        result = f"{coefficient}e{sign}{scientific_exponent}"
    return ("-" if negative else "") + result


def canonical_json_bytes(value: Any) -> bytes:
    return _canonicalize(value).encode("utf-8")


def validate_persistable_json(value: Any) -> None:
    """Fail closed before task, artifact, checkpoint, or audit persistence."""
    _reject_secrets_and_paths(value)
    canonical_json_bytes(value)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalized_key(key: str) -> str:
    return "".join(character for character in key.casefold() if character.isalnum())


def _looks_like_absolute_path(value: str) -> bool:
    return (
        value.startswith("/")
        or value.casefold().startswith("file://")
        or bool(_WINDOWS_ABSOLUTE_RE.match(value))
    )


def _reject_secrets_and_paths(value: Any, *, trail: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ArtifactRegistryError("ARTIFACT_KEY_INVALID", "Artifact keys must be strings")
            if _normalized_key(key) in _FORBIDDEN_SECRET_KEYS:
                raise ArtifactRegistryError("ARTIFACT_SECRET_FORBIDDEN", f"Secret-bearing field is forbidden at {'.'.join(trail + (key,))}")
            _reject_secrets_and_paths(child, trail=trail + (key,))
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secrets_and_paths(child, trail=trail + (str(index),))
        return
    if isinstance(value, str) and _looks_like_absolute_path(value):
        raise ArtifactRegistryError("ARTIFACT_PATH_FORBIDDEN", f"Absolute local path is forbidden at {'.'.join(trail)}")


def _validate_id(name: str, value: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ArtifactRegistryError("ARTIFACT_ID_INVALID", f"{name} is invalid")


def _validate_digest(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ArtifactRegistryError("ARTIFACT_DIGEST_INVALID", f"{name} must be a lowercase SHA-256 digest")


def _validate_revision(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > _MAX_SAFE_INTEGER:
        raise ArtifactRegistryError("ARTIFACT_REVISION_INVALID", f"{name} must be a positive safe integer")


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ArtifactRegistryError("ARTIFACT_STORAGE_UNSAFE", "Artifact storage contains a link or reparse directory")
    return path


def _atomic_publish(path: Path, data: bytes) -> None:
    _ensure_directory(path.parent)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.partial"
    try:
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise ArtifactRegistryError("ARTIFACT_ALREADY_EXISTS", "Immutable artifact record already exists") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _safe_read(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise ArtifactRegistryError("ARTIFACT_NOT_FOUND", "Artifact registry entry was not found") from error
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ArtifactRegistryError("ARTIFACT_STORAGE_UNSAFE", "Artifact registry entry is not a regular file")
    if info.st_nlink != 1:
        raise ArtifactRegistryError("ARTIFACT_STORAGE_UNSAFE", "Artifact registry entry has an unexpected hard-link count")
    if info.st_size > maximum_bytes:
        raise ArtifactRegistryError("ARTIFACT_TOO_LARGE", "Artifact registry entry exceeds its size limit")
    data = path.read_bytes()
    if len(data) != info.st_size:
        raise ArtifactRegistryError("ARTIFACT_CHANGED", "Artifact registry entry changed while being read")
    after = path.lstat()
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
        raise ArtifactRegistryError("ARTIFACT_CHANGED", "Artifact registry entry changed while being read")
    return data


def _safe_file_digest(path: Path, *, maximum_bytes: int) -> tuple[int, str]:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise ArtifactRegistryError("ARTIFACT_NOT_FOUND", "Artifact Blob was not found") from error
    attributes = getattr(info, "st_file_attributes", 0)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or attributes & 0x400
        or info.st_nlink != 1
    ):
        raise ArtifactRegistryError("ARTIFACT_STORAGE_UNSAFE", "Artifact Blob is not a private regular file")
    if info.st_size < 0 or info.st_size > maximum_bytes:
        raise ArtifactRegistryError("ARTIFACT_BLOB_TOO_LARGE", "Artifact Blob exceeds its size limit")
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                total += len(chunk)
                if total > maximum_bytes:
                    raise ArtifactRegistryError("ARTIFACT_BLOB_TOO_LARGE", "Artifact Blob exceeds its size limit")
                digest.update(chunk)
    except OSError as error:
        raise ArtifactRegistryError("ARTIFACT_BLOB_UNAVAILABLE", "Artifact Blob could not be read") from error
    after = path.lstat()
    if (
        total != info.st_size
        or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    ):
        raise ArtifactRegistryError("ARTIFACT_CHANGED", "Artifact Blob changed while being read")
    return total, digest.hexdigest()


class ArtifactRegistry:
    def __init__(self, root: Path, *, authentication_key: bytes, service_instance_id: str, key_id: str = "artifact-registry-v1") -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise ArtifactRegistryError("ARTIFACT_KEY_INVALID", "Registry authentication key must contain at least 256 bits")
        _validate_id("service_instance_id", service_instance_id)
        _validate_id("key_id", key_id)
        self._root = _ensure_directory(Path(root).absolute())
        self._authentication_key = bytes(authentication_key)
        self._service_instance_id = service_instance_id
        self._key_id = key_id
        self._lock = threading.RLock()
        for child in ("artifacts", "records", "handles", "revocations", "blobs"):
            _ensure_directory(self._root / child)

    def _ensure_storage_parent(self, path: Path) -> None:
        absolute = path.absolute()
        try:
            relative = absolute.relative_to(self._root)
        except ValueError as error:
            raise ArtifactRegistryError("ARTIFACT_STORAGE_UNSAFE", "Artifact path escapes the registry root") from error
        current = _ensure_directory(self._root)
        for part in relative.parts:
            current = _ensure_directory(current / part)

    def _publish(self, path: Path, data: bytes) -> None:
        self._ensure_storage_parent(path.parent)
        _atomic_publish(path, data)

    def _read(self, path: Path, *, maximum_bytes: int) -> bytes:
        self._ensure_storage_parent(path.parent)
        return _safe_read(path, maximum_bytes=maximum_bytes)

    def _mac(self, domain: str, value: Mapping[str, Any]) -> str:
        message = domain.encode("ascii") + b"\x00" + canonical_json_bytes(dict(value))
        return hmac.new(self._authentication_key, message, hashlib.sha256).hexdigest()

    def _json(self, path: Path, maximum_bytes: int) -> dict[str, Any]:
        raw = self._read(path, maximum_bytes=maximum_bytes)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ArtifactRegistryError("ARTIFACT_RECORD_INVALID", "Artifact registry entry is not canonical JSON") from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise ArtifactRegistryError("ARTIFACT_RECORD_INVALID", "Artifact registry entry is not canonical JSON")
        return value

    def _artifact_path(self, project_id: str, artifact_id: str, artifact_revision: int) -> Path:
        identity = _sha256(f"{project_id}\x00{artifact_id}\x00{artifact_revision}".encode("utf-8"))
        return self._root / "artifacts" / identity[:2] / f"{identity}.json"

    def _record_path(self, registry_auth_ref: str) -> Path:
        identity = _sha256(registry_auth_ref.encode("utf-8"))
        return self._root / "records" / identity[:2] / f"{identity}.json"

    def _handle_path(self, handle: str) -> Path:
        identity = _sha256(handle.encode("ascii"))
        return self._root / "handles" / identity[:2] / f"{identity}.json"

    def _revocation_path(self, registry_auth_ref: str) -> Path:
        identity = _sha256(registry_auth_ref.encode("utf-8"))
        return self._root / "revocations" / identity[:2] / f"{identity}.json"

    def _blob_path(self, digest: str) -> Path:
        return self._root / "blobs" / digest[:2] / digest

    def _validate_audience(self, audience: ArtifactAudienceBinding) -> None:
        _validate_digest("owner_digest", audience.owner_digest)
        _validate_id("host_id", audience.host_id)
        _validate_id("plugin_id", audience.plugin_id)
        _validate_id("session_id", audience.session_id)

    @staticmethod
    def _validate_completeness(value: Mapping[str, Any]) -> None:
        if not isinstance(value, Mapping):
            raise ArtifactRegistryError("ARTIFACT_COMPLETENESS_INVALID", "Completeness must be an object")
        allowed = {"complete", "partial_declared", "unknown", "blocked"}
        if value.get("state") not in allowed:
            raise ArtifactRegistryError("ARTIFACT_COMPLETENESS_INVALID", "Completeness state is invalid")
        omitted = value.get("omittedLocators", [])
        reasons = value.get("reasonCodes", [])
        if not isinstance(omitted, list) or not isinstance(reasons, list):
            raise ArtifactRegistryError("ARTIFACT_COMPLETENESS_INVALID", "Completeness lists are invalid")
        if value.get("state") == "complete" and (omitted or reasons):
            raise ArtifactRegistryError("ARTIFACT_COMPLETENESS_INVALID", "Complete artifacts cannot declare omissions")

    @staticmethod
    def _validate_producer(value: Mapping[str, Any]) -> None:
        if not isinstance(value, Mapping):
            raise ArtifactRegistryError("ARTIFACT_PRODUCER_INVALID", "Producer must be an object")
        _validate_id("producer.component", value.get("component"))
        _validate_id("producer.version", value.get("version"))

    @staticmethod
    def _ref_key(value: Mapping[str, Any]) -> tuple[str, int, str]:
        return str(value.get("artifactId")), int(value.get("artifactRevision", 0)), str(value.get("artifactDigest"))

    def _verify_record(self, record: Mapping[str, Any]) -> None:
        if record.get("schema") != "study.artifact.registry-record" or record.get("schemaVersion") != 1:
            raise ArtifactRegistryError("ARTIFACT_RECORD_INVALID", "Registry record schema is invalid")
        auth_tag = record.get("authTag")
        if not isinstance(auth_tag, str) or not _SHA256_RE.fullmatch(auth_tag):
            raise ArtifactRegistryError("ARTIFACT_AUTH_INVALID", "Registry authentication tag is invalid")
        unsigned = dict(record)
        unsigned.pop("authTag", None)
        if not hmac.compare_digest(auth_tag, self._mac("study.artifact.registry-record.v1", unsigned)):
            raise ArtifactRegistryError("ARTIFACT_AUTH_INVALID", "Registry authentication failed")
        if record.get("keyId") != self._key_id:
            raise ArtifactRegistryError("ARTIFACT_AUTH_INVALID", "Registry record uses an unavailable authentication key")

    def _verify_artifact_ref(
        self,
        artifact_ref: Mapping[str, Any],
        audience: ArtifactAudienceBinding,
        *,
        expected_project_id: str | None = None,
        seen: set[tuple[str, int, str]] | None = None,
        verified: dict[tuple[str, int, str], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        required = {"artifactId", "projectId", "projectRevision", "artifactRevision", "payloadSchema", "payloadSchemaVersion", "artifactDigest", "registryAuthRef"}
        if set(artifact_ref) != required:
            raise ArtifactRegistryError("ARTIFACT_REF_INVALID", "Artifact reference fields are invalid")
        _validate_id("artifactId", artifact_ref["artifactId"])
        _validate_id("projectId", artifact_ref["projectId"])
        _validate_revision("projectRevision", artifact_ref["projectRevision"])
        _validate_revision("artifactRevision", artifact_ref["artifactRevision"])
        _validate_id("payloadSchema", artifact_ref["payloadSchema"])
        _validate_revision("payloadSchemaVersion", artifact_ref["payloadSchemaVersion"])
        _validate_digest("artifactDigest", artifact_ref["artifactDigest"])
        _validate_id("registryAuthRef", artifact_ref["registryAuthRef"])
        if expected_project_id is not None and artifact_ref["projectId"] != expected_project_id:
            raise ArtifactRegistryError("ARTIFACT_SCOPE_MISMATCH", "Cross-project artifact reference is forbidden")
        key = self._ref_key(artifact_ref)
        active = seen if seen is not None else set()
        if key in active:
            raise ArtifactRegistryError("ARTIFACT_PARENT_CYCLE", "Artifact parent cycle was detected")
        cache = verified if verified is not None else {}
        if key in cache:
            return cache[key]
        active.add(key)
        try:
            envelope = self._json(self._artifact_path(artifact_ref["projectId"], artifact_ref["artifactId"], artifact_ref["artifactRevision"]), _MAX_ARTIFACT_BYTES)
            if any(envelope.get(field) != artifact_ref[field] for field in required):
                raise ArtifactRegistryError("ARTIFACT_REF_MISMATCH", "Artifact reference does not match its envelope")
            unsigned_envelope = dict(envelope)
            unsigned_envelope.pop("artifactDigest", None)
            unsigned_envelope.pop("registryAuthRef", None)
            if _sha256(canonical_json_bytes(unsigned_envelope)) != artifact_ref["artifactDigest"]:
                raise ArtifactRegistryError("ARTIFACT_DIGEST_MISMATCH", "Artifact digest verification failed")
            payload = envelope.get("payload")
            if _sha256(canonical_json_bytes(payload)) != envelope.get("payloadSha256"):
                raise ArtifactRegistryError("ARTIFACT_PAYLOAD_MISMATCH", "Artifact payload digest verification failed")
            record = self._json(self._record_path(artifact_ref["registryAuthRef"]), _MAX_RECORD_BYTES)
            self._verify_record(record)
            expected_record = {
                "registryAuthRef": artifact_ref["registryAuthRef"],
                "artifactId": artifact_ref["artifactId"],
                "projectId": artifact_ref["projectId"],
                "projectOwnerDigest": audience.owner_digest,
                "artifactDigest": artifact_ref["artifactDigest"],
                "projectScopeDigest": _sha256(canonical_json_bytes(audience.project_scope(artifact_ref["projectId"]))),
            }
            if any(record.get(field) != value for field, value in expected_record.items()):
                raise ArtifactRegistryError("ARTIFACT_AUTH_MISMATCH", "Registry record does not authorize this artifact")
            if self._revocation_path(artifact_ref["registryAuthRef"]).exists():
                revocation = self._json(self._revocation_path(artifact_ref["registryAuthRef"]), _MAX_RECORD_BYTES)
                revocation_tag = revocation.get("authTag")
                unsigned_revocation = dict(revocation)
                unsigned_revocation.pop("authTag", None)
                if (
                    revocation.get("registryAuthRef") != artifact_ref["registryAuthRef"]
                    or not isinstance(revocation_tag, str)
                    or not hmac.compare_digest(revocation_tag, self._mac("study.artifact.revocation.v1", unsigned_revocation))
                ):
                    raise ArtifactRegistryError("ARTIFACT_REVOCATION_INVALID", "Artifact revocation record is invalid")
                raise ArtifactRegistryError("ARTIFACT_REVOKED", "Artifact has been revoked")
            for parent in envelope.get("parents", []):
                if not isinstance(parent, Mapping):
                    raise ArtifactRegistryError("ARTIFACT_PARENT_INVALID", "Artifact parent reference is invalid")
                self._verify_artifact_ref(
                    parent,
                    audience,
                    expected_project_id=artifact_ref["projectId"],
                    seen=active,
                    verified=cache,
                )
            cache[key] = envelope
            return envelope
        finally:
            active.remove(key)

    def publish(self, *, audience: ArtifactAudienceBinding, project_id: str, project_revision: int, artifact_id: str, artifact_revision: int, payload_schema: str, payload_schema_version: int, payload: Any, producer: Mapping[str, Any], parents: Sequence[Mapping[str, Any]], input_fingerprint: str, completeness: Mapping[str, Any], issue_refs: Sequence[str]) -> ArtifactPublication:
        with self._lock:
            self._validate_audience(audience)
            _validate_id("project_id", project_id)
            _validate_id("artifact_id", artifact_id)
            _validate_revision("project_revision", project_revision)
            _validate_revision("artifact_revision", artifact_revision)
            _validate_id("payload_schema", payload_schema)
            _validate_revision("payload_schema_version", payload_schema_version)
            _validate_digest("input_fingerprint", input_fingerprint)
            self._validate_producer(producer)
            self._validate_completeness(completeness)
            if not isinstance(issue_refs, Sequence) or isinstance(issue_refs, (str, bytes)):
                raise ArtifactRegistryError("ARTIFACT_ISSUES_INVALID", "Issue references must be a list")
            for issue_ref in issue_refs:
                _validate_id("issue_ref", issue_ref)
            if len(set(issue_refs)) != len(issue_refs):
                raise ArtifactRegistryError("ARTIFACT_ISSUES_INVALID", "Issue references must be unique")
            verified_parents: list[Mapping[str, Any]] = []
            verified_cache: dict[tuple[str, int, str], dict[str, Any]] = {}
            for parent in parents:
                self._verify_artifact_ref(
                    parent,
                    audience,
                    expected_project_id=project_id,
                    verified=verified_cache,
                )
                verified_parents.append(dict(parent))
            parent_keys = [self._ref_key(parent) for parent in verified_parents]
            if len(set(parent_keys)) != len(parent_keys):
                raise ArtifactRegistryError("ARTIFACT_PARENT_INVALID", "Artifact parents must be unique")
            prior_versions = [parent for parent in verified_parents if parent["artifactId"] == artifact_id]
            if artifact_revision == 1 and prior_versions:
                raise ArtifactRegistryError("ARTIFACT_REVISION_CONFLICT", "The first artifact revision cannot have an earlier self revision")
            if artifact_revision > 1:
                if len(prior_versions) != 1 or prior_versions[0]["artifactRevision"] != artifact_revision - 1:
                    raise ArtifactRegistryError("ARTIFACT_REVISION_CONFLICT", "A new artifact revision must name exactly its immediately preceding revision as a parent")
                if prior_versions[0]["payloadSchema"] != payload_schema:
                    raise ArtifactRegistryError("ARTIFACT_REVISION_CONFLICT", "Artifact revisions cannot change payload schema")
            if any(parent["projectRevision"] > project_revision for parent in verified_parents):
                raise ArtifactRegistryError("ARTIFACT_REVISION_CONFLICT", "Parent project revision cannot exceed the new project revision")
            _reject_secrets_and_paths(payload)
            _reject_secrets_and_paths(dict(producer))
            _reject_secrets_and_paths(dict(completeness))
            registry_auth_ref = "auth_" + secrets.token_urlsafe(24)
            created_at = _utc_now()
            unsigned_envelope: dict[str, Any] = {
                "envelopeSchema": "study.artifact.envelope",
                "envelopeSchemaVersion": 1,
                "payloadSchema": payload_schema,
                "payloadSchemaVersion": payload_schema_version,
                "artifactId": artifact_id,
                "projectId": project_id,
                "projectRevision": project_revision,
                "artifactRevision": artifact_revision,
                "payloadSha256": _sha256(canonical_json_bytes(payload)),
                "createdAt": created_at,
                "producer": dict(producer),
                "parents": verified_parents,
                "inputFingerprint": input_fingerprint,
                "completeness": dict(completeness),
                "issueRefs": list(issue_refs),
                "payload": payload,
            }
            artifact_digest = _sha256(canonical_json_bytes(unsigned_envelope))
            envelope = {**unsigned_envelope, "artifactDigest": artifact_digest, "registryAuthRef": registry_auth_ref}
            artifact_ref = {
                "artifactId": artifact_id,
                "projectId": project_id,
                "projectRevision": project_revision,
                "artifactRevision": artifact_revision,
                "payloadSchema": payload_schema,
                "payloadSchemaVersion": payload_schema_version,
                "artifactDigest": artifact_digest,
                "registryAuthRef": registry_auth_ref,
            }
            scope_digest = _sha256(canonical_json_bytes(audience.project_scope(project_id)))
            unsigned_record = {
                "schema": "study.artifact.registry-record",
                "schemaVersion": 1,
                "registryAuthRef": registry_auth_ref,
                "artifactId": artifact_id,
                "projectId": project_id,
                "projectOwnerDigest": audience.owner_digest,
                "artifactDigest": artifact_digest,
                "createdByServiceInstanceId": self._service_instance_id,
                "keyId": self._key_id,
                "projectScopeDigest": scope_digest,
                "createdAt": created_at,
            }
            record = {**unsigned_record, "authTag": self._mac("study.artifact.registry-record.v1", unsigned_record)}
            artifact_bytes = canonical_json_bytes(envelope)
            record_bytes = canonical_json_bytes(record)
            if len(artifact_bytes) > _MAX_ARTIFACT_BYTES:
                raise ArtifactRegistryError("ARTIFACT_TOO_LARGE", "Artifact envelope exceeds its size limit")
            self._publish(self._artifact_path(project_id, artifact_id, artifact_revision), artifact_bytes)
            try:
                self._publish(self._record_path(registry_auth_ref), record_bytes)
            except Exception:
                try:
                    self._artifact_path(project_id, artifact_id, artifact_revision).unlink()
                except OSError:
                    pass
                raise
            handle = self.issue_handle(artifact_ref, audience)
            return ArtifactPublication(handle=handle, artifact_ref=artifact_ref, envelope=envelope)

    def publish_idempotent(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        project_revision: int,
        artifact_id: str,
        artifact_revision: int,
        payload_schema: str,
        payload_schema_version: int,
        payload: Any,
        producer: Mapping[str, Any],
        parents: Sequence[Mapping[str, Any]],
        input_fingerprint: str,
        completeness: Mapping[str, Any],
        issue_refs: Sequence[str],
    ) -> ArtifactPublication:
        """Publish once, or safely reissue a handle for the identical artifact.

        The immutable artifact identity is deterministic for recoverable Study
        operations. If a process stopped after writing the envelope but before
        its authenticated Registry record, an exact retry repairs only that
        record. A semantic mismatch fails closed instead of adopting the file.
        """

        arguments = {
            "audience": audience,
            "project_id": project_id,
            "project_revision": project_revision,
            "artifact_id": artifact_id,
            "artifact_revision": artifact_revision,
            "payload_schema": payload_schema,
            "payload_schema_version": payload_schema_version,
            "payload": payload,
            "producer": producer,
            "parents": parents,
            "input_fingerprint": input_fingerprint,
            "completeness": completeness,
            "issue_refs": issue_refs,
        }
        try:
            return self.publish(**arguments)
        except ArtifactRegistryError as error:
            if error.code != "ARTIFACT_ALREADY_EXISTS":
                raise
        with self._lock:
            self._validate_audience(audience)
            envelope = self._json(
                self._artifact_path(project_id, artifact_id, artifact_revision),
                _MAX_ARTIFACT_BYTES,
            )
            semantic = {
                "payloadSchema": payload_schema,
                "payloadSchemaVersion": payload_schema_version,
                "artifactId": artifact_id,
                "projectId": project_id,
                "projectRevision": project_revision,
                "artifactRevision": artifact_revision,
                "producer": dict(producer),
                "parents": [dict(parent) for parent in parents],
                "inputFingerprint": input_fingerprint,
                "completeness": dict(completeness),
                "issueRefs": list(issue_refs),
                "payload": payload,
            }
            if any(envelope.get(name) != value for name, value in semantic.items()):
                raise ArtifactRegistryError(
                    "ARTIFACT_IDEMPOTENCY_CONFLICT",
                    "Immutable artifact identity was reused with different content",
                )
            if envelope.get("payloadSha256") != _sha256(canonical_json_bytes(payload)):
                raise ArtifactRegistryError(
                    "ARTIFACT_PAYLOAD_MISMATCH", "Existing artifact payload failed verification"
                )
            unsigned_envelope = dict(envelope)
            unsigned_envelope.pop("artifactDigest", None)
            unsigned_envelope.pop("registryAuthRef", None)
            if envelope.get("artifactDigest") != _sha256(canonical_json_bytes(unsigned_envelope)):
                raise ArtifactRegistryError(
                    "ARTIFACT_DIGEST_MISMATCH", "Existing artifact envelope failed verification"
                )
            registry_auth_ref = envelope.get("registryAuthRef")
            _validate_id("registryAuthRef", registry_auth_ref)
            artifact_ref = {
                "artifactId": artifact_id,
                "projectId": project_id,
                "projectRevision": project_revision,
                "artifactRevision": artifact_revision,
                "payloadSchema": payload_schema,
                "payloadSchemaVersion": payload_schema_version,
                "artifactDigest": envelope["artifactDigest"],
                "registryAuthRef": registry_auth_ref,
            }
            record_path = self._record_path(registry_auth_ref)
            if not record_path.exists():
                unsigned_record = {
                    "schema": "study.artifact.registry-record",
                    "schemaVersion": 1,
                    "registryAuthRef": registry_auth_ref,
                    "artifactId": artifact_id,
                    "projectId": project_id,
                    "projectOwnerDigest": audience.owner_digest,
                    "artifactDigest": envelope["artifactDigest"],
                    "createdByServiceInstanceId": self._service_instance_id,
                    "keyId": self._key_id,
                    "projectScopeDigest": _sha256(canonical_json_bytes(audience.project_scope(project_id))),
                    "createdAt": envelope["createdAt"],
                }
                record = {**unsigned_record, "authTag": self._mac("study.artifact.registry-record.v1", unsigned_record)}
                try:
                    self._publish(record_path, canonical_json_bytes(record))
                except ArtifactRegistryError as record_error:
                    if record_error.code != "ARTIFACT_ALREADY_EXISTS":
                        raise
            verified = self._verify_artifact_ref(artifact_ref, audience)
            handle = self.issue_handle(artifact_ref, audience)
            return ArtifactPublication(handle=handle, artifact_ref=artifact_ref, envelope=verified)

    def issue_handle(self, artifact_ref: Mapping[str, Any], audience: ArtifactAudienceBinding) -> str:
        with self._lock:
            self._validate_audience(audience)
            self._verify_artifact_ref(artifact_ref, audience)
            handle = "study_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
            unsigned = {
                "schema": "study.artifact.handle-binding",
                "schemaVersion": 1,
                "handleDigest": _sha256(handle.encode("ascii")),
                "artifactRef": dict(artifact_ref),
                "projectScopeDigest": _sha256(canonical_json_bytes(audience.project_scope(artifact_ref["projectId"]))),
                "audienceDigest": _sha256(canonical_json_bytes(audience.audience(self._service_instance_id))),
                "serviceInstanceId": self._service_instance_id,
                "createdAt": _utc_now(),
            }
            binding = {**unsigned, "authTag": self._mac("study.artifact.handle-binding.v1", unsigned)}
            self._publish(self._handle_path(handle), canonical_json_bytes(binding))
            return handle

    def verify_ref(self, artifact_ref: Mapping[str, Any], audience: ArtifactAudienceBinding) -> dict[str, Any]:
        """Verify an internal reference without accepting any caller-supplied handle metadata."""
        with self._lock:
            self._validate_audience(audience)
            return self._verify_artifact_ref(artifact_ref, audience)

    def resolve_with_ref(self, handle: str, audience: ArtifactAudienceBinding) -> tuple[dict[str, Any], dict[str, Any]]:
        envelope = self.resolve(handle, audience)
        artifact_ref = {
            "artifactId": envelope["artifactId"],
            "projectId": envelope["projectId"],
            "projectRevision": envelope["projectRevision"],
            "artifactRevision": envelope["artifactRevision"],
            "payloadSchema": envelope["payloadSchema"],
            "payloadSchemaVersion": envelope["payloadSchemaVersion"],
            "artifactDigest": envelope["artifactDigest"],
            "registryAuthRef": envelope["registryAuthRef"],
        }
        return artifact_ref, envelope

    def resolve(self, handle: str, audience: ArtifactAudienceBinding) -> dict[str, Any]:
        with self._lock:
            self._validate_audience(audience)
            if not isinstance(handle, str) or not _HANDLE_RE.fullmatch(handle):
                raise ArtifactRegistryError("ARTIFACT_HANDLE_INVALID", "Artifact handle is invalid")
            binding = self._json(self._handle_path(handle), _MAX_RECORD_BYTES)
            auth_tag = binding.get("authTag")
            unsigned = dict(binding)
            unsigned.pop("authTag", None)
            if not isinstance(auth_tag, str) or not hmac.compare_digest(auth_tag, self._mac("study.artifact.handle-binding.v1", unsigned)):
                raise ArtifactRegistryError("ARTIFACT_HANDLE_AUTH_INVALID", "Artifact handle authentication failed")
            expected = {
                "handleDigest": _sha256(handle.encode("ascii")),
                "serviceInstanceId": self._service_instance_id,
                "audienceDigest": _sha256(canonical_json_bytes(audience.audience(self._service_instance_id))),
            }
            if any(binding.get(field) != value for field, value in expected.items()):
                raise ArtifactRegistryError("ARTIFACT_HANDLE_SCOPE_MISMATCH", "Artifact handle is not valid for this session")
            artifact_ref = binding.get("artifactRef")
            if not isinstance(artifact_ref, Mapping):
                raise ArtifactRegistryError("ARTIFACT_HANDLE_INVALID", "Artifact handle contains no artifact reference")
            expected_scope = _sha256(canonical_json_bytes(audience.project_scope(artifact_ref.get("projectId"))))
            if binding.get("projectScopeDigest") != expected_scope:
                raise ArtifactRegistryError("ARTIFACT_HANDLE_SCOPE_MISMATCH", "Artifact handle project scope does not match")
            return self._verify_artifact_ref(artifact_ref, audience)

    def revoke(self, artifact_ref: Mapping[str, Any], audience: ArtifactAudienceBinding, *, reason_code: str) -> bool:
        with self._lock:
            try:
                envelope = self._verify_artifact_ref(artifact_ref, audience)
            except ArtifactRegistryError as error:
                if error.code == "ARTIFACT_REVOKED":
                    return False
                raise
            _validate_id("reason_code", reason_code)
            unsigned_record = {
                "schema": "study.artifact.revocation",
                "schemaVersion": 1,
                "registryAuthRef": envelope["registryAuthRef"],
                "artifactDigest": envelope["artifactDigest"],
                "reasonCode": reason_code,
                "revokedAt": _utc_now(),
            }
            record = {**unsigned_record, "authTag": self._mac("study.artifact.revocation.v1", unsigned_record)}
            try:
                self._publish(self._revocation_path(envelope["registryAuthRef"]), canonical_json_bytes(record))
                return True
            except ArtifactRegistryError as error:
                if error.code == "ARTIFACT_ALREADY_EXISTS":
                    return False
                raise

    def put_blob(self, data: bytes, *, media_type: str) -> dict[str, Any]:
        if not isinstance(data, bytes) or len(data) > _MAX_BLOB_BYTES:
            raise ArtifactRegistryError("ARTIFACT_BLOB_TOO_LARGE", "Blob exceeds its size limit")
        if not isinstance(media_type, str) or not _MEDIA_TYPE_RE.fullmatch(media_type):
            raise ArtifactRegistryError("ARTIFACT_BLOB_INVALID", "Blob media type is invalid")
        digest = _sha256(data)
        path = self._blob_path(digest)
        with self._lock:
            try:
                self._publish(path, data)
            except ArtifactRegistryError as error:
                if error.code != "ARTIFACT_ALREADY_EXISTS" or self._read(path, maximum_bytes=_MAX_BLOB_BYTES) != data:
                    raise
        return {"blobId": f"sha256:{digest}", "sha256": digest, "sizeBytes": len(data), "mediaType": media_type}

    def put_blob_path(
        self,
        source_path: Path,
        *,
        media_type: str,
        maximum_bytes: int = _MAX_BLOB_BYTES,
    ) -> dict[str, Any]:
        """Stream one verified regular file into the content-addressed Blob store."""

        if not isinstance(media_type, str) or not _MEDIA_TYPE_RE.fullmatch(media_type):
            raise ArtifactRegistryError("ARTIFACT_BLOB_INVALID", "Blob media type is invalid")
        if (
            isinstance(maximum_bytes, bool)
            or not isinstance(maximum_bytes, int)
            or maximum_bytes < 0
            or maximum_bytes > _MAX_BLOB_BYTES
        ):
            raise ArtifactRegistryError("ARTIFACT_BLOB_INVALID", "Blob size limit is invalid")
        path = Path(source_path)
        if not path.is_absolute():
            raise ArtifactRegistryError("ARTIFACT_BLOB_INVALID", "Blob source must be absolute")
        try:
            before = path.lstat()
        except OSError as error:
            raise ArtifactRegistryError("ARTIFACT_BLOB_UNAVAILABLE", "Blob source is unavailable") from error
        attributes = getattr(before, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or attributes & 0x400
            or before.st_nlink != 1
        ):
            raise ArtifactRegistryError("ARTIFACT_BLOB_UNSAFE", "Blob source is not a unique regular file")
        if before.st_size < 0 or before.st_size > maximum_bytes:
            raise ArtifactRegistryError("ARTIFACT_BLOB_TOO_LARGE", "Blob exceeds its size limit")
        incoming = self._root / "blobs" / f".incoming-{secrets.token_hex(24)}.partial"
        self._ensure_storage_parent(incoming.parent)
        source_descriptor: int | None = None
        output_descriptor: int | None = None
        digest_builder = hashlib.sha256()
        total = 0
        stream_completed = False
        try:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            source_descriptor = os.open(path, flags)
            opened = os.fstat(source_descriptor)
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
            ):
                raise ArtifactRegistryError("ARTIFACT_BLOB_CHANGED", "Blob source changed before reading")
            output_descriptor = os.open(
                incoming,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOINHERIT", 0),
                0o600,
            )
            while True:
                chunk = os.read(source_descriptor, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum_bytes:
                    raise ArtifactRegistryError("ARTIFACT_BLOB_TOO_LARGE", "Blob exceeds its size limit")
                digest_builder.update(chunk)
                offset = 0
                while offset < len(chunk):
                    written = os.write(output_descriptor, chunk[offset:])
                    if written <= 0:
                        raise ArtifactRegistryError("ARTIFACT_BLOB_WRITE_FAILED", "Blob write stalled")
                    offset += written
            os.fsync(output_descriptor)
            after_fd = os.fstat(source_descriptor)
            after_path = path.lstat()
            identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            if identity != (after_fd.st_dev, after_fd.st_ino, after_fd.st_size, after_fd.st_mtime_ns) or identity != (
                after_path.st_dev,
                after_path.st_ino,
                after_path.st_size,
                after_path.st_mtime_ns,
            ):
                raise ArtifactRegistryError("ARTIFACT_BLOB_CHANGED", "Blob source changed while reading")
            stream_completed = True
        except OSError as error:
            raise ArtifactRegistryError("ARTIFACT_BLOB_UNAVAILABLE", "Blob source could not be read safely") from error
        finally:
            try:
                if source_descriptor is not None:
                    os.close(source_descriptor)
            finally:
                try:
                    if output_descriptor is not None:
                        os.close(output_descriptor)
                finally:
                    if not stream_completed:
                        try:
                            incoming.unlink()
                        except FileNotFoundError:
                            pass
        digest = digest_builder.hexdigest()
        destination = self._blob_path(digest)
        try:
            with self._lock:
                self._ensure_storage_parent(destination.parent)
                try:
                    os.link(incoming, destination)
                except FileExistsError:
                    existing_size, existing_digest = _safe_file_digest(destination, maximum_bytes=maximum_bytes)
                    if existing_size != total or existing_digest != digest:
                        raise ArtifactRegistryError("ARTIFACT_BLOB_MISMATCH", "Existing Blob failed verification")
        finally:
            try:
                incoming.unlink()
            except FileNotFoundError:
                pass
        return {"blobId": f"sha256:{digest}", "sha256": digest, "sizeBytes": total, "mediaType": media_type}

    def read_blob(self, blob_ref: Mapping[str, Any]) -> bytes:
        digest = blob_ref.get("sha256")
        size = blob_ref.get("sizeBytes")
        _validate_digest("blob.sha256", digest)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > _MAX_BLOB_BYTES:
            raise ArtifactRegistryError("ARTIFACT_BLOB_INVALID", "Blob size is invalid")
        data = self._read(self._blob_path(digest), maximum_bytes=_MAX_BLOB_BYTES)
        if len(data) != size or _sha256(data) != digest or blob_ref.get("blobId") != f"sha256:{digest}":
            raise ArtifactRegistryError("ARTIFACT_BLOB_MISMATCH", "Blob integrity verification failed")
        return data

    def read_blob_prefix(
        self,
        blob_ref: Mapping[str, Any],
        *,
        maximum_prefix_bytes: int,
    ) -> tuple[bytes, bool]:
        """Verify a Blob by streaming it while retaining only a bounded prefix."""

        digest = blob_ref.get("sha256")
        size = blob_ref.get("sizeBytes")
        _validate_digest("blob.sha256", digest)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > _MAX_BLOB_BYTES:
            raise ArtifactRegistryError("ARTIFACT_BLOB_INVALID", "Blob size is invalid")
        if (
            isinstance(maximum_prefix_bytes, bool)
            or not isinstance(maximum_prefix_bytes, int)
            or maximum_prefix_bytes < 0
            or maximum_prefix_bytes > _MAX_BLOB_BYTES
        ):
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_INVALID", "Blob prefix limit is invalid"
            )
        if blob_ref.get("blobId") != f"sha256:{digest}":
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_MISMATCH", "Blob identity is invalid"
            )
        path = self._blob_path(digest)
        try:
            before = path.lstat()
        except OSError as error:
            raise ArtifactRegistryError(
                "ARTIFACT_NOT_FOUND", "Blob registry entry was not found"
            ) from error
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or getattr(before, "st_file_attributes", 0) & 0x400
            or before.st_nlink != 1
            or before.st_size != size
        ):
            raise ArtifactRegistryError(
                "ARTIFACT_STORAGE_UNSAFE", "Blob registry entry is unsafe"
            )
        builder = hashlib.sha256()
        retained = bytearray()
        total = 0
        try:
            with path.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_BLOB_BYTES:
                        raise ArtifactRegistryError(
                            "ARTIFACT_BLOB_TOO_LARGE", "Blob exceeds its size limit"
                        )
                    builder.update(chunk)
                    remaining = maximum_prefix_bytes - len(retained)
                    if remaining > 0:
                        retained.extend(chunk[:remaining])
        except OSError as error:
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_UNAVAILABLE", "Blob could not be read safely"
            ) from error
        try:
            after = path.lstat()
        except OSError as error:
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_CHANGED", "Blob changed while being read"
            ) from error
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_CHANGED", "Blob changed while being read"
            )
        if total != size or builder.hexdigest() != digest:
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_MISMATCH", "Blob integrity verification failed"
            )
        return bytes(retained), size > maximum_prefix_bytes

    def materialize_blob(
        self,
        blob_ref: Mapping[str, Any],
        destination: str | Path,
    ) -> dict[str, Any]:
        """Stream a verified private Blob to a new, caller-owned regular file."""

        digest = blob_ref.get("sha256")
        size = blob_ref.get("sizeBytes")
        _validate_digest("blob.sha256", digest)
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or size > _MAX_BLOB_BYTES
            or blob_ref.get("blobId") != f"sha256:{digest}"
        ):
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_INVALID", "Blob identity is invalid"
            )
        target = Path(destination)
        if not target.is_absolute():
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_DESTINATION_INVALID",
                "Blob destination must be absolute",
            )
        try:
            parent = target.parent.resolve(strict=True)
            parent_info = parent.lstat()
        except OSError as error:
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_DESTINATION_INVALID",
                "Blob destination parent is unavailable",
            ) from error
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or stat.S_ISLNK(parent_info.st_mode)
            or getattr(parent_info, "st_file_attributes", 0) & 0x400
            or target.parent.absolute() != parent
        ):
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_DESTINATION_INVALID",
                "Blob destination parent is unsafe",
            )
        source_path = self._blob_path(digest)
        try:
            before = source_path.lstat()
        except OSError as error:
            raise ArtifactRegistryError(
                "ARTIFACT_NOT_FOUND", "Blob registry entry was not found"
            ) from error
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or getattr(before, "st_file_attributes", 0) & 0x400
            or before.st_nlink != 1
            or before.st_size != size
        ):
            raise ArtifactRegistryError(
                "ARTIFACT_STORAGE_UNSAFE", "Blob registry entry is unsafe"
            )
        source_fd: int | None = None
        target_fd: int | None = None
        completed = False
        target_created = False
        total = 0
        builder = hashlib.sha256()
        try:
            source_flags = (
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOINHERIT", 0)
            )
            if hasattr(os, "O_NOFOLLOW"):
                source_flags |= os.O_NOFOLLOW
            source_fd = os.open(source_path, source_flags)
            opened = os.fstat(source_fd)
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
            ):
                raise ArtifactRegistryError(
                    "ARTIFACT_BLOB_CHANGED",
                    "Blob changed before materialization",
                )
            target_fd = os.open(
                target,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOINHERIT", 0),
                0o600,
            )
            target_created = True
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > size:
                    raise ArtifactRegistryError(
                        "ARTIFACT_BLOB_CHANGED",
                        "Blob grew during materialization",
                    )
                builder.update(chunk)
                offset = 0
                while offset < len(chunk):
                    written = os.write(target_fd, chunk[offset:])
                    if written <= 0:
                        raise ArtifactRegistryError(
                            "ARTIFACT_BLOB_WRITE_FAILED",
                            "Blob materialization stalled",
                        )
                    offset += written
            os.fsync(target_fd)
            after = os.fstat(source_fd)
            if (
                total != size
                or builder.hexdigest() != digest
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            ):
                raise ArtifactRegistryError(
                    "ARTIFACT_BLOB_MISMATCH",
                    "Blob integrity changed during materialization",
                )
            completed = True
        except FileExistsError as error:
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_DESTINATION_EXISTS",
                "Blob destination already exists",
            ) from error
        except ArtifactRegistryError:
            raise
        except OSError as error:
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_WRITE_FAILED",
                "Blob could not be materialized safely",
            ) from error
        finally:
            if source_fd is not None:
                os.close(source_fd)
            if target_fd is not None:
                os.close(target_fd)
            if not completed and target_created:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
        try:
            target_info = target.lstat()
        except OSError as error:
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_WRITE_FAILED",
                "Materialized Blob is unavailable",
            ) from error
        if (
            not stat.S_ISREG(target_info.st_mode)
            or stat.S_ISLNK(target_info.st_mode)
            or getattr(target_info, "st_file_attributes", 0) & 0x400
            or target_info.st_nlink != 1
            or target_info.st_size != size
        ):
            try:
                target.unlink()
            except OSError:
                pass
            raise ArtifactRegistryError(
                "ARTIFACT_BLOB_WRITE_FAILED",
                "Materialized Blob failed final verification",
            )
        return {"sha256": digest, "sizeBytes": size, "path": str(target)}
