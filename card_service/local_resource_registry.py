from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from .artifact_registry import ArtifactAudienceBinding, canonical_json_bytes


MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024 * 1024
MAX_DIRECTORY_BYTES = 64 * 1024 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 100_000
MAX_OUTPUT_FILES = 100_000
MAX_DEPTH = 32
MAX_USES = 4_096
MAX_USE_HISTORY = 4_096
MAX_LIFETIME = timedelta(hours=24)
MAX_SAFE_INTEGER = 9_007_199_254_740_991

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESOURCE_REF_RE = re.compile(r"^resource_[A-Za-z0-9_-]{43}$")
_WINDOWS_RESERVED = frozenset(
    {
        "CON", "PRN", "AUX", "NUL", "CLOCK$",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_SECRET_KEY_PARTS = (
    "apikey", "authorization", "accesstoken", "refreshtoken", "password",
    "secret", "credential", "cookie", "oauth", "bearertoken", "clientsecret",
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}\b", re.IGNORECASE),
)

RESOURCE_KINDS = frozenset({"file", "directory", "output_directory"})
RESOURCE_ACTIONS = {
    "file": frozenset({"read"}),
    "directory": frozenset({"enumerate", "read"}),
    "output_directory": frozenset({"create", "versioned", "replace"}),
}


class LocalResourceRegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResolvedLocalResource:
    resource_ref: str
    grant_id: str
    kind: str
    path: Path
    display_name: str
    resource_revision_digest: str
    revocation_epoch: int
    constraints: Mapping[str, Any]
    snapshot: Mapping[str, Any]
    resolution_proof: str

    def legacy_binding(
        self,
        *,
        json_pointer: str,
        raw_project_value: str,
        legacy_kind: str,
    ):
        from .legacy_project_projection import LegacyResourceBinding

        allowed = {
            "file": {"source_file", "media_file"},
            "directory": {"source_directory"},
            "output_directory": {"output_directory"},
        }
        if legacy_kind not in allowed[self.kind]:
            raise LocalResourceRegistryError(
                "RESOURCE_KIND_MISMATCH", "legacy resource kind exceeds the trusted grant"
            )
        normalized = _normalize_lexical_path(raw_project_value)
        if os.path.normcase(str(normalized)) != os.path.normcase(str(self.path)):
            raise LocalResourceRegistryError(
                "RESOURCE_PATH_MISMATCH", "legacy Project path does not match the trusted grant"
            )
        return LegacyResourceBinding(
            slot_id="slot-" + self.grant_id.rsplit("_", 1)[-1][:24],
            json_pointer=json_pointer,
            kind=legacy_kind,
            internal_resource_binding_id=self.grant_id,
            resource_revision_digest=self.resource_revision_digest,
            resource_value_digest=hashlib.sha256(raw_project_value.encode("utf-8")).hexdigest(),
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise LocalResourceRegistryError("RESOURCE_TIME_INVALID", "timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LocalResourceRegistryError("RESOURCE_TIME_INVALID", f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise LocalResourceRegistryError("RESOURCE_TIME_INVALID", f"{label} is invalid") from error
    return parsed.astimezone(timezone.utc)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise LocalResourceRegistryError("RESOURCE_SCHEMA_INVALID", f"{label} is invalid")
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise LocalResourceRegistryError("RESOURCE_SCHEMA_INVALID", f"{label} must be a SHA-256 digest")
    return value


def _require_integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise LocalResourceRegistryError("RESOURCE_SCHEMA_INVALID", f"{label} is outside its allowed range")
    return value


def _exact(value: Any, required: set[str], optional: set[str], label: str) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or not required.issubset(value)
        or not set(value).issubset(required | optional)
    ):
        raise LocalResourceRegistryError("RESOURCE_SCHEMA_INVALID", f"{label} fields are invalid")
    return dict(value)


def _validate_no_secrets(value: Any, *, allow_raw_path: bool = False, trail: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise LocalResourceRegistryError("RESOURCE_SCHEMA_INVALID", "resource record keys must be text")
            normalized = _normalized_key(key)
            if any(part in normalized for part in _SECRET_KEY_PARTS):
                raise LocalResourceRegistryError(
                    "RESOURCE_SECRET_FORBIDDEN",
                    f"secret-bearing field at {'.'.join(trail + (key,))}",
                )
            _validate_no_secrets(
                child,
                allow_raw_path=allow_raw_path and key == "rawPath",
                trail=trail + (key,),
            )
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_no_secrets(child, trail=trail + (str(index),))
        return
    if isinstance(value, str) and not allow_raw_path:
        if any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
            raise LocalResourceRegistryError(
                "RESOURCE_SECRET_FORBIDDEN",
                f"credential-like value at {'.'.join(trail)}",
            )


def _safe_display_name(value: str, kind: str) -> str:
    fallback = {
        "file": "Selected file",
        "directory": "Selected folder",
        "output_directory": "Selected output folder",
    }[kind]
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 240
        or any(ord(character) < 0x20 or character in "/\\" for character in value)
        or any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)
    ):
        return fallback
    return value


def _has_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _normalize_lexical_path(value: str | os.PathLike[str]) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise LocalResourceRegistryError("RESOURCE_PATH_INVALID", "resource path is invalid")
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or any(ord(character) < 0x20 for character in raw):
        raise LocalResourceRegistryError("RESOURCE_PATH_INVALID", "resource path is invalid")
    if raw.startswith(("\\\\", "//", "\\?\\", "\\.\\")):
        raise LocalResourceRegistryError("RESOURCE_PATH_INVALID", "UNC and device paths are forbidden")
    path = Path(raw)
    if not path.is_absolute():
        raise LocalResourceRegistryError("RESOURCE_PATH_INVALID", "resource path must be absolute")
    normalized = Path(os.path.normpath(os.path.abspath(raw)))
    drive = normalized.drive
    remainder = str(normalized)[len(drive):]
    if ":" in remainder:
        raise LocalResourceRegistryError("RESOURCE_PATH_INVALID", "alternate data streams are forbidden")
    if os.name == "nt":
        for part in normalized.parts[1:]:
            if part.endswith((" ", ".")):
                raise LocalResourceRegistryError("RESOURCE_PATH_INVALID", "trailing spaces and dots are forbidden")
            stem = part.split(".", 1)[0].upper()
            if stem in _WINDOWS_RESERVED:
                raise LocalResourceRegistryError("RESOURCE_PATH_INVALID", "Windows reserved path names are forbidden")
    return normalized

def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or _has_reparse(info):
        raise LocalResourceRegistryError(
            "RESOURCE_STORAGE_UNSAFE", "resource registry storage contains a link or reparse directory"
        )
    return path


def _temporary_file(path: Path, data: bytes) -> Path:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.partial"
    with temporary.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return temporary


def _validate_path_chain(path: Path) -> os.stat_result:
    anchor = Path(path.anchor)
    current = anchor
    try:
        root_info = current.lstat()
    except OSError as error:
        raise LocalResourceRegistryError("RESOURCE_PATH_UNAVAILABLE", "resource path is unavailable") from error
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode) or _has_reparse(root_info):
        raise LocalResourceRegistryError("RESOURCE_PATH_UNSAFE", "resource path traverses a link or reparse point")
    info = root_info
    for part in path.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except OSError as error:
            raise LocalResourceRegistryError("RESOURCE_PATH_UNAVAILABLE", "resource path is unavailable") from error
        if stat.S_ISLNK(info.st_mode) or _has_reparse(info):
            raise LocalResourceRegistryError(
                "RESOURCE_PATH_UNSAFE", "resource path traverses a link or reparse point"
            )
    return info


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _file_snapshot(path: Path) -> dict[str, Any]:
    before = _validate_path_chain(path)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or _has_reparse(before)
        or before.st_nlink != 1
    ):
        raise LocalResourceRegistryError(
            "RESOURCE_FILE_UNSAFE", "selected resource is not a private regular file"
        )
    if before.st_size < 0 or before.st_size > MAX_FILE_BYTES:
        raise LocalResourceRegistryError("RESOURCE_FILE_TOO_LARGE", "selected file exceeds its size limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    read_bytes = 0
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise LocalResourceRegistryError("RESOURCE_PATH_UNAVAILABLE", "selected file cannot be opened") from error
    try:
        descriptor_info = os.fstat(descriptor)
        if (
            _identity(before) != _identity(descriptor_info)
            or not stat.S_ISREG(descriptor_info.st_mode)
            or descriptor_info.st_nlink != 1
        ):
            raise LocalResourceRegistryError("RESOURCE_CHANGED", "selected file changed during authorization")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            read_bytes += len(chunk)
            if read_bytes > MAX_FILE_BYTES:
                raise LocalResourceRegistryError("RESOURCE_FILE_TOO_LARGE", "selected file exceeds its size limit")
            digest.update(chunk)
    finally:
        os.close(descriptor)
    after = _validate_path_chain(path)
    if _identity(before) != _identity(after) or read_bytes != before.st_size:
        raise LocalResourceRegistryError("RESOURCE_CHANGED", "selected file changed during authorization")
    return {
        "type": "file",
        "stDev": str(before.st_dev),
        "stIno": str(before.st_ino),
        "sizeBytes": read_bytes,
        "mtimeNs": str(before.st_mtime_ns),
        "sha256": digest.hexdigest(),
    }


def _directory_snapshot(path: Path, kind: str) -> dict[str, Any]:
    info = _validate_path_chain(path)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or _has_reparse(info):
        raise LocalResourceRegistryError("RESOURCE_DIRECTORY_UNSAFE", "selected resource is not a safe directory")
    snapshot = {
        "type": kind,
        "stDev": str(info.st_dev),
        "stIno": str(info.st_ino),
    }
    if kind == "directory":
        snapshot["mtimeNs"] = str(info.st_mtime_ns)
    return snapshot


def _snapshot(path: Path, kind: str) -> tuple[dict[str, Any], str]:
    value = _file_snapshot(path) if kind == "file" else _directory_snapshot(path, kind)
    return value, _sha(canonical_json_bytes(value))


def _normalize_actions(value: Any, kind: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LocalResourceRegistryError("RESOURCE_CONSTRAINT_INVALID", "actions must be a list")
    actions = list(value)
    if (
        not actions
        or len(actions) != len(set(actions))
        or any(not isinstance(action, str) or action not in RESOURCE_ACTIONS[kind] for action in actions)
    ):
        raise LocalResourceRegistryError("RESOURCE_CONSTRAINT_INVALID", "actions exceed the selected resource grant")
    return sorted(actions, key=lambda action: action.encode("utf-8"))


def _normalize_constraints(kind: str, value: Mapping[str, Any], *, file_size: int | None) -> dict[str, Any]:
    if kind == "file":
        source = _exact(value, {"actions", "maxBytes"}, set(), "file constraints")
        maximum = _require_integer(source["maxBytes"], "maxBytes", minimum=1, maximum=MAX_FILE_BYTES)
        if file_size is not None and maximum < file_size:
            raise LocalResourceRegistryError(
                "RESOURCE_CONSTRAINT_INVALID", "file byte limit is smaller than the selected file"
            )
        return {"actions": _normalize_actions(source["actions"], kind), "maxBytes": maximum}
    if kind == "directory":
        source = _exact(
            value, {"actions", "maxDepth", "maxEntries", "maxTotalBytes"}, set(), "directory constraints"
        )
        return {
            "actions": _normalize_actions(source["actions"], kind),
            "maxDepth": _require_integer(source["maxDepth"], "maxDepth", minimum=0, maximum=MAX_DEPTH),
            "maxEntries": _require_integer(
                source["maxEntries"], "maxEntries", minimum=1, maximum=MAX_DIRECTORY_ENTRIES
            ),
            "maxTotalBytes": _require_integer(
                source["maxTotalBytes"], "maxTotalBytes", minimum=1, maximum=MAX_DIRECTORY_BYTES
            ),
        }
    source = _exact(
        value, {"actions", "maxFiles", "maxTotalBytes"}, set(), "output directory constraints"
    )
    return {
        "actions": _normalize_actions(source["actions"], kind),
        "maxFiles": _require_integer(source["maxFiles"], "maxFiles", minimum=1, maximum=MAX_OUTPUT_FILES),
        "maxTotalBytes": _require_integer(
            source["maxTotalBytes"], "maxTotalBytes", minimum=1, maximum=MAX_OUTPUT_BYTES
        ),
    }


def _constraints_are_narrower(candidate: Mapping[str, Any], granted: Mapping[str, Any]) -> bool:
    if set(candidate) != set(granted):
        return False
    if not set(candidate["actions"]).issubset(granted["actions"]):
        return False
    return all(
        key == "actions"
        or (
            isinstance(candidate[key], int)
            and not isinstance(candidate[key], bool)
            and candidate[key] <= granted[key]
        )
        for key in granted
    )


def _validate_audience(audience: ArtifactAudienceBinding) -> None:
    if not isinstance(audience, ArtifactAudienceBinding):
        raise LocalResourceRegistryError("RESOURCE_AUDIENCE_INVALID", "trusted audience binding is required")
    _require_digest(audience.owner_digest, "ownerDigest")
    _require_id(audience.host_id, "hostInstanceId")
    _require_id(audience.plugin_id, "pluginInstanceId")
    _require_id(audience.session_id, "sessionId")


def _validate_reference(value: Any) -> str:
    if not isinstance(value, str) or not _RESOURCE_REF_RE.fullmatch(value):
        raise LocalResourceRegistryError("RESOURCE_REF_INVALID", "resource reference is invalid")
    return value


def _validate_opaque_input(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 512
        or any(ord(character) < 0x20 for character in value)
        or any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)
    ):
        raise LocalResourceRegistryError("RESOURCE_REQUEST_INVALID", f"{label} is invalid")
    return value


def _record_state(record: Mapping[str, Any], now: datetime) -> str:
    if record["revoked"]:
        return "revoked"
    if now >= _parse_timestamp(record["expiresAt"], "expiresAt"):
        return "expired"
    if record["useCount"] >= record["maxUses"]:
        return "exhausted"
    return "active"


def _public_summary(record: Mapping[str, Any], resource_ref: str, now: datetime) -> dict[str, Any]:
    return {
        "schema": "study.local-resource.summary",
        "schemaVersion": 1,
        "resourceRef": resource_ref,
        "kind": record["kind"],
        "displayName": record["displayName"],
        "actions": list(record["constraints"]["actions"]),
        "constraints": json.loads(json.dumps(record["constraints"])),
        "resourceRevisionDigest": record["resourceRevisionDigest"],
        "expiresAt": record["expiresAt"],
        "state": _record_state(record, now),
        "revocationEpoch": record["revocationEpoch"],
        "remainingUses": max(0, record["maxUses"] - record["useCount"]),
    }


class LocalResourceGrantRegistry:
    """Authenticated, session-bound grants for local files and directories.

    Raw paths exist only in the private authenticated ledger. Public callers receive
    opaque references and redacted summaries; a reference cannot be resolved without
    the exact trusted audience and Card Service instance that approved it.
    """

    def __init__(
        self,
        root: Path,
        *,
        authentication_key: bytes,
        service_instance_id: str,
        key_id: str = "study-local-resource-v1",
        gesture_verifier: Callable[[str, str, str, str], bool] | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise LocalResourceRegistryError(
                "RESOURCE_AUTH_KEY_INVALID", "resource authentication key must contain at least 256 bits"
            )
        self._authentication_key = bytes(authentication_key)
        self._service_instance_id = _require_id(service_instance_id, "serviceInstanceId")
        self._key_id = _require_id(key_id, "keyId")
        if gesture_verifier is not None and not callable(gesture_verifier):
            raise LocalResourceRegistryError(
                "RESOURCE_GESTURE_VERIFIER_INVALID", "trusted gesture verifier is invalid"
            )
        if not callable(clock):
            raise LocalResourceRegistryError("RESOURCE_CLOCK_INVALID", "resource clock is invalid")
        self._gesture_verifier = gesture_verifier
        self._clock = clock
        self._root = _ensure_directory(Path(root).absolute())
        self._records_root = _ensure_directory(self._root / "records")
        self._bindings_root = _ensure_directory(self._root / "bindings")
        self._lock_path = self._root / "local-resources.lock"
        try:
            with self._lock_path.open("xb") as output:
                output.write(b"\x00")
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            pass
        self._thread_lock = threading.RLock()

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise LocalResourceRegistryError("RESOURCE_CLOCK_INVALID", "resource clock returned an invalid time")
        return value.astimezone(timezone.utc)

    def _ensure_parent(self, path: Path) -> None:
        try:
            relative = path.absolute().relative_to(self._root)
        except ValueError as error:
            raise LocalResourceRegistryError(
                "RESOURCE_STORAGE_UNSAFE", "resource registry path escapes its storage root"
            ) from error
        current = _ensure_directory(self._root)
        for part in relative.parts:
            current = _ensure_directory(current / part)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._thread_lock:
            info = self._lock_path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or _has_reparse(info)
                or info.st_nlink != 1
            ):
                raise LocalResourceRegistryError(
                    "RESOURCE_STORAGE_UNSAFE", "resource registry lock is not a private regular file"
                )
            with self._lock_path.open("r+b") as lock_file:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _mac(self, domain: str, value: Mapping[str, Any] | bytes) -> str:
        payload = value if isinstance(value, bytes) else canonical_json_bytes(dict(value))
        return hmac.new(
            self._authentication_key, domain.encode("ascii") + b"\x00" + payload, hashlib.sha256
        ).hexdigest()

    def _audience_digest(self, audience: ArtifactAudienceBinding) -> str:
        _validate_audience(audience)
        return _sha(canonical_json_bytes(audience.audience(self._service_instance_id)))

    def _opaque_digest(self, domain: str, value: str) -> str:
        return self._mac(domain, value.encode("utf-8"))

    def _derive_grant_id(self, audience_digest: str, request_id: str) -> str:
        digest = self._mac(
            "study.local-resource.grant-id.v1",
            audience_digest.encode("ascii") + b"\x00" + request_id.encode("utf-8"),
        )
        return "localgrant_" + digest[:48]

    def _derive_resource_ref(self, grant_id: str) -> str:
        raw = hmac.new(
            self._authentication_key,
            b"study.local-resource.ref.v1\x00" + grant_id.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return "resource_" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _record_path(self, grant_id: str) -> Path:
        identity = _sha(_require_id(grant_id, "grantId").encode("ascii"))
        return self._records_root / identity[:2] / f"{identity}.json"

    def _binding_path(self, resource_ref: str) -> Path:
        identity = _sha(_validate_reference(resource_ref).encode("ascii"))
        return self._bindings_root / identity[:2] / f"{identity}.json"

    def _safe_read(self, path: Path) -> bytes:
        self._ensure_parent(path.parent)
        try:
            info = path.lstat()
        except FileNotFoundError as error:
            raise LocalResourceRegistryError("RESOURCE_NOT_FOUND", "resource grant was not found") from error
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or _has_reparse(info)
            or info.st_nlink != 1
            or info.st_size > MAX_RECORD_BYTES
        ):
            raise LocalResourceRegistryError(
                "RESOURCE_STORAGE_UNSAFE", "resource registry entry is unsafe or too large"
            )
        raw = path.read_bytes()
        after = path.lstat()
        if len(raw) != info.st_size or _identity(info) != _identity(after):
            raise LocalResourceRegistryError("RESOURCE_RECORD_CHANGED", "resource record changed while being read")
        return raw

    def _decode_json(self, raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource record is not valid JSON") from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource record is not canonical JSON")
        return value

    def _authenticate_record(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**dict(value), "authKeyId": self._key_id}
        return {**unsigned, "authTag": self._mac("study.local-resource.record.v1", unsigned)}

    def _authenticate_binding(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**dict(value), "authKeyId": self._key_id}
        return {**unsigned, "authTag": self._mac("study.local-resource.binding.v1", unsigned)}

    def _validate_record(self, value: Mapping[str, Any]) -> dict[str, Any]:
        record = _exact(
            value,
            {
                "schema", "schemaVersion", "grantId", "kind", "audienceDigest", "rawPath",
                "displayName", "resourceRevisionDigest", "snapshot", "constraints",
                "requestDigest", "attestationDigest", "issuedAt", "expiresAt", "maxUses",
                "useCount", "useHistory", "revoked", "revocationEpoch", "revokeDigest",
                "revokeAttestationDigest", "revokedAt", "revision", "authKeyId", "authTag",
            },
            set(),
            "resource record",
        )
        if record["schema"] != "study.local-resource.record" or record["schemaVersion"] != 1:
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource record schema is invalid")
        tag = record["authTag"]
        unsigned = dict(record)
        unsigned.pop("authTag")
        if (
            record["authKeyId"] != self._key_id
            or not isinstance(tag, str)
            or not _SHA256_RE.fullmatch(tag)
            or not hmac.compare_digest(tag, self._mac("study.local-resource.record.v1", unsigned))
        ):
            raise LocalResourceRegistryError("RESOURCE_RECORD_CORRUPT", "resource record authentication failed")
        _validate_no_secrets(record, allow_raw_path=True)
        _require_id(record["grantId"], "grantId")
        if record["kind"] not in RESOURCE_KINDS:
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource kind is invalid")
        _require_digest(record["audienceDigest"], "audienceDigest")
        raw_path = record["rawPath"]
        if not isinstance(raw_path, str) or str(_normalize_lexical_path(raw_path)) != raw_path:
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "stored resource path is invalid")
        if record["displayName"] != _safe_display_name(Path(raw_path).name, record["kind"]):
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource display name is invalid")
        _require_digest(record["resourceRevisionDigest"], "resourceRevisionDigest")
        _require_digest(record["requestDigest"], "requestDigest")
        _require_digest(record["attestationDigest"], "attestationDigest")
        snapshot = record["snapshot"]
        if not isinstance(snapshot, Mapping):
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource snapshot is invalid")
        if record["kind"] == "file":
            expected_snapshot_fields = {"type", "stDev", "stIno", "sizeBytes", "mtimeNs", "sha256"}
            identity_fields = ("stDev", "stIno", "mtimeNs")
        elif record["kind"] == "directory":
            expected_snapshot_fields = {"type", "stDev", "stIno", "mtimeNs"}
            identity_fields = ("stDev", "stIno", "mtimeNs")
        else:
            expected_snapshot_fields = {"type", "stDev", "stIno"}
            identity_fields = ("stDev", "stIno")
        if set(snapshot) != expected_snapshot_fields or snapshot.get("type") != record["kind"]:
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource snapshot fields are invalid")
        if not all(
            isinstance(snapshot.get(key), str) and snapshot[key].isdigit()
            for key in identity_fields
        ):
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource snapshot identity is invalid")
        file_size: int | None = None
        if record["kind"] == "file":
            file_size = _require_integer(
                snapshot["sizeBytes"], "sizeBytes", minimum=0, maximum=MAX_FILE_BYTES
            )
            _require_digest(snapshot["sha256"], "snapshot.sha256")
        if _sha(canonical_json_bytes(dict(snapshot))) != record["resourceRevisionDigest"]:
            raise LocalResourceRegistryError("RESOURCE_RECORD_CORRUPT", "resource snapshot digest is invalid")
        normalized_constraints = _normalize_constraints(
            record["kind"], record["constraints"], file_size=file_size
        )
        if record["constraints"] != normalized_constraints:
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource constraints are not canonical")
        issued = _parse_timestamp(record["issuedAt"], "issuedAt")
        expires = _parse_timestamp(record["expiresAt"], "expiresAt")
        if not issued < expires or expires - issued > MAX_LIFETIME:
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource grant lifetime is invalid")
        maximum_uses = _require_integer(record["maxUses"], "maxUses", minimum=1, maximum=MAX_USES)
        use_count = _require_integer(record["useCount"], "useCount", minimum=0, maximum=maximum_uses)
        if (
            not isinstance(record["useHistory"], list)
            or len(record["useHistory"]) != use_count
            or len(record["useHistory"]) > MAX_USE_HISTORY
        ):
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource use history is invalid")
        seen_uses: set[str] = set()
        previous_use_time = issued
        for entry in record["useHistory"]:
            item = _exact(
                entry, {"useDigest", "requestDigest", "action", "usedAt"}, set(), "resource use"
            )
            use_digest = _require_digest(item["useDigest"], "useDigest")
            if use_digest in seen_uses:
                raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource use is duplicated")
            seen_uses.add(use_digest)
            _require_digest(item["requestDigest"], "use.requestDigest")
            if item["action"] not in record["constraints"]["actions"]:
                raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource use action is invalid")
            used_at = _parse_timestamp(item["usedAt"], "usedAt")
            if used_at < previous_use_time or used_at >= expires:
                raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource use time is invalid")
            previous_use_time = used_at
        if not isinstance(record["revoked"], bool):
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource revoked state is invalid")
        epoch = _require_integer(record["revocationEpoch"], "revocationEpoch", minimum=0, maximum=1)
        if record["revoked"] != (epoch == 1):
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource revocation state is inconsistent")
        if record["revoked"]:
            _require_digest(record["revokeDigest"], "revokeDigest")
            _require_digest(record["revokeAttestationDigest"], "revokeAttestationDigest")
            revoked_at = _parse_timestamp(record["revokedAt"], "revokedAt")
            if revoked_at < issued:
                raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource revocation time is invalid")
        elif any(
            record[field] is not None
            for field in ("revokeDigest", "revokeAttestationDigest", "revokedAt")
        ):
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource revocation audit is invalid")
        revision = _require_integer(record["revision"], "revision", minimum=1, maximum=MAX_SAFE_INTEGER)
        if revision != 1 + use_count + epoch:
            raise LocalResourceRegistryError("RESOURCE_RECORD_INVALID", "resource revision is inconsistent")
        return record

    def _validate_binding(
        self, value: Mapping[str, Any], resource_ref: str, audience_digest: str
    ) -> dict[str, Any]:
        binding = _exact(
            value,
            {
                "schema", "schemaVersion", "resourceRefDigest", "grantId", "audienceDigest",
                "authKeyId", "authTag",
            },
            set(),
            "resource binding",
        )
        if binding["schema"] != "study.local-resource.binding" or binding["schemaVersion"] != 1:
            raise LocalResourceRegistryError("RESOURCE_BINDING_INVALID", "resource binding schema is invalid")
        tag = binding["authTag"]
        unsigned = dict(binding)
        unsigned.pop("authTag")
        if (
            binding["authKeyId"] != self._key_id
            or not isinstance(tag, str)
            or not _SHA256_RE.fullmatch(tag)
            or not hmac.compare_digest(tag, self._mac("study.local-resource.binding.v1", unsigned))
        ):
            raise LocalResourceRegistryError("RESOURCE_BINDING_CORRUPT", "resource binding authentication failed")
        if binding["resourceRefDigest"] != _sha(resource_ref.encode("ascii")):
            raise LocalResourceRegistryError("RESOURCE_BINDING_MISMATCH", "resource reference binding is invalid")
        if binding["audienceDigest"] != audience_digest:
            raise LocalResourceRegistryError(
                "RESOURCE_AUDIENCE_MISMATCH", "resource grant belongs to another trusted session"
            )
        _require_id(binding["grantId"], "grantId")
        return binding

    def _load_record(self, grant_id: str) -> tuple[dict[str, Any], bytes]:
        raw = self._safe_read(self._record_path(grant_id))
        return self._validate_record(self._decode_json(raw)), raw

    def _load_binding(
        self, resource_ref: str, audience_digest: str
    ) -> dict[str, Any]:
        raw = self._safe_read(self._binding_path(resource_ref))
        return self._validate_binding(self._decode_json(raw), resource_ref, audience_digest)

    def _publish_new(self, path: Path, raw: bytes) -> None:
        self._ensure_parent(path.parent)
        temporary = _temporary_file(path, raw)
        try:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise LocalResourceRegistryError(
                    "RESOURCE_ALREADY_EXISTS", "resource registry entry already exists"
                ) from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _replace(self, path: Path, raw: bytes, previous_raw: bytes) -> None:
        self._ensure_parent(path.parent)
        backup = path.with_suffix(path.suffix + ".bak")
        backup_temp = _temporary_file(backup, previous_raw)
        current_temp = _temporary_file(path, raw)
        try:
            os.replace(backup_temp, backup)
            os.replace(current_temp, path)
        finally:
            for temporary in (backup_temp, current_temp):
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def _verify_gesture(
        self,
        *,
        audience_digest: str,
        request_digest: str,
        attestation_ref: str,
        action: str,
    ) -> str:
        attestation_ref = _validate_opaque_input(attestation_ref, "attestationRef")
        if self._gesture_verifier is None:
            raise LocalResourceRegistryError(
                "RESOURCE_GESTURE_REQUIRED", "trusted user gesture verification is unavailable"
            )
        try:
            verified = self._gesture_verifier(
                audience_digest, request_digest, attestation_ref, action
            )
        except Exception as error:
            raise LocalResourceRegistryError(
                "RESOURCE_GESTURE_FAILED", "trusted user gesture verification failed"
            ) from error
        if verified is not True:
            raise LocalResourceRegistryError(
                "RESOURCE_GESTURE_REQUIRED", "a current trusted user gesture is required"
            )
        return self._opaque_digest("study.local-resource.attestation.v1", attestation_ref)

    @staticmethod
    def _authorize_record(record: Mapping[str, Any], audience_digest: str) -> None:
        if record["audienceDigest"] != audience_digest:
            raise LocalResourceRegistryError(
                "RESOURCE_AUDIENCE_MISMATCH", "resource grant belongs to another trusted session"
            )

    def _resolve_record(
        self, resource_ref: str, audience: ArtifactAudienceBinding
    ) -> tuple[str, dict[str, Any], bytes]:
        resource_ref = _validate_reference(resource_ref)
        audience_digest = self._audience_digest(audience)
        binding = self._load_binding(resource_ref, audience_digest)
        record, raw = self._load_record(binding["grantId"])
        self._authorize_record(record, audience_digest)
        return resource_ref, record, raw
    def _resolution_proof(
        self,
        *,
        resource_ref: str,
        grant_id: str,
        kind: str,
        resource_revision_digest: str,
        path: Path,
        revocation_epoch: int,
        constraints: Mapping[str, Any],
        snapshot: Mapping[str, Any],
    ) -> str:
        return self._mac(
            "study.local-resource.resolution.v1",
            {
                "resourceRefDigest": self._opaque_digest(
                    "study.local-resource.resolved-ref.v1", resource_ref
                ),
                "grantId": grant_id,
                "kind": kind,
                "resourceRevisionDigest": resource_revision_digest,
                "revocationEpoch": revocation_epoch,
                "constraints": dict(constraints),
                "pathDigest": self._opaque_digest(
                    "study.local-resource.resolved-path.v1", str(path)
                ),
                "snapshot": dict(snapshot),
                "serviceInstanceId": self._service_instance_id,
            },
        )

    def _resolved(
        self,
        *,
        resource_ref: str,
        record: Mapping[str, Any],
        path: Path,
        constraints: Mapping[str, Any],
    ) -> ResolvedLocalResource:
        snapshot = json.loads(json.dumps(record["snapshot"]))
        effective_constraints = json.loads(json.dumps(dict(constraints)))
        return ResolvedLocalResource(
            resource_ref=resource_ref,
            grant_id=record["grantId"],
            kind=record["kind"],
            path=path,
            display_name=record["displayName"],
            resource_revision_digest=record["resourceRevisionDigest"],
            revocation_epoch=record["revocationEpoch"],
            constraints=effective_constraints,
            snapshot=snapshot,
            resolution_proof=self._resolution_proof(
                resource_ref=resource_ref,
                grant_id=record["grantId"],
                kind=record["kind"],
                resource_revision_digest=record["resourceRevisionDigest"],
                revocation_epoch=record["revocationEpoch"],
                path=path,
                constraints=effective_constraints,
                snapshot=snapshot,
            ),
        )

    def assert_resolution_active(
        self,
        resource: ResolvedLocalResource,
        audience: ArtifactAudienceBinding,
        *,
        required_action: str | None = None,
    ) -> None:
        if not isinstance(resource, ResolvedLocalResource):
            raise LocalResourceRegistryError(
                "RESOURCE_RESOLUTION_INVALID", "resolved local resource is invalid"
            )
        expected_proof = self._resolution_proof(
            resource_ref=resource.resource_ref,
            grant_id=resource.grant_id,
            kind=resource.kind,
            resource_revision_digest=resource.resource_revision_digest,
            revocation_epoch=resource.revocation_epoch,
            path=resource.path,
            constraints=resource.constraints,
            snapshot=resource.snapshot,
        )
        if not hmac.compare_digest(resource.resolution_proof, expected_proof):
            raise LocalResourceRegistryError(
                "RESOURCE_RESOLUTION_INVALID", "resolved local resource proof is invalid"
            )
        with self._transaction():
            normalized_ref, record, _ = self._resolve_record(resource.resource_ref, audience)
            if (
                normalized_ref != resource.resource_ref
                or record["grantId"] != resource.grant_id
                or record["kind"] != resource.kind
                or record["resourceRevisionDigest"] != resource.resource_revision_digest
                or record["snapshot"] != dict(resource.snapshot)
            ):
                raise LocalResourceRegistryError(
                    "RESOURCE_RESOLUTION_INVALID",
                    "resolved local resource no longer matches its authenticated grant",
                )
            state = _record_state(record, self._now())
            if record["revocationEpoch"] != resource.revocation_epoch:
                raise LocalResourceRegistryError(
                    "RESOURCE_REVOCATION_CHANGED", "resource revocation epoch changed"
                )
            if state == "revoked":
                raise LocalResourceRegistryError(
                    "RESOURCE_REVOKED", "resource grant has been revoked"
                )
            if state == "expired":
                raise LocalResourceRegistryError(
                    "RESOURCE_EXPIRED", "resource grant has expired"
                )
            if required_action is not None and required_action not in record["constraints"]["actions"]:
                raise LocalResourceRegistryError(
                    "RESOURCE_ACTION_FORBIDDEN", "resource action exceeds the approved grant"
                )
            if not _constraints_are_narrower(resource.constraints, record["constraints"]):
                raise LocalResourceRegistryError(
                    "RESOURCE_CONSTRAINT_FORBIDDEN",
                    "resolved resource constraints exceed the approved grant",
                )
            normalized_path = _normalize_lexical_path(record["rawPath"])
            if os.path.normcase(str(normalized_path)) != os.path.normcase(str(resource.path)):
                raise LocalResourceRegistryError(
                    "RESOURCE_PATH_MISMATCH", "resolved local resource path changed"
                )
            current_snapshot, current_digest = _snapshot(normalized_path, record["kind"])
            if (
                current_snapshot != record["snapshot"]
                or current_digest != record["resourceRevisionDigest"]
            ):
                raise LocalResourceRegistryError(
                    "RESOURCE_CHANGED", "resource changed after user authorization"
                )



    def issue_grant(
        self,
        *,
        audience: ArtifactAudienceBinding,
        grant_request_id: str,
        raw_path: str | os.PathLike[str],
        kind: str,
        constraints: Mapping[str, Any],
        attestation_ref: str,
        expires_at: datetime | str | None = None,
        max_uses: int = 1,
    ) -> dict[str, Any]:
        audience_digest = self._audience_digest(audience)
        request_id = _validate_opaque_input(grant_request_id, "grantRequestId")
        if kind not in RESOURCE_KINDS:
            raise LocalResourceRegistryError("RESOURCE_KIND_INVALID", "resource kind is unsupported")
        normalized_path = _normalize_lexical_path(raw_path)
        try:
            normalized_path.relative_to(self._root)
        except ValueError:
            pass
        else:
            raise LocalResourceRegistryError(
                "RESOURCE_PATH_UNSAFE", "resource registry storage cannot authorize itself"
            )
        grant_id = self._derive_grant_id(audience_digest, request_id)
        resource_ref = self._derive_resource_ref(grant_id)
        record_path = self._record_path(grant_id)

        existing: dict[str, Any] | None = None
        with self._transaction():
            try:
                existing, _ = self._load_record(grant_id)
                self._authorize_record(existing, audience_digest)
            except LocalResourceRegistryError as error:
                if error.code != "RESOURCE_NOT_FOUND":
                    raise
        current_snapshot, resource_revision_digest = _snapshot(normalized_path, kind)
        file_size = current_snapshot.get("sizeBytes") if kind == "file" else None
        normalized_constraints = _normalize_constraints(kind, constraints, file_size=file_size)
        maximum_uses = _require_integer(max_uses, "maxUses", minimum=1, maximum=MAX_USES)
        now = self._now()
        if expires_at is None and existing is not None:
            expires = _parse_timestamp(existing["expiresAt"], "expiresAt")
        elif expires_at is None:
            expires = now + timedelta(minutes=15)
        elif isinstance(expires_at, str):
            expires = _parse_timestamp(expires_at, "expiresAt")
        elif isinstance(expires_at, datetime) and expires_at.tzinfo is not None:
            expires = expires_at.astimezone(timezone.utc)
        else:
            raise LocalResourceRegistryError("RESOURCE_TIME_INVALID", "expiresAt is invalid")
        if existing is None and (expires <= now or expires - now > MAX_LIFETIME):
            raise LocalResourceRegistryError(
                "RESOURCE_TIME_INVALID", "resource grant must expire within the next 24 hours"
            )
        expires_text = _timestamp(expires)
        request_manifest = {
            "schema": "study.local-resource.grant-request",
            "schemaVersion": 1,
            "audienceDigest": audience_digest,
            "grantId": grant_id,
            "kind": kind,
            "pathDigest": self._opaque_digest(
                "study.local-resource.path.v1", os.path.normcase(str(normalized_path))
            ),
            "resourceRevisionDigest": resource_revision_digest,
            "constraints": normalized_constraints,
            "expiresAt": expires_text,
            "maxUses": maximum_uses,
        }
        request_digest = _sha(canonical_json_bytes(request_manifest))

        if existing is not None:
            if existing["requestDigest"] != request_digest:
                raise LocalResourceRegistryError(
                    "RESOURCE_IDEMPOTENCY_CONFLICT",
                    "grantRequestId was already used for a different resource grant",
                )
            with self._transaction():
                current, _ = self._load_record(grant_id)
                self._authorize_record(current, audience_digest)
                if current["requestDigest"] != request_digest:
                    raise LocalResourceRegistryError(
                        "RESOURCE_IDEMPOTENCY_CONFLICT",
                        "grantRequestId was already used for a different resource grant",
                    )
                try:
                    self._load_binding(resource_ref, audience_digest)
                except LocalResourceRegistryError as error:
                    if error.code != "RESOURCE_NOT_FOUND":
                        raise
                    binding = self._authenticate_binding(
                        {
                            "schema": "study.local-resource.binding",
                            "schemaVersion": 1,
                            "resourceRefDigest": _sha(resource_ref.encode("ascii")),
                            "grantId": grant_id,
                            "audienceDigest": audience_digest,
                        }
                    )
                    self._publish_new(
                        self._binding_path(resource_ref), canonical_json_bytes(binding)
                    )
                return _public_summary(current, resource_ref, now)

        attestation_digest = self._verify_gesture(
            audience_digest=audience_digest,
            request_digest=request_digest,
            attestation_ref=attestation_ref,
            action="approve_local_resource",
        )
        unsigned_record = {
            "schema": "study.local-resource.record",
            "schemaVersion": 1,
            "grantId": grant_id,
            "kind": kind,
            "audienceDigest": audience_digest,
            "rawPath": str(normalized_path),
            "displayName": _safe_display_name(normalized_path.name, kind),
            "resourceRevisionDigest": resource_revision_digest,
            "snapshot": current_snapshot,
            "constraints": normalized_constraints,
            "requestDigest": request_digest,
            "attestationDigest": attestation_digest,
            "issuedAt": _timestamp(now),
            "expiresAt": expires_text,
            "maxUses": maximum_uses,
            "useCount": 0,
            "useHistory": [],
            "revoked": False,
            "revocationEpoch": 0,
            "revokeDigest": None,
            "revokeAttestationDigest": None,
            "revokedAt": None,
            "revision": 1,
        }
        _validate_no_secrets(unsigned_record, allow_raw_path=True)
        record = self._authenticate_record(unsigned_record)
        self._validate_record(record)
        binding = self._authenticate_binding(
            {
                "schema": "study.local-resource.binding",
                "schemaVersion": 1,
                "resourceRefDigest": _sha(resource_ref.encode("ascii")),
                "grantId": grant_id,
                "audienceDigest": audience_digest,
            }
        )
        with self._transaction():
            try:
                current, _ = self._load_record(grant_id)
            except LocalResourceRegistryError as error:
                if error.code != "RESOURCE_NOT_FOUND":
                    raise
            else:
                self._authorize_record(current, audience_digest)
                if current["requestDigest"] != request_digest:
                    raise LocalResourceRegistryError(
                        "RESOURCE_IDEMPOTENCY_CONFLICT",
                        "grantRequestId was already used for a different resource grant",
                    )
                return _public_summary(current, resource_ref, now)
            self._publish_new(record_path, canonical_json_bytes(record))
            try:
                self._publish_new(
                    self._binding_path(resource_ref), canonical_json_bytes(binding)
                )
            except Exception:
                # The authenticated record is intentionally retained. A retry with
                # the same request repairs the missing binding without widening it.
                raise
        return _public_summary(record, resource_ref, now)

    def inspect(
        self, resource_ref: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        with self._transaction():
            normalized_ref, record, _ = self._resolve_record(resource_ref, audience)
            return _public_summary(record, normalized_ref, self._now())

    def consume(
        self,
        resource_ref: str,
        audience: ArtifactAudienceBinding,
        *,
        action: str,
        use_id: str,
        expected_resource_revision_digest: str,
        expected_revocation_epoch: int,
        requested_constraints: Mapping[str, Any] | None = None,
    ) -> ResolvedLocalResource:
        use_id = _validate_opaque_input(use_id, "useId")
        expected_digest = _require_digest(
            expected_resource_revision_digest, "expectedResourceRevisionDigest"
        )
        expected_epoch = _require_integer(
            expected_revocation_epoch, "expectedRevocationEpoch", minimum=0, maximum=1
        )
        if not isinstance(action, str):
            raise LocalResourceRegistryError("RESOURCE_ACTION_INVALID", "resource action is invalid")
        audience_digest = self._audience_digest(audience)
        with self._transaction():
            normalized_ref, record, previous_raw = self._resolve_record(resource_ref, audience)
            self._authorize_record(record, audience_digest)
            now = self._now()
            state = _record_state(record, now)
            if state == "revoked":
                raise LocalResourceRegistryError("RESOURCE_REVOKED", "resource grant has been revoked")
            if state == "expired":
                raise LocalResourceRegistryError("RESOURCE_EXPIRED", "resource grant has expired")
            if expected_epoch != record["revocationEpoch"]:
                raise LocalResourceRegistryError(
                    "RESOURCE_REVOCATION_CHANGED", "resource revocation epoch changed"
                )
            if expected_digest != record["resourceRevisionDigest"]:
                raise LocalResourceRegistryError(
                    "RESOURCE_REVISION_MISMATCH", "resource revision does not match the approved resource"
                )
            if action not in record["constraints"]["actions"]:
                raise LocalResourceRegistryError(
                    "RESOURCE_ACTION_FORBIDDEN", "resource action exceeds the approved grant"
                )
            normalized_path = _normalize_lexical_path(record["rawPath"])
            current_snapshot, current_digest = _snapshot(normalized_path, record["kind"])
            if (
                current_digest != record["resourceRevisionDigest"]
                or current_snapshot != record["snapshot"]
            ):
                raise LocalResourceRegistryError(
                    "RESOURCE_CHANGED", "resource changed after user authorization"
                )
            file_size = current_snapshot.get("sizeBytes") if record["kind"] == "file" else None
            effective_constraints = (
                json.loads(json.dumps(record["constraints"]))
                if requested_constraints is None
                else _normalize_constraints(
                    record["kind"], requested_constraints, file_size=file_size
                )
            )
            if not _constraints_are_narrower(effective_constraints, record["constraints"]):
                raise LocalResourceRegistryError(
                    "RESOURCE_CONSTRAINT_FORBIDDEN", "requested constraints exceed the approved grant"
                )
            use_digest = self._mac(
                "study.local-resource.use-id.v1",
                audience_digest.encode("ascii") + b"\x00" + use_id.encode("utf-8"),
            )
            request_digest = _sha(
                canonical_json_bytes(
                    {
                        "schema": "study.local-resource.use-request",
                        "schemaVersion": 1,
                        "grantId": record["grantId"],
                        "useDigest": use_digest,
                        "action": action,
                        "resourceRevisionDigest": expected_digest,
                        "revocationEpoch": expected_epoch,
                        "constraints": effective_constraints,
                    }
                )
            )
            for entry in record["useHistory"]:
                if entry["useDigest"] == use_digest:
                    if entry["requestDigest"] != request_digest:
                        raise LocalResourceRegistryError(
                            "RESOURCE_USE_ID_CONFLICT", "useId was reused for a different request"
                        )
                    return self._resolved(
                        resource_ref=normalized_ref,
                        record=record,
                        path=normalized_path,
                        constraints=effective_constraints,
                    )
            if state == "exhausted":
                raise LocalResourceRegistryError(
                    "RESOURCE_USES_EXHAUSTED", "resource grant has no remaining uses"
                )
            history = [
                *record["useHistory"],
                {
                    "useDigest": use_digest,
                    "requestDigest": request_digest,
                    "action": action,
                    "usedAt": _timestamp(now),
                },
            ]
            unsigned = dict(record)
            unsigned.pop("authKeyId")
            unsigned.pop("authTag")
            unsigned.update(
                {
                    "useCount": record["useCount"] + 1,
                    "useHistory": history,
                    "revision": record["revision"] + 1,
                }
            )
            updated = self._authenticate_record(unsigned)
            self._validate_record(updated)
            self._replace(
                self._record_path(record["grantId"]),
                canonical_json_bytes(updated),
                previous_raw,
            )
            return self._resolved(
                resource_ref=normalized_ref,
                record=updated,
                path=normalized_path,
                constraints=effective_constraints,
            )

    def revoke(
        self,
        resource_ref: str,
        audience: ArtifactAudienceBinding,
        *,
        revocation_id: str,
        expected_revocation_epoch: int,
        attestation_ref: str,
    ) -> dict[str, Any]:
        revocation_id = _validate_opaque_input(revocation_id, "revocationId")
        expected_epoch = _require_integer(
            expected_revocation_epoch, "expectedRevocationEpoch", minimum=0, maximum=1
        )
        audience_digest = self._audience_digest(audience)
        revocation_digest = self._mac(
            "study.local-resource.revocation-id.v1",
            audience_digest.encode("ascii") + b"\x00" + revocation_id.encode("utf-8"),
        )
        with self._transaction():
            normalized_ref, record, _ = self._resolve_record(resource_ref, audience)
            if record["revoked"]:
                if record["revokeDigest"] == revocation_digest:
                    return _public_summary(record, normalized_ref, self._now())
                raise LocalResourceRegistryError(
                    "RESOURCE_ALREADY_REVOKED", "resource grant was already revoked"
                )
            request_digest = _sha(
                canonical_json_bytes(
                    {
                        "schema": "study.local-resource.revoke-request",
                        "schemaVersion": 1,
                        "grantId": record["grantId"],
                        "resourceRefDigest": _sha(normalized_ref.encode("ascii")),
                        "revocationDigest": revocation_digest,
                        "expectedRevocationEpoch": expected_epoch,
                    }
                )
            )
        revocation_attestation_digest = self._verify_gesture(
            audience_digest=audience_digest,
            request_digest=request_digest,
            attestation_ref=attestation_ref,
            action="revoke_local_resource",
        )
        with self._transaction():
            normalized_ref, current, previous_raw = self._resolve_record(resource_ref, audience)
            if current["revoked"]:
                if current["revokeDigest"] == revocation_digest:
                    return _public_summary(current, normalized_ref, self._now())
                raise LocalResourceRegistryError(
                    "RESOURCE_ALREADY_REVOKED", "resource grant was already revoked"
                )
            if current["revocationEpoch"] != expected_epoch:
                raise LocalResourceRegistryError(
                    "RESOURCE_REVOCATION_CHANGED", "resource revocation epoch changed"
                )
            now = self._now()
            unsigned = dict(current)
            unsigned.pop("authKeyId")
            unsigned.pop("authTag")
            unsigned.update(
                {
                    "revoked": True,
                    "revocationEpoch": current["revocationEpoch"] + 1,
                    "revokeDigest": revocation_digest,
                    "revokeAttestationDigest": revocation_attestation_digest,
                    "revokedAt": _timestamp(now),
                    "revision": current["revision"] + 1,
                }
            )
            updated = self._authenticate_record(unsigned)
            self._validate_record(updated)
            self._replace(
                self._record_path(current["grantId"]),
                canonical_json_bytes(updated),
                previous_raw,
            )
            return _public_summary(updated, normalized_ref, now)
