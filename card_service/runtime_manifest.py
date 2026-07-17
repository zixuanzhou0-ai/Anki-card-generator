from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class RuntimeManifestError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def assert_stable_path(path: Path) -> Path:
    if not path.is_absolute():
        raise RuntimeManifestError("RUNTIME_PATH_RELATIVE", "Managed runtime path must be absolute")
    resolved = path.resolve(strict=True)
    current = Path(resolved.anchor)
    for part in resolved.parts[1:]:
        current /= part
        if current.is_symlink() or _has_reparse_attribute(current):
            raise RuntimeManifestError("RUNTIME_REPARSE_BLOCKED", "Managed runtime path contains a reparse point")
    if not resolved.is_file():
        raise RuntimeManifestError("RUNTIME_FILE_REQUIRED", "Managed runtime entry must be a file")
    return resolved


@dataclass(frozen=True)
class RuntimeEntry:
    resource_id: str
    path: Path
    size: int
    sha256: str

    def manifest_value(self) -> dict[str, object]:
        return {
            "resourceId": self.resource_id,
            "path": str(self.path),
            "size": self.size,
            "sha256": self.sha256,
        }


class ManagedRuntimeManifest:
    def __init__(self, entries: Iterable[tuple[str, Path]]) -> None:
        resolved_entries: list[RuntimeEntry] = []
        seen_ids: set[str] = set()
        seen_paths: set[str] = set()
        for resource_id, raw_path in entries:
            if not resource_id or resource_id in seen_ids:
                raise RuntimeManifestError("RUNTIME_RESOURCE_DUPLICATE", "Managed runtime resource ID is missing or duplicated")
            path = assert_stable_path(raw_path)
            path_key = os.path.normcase(str(path))
            if path_key in seen_paths:
                continue
            seen_ids.add(resource_id)
            seen_paths.add(path_key)
            resolved_entries.append(
                RuntimeEntry(
                    resource_id=resource_id,
                    path=path,
                    size=path.stat().st_size,
                    sha256=file_sha256(path),
                )
            )
        if not resolved_entries:
            raise RuntimeManifestError("RUNTIME_MANIFEST_EMPTY", "Managed runtime manifest must not be empty")
        self.entries = tuple(sorted(resolved_entries, key=lambda item: item.resource_id.encode("utf-8")))
        self.value = {
            "schemaVersion": 1,
            "entries": [entry.manifest_value() for entry in self.entries],
        }
        self.digest = hashlib.sha256(canonical_bytes(self.value)).hexdigest()

    def verify(self) -> None:
        for entry in self.entries:
            try:
                path = assert_stable_path(entry.path)
                size = path.stat().st_size
                digest = file_sha256(path)
            except (OSError, RuntimeManifestError) as error:
                raise RuntimeManifestError("MANAGED_RUNTIME_CHANGED", "Managed runtime entry is unavailable") from error
            if size != entry.size or digest != entry.sha256:
                raise RuntimeManifestError("MANAGED_RUNTIME_CHANGED", "Managed runtime entry changed after service startup")

    def write(self, path: Path) -> None:
        if not path.is_absolute():
            raise RuntimeManifestError("RUNTIME_MANIFEST_PATH_RELATIVE", "Runtime manifest path must be absolute")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        payload = canonical_bytes(self.value)
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def public_summary(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "digest": f"sha256:{self.digest}",
            "entryCount": len(self.entries),
            "pathDisclosure": False,
            "signedReleaseManifest": False,
            "complete": False,
        }


def worker_runtime_entries(
    worker_path: Path,
    bootstrap_path: Path,
    broker_client_path: Path,
    python_path: Path,
) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = [
        ("managed-python:executable", python_path),
        ("card-service:worker-bootstrap", bootstrap_path),
        ("card-service:broker-client", broker_client_path),
        ("legacy-worker:entry", worker_path),
    ]
    module_root = worker_path.parent / "acg"
    if module_root.is_dir():
        for path in sorted(module_root.rglob("*.py"), key=lambda value: value.as_posix().encode("utf-8")):
            relative = path.relative_to(worker_path.parent).as_posix()
            entries.append((f"legacy-worker:module:{relative}", path))
    return entries


def managed_tool_runtime_entries(
    directories: Iterable[Path],
    *,
    maximum_files: int = 4096,
    maximum_total_bytes: int = 8 * 1024 * 1024 * 1024,
) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    total_bytes = 0
    for index, directory in enumerate(directories):
        for path in sorted(directory.rglob("*"), key=lambda value: value.as_posix().encode("utf-8")):
            if not path.is_file():
                continue
            total_bytes += path.stat().st_size
            if len(entries) >= maximum_files or total_bytes > maximum_total_bytes:
                raise RuntimeManifestError("MANAGED_TOOL_SET_TOO_LARGE", "Managed tool bundle exceeds its manifest limit")
            relative = path.relative_to(directory).as_posix()
            entries.append((f"managed-tool:{index}:{relative}", path))
    return entries
