"""Fail-closed rehydration of opaque local grants into task-owned staging.

The Worker never receives a path from the local resource grant ledger.  Card
Service consumes and revalidates a grant, copies a stable byte snapshot into a
task workspace, hardens that snapshot for the task sandbox, and returns only a
workspace-relative locator backed by an authenticated private receipt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping

from .artifact_registry import ArtifactAudienceBinding, canonical_json_bytes
from .local_resource_registry import (
    LocalResourceGrantRegistry,
    LocalResourceRegistryError,
    ResolvedLocalResource,
)


CHUNK_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_PATH_CHARS = 32_768
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_STAGING_REF_RE = re.compile(r"^stg1_[A-Za-z0-9_-]{43}$")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CLOCK$",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ResourceStagingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StagedResource:
    staging_ref: str
    task_id: str
    kind: str
    workspace_relative_path: str
    source_revision_digest: str
    manifest_digest: str
    total_bytes: int
    entry_count: int
    hardening_applied: bool
    resolution_proof: str

    def worker_locator(self) -> dict[str, Any]:
        """Return the only path-shaped value allowed to cross into a Worker request."""

        return {
            "schema": "study.task-resource-locator",
            "schemaVersion": 1,
            "kind": self.kind,
            "workspaceRelativePath": self.workspace_relative_path,
            "sourceRevisionDigest": self.source_revision_digest,
            "manifestDigest": self.manifest_digest,
            "totalBytes": self.total_bytes,
            "entryCount": self.entry_count,
            "hardeningApplied": self.hardening_applied,
        }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ResourceStagingError("STAGING_ID_INVALID", f"{label} is invalid")
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ResourceStagingError("STAGING_DIGEST_INVALID", f"{label} is invalid")
    return value


def _require_ref(value: Any) -> str:
    if not isinstance(value, str) or not _STAGING_REF_RE.fullmatch(value):
        raise ResourceStagingError(
            "STAGING_REF_INVALID", "staging reference is invalid"
        )
    return value


def _has_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _safe_existing(path: Path, *, directory: bool | None = None) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as error:
        raise ResourceStagingError(
            "STAGING_PATH_UNAVAILABLE", "staging path is unavailable"
        ) from error
    if stat.S_ISLNK(info.st_mode) or _has_reparse(info):
        raise ResourceStagingError(
            "STAGING_REPARSE_BLOCKED", "links and reparse points are forbidden"
        )
    if directory is True and not stat.S_ISDIR(info.st_mode):
        raise ResourceStagingError(
            "STAGING_PATH_INVALID", "expected a staging directory"
        )
    if directory is False and not stat.S_ISREG(info.st_mode):
        raise ResourceStagingError("STAGING_PATH_INVALID", "expected a staged file")
    return info


def _safe_chain(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    if not current.anchor:
        raise ResourceStagingError(
            "STAGING_PATH_INVALID", "staging path must be absolute"
        )
    for part in absolute.parts[1:]:
        current = current / part
        if current.exists() or current.is_symlink():
            _safe_existing(current)


def _workspace_identity(workspace: Path) -> dict[str, str]:
    _safe_chain(workspace)
    info = _safe_existing(workspace, directory=True)
    return {"stDev": str(info.st_dev), "stIno": str(info.st_ino)}


def _paths_overlap(first: Path, second: Path) -> bool:
    first_value = os.path.normcase(str(first.absolute()))
    second_value = os.path.normcase(str(second.absolute()))
    try:
        common = os.path.commonpath((first_value, second_value))
    except ValueError:
        return False
    return common in {first_value, second_value}


def _safe_component(name: str) -> str:
    if (
        not name
        or name in {".", ".."}
        or len(name) > 255
        or any(ord(character) < 0x20 for character in name)
        or "/" in name
        or "\\" in name
        or unicodedata.normalize("NFC", name) != name
    ):
        raise ResourceStagingError(
            "STAGING_NAME_INVALID", "source entry name is unsafe"
        )
    if os.name == "nt":
        if name.endswith((".", " ")) or ":" in name:
            raise ResourceStagingError(
                "STAGING_NAME_INVALID", "source entry name is unsafe"
            )
        if name.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
            raise ResourceStagingError(
                "STAGING_NAME_RESERVED", "source entry uses a reserved Windows name"
            )
    return name


def _portable_suffix(path: Path) -> str:
    suffix = path.suffix.casefold()
    if re.fullmatch(r"\.[a-z0-9]{1,12}", suffix or ""):
        return suffix
    return ".bin"


def _relative_posix(parts: tuple[str, ...]) -> str:
    if not parts:
        return "."
    value = PurePosixPath(*parts).as_posix()
    if (
        len(value) > MAX_PATH_CHARS
        or value.startswith("/")
        or ".." in PurePosixPath(value).parts
    ):
        raise ResourceStagingError(
            "STAGING_RELATIVE_PATH_INVALID", "staged relative path is invalid"
        )
    return value


def _open_source(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(path, flags)
    except OSError as error:
        raise ResourceStagingError(
            "STAGING_SOURCE_OPEN_FAILED", "source file could not be opened safely"
        ) from error


def _open_destination(path: Path) -> int:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOINHERIT", 0)
    )
    try:
        return os.open(path, flags, 0o600)
    except OSError as error:
        raise ResourceStagingError(
            "STAGING_DESTINATION_CREATE_FAILED",
            "staged file could not be created exclusively",
        ) from error


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


def _copy_file_snapshot(
    source: Path, target: Path, *, maximum_bytes: int
) -> dict[str, Any]:
    source_fd = _open_source(source)
    target_fd: int | None = None
    digest = hashlib.sha256()
    copied = 0
    try:
        before = os.fstat(source_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or _has_reparse(before)
        ):
            raise ResourceStagingError(
                "STAGING_SOURCE_UNSAFE", "source must be a unique regular file"
            )
        if before.st_size > maximum_bytes:
            raise ResourceStagingError(
                "STAGING_BYTE_LIMIT", "source exceeds the approved staging byte limit"
            )
        target_fd = _open_destination(target)
        while True:
            chunk = os.read(source_fd, CHUNK_BYTES)
            if not chunk:
                break
            copied += len(chunk)
            if copied > maximum_bytes:
                raise ResourceStagingError(
                    "STAGING_BYTE_LIMIT",
                    "source exceeded its approved byte limit while copying",
                )
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                if written <= 0:
                    raise ResourceStagingError(
                        "STAGING_WRITE_FAILED",
                        "staged file write did not make progress",
                    )
                view = view[written:]
            digest.update(chunk)
        os.fsync(target_fd)
        after = os.fstat(source_fd)
        if _file_identity(before) != _file_identity(after) or copied != before.st_size:
            raise ResourceStagingError(
                "STAGING_SOURCE_CHANGED",
                "source file changed while it was being staged",
            )
        staged = os.fstat(target_fd)
        if not stat.S_ISREG(staged.st_mode) or staged.st_size != copied:
            raise ResourceStagingError(
                "STAGING_WRITE_FAILED", "staged file identity or size is invalid"
            )
        return {"sizeBytes": copied, "sha256": digest.hexdigest()}
    finally:
        if target_fd is not None:
            os.close(target_fd)
        os.close(source_fd)


def _read_file_snapshot(source: Path, *, maximum_bytes: int) -> dict[str, Any]:
    descriptor = _open_source(source)
    digest = hashlib.sha256()
    total = 0
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or _has_reparse(before)
        ):
            raise ResourceStagingError(
                "STAGING_CONTENT_INVALID", "staged file is not regular"
            )
        while True:
            chunk = os.read(descriptor, CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_bytes:
                raise ResourceStagingError(
                    "STAGING_BYTE_LIMIT",
                    "staged content exceeds its authenticated limit",
                )
            digest.update(chunk)
        after = os.fstat(descriptor)
        if _file_identity(before) != _file_identity(after) or total != before.st_size:
            raise ResourceStagingError(
                "STAGING_CONTENT_CHANGED", "staged file changed while it was verified"
            )
        return {"sizeBytes": total, "sha256": digest.hexdigest()}
    finally:
        os.close(descriptor)


def _directory_manifest(
    source_root: Path,
    *,
    constraints: Mapping[str, Any],
    destination_root: Path | None,
) -> tuple[list[dict[str, Any]], int]:
    maximum_depth = int(constraints["maxDepth"])
    maximum_entries = int(constraints["maxEntries"])
    maximum_bytes = int(constraints["maxTotalBytes"])
    manifest: list[dict[str, Any]] = []
    total_bytes = 0

    def walk(
        source: Path, destination: Path | None, parts: tuple[str, ...], depth: int
    ) -> None:
        nonlocal total_bytes
        before = _safe_existing(source, directory=True)
        try:
            entries = list(os.scandir(source))
        except OSError as error:
            raise ResourceStagingError(
                "STAGING_DIRECTORY_READ_FAILED",
                "source directory could not be enumerated",
            ) from error
        normalized_seen: set[str] = set()
        ordered: list[tuple[str, os.DirEntry[str]]] = []
        for entry in entries:
            name = _safe_component(entry.name)
            collision_key = unicodedata.normalize("NFC", name).casefold()
            if collision_key in normalized_seen:
                raise ResourceStagingError(
                    "STAGING_NAME_COLLISION",
                    "source directory contains colliding names",
                )
            normalized_seen.add(collision_key)
            ordered.append((name, entry))
        ordered.sort(key=lambda item: (item[0].casefold(), item[0].encode("utf-8")))

        for name, entry in ordered:
            entry_parts = (*parts, name)
            relative = _relative_posix(entry_parts)
            entry_depth = depth + 1
            if entry_depth > maximum_depth:
                raise ResourceStagingError(
                    "STAGING_DEPTH_LIMIT", "source directory exceeds the approved depth"
                )
            if len(manifest) >= maximum_entries:
                raise ResourceStagingError(
                    "STAGING_ENTRY_LIMIT",
                    "source directory exceeds the approved entry limit",
                )
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise ResourceStagingError(
                    "STAGING_SOURCE_CHANGED", "source entry changed during enumeration"
                ) from error
            if entry.is_symlink() or _has_reparse(info):
                raise ResourceStagingError(
                    "STAGING_REPARSE_BLOCKED",
                    "source directory contains a link or reparse point",
                )
            source_child = source / name
            destination_child = destination / name if destination is not None else None
            if stat.S_ISDIR(info.st_mode):
                manifest.append({"path": relative, "kind": "directory"})
                if destination_child is not None:
                    destination_child.mkdir(mode=0o700, exist_ok=False)
                walk(source_child, destination_child, entry_parts, entry_depth)
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ResourceStagingError(
                    "STAGING_SOURCE_UNSAFE",
                    "source directory contains an unsupported entry",
                )
            remaining = maximum_bytes - total_bytes
            if remaining < 0:
                raise ResourceStagingError(
                    "STAGING_BYTE_LIMIT",
                    "source directory exceeds the approved byte limit",
                )
            snapshot = (
                _copy_file_snapshot(
                    source_child, destination_child, maximum_bytes=remaining
                )
                if destination_child is not None
                else _read_file_snapshot(source_child, maximum_bytes=remaining)
            )
            total_bytes += snapshot["sizeBytes"]
            manifest.append(
                {
                    "path": relative,
                    "kind": "file",
                    "sizeBytes": snapshot["sizeBytes"],
                    "sha256": snapshot["sha256"],
                }
            )
        after = _safe_existing(source, directory=True)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ResourceStagingError(
                "STAGING_SOURCE_CHANGED", "source directory changed while it was staged"
            )

    walk(source_root, destination_root, (), 0)
    return manifest, total_bytes


def _manifest_digest(manifest: list[dict[str, Any]]) -> str:
    raw = canonical_json_bytes(
        {"schema": "study.directory-manifest", "schemaVersion": 1, "entries": manifest}
    )
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ResourceStagingError(
            "STAGING_MANIFEST_LIMIT", "directory manifest exceeds its byte limit"
        )
    return _sha(raw)


def _remove_tree(path: Path) -> None:
    try:
        if path.exists() or path.is_symlink():
            (
                shutil.rmtree(path)
                if path.is_dir() and not path.is_symlink()
                else path.unlink()
            )
    except OSError as error:
        raise ResourceStagingError(
            "STAGING_CLEANUP_FAILED", "partial staged content could not be removed"
        ) from error
    if path.exists() or path.is_symlink():
        raise ResourceStagingError(
            "STAGING_CLEANUP_FAILED",
            "partial staged content still exists after cleanup",
        )


class TaskResourceStager:
    """Authenticated task staging for already-consumed local resource grants."""

    def __init__(
        self,
        state_root: Path,
        *,
        authentication_key: bytes,
        service_instance_id: str,
        key_id: str = "study-resource-staging-v1",
        harden_callback: Callable[[Path, str], None] | None = None,
        require_hardening: bool = True,
    ) -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise ResourceStagingError(
                "STAGING_AUTH_KEY_INVALID",
                "staging authentication key must contain 256 bits",
            )
        self._authentication_key = bytes(authentication_key)
        self._service_instance_id = _require_id(
            service_instance_id, "serviceInstanceId"
        )
        self._key_id = _require_id(key_id, "keyId")
        if harden_callback is not None and not callable(harden_callback):
            raise ResourceStagingError(
                "STAGING_HARDENER_INVALID", "staging hardener is invalid"
            )
        self._harden_callback = harden_callback
        self._require_hardening = require_hardening is True
        self._state_root = Path(state_root).absolute()
        self._state_root.mkdir(parents=True, exist_ok=True)
        _safe_existing(self._state_root, directory=True)
        self._records_root = self._state_root / "records"
        _safe_chain(self._state_root)
        self._records_root.mkdir(exist_ok=True)
        _safe_existing(self._records_root, directory=True)
        self._lock_path = self._state_root / "resource-staging.lock"
        _safe_chain(self._records_root)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self._lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOINHERIT", 0),
                0o600,
            )
            if os.write(descriptor, b"\x00") != 1:
                raise ResourceStagingError(
                    "STAGING_WRITE_FAILED", "lock initialization stalled"
                )
            os.fsync(descriptor)
        except FileExistsError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
        self._thread_lock = threading.RLock()

    def _mac(self, domain: str, value: Mapping[str, Any] | bytes) -> str:
        payload = (
            value if isinstance(value, bytes) else canonical_json_bytes(dict(value))
        )
        return hmac.new(
            self._authentication_key,
            domain.encode("ascii") + b"\x00" + payload,
            hashlib.sha256,
        ).hexdigest()

    def _audience_digest(self, audience: ArtifactAudienceBinding) -> str:
        if not isinstance(audience, ArtifactAudienceBinding):
            raise ResourceStagingError(
                "STAGING_AUDIENCE_INVALID", "staging audience is invalid"
            )
        return _sha(canonical_json_bytes(audience.audience(self._service_instance_id)))

    def _source_ref_digest(self, resource_ref: str) -> str:
        return self._mac(
            "study.resource-staging.source-ref.v1", resource_ref.encode("utf-8")
        )

    def _derive_ref(self, audience_digest: str, task_id: str, request_id: str) -> str:
        raw = hmac.new(
            self._authentication_key,
            b"study.resource-staging.ref.v1\x00"
            + audience_digest.encode("ascii")
            + b"\x00"
            + task_id.encode("utf-8")
            + b"\x00"
            + request_id.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return "stg1_" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _record_path(self, staging_ref: str) -> Path:
        digest = _sha(staging_ref.encode("ascii"))
        parent = self._records_root / digest[:2]
        parent.mkdir(exist_ok=True)
        _safe_existing(parent, directory=True)
        _safe_chain(parent)
        return parent / f"{digest}.json"

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._thread_lock:
            info = _safe_existing(self._lock_path, directory=False)
            if info.st_nlink != 1:
                raise ResourceStagingError(
                    "STAGING_STORAGE_UNSAFE",
                    "staging lock is not a unique regular file",
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

    def _authenticate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = dict(value)
        unsigned["authKeyId"] = self._key_id
        unsigned["authTag"] = self._mac("study.resource-staging.record.v1", unsigned)
        return unsigned

    def _validate_record(self, value: Mapping[str, Any]) -> dict[str, Any]:
        required = {
            "schema",
            "schemaVersion",
            "stagingRef",
            "taskId",
            "serviceInstanceId",
            "audienceDigest",
            "requestDigest",
            "sourceRefDigest",
            "sourceRevisionDigest",
            "kind",
            "workspaceIdentity",
            "workspaceRelativePath",
            "manifest",
            "manifestDigest",
            "totalBytes",
            "entryCount",
            "hardeningApplied",
            "authKeyId",
            "authTag",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging record shape is invalid"
            )
        record = dict(value)
        if (
            record["schema"] != "study.resource-staging.record"
            or record["schemaVersion"] != 1
        ):
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging record schema is invalid"
            )
        if (
            record["serviceInstanceId"] != self._service_instance_id
            or record["authKeyId"] != self._key_id
        ):
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging record owner is invalid"
            )
        _require_ref(record["stagingRef"])
        _require_id(record["taskId"], "taskId")
        for field in (
            "audienceDigest",
            "requestDigest",
            "sourceRefDigest",
            "sourceRevisionDigest",
            "manifestDigest",
            "authTag",
        ):
            _require_digest(record[field], field)
        if record["kind"] not in {"file", "directory"}:
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging resource kind is invalid"
            )
        if not isinstance(record["workspaceIdentity"], dict) or set(
            record["workspaceIdentity"]
        ) != {
            "stDev",
            "stIno",
        }:
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "workspace identity is invalid"
            )
        if not isinstance(record["workspaceRelativePath"], str):
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "workspace locator is invalid"
            )
        if not isinstance(record["manifest"], list):
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging manifest is invalid"
            )
        if (
            not isinstance(record["totalBytes"], int)
            or isinstance(record["totalBytes"], bool)
            or record["totalBytes"] < 0
            or not isinstance(record["entryCount"], int)
            or isinstance(record["entryCount"], bool)
            or record["entryCount"] < 0
            or not isinstance(record["hardeningApplied"], bool)
        ):
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging record counts are invalid"
            )
        unsigned = dict(record)
        tag = unsigned.pop("authTag")
        if not hmac.compare_digest(
            tag, self._mac("study.resource-staging.record.v1", unsigned)
        ):
            raise ResourceStagingError(
                "STAGING_RECORD_CORRUPT", "staging record authentication failed"
            )
        if _manifest_digest(record["manifest"]) != record["manifestDigest"]:
            raise ResourceStagingError(
                "STAGING_RECORD_CORRUPT", "staging manifest digest is invalid"
            )
        return record

    def _load_record(self, staging_ref: str) -> dict[str, Any]:
        path = self._record_path(staging_ref)
        try:
            info = path.lstat()
        except FileNotFoundError as error:
            raise ResourceStagingError(
                "STAGING_NOT_FOUND", "staged resource was not found"
            ) from error
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or _has_reparse(info)
            or info.st_nlink != 1
            or info.st_size > MAX_MANIFEST_BYTES
        ):
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging record is not a bounded unique file"
            )
        try:
            with path.open("rb") as source:
                raw = source.read(MAX_MANIFEST_BYTES + 1)
        except FileNotFoundError as error:
            raise ResourceStagingError(
                "STAGING_NOT_FOUND", "staged resource was not found"
            ) from error
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging record is too large"
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging record is invalid JSON"
            ) from error
        if canonical_json_bytes(value) != raw:
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging record is not canonical"
            )
        return self._validate_record(value)

    def _publish_record(self, record: Mapping[str, Any]) -> None:
        path = self._record_path(record["stagingRef"])
        raw = canonical_json_bytes(dict(record))
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(16)}.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOINHERIT", 0),
            0o600,
        )
        try:
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise ResourceStagingError(
                        "STAGING_WRITE_FAILED", "record write stalled"
                    )
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise ResourceStagingError(
                "STAGING_ALREADY_EXISTS", "staging record already exists"
            ) from error
        finally:
            temporary.unlink(missing_ok=True)

    def _proof(self, record: Mapping[str, Any]) -> str:
        return self._mac(
            "study.resource-staging.resolution.v1",
            {
                "stagingRef": record["stagingRef"],
                "taskId": record["taskId"],
                "sourceRevisionDigest": record["sourceRevisionDigest"],
                "manifestDigest": record["manifestDigest"],
                "workspaceIdentity": record["workspaceIdentity"],
                "workspaceRelativePath": record["workspaceRelativePath"],
                "hardeningApplied": record["hardeningApplied"],
            },
        )

    def _public(self, record: Mapping[str, Any]) -> StagedResource:
        return StagedResource(
            staging_ref=record["stagingRef"],
            task_id=record["taskId"],
            kind=record["kind"],
            workspace_relative_path=record["workspaceRelativePath"],
            source_revision_digest=record["sourceRevisionDigest"],
            manifest_digest=record["manifestDigest"],
            total_bytes=record["totalBytes"],
            entry_count=record["entryCount"],
            hardening_applied=record["hardeningApplied"],
            resolution_proof=self._proof(record),
        )

    @staticmethod
    def _workspace(task_workspace: Path, task_id: str) -> tuple[Path, dict[str, str]]:
        workspace = Path(task_workspace).absolute()
        if not workspace.is_absolute() or len(str(workspace)) > MAX_PATH_CHARS:
            raise ResourceStagingError(
                "STAGING_WORKSPACE_INVALID", "task workspace is invalid"
            )
        if workspace.name != task_id:
            raise ResourceStagingError(
                "STAGING_TASK_MISMATCH",
                "task workspace is not owned by the requested task",
            )
        return workspace, _workspace_identity(workspace)

    def _request_digest(
        self,
        *,
        task_id: str,
        audience_digest: str,
        source_ref_digest: str,
        resource: ResolvedLocalResource,
        workspace_identity: Mapping[str, str],
    ) -> str:
        return _sha(
            canonical_json_bytes(
                {
                    "schema": "study.resource-staging.request",
                    "schemaVersion": 1,
                    "taskId": task_id,
                    "audienceDigest": audience_digest,
                    "sourceRefDigest": source_ref_digest,
                    "sourceRevisionDigest": resource.resource_revision_digest,
                    "kind": resource.kind,
                    "constraints": dict(resource.constraints),
                    "workspaceIdentity": dict(workspace_identity),
                    "serviceInstanceId": self._service_instance_id,
                }
            )
        )

    def _verify_public(self, staged: StagedResource, record: Mapping[str, Any]) -> None:
        if not isinstance(staged, StagedResource):
            raise ResourceStagingError(
                "STAGING_RESOLUTION_INVALID", "staged resource is invalid"
            )
        expected = self._public(record)
        if staged != expected or not hmac.compare_digest(
            staged.resolution_proof, self._proof(record)
        ):
            raise ResourceStagingError(
                "STAGING_RESOLUTION_INVALID", "staged resource proof is invalid"
            )

    def stage(
        self,
        resource: ResolvedLocalResource,
        *,
        registry: LocalResourceGrantRegistry,
        audience: ArtifactAudienceBinding,
        task_id: str,
        task_workspace: Path,
        staging_request_id: str,
        task_sandbox_id: str | None,
    ) -> StagedResource:
        task_id = _require_id(task_id, "taskId")
        request_id = _require_id(staging_request_id, "stagingRequestId")
        if not isinstance(registry, LocalResourceGrantRegistry):
            raise ResourceStagingError(
                "STAGING_REGISTRY_INVALID", "local resource registry is invalid"
            )
        if resource.kind not in {"file", "directory"}:
            raise ResourceStagingError(
                "STAGING_KIND_UNSUPPORTED",
                "only input files and directories can be staged",
            )
        try:
            registry.assert_resolution_active(
                resource, audience, required_action="read"
            )
        except LocalResourceRegistryError as error:
            raise ResourceStagingError(error.code, error.message) from error
        workspace, workspace_identity = self._workspace(task_workspace, task_id)
        if (
            _paths_overlap(resource.path, workspace)
            or _paths_overlap(resource.path, self._state_root)
            or _paths_overlap(workspace, self._state_root)
        ):
            raise ResourceStagingError(
                "STAGING_PATH_OVERLAP",
                "source, task workspace, and private staging state must not overlap",
            )
        audience_digest = self._audience_digest(audience)
        source_ref_digest = self._source_ref_digest(resource.resource_ref)
        staging_ref = self._derive_ref(audience_digest, task_id, request_id)
        request_digest = self._request_digest(
            task_id=task_id,
            audience_digest=audience_digest,
            source_ref_digest=source_ref_digest,
            resource=resource,
            workspace_identity=workspace_identity,
        )

        with self._transaction():
            try:
                existing = self._load_record(staging_ref)
            except ResourceStagingError as error:
                if error.code != "STAGING_NOT_FOUND":
                    raise
            else:
                if existing["requestDigest"] != request_digest:
                    raise ResourceStagingError(
                        "STAGING_IDEMPOTENCY_CONFLICT",
                        "stagingRequestId was reused for a different staging request",
                    )
                staged = self._public(existing)
                self._resolve_path(
                    staged,
                    record=existing,
                    resource=resource,
                    registry=registry,
                    audience=audience,
                    task_workspace=workspace,
                )
                return staged

            inputs = workspace / "inputs"
            if not inputs.exists():
                inputs.mkdir(mode=0o700)
            _safe_existing(inputs, directory=True)
            slot_name = "resource-" + staging_ref.removeprefix("stg1_")[:24]
            final_slot = inputs / slot_name
            _safe_chain(inputs)
            if final_slot.exists() or final_slot.is_symlink():
                raise ResourceStagingError(
                    "STAGING_ORPHAN_CONFLICT",
                    "staging destination already exists without a receipt",
                )
            partial = inputs / f".{slot_name}.{secrets.token_hex(16)}.partial"
            partial.mkdir(mode=0o700)
            published = False
            try:
                if resource.kind == "file":
                    payload_name = "payload" + _portable_suffix(resource.path)
                    payload = partial / payload_name
                    snapshot = _copy_file_snapshot(
                        resource.path,
                        payload,
                        maximum_bytes=int(resource.constraints["maxBytes"]),
                    )
                    manifest = [
                        {
                            "path": payload_name,
                            "kind": "file",
                            "sizeBytes": snapshot["sizeBytes"],
                            "sha256": snapshot["sha256"],
                        }
                    ]
                    total_bytes = snapshot["sizeBytes"]
                    payload_relative = f"inputs/{slot_name}/{payload_name}"
                else:
                    payload = partial / "payload"
                    payload.mkdir(mode=0o700)
                    manifest, total_bytes = _directory_manifest(
                        resource.path,
                        constraints=resource.constraints,
                        destination_root=payload,
                    )
                    replay_manifest, replay_bytes = _directory_manifest(
                        resource.path,
                        constraints=resource.constraints,
                        destination_root=None,
                    )
                    if replay_manifest != manifest or replay_bytes != total_bytes:
                        raise ResourceStagingError(
                            "STAGING_SOURCE_CHANGED",
                            "source directory changed during staging",
                        )
                    payload_relative = f"inputs/{slot_name}/payload"
                try:
                    registry.assert_resolution_active(
                        resource, audience, required_action="read"
                    )
                except LocalResourceRegistryError as error:
                    raise ResourceStagingError(error.code, error.message) from error
                os.rename(partial, final_slot)
                published = True
                hardening_applied = False
                if self._harden_callback is not None:
                    if task_sandbox_id is None:
                        raise ResourceStagingError(
                            "STAGING_SANDBOX_ID_REQUIRED",
                            "task sandbox identity is required for staging hardening",
                        )
                    self._harden_callback(final_slot, task_sandbox_id)
                    hardening_applied = True
                elif self._require_hardening:
                    raise ResourceStagingError(
                        "STAGING_HARDENING_REQUIRED",
                        "production staging hardening is unavailable",
                    )
                record = self._authenticate(
                    {
                        "schema": "study.resource-staging.record",
                        "schemaVersion": 1,
                        "stagingRef": staging_ref,
                        "taskId": task_id,
                        "serviceInstanceId": self._service_instance_id,
                        "audienceDigest": audience_digest,
                        "requestDigest": request_digest,
                        "sourceRefDigest": source_ref_digest,
                        "sourceRevisionDigest": resource.resource_revision_digest,
                        "kind": resource.kind,
                        "workspaceIdentity": workspace_identity,
                        "workspaceRelativePath": payload_relative,
                        "manifest": manifest,
                        "manifestDigest": _manifest_digest(manifest),
                        "totalBytes": total_bytes,
                        "entryCount": len(manifest),
                        "hardeningApplied": hardening_applied,
                    }
                )
                self._validate_record(record)
                self._publish_record(record)
                return self._public(record)
            except Exception:
                _remove_tree(final_slot if published else partial)
                raise

    def _resolve_path(
        self,
        staged: StagedResource,
        *,
        record: Mapping[str, Any],
        resource: ResolvedLocalResource,
        registry: LocalResourceGrantRegistry,
        audience: ArtifactAudienceBinding,
        task_workspace: Path,
    ) -> Path:
        self._verify_public(staged, record)
        audience_digest = self._audience_digest(audience)
        if record["audienceDigest"] != audience_digest:
            raise ResourceStagingError(
                "STAGING_AUDIENCE_MISMATCH",
                "staged resource belongs to another audience",
            )
        if record["sourceRefDigest"] != self._source_ref_digest(resource.resource_ref):
            raise ResourceStagingError(
                "STAGING_SOURCE_MISMATCH", "staged resource belongs to another source"
            )
        try:
            registry.assert_resolution_active(
                resource, audience, required_action="read"
            )
        except LocalResourceRegistryError as error:
            raise ResourceStagingError(error.code, error.message) from error
        workspace, identity = self._workspace(task_workspace, record["taskId"])
        if identity != record["workspaceIdentity"]:
            raise ResourceStagingError(
                "STAGING_WORKSPACE_CHANGED", "task workspace identity changed"
            )
        relative = PurePosixPath(record["workspaceRelativePath"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ResourceStagingError(
                "STAGING_RECORD_INVALID", "staging locator is invalid"
            )
        path = workspace.joinpath(*relative.parts)
        try:
            path.relative_to(workspace)
        except ValueError as error:
            raise ResourceStagingError(
                "STAGING_PATH_ESCAPE", "staging locator escaped its task"
            ) from error
        if record["kind"] == "file":
            current = _read_file_snapshot(path, maximum_bytes=record["totalBytes"])
            expected = record["manifest"]
            actual = [
                {
                    "path": path.name,
                    "kind": "file",
                    "sizeBytes": current["sizeBytes"],
                    "sha256": current["sha256"],
                }
            ]
            if actual != expected:
                raise ResourceStagingError(
                    "STAGING_CONTENT_CHANGED",
                    "staged file no longer matches its receipt",
                )
        else:
            manifest, total = _directory_manifest(
                path,
                constraints=resource.constraints,
                destination_root=None,
            )
            if manifest != record["manifest"] or total != record["totalBytes"]:
                raise ResourceStagingError(
                    "STAGING_CONTENT_CHANGED",
                    "staged directory no longer matches its receipt",
                )
        return path

    def resolve_worker_path(
        self,
        staged: StagedResource,
        *,
        resource: ResolvedLocalResource,
        registry: LocalResourceGrantRegistry,
        audience: ArtifactAudienceBinding,
        task_workspace: Path,
    ) -> Path:
        staging_ref = _require_ref(staged.staging_ref)
        with self._transaction():
            record = self._load_record(staging_ref)
            return self._resolve_path(
                staged,
                record=record,
                resource=resource,
                registry=registry,
                audience=audience,
                task_workspace=task_workspace,
            )
