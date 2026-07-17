from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .runtime_manifest import canonical_bytes, file_sha256


MAX_PACKAGE_MANIFEST_BYTES = 4 * 1024 * 1024
PACKAGE_MANIFEST_NAME = "runtime-package-v1.json"
REQUIRED_RUNTIME_RESOURCES = frozenset(
    {
        "managed-python:executable",
        "card-service:worker-bootstrap",
        "card-service:broker-client",
        "card-service:windows-restricted-launcher",
        "card-service:windows-sandbox-acl",
        "legacy-worker:entry",
    }
)
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class RuntimePackageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _assert_stable_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise RuntimePackageError("RUNTIME_PACKAGE_ROOT_RELATIVE", "Runtime package root must be absolute")
    resolved = path.resolve(strict=True)
    current = Path(resolved.anchor)
    for part in resolved.parts[1:]:
        current /= part
        if current.is_symlink() or _has_reparse_attribute(current):
            raise RuntimePackageError("RUNTIME_PACKAGE_REPARSE_BLOCKED", "Runtime package root contains a reparse point")
    if not resolved.is_dir():
        raise RuntimePackageError("RUNTIME_PACKAGE_ROOT_INVALID", "Runtime package root must be a directory")
    return resolved


def _relative_package_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or chr(92) in value or ":" in value:
        raise RuntimePackageError("RUNTIME_PACKAGE_PATH_INVALID", "Runtime package resource path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise RuntimePackageError("RUNTIME_PACKAGE_PATH_INVALID", "Runtime package resource path is invalid")
    for part in relative.parts:
        stem = part.rstrip(" .").split(".", 1)[0].upper()
        if part != part.rstrip(" .") or stem in _WINDOWS_RESERVED:
            raise RuntimePackageError("RUNTIME_PACKAGE_PATH_INVALID", "Runtime package resource path is invalid")
    return relative


@dataclass(frozen=True)
class RuntimePackageResource:
    resource_id: str
    relative_path: str
    path: Path
    size: int
    sha256: str


class ManagedRuntimePackage:
    """Verifies an immutable, root-contained runtime package.

    Signature and publisher trust are deliberately a later release-manifest
    boundary. This class never reports a package as release-complete.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = _assert_stable_directory(Path(root))
        manifest_candidate = self.root / PACKAGE_MANIFEST_NAME
        if manifest_candidate.is_symlink() or (
            manifest_candidate.exists() and _has_reparse_attribute(manifest_candidate)
        ):
            raise RuntimePackageError("RUNTIME_PACKAGE_REPARSE_BLOCKED", "Runtime package manifest is a reparse point")
        self.manifest_path = manifest_candidate.resolve()
        if self.manifest_path.parent != self.root:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_INVALID", "Runtime package manifest escaped its root")
        try:
            source = self.manifest_path.read_bytes()
        except OSError as error:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_MISSING", "Runtime package manifest is unavailable") from error
        if not source or len(source) > MAX_PACKAGE_MANIFEST_BYTES:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_INVALID", "Runtime package manifest is empty or too large")
        try:
            value = json.loads(source)
        except ValueError as error:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_INVALID", "Runtime package manifest is invalid JSON") from error
        if not isinstance(value, dict) or set(value) != {"schemaVersion", "packageId", "version", "resources"}:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_INVALID", "Runtime package manifest shape is invalid")
        if canonical_bytes(value) != source:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_NONCANONICAL", "Runtime package manifest must use canonical JSON")
        package_id = value.get("packageId")
        version = value.get("version")
        resources = value.get("resources")
        if package_id != "anki-study-managed-runtime" or not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            raise RuntimePackageError("RUNTIME_PACKAGE_IDENTITY_INVALID", "Runtime package identity or version is invalid")
        if not isinstance(resources, list) or not resources:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_INVALID", "Runtime package resources are missing")
        resource_ids = [raw.get("resourceId") if isinstance(raw, dict) else None for raw in resources]
        if not all(isinstance(resource_id, str) for resource_id in resource_ids) or resource_ids != sorted(
            resource_ids,
            key=lambda resource_id: resource_id.encode("utf-8"),
        ):
            raise RuntimePackageError(
                "RUNTIME_PACKAGE_MANIFEST_NONCANONICAL",
                "Runtime package resources must be sorted by resource ID",
            )

        entries: dict[str, RuntimePackageResource] = {}
        path_keys: set[str] = set()
        for raw in resources:
            if not isinstance(raw, dict) or set(raw) != {"resourceId", "relativePath", "size", "sha256"}:
                raise RuntimePackageError("RUNTIME_PACKAGE_RESOURCE_INVALID", "Runtime package resource entry is invalid")
            resource_id = raw.get("resourceId")
            size = raw.get("size")
            sha256 = raw.get("sha256")
            if (
                not isinstance(resource_id, str)
                or not resource_id
                or resource_id in entries
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
                or not isinstance(sha256, str)
                or not _SHA256_RE.fullmatch(sha256)
            ):
                raise RuntimePackageError("RUNTIME_PACKAGE_RESOURCE_INVALID", "Runtime package resource entry is invalid")
            relative = _relative_package_path(raw.get("relativePath"))
            path_key = relative.as_posix().casefold()
            if path_key in path_keys:
                raise RuntimePackageError("RUNTIME_PACKAGE_PATH_COLLISION", "Runtime package resource paths collide")
            path_keys.add(path_key)
            candidate = self.root.joinpath(*relative.parts)
            current = self.root
            for part in relative.parts:
                current /= part
                if current.is_symlink() or (current.exists() and _has_reparse_attribute(current)):
                    raise RuntimePackageError(
                        "RUNTIME_PACKAGE_REPARSE_BLOCKED",
                        "Runtime package resource path contains a reparse point",
                    )
            try:
                resolved = candidate.resolve(strict=True)
                common = os.path.commonpath((os.path.normcase(str(self.root)), os.path.normcase(str(resolved))))
            except (OSError, ValueError) as error:
                raise RuntimePackageError("RUNTIME_PACKAGE_RESOURCE_MISSING", "Runtime package resource is unavailable") from error
            if common != os.path.normcase(str(self.root)) or resolved.is_symlink() or _has_reparse_attribute(resolved):
                raise RuntimePackageError("RUNTIME_PACKAGE_PATH_ESCAPE", "Runtime package resource escaped its root")
            if not resolved.is_file() or resolved.stat().st_size != size or file_sha256(resolved) != sha256:
                raise RuntimePackageError("RUNTIME_PACKAGE_RESOURCE_CHANGED", "Runtime package resource hash or size changed")
            entries[resource_id] = RuntimePackageResource(
                resource_id=resource_id,
                relative_path=relative.as_posix(),
                path=resolved,
                size=size,
                sha256=sha256,
            )
        missing = REQUIRED_RUNTIME_RESOURCES - entries.keys()
        if missing:
            raise RuntimePackageError("RUNTIME_PACKAGE_RESOURCE_MISSING", "Runtime package is missing required resources")
        actual_path_keys: set[str] = set()
        for path in self.root.rglob("*"):
            if path.is_symlink() or _has_reparse_attribute(path):
                raise RuntimePackageError(
                    "RUNTIME_PACKAGE_REPARSE_BLOCKED",
                    "Runtime package contains a reparse point",
                )
            if path.is_file() and path != self.manifest_path:
                actual_path_keys.add(path.relative_to(self.root).as_posix().casefold())
        if actual_path_keys != path_keys:
            raise RuntimePackageError(
                "RUNTIME_PACKAGE_UNLISTED_RESOURCE",
                "Runtime package contains missing or unlisted files",
            )
        self.package_id = package_id
        self.version = version
        self.value = value
        self.digest = hashlib.sha256(source).hexdigest()
        self.resources = entries

    def resource_path(self, resource_id: str) -> Path:
        try:
            return self.resources[resource_id].path
        except KeyError as error:
            raise RuntimePackageError("RUNTIME_PACKAGE_RESOURCE_MISSING", "Runtime package resource is unavailable") from error

    def runtime_entries(self) -> list[tuple[str, Path]]:
        return [(resource.resource_id, resource.path) for resource in self.resources.values()]

    def verify(self) -> None:
        current = ManagedRuntimePackage(self.root)
        if current.digest != self.digest:
            raise RuntimePackageError("RUNTIME_PACKAGE_CHANGED", "Runtime package manifest changed after service startup")

    def public_summary(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "packageId": self.package_id,
            "version": self.version,
            "digest": f"sha256:{self.digest}",
            "resourceCount": len(self.resources),
            "pathDisclosure": False,
            "signatureVerified": False,
            "complete": False,
        }
