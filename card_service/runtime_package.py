from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .runtime_manifest import canonical_bytes, file_sha256
from .runtime_trust import (
    SIGNATURE_FILE_NAME,
    RuntimePackageTrustPolicy,
    RuntimeTrustError,
    VerifiedRuntimeSignature,
    compare_semver,
    verify_runtime_signature,
)


MAX_PACKAGE_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_SBOM_BYTES = 16 * 1024 * 1024
PACKAGE_MANIFEST_NAME = "runtime-package-v1.json"
CARD_SERVICE_VERSION = "0.1.0"
SBOM_RESOURCE_ID = "metadata:sbom-spdx"
REQUIRED_RUNTIME_RESOURCES = frozenset(
    {
        "managed-python:executable",
        "card-service:worker-bootstrap",
        "card-service:broker-client",
        "card-service:windows-restricted-launcher",
        "card-service:windows-sandbox-acl",
        "legacy-worker:entry",
        "legacy-worker:module:acg/media_tool_policy.py",
        "managed-tool:ffmpeg",
        "managed-tool:ffprobe",
        "managed-tool:yt-dlp",
        SBOM_RESOURCE_ID,
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


def _read_bounded(path: Path, maximum_bytes: int, *, code: str, label: str) -> bytes:
    try:
        if path.stat().st_size > maximum_bytes:
            raise RuntimePackageError(code, f"{label} is too large")
        with path.open("rb") as handle:
            source = handle.read(maximum_bytes + 1)
    except RuntimePackageError:
        raise
    except OSError as error:
        raise RuntimePackageError(code, f"{label} is unavailable") from error
    if not source or len(source) > maximum_bytes:
        raise RuntimePackageError(code, f"{label} is empty or too large")
    return source


def current_runtime_platform() -> str:
    system = "windows" if os.name == "nt" else sys.platform.lower()
    machine = platform.machine().lower()
    architecture = "x86_64" if machine in {"amd64", "x86_64"} else machine
    return f"{system}-{architecture}"


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


def _verify_spdx_sbom(
    resource: RuntimePackageResource,
    *,
    package_version: str,
    entries: dict[str, RuntimePackageResource],
) -> None:
    if resource.size > MAX_SBOM_BYTES:
        raise RuntimePackageError("RUNTIME_PACKAGE_SBOM_INVALID", "Runtime package SBOM is too large")
    try:
        source = _read_bounded(
            resource.path,
            MAX_SBOM_BYTES,
            code="RUNTIME_PACKAGE_SBOM_INVALID",
            label="Runtime package SBOM",
        )
        value = json.loads(source)
    except ValueError as error:
        raise RuntimePackageError("RUNTIME_PACKAGE_SBOM_INVALID", "Runtime package SBOM is invalid") from error
    if not isinstance(value, dict) or canonical_bytes(value) != source:
        raise RuntimePackageError("RUNTIME_PACKAGE_SBOM_INVALID", "Runtime package SBOM must use canonical JSON")
    if (
        value.get("spdxVersion") != "SPDX-2.3"
        or value.get("dataLicense") != "CC0-1.0"
        or value.get("SPDXID") != "SPDXRef-DOCUMENT"
        or value.get("name") != f"anki-study-managed-runtime-{package_version}"
        or not isinstance(value.get("documentNamespace"), str)
        or not str(value.get("documentNamespace")).startswith("urn:uuid:")
        or not isinstance(value.get("creationInfo"), dict)
        or not isinstance(value.get("files"), list)
    ):
        raise RuntimePackageError("RUNTIME_PACKAGE_SBOM_INVALID", "Runtime package SBOM metadata is invalid")
    expected = {
        f"./{entry.relative_path}": entry.sha256
        for resource_id, entry in entries.items()
        if resource_id != SBOM_RESOURCE_ID
    }
    observed: dict[str, str] = {}
    ordered_names: list[str] = []
    for raw in value["files"]:
        if not isinstance(raw, dict):
            raise RuntimePackageError("RUNTIME_PACKAGE_SBOM_INVALID", "Runtime package SBOM file entry is invalid")
        file_name = raw.get("fileName")
        checksums = raw.get("checksums")
        if not isinstance(file_name, str) or not isinstance(checksums, list):
            raise RuntimePackageError("RUNTIME_PACKAGE_SBOM_INVALID", "Runtime package SBOM file entry is invalid")
        sha256_values = [
            checksum.get("checksumValue")
            for checksum in checksums
            if isinstance(checksum, dict) and checksum.get("algorithm") == "SHA256"
        ]
        if (
            len(sha256_values) != 1
            or not isinstance(sha256_values[0], str)
            or _SHA256_RE.fullmatch(sha256_values[0]) is None
            or file_name in observed
        ):
            raise RuntimePackageError("RUNTIME_PACKAGE_SBOM_INVALID", "Runtime package SBOM checksum is invalid")
        observed[file_name] = sha256_values[0]
        ordered_names.append(file_name)
    if ordered_names != sorted(ordered_names, key=lambda item: item.encode("utf-8")) or observed != expected:
        raise RuntimePackageError("RUNTIME_PACKAGE_SBOM_MISMATCH", "Runtime package SBOM does not cover exact resources")


class ManagedRuntimePackage:
    """Verifies an immutable runtime package and its detached publisher signature."""

    def __init__(
        self,
        root: str | Path,
        *,
        trust_policy: RuntimePackageTrustPolicy | None = None,
        require_signature: bool = False,
        now: datetime | None = None,
    ) -> None:
        if require_signature and trust_policy is None:
            raise RuntimePackageError(
                "RUNTIME_TRUST_POLICY_REQUIRED",
                "A trusted publisher policy is required for packaged runtime mode",
            )
        self._trust_policy = trust_policy
        self._require_signature = require_signature
        self._now = now
        self.root = _assert_stable_directory(Path(root))
        manifest_candidate = self.root / PACKAGE_MANIFEST_NAME
        if manifest_candidate.is_symlink() or (
            manifest_candidate.exists() and _has_reparse_attribute(manifest_candidate)
        ):
            raise RuntimePackageError("RUNTIME_PACKAGE_REPARSE_BLOCKED", "Runtime package manifest is a reparse point")
        self.manifest_path = manifest_candidate.resolve()
        if self.manifest_path.parent != self.root:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_INVALID", "Runtime package manifest escaped its root")
        source = _read_bounded(
            self.manifest_path,
            MAX_PACKAGE_MANIFEST_BYTES,
            code="RUNTIME_PACKAGE_MANIFEST_INVALID",
            label="Runtime package manifest",
        )
        try:
            value = json.loads(source)
        except ValueError as error:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_INVALID", "Runtime package manifest is invalid JSON") from error
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "packageId",
            "version",
            "compatibility",
            "sbom",
            "resources",
        }:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_INVALID", "Runtime package manifest shape is invalid")
        if canonical_bytes(value) != source:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_NONCANONICAL", "Runtime package manifest must use canonical JSON")
        if value.get("schemaVersion") != 1:
            raise RuntimePackageError("RUNTIME_PACKAGE_MANIFEST_INVALID", "Runtime package schema version is invalid")
        package_id = value.get("packageId")
        version = value.get("version")
        compatibility = value.get("compatibility")
        sbom = value.get("sbom")
        resources = value.get("resources")
        if package_id != "anki-study-managed-runtime" or not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            raise RuntimePackageError("RUNTIME_PACKAGE_IDENTITY_INVALID", "Runtime package identity or version is invalid")
        if not isinstance(compatibility, dict) or set(compatibility) != {
            "cardServiceApiVersion",
            "minimumCardServiceVersion",
            "platform",
        }:
            raise RuntimePackageError("RUNTIME_PACKAGE_COMPATIBILITY_INVALID", "Runtime package compatibility is invalid")
        minimum_service_version = compatibility.get("minimumCardServiceVersion")
        if (
            compatibility.get("cardServiceApiVersion") != 1
            or not isinstance(minimum_service_version, str)
            or compatibility.get("platform") != current_runtime_platform()
        ):
            raise RuntimePackageError("RUNTIME_PACKAGE_INCOMPATIBLE", "Runtime package is incompatible with this host")
        try:
            if compare_semver(CARD_SERVICE_VERSION, minimum_service_version) < 0:
                raise RuntimePackageError(
                    "RUNTIME_PACKAGE_INCOMPATIBLE",
                    "Runtime package requires a newer Card Service",
                )
        except RuntimeTrustError as error:
            raise RuntimePackageError(error.code, str(error)) from error
        if sbom != {"format": "SPDX-2.3", "resourceId": SBOM_RESOURCE_ID}:
            raise RuntimePackageError("RUNTIME_PACKAGE_SBOM_INVALID", "Runtime package SBOM declaration is invalid")
        self.signature: VerifiedRuntimeSignature | None = None
        signature_path = self.root / SIGNATURE_FILE_NAME
        if trust_policy is not None:
            try:
                self.signature = verify_runtime_signature(
                    signature_path,
                    manifest_sha256=hashlib.sha256(source).hexdigest(),
                    package_version=version,
                    trust_policy=trust_policy,
                    now=now,
                )
            except RuntimeTrustError as error:
                raise RuntimePackageError(error.code, str(error)) from error
        elif require_signature or signature_path.exists():
            raise RuntimePackageError(
                "RUNTIME_TRUST_POLICY_REQUIRED",
                "Runtime package signature cannot be verified without a trusted publisher policy",
            )
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
        _verify_spdx_sbom(entries[SBOM_RESOURCE_ID], package_version=version, entries=entries)
        actual_path_keys: set[str] = set()
        for path in self.root.rglob("*"):
            if path.is_symlink() or _has_reparse_attribute(path):
                raise RuntimePackageError(
                    "RUNTIME_PACKAGE_REPARSE_BLOCKED",
                    "Runtime package contains a reparse point",
                )
            if path.is_file() and path not in {self.manifest_path, signature_path.resolve()}:
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
        current = ManagedRuntimePackage(
            self.root,
            trust_policy=self._trust_policy,
            require_signature=self._require_signature,
            now=self._now,
        )
        if current.digest != self.digest:
            raise RuntimePackageError("RUNTIME_PACKAGE_CHANGED", "Runtime package manifest changed after service startup")

    def public_summary(self) -> dict[str, object]:
        summary: dict[str, object] = {
            "schemaVersion": 1,
            "packageId": self.package_id,
            "version": self.version,
            "digest": f"sha256:{self.digest}",
            "resourceCount": len(self.resources),
            "pathDisclosure": False,
            "signatureVerified": self.signature is not None,
            "sbomVerified": True,
            "complete": False,
        }
        if self.signature is not None:
            summary.update(
                {
                    "publisherAuthority": self.signature.authority,
                    "trustSequence": self.signature.trust_sequence,
                    "signedAt": self.signature.signed_at,
                    "expiresAt": self.signature.expires_at,
                    "trustPolicyDigest": f"sha256:{self.signature.trust_policy_digest}",
                }
            )
        return summary
