from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable

from .runtime_manifest import RuntimeManifestError, assert_stable_path, canonical_bytes, file_sha256
from .runtime_package import (
    CARD_SERVICE_VERSION,
    MAX_PACKAGE_MANIFEST_BYTES,
    MAX_SBOM_BYTES,
    PACKAGE_MANIFEST_NAME,
    REQUIRED_RUNTIME_RESOURCES,
    SBOM_RESOURCE_ID,
    current_runtime_platform,
)
from .runtime_trust import SIGNATURE_FILE_NAME


MAX_BUILD_FILES = 100_000
MAX_BUILD_BYTES = 16 * 1024 * 1024 * 1024
SBOM_RELATIVE_PATH = "metadata/SBOM.spdx.json"
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/+-]{0,255}$")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class RuntimeBuildError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RuntimeBuildResource:
    resource_id: str
    source: Path
    relative_path: str


@dataclass(frozen=True)
class RuntimeBuildResult:
    root: Path
    manifest_path: Path
    sbom_path: Path
    manifest_sha256: str
    resource_count: int
    total_bytes: int


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _stable_output_parent(path: Path) -> Path:
    if not path.is_absolute():
        raise RuntimeBuildError("RUNTIME_BUILD_OUTPUT_RELATIVE", "Runtime build output must be absolute")
    parent = path.parent.resolve(strict=True)
    current = Path(parent.anchor)
    for part in parent.parts[1:]:
        current /= part
        if current.is_symlink() or _has_reparse_attribute(current):
            raise RuntimeBuildError("RUNTIME_BUILD_REPARSE_BLOCKED", "Runtime build output parent contains a reparse point")
    if not parent.is_dir():
        raise RuntimeBuildError("RUNTIME_BUILD_OUTPUT_INVALID", "Runtime build output parent must be a directory")
    return parent


def _relative_path(value: str) -> PurePosixPath:
    if not value or chr(92) in value or ":" in value:
        raise RuntimeBuildError("RUNTIME_BUILD_PATH_INVALID", "Runtime resource path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise RuntimeBuildError("RUNTIME_BUILD_PATH_INVALID", "Runtime resource path is invalid")
    for part in relative.parts:
        stem = part.rstrip(" .").split(".", 1)[0].upper()
        if part != part.rstrip(" .") or stem in _WINDOWS_RESERVED:
            raise RuntimeBuildError("RUNTIME_BUILD_PATH_INVALID", "Runtime resource path is invalid")
    return relative


def _created_at(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RuntimeBuildError("RUNTIME_BUILD_TIMESTAMP_INVALID", "createdAt must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise RuntimeBuildError("RUNTIME_BUILD_TIMESTAMP_INVALID", "createdAt is invalid") from error
    if parsed.tzinfo != timezone.utc or parsed.microsecond != 0:
        raise RuntimeBuildError(
            "RUNTIME_BUILD_TIMESTAMP_INVALID",
            "createdAt must use whole seconds in UTC",
        )
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _copy_verified(source: Path, target: Path) -> tuple[int, str]:
    try:
        stable = assert_stable_path(source)
    except (OSError, RuntimeManifestError) as error:
        code = getattr(error, "code", "RUNTIME_BUILD_SOURCE_INVALID")
        raise RuntimeBuildError(str(code), "Runtime build source is unavailable or unsafe") from error
    before = stable.stat()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(stable, target)
    source_digest = file_sha256(stable)
    after = stable.stat()
    target_digest = file_sha256(target)
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or source_digest != target_digest
    ):
        raise RuntimeBuildError("RUNTIME_BUILD_SOURCE_CHANGED", "Runtime build source changed while it was copied")
    if os.name != "nt":
        target.chmod(stat.S_IMODE(before.st_mode))
    return target.stat().st_size, target_digest


def _spdx_id(relative_path: str) -> str:
    return f"SPDXRef-File-{hashlib.sha256(relative_path.encode('utf-8')).hexdigest()[:24]}"


def build_runtime_package(
    output_root: Path,
    *,
    version: str,
    resources: Iterable[RuntimeBuildResource],
    created_at: str,
    creator: str = "Organization: Anki Study Agent",
) -> RuntimeBuildResult:
    """Build an unsigned, deterministic runtime package staging directory.

    The release signer is intentionally separate: this function never accepts,
    reads, or writes publisher private key material.
    """

    if not _VERSION_RE.fullmatch(version):
        raise RuntimeBuildError("RUNTIME_BUILD_VERSION_INVALID", "Runtime package version is invalid")
    if (
        not creator.startswith(("Organization: ", "Person: ", "Tool: "))
        or len(creator) > 256
        or any(ord(character) < 0x20 for character in creator)
    ):
        raise RuntimeBuildError("RUNTIME_BUILD_CREATOR_INVALID", "SPDX creator is invalid")
    timestamp = _created_at(created_at)
    parent = _stable_output_parent(output_root)
    if output_root.exists():
        raise RuntimeBuildError("RUNTIME_BUILD_OUTPUT_EXISTS", "Runtime build output already exists")

    prepared: list[tuple[str, Path, PurePosixPath]] = []
    resource_ids: set[str] = set()
    path_keys: set[str] = set()
    for resource in resources:
        if (
            not isinstance(resource, RuntimeBuildResource)
            or _RESOURCE_ID_RE.fullmatch(resource.resource_id) is None
            or resource.resource_id == SBOM_RESOURCE_ID
            or resource.resource_id in resource_ids
        ):
            raise RuntimeBuildError("RUNTIME_BUILD_RESOURCE_INVALID", "Runtime resource ID is invalid or duplicated")
        relative = _relative_path(resource.relative_path)
        path_key = relative.as_posix().casefold()
        if path_key in path_keys or path_key in {
            PACKAGE_MANIFEST_NAME.casefold(),
            SIGNATURE_FILE_NAME.casefold(),
            SBOM_RELATIVE_PATH.casefold(),
        }:
            raise RuntimeBuildError("RUNTIME_BUILD_PATH_COLLISION", "Runtime resource paths collide")
        resource_ids.add(resource.resource_id)
        path_keys.add(path_key)
        prepared.append((resource.resource_id, resource.source, relative))
    missing = (REQUIRED_RUNTIME_RESOURCES - {SBOM_RESOURCE_ID}) - resource_ids
    if missing:
        raise RuntimeBuildError("RUNTIME_BUILD_RESOURCE_MISSING", "Runtime build is missing required resources")
    if not prepared or len(prepared) > MAX_BUILD_FILES:
        raise RuntimeBuildError("RUNTIME_BUILD_TOO_LARGE", "Runtime build has an invalid resource count")
    prepared.sort(key=lambda value: value[0].encode("utf-8"))

    with tempfile.TemporaryDirectory(prefix=f".{output_root.name}.build-", dir=parent) as temporary:
        staging = Path(temporary) / "runtime"
        staging.mkdir()
        manifest_resources: list[dict[str, object]] = []
        total_bytes = 0
        for resource_id, source, relative in prepared:
            size, digest = _copy_verified(source, staging.joinpath(*relative.parts))
            total_bytes += size
            if total_bytes > MAX_BUILD_BYTES:
                raise RuntimeBuildError("RUNTIME_BUILD_TOO_LARGE", "Runtime build exceeds its byte limit")
            manifest_resources.append(
                {
                    "resourceId": resource_id,
                    "relativePath": relative.as_posix(),
                    "size": size,
                    "sha256": digest,
                }
            )

        namespace_material = canonical_bytes(
            {
                "packageId": "anki-study-managed-runtime",
                "version": version,
                "platform": current_runtime_platform(),
                "resources": manifest_resources,
            }
        )
        namespace = uuid.uuid5(
            uuid.NAMESPACE_URL,
            hashlib.sha256(namespace_material).hexdigest(),
        )
        by_path = sorted(
            manifest_resources,
            key=lambda item: str(item["relativePath"]).encode("utf-8"),
        )
        sbom = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "creationInfo": {
                "created": timestamp,
                "creators": [creator],
            },
            "dataLicense": "CC0-1.0",
            "documentNamespace": f"urn:uuid:{namespace}",
            "files": [
                {
                    "SPDXID": _spdx_id(str(resource["relativePath"])),
                    "checksums": [
                        {
                            "algorithm": "SHA256",
                            "checksumValue": resource["sha256"],
                        }
                    ],
                    "fileName": f"./{resource['relativePath']}",
                }
                for resource in by_path
            ],
            "name": f"anki-study-managed-runtime-{version}",
            "spdxVersion": "SPDX-2.3",
        }
        sbom_path = staging / SBOM_RELATIVE_PATH
        sbom_path.parent.mkdir(parents=True, exist_ok=True)
        sbom_source = canonical_bytes(sbom)
        if len(sbom_source) > MAX_SBOM_BYTES:
            raise RuntimeBuildError("RUNTIME_BUILD_TOO_LARGE", "Runtime package SBOM exceeds its byte limit")
        sbom_path.write_bytes(sbom_source)
        total_bytes += len(sbom_source)
        manifest_resources.append(
            {
                "resourceId": SBOM_RESOURCE_ID,
                "relativePath": SBOM_RELATIVE_PATH,
                "size": len(sbom_source),
                "sha256": hashlib.sha256(sbom_source).hexdigest(),
            }
        )
        manifest_resources.sort(key=lambda item: str(item["resourceId"]).encode("utf-8"))
        manifest = {
            "schemaVersion": 1,
            "packageId": "anki-study-managed-runtime",
            "version": version,
            "compatibility": {
                "cardServiceApiVersion": 1,
                "minimumCardServiceVersion": CARD_SERVICE_VERSION,
                "platform": current_runtime_platform(),
            },
            "sbom": {
                "format": "SPDX-2.3",
                "resourceId": SBOM_RESOURCE_ID,
            },
            "resources": manifest_resources,
        }
        manifest_source = canonical_bytes(manifest)
        if len(manifest_source) > MAX_PACKAGE_MANIFEST_BYTES:
            raise RuntimeBuildError("RUNTIME_BUILD_TOO_LARGE", "Runtime package manifest exceeds its byte limit")
        manifest_path = staging / PACKAGE_MANIFEST_NAME
        manifest_path.write_bytes(manifest_source)
        total_bytes += len(manifest_source)
        if total_bytes > MAX_BUILD_BYTES:
            raise RuntimeBuildError("RUNTIME_BUILD_TOO_LARGE", "Runtime build exceeds its byte limit")
        manifest_digest = hashlib.sha256(manifest_source).hexdigest()
        os.replace(staging, output_root)

    return RuntimeBuildResult(
        root=output_root,
        manifest_path=output_root / PACKAGE_MANIFEST_NAME,
        sbom_path=output_root / SBOM_RELATIVE_PATH,
        manifest_sha256=manifest_digest,
        resource_count=len(manifest_resources),
        total_bytes=total_bytes,
    )
