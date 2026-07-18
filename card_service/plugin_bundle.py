from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .runtime_manifest import RuntimeManifestError, assert_stable_path, canonical_bytes, file_sha256
from .runtime_package import ManagedRuntimePackage, RuntimePackageError
from .runtime_trust import RuntimePackageTrustPolicy, RuntimeTrustError
from .windows_sandbox_acl import (
    CONTAINER_INHERIT_ACE,
    OBJECT_INHERIT_ACE,
    DaclEntry,
    WindowsSandboxAclError,
    apply_exact_dacl,
    harden_runtime_tree,
    read_dacl,
    runtime_sandbox_sid,
    service_root_grants,
    verify_runtime_tree_dacl,
)


RELEASE_MANIFEST_NAME = "release-package-v1.json"
RELEASE_SBOM_NAME = "SBOM.spdx.json"
PLUGIN_MANIFEST_PATH = ".codex-plugin/plugin.json"
LAUNCHER_PATH = "server/launcher/anki-study-agent.exe"
RUNTIME_PATH = "server/runtime"
TRUST_POLICY_PATH = "server/runtime-publisher-trust-v1.json"
MAX_RELEASE_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_RELEASE_SBOM_BYTES = 16 * 1024 * 1024
MAX_PLUGIN_MANIFEST_BYTES = 256 * 1024
MAX_BUNDLE_FILES = 60_000
MAX_BUNDLE_BYTES = 20 * 1024 * 1024 * 1024
MAX_BUNDLE_DEPTH = 40
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/+-]{0,511}$")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_PASSIVE_RELEASE_STATE = {
    "channel": "development-candidate",
    "installable": False,
    "mcpDeclared": False,
    "outerSignatureVerified": False,
    "publisherKeyManaged": False,
}


class PluginBundleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PluginBundleBuildResult:
    root: Path
    manifest_path: Path
    sbom_path: Path
    manifest_sha256: str
    resource_count: int
    total_bytes: int


@dataclass(frozen=True)
class _BundleInput:
    resource_id: str
    source: Path
    relative_path: PurePosixPath


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _stable_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise PluginBundleError("PLUGIN_BUNDLE_PATH_INVALID", f"{label} must be absolute")
    try:
        resolved = path.resolve(strict=True)
        current = Path(resolved.anchor)
        for part in resolved.parts[1:]:
            current /= part
            if current.is_symlink() or _has_reparse_attribute(current):
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_REPARSE_BLOCKED",
                    f"{label} contains a reparse point",
                )
    except OSError as error:
        raise PluginBundleError(
            "PLUGIN_BUNDLE_PATH_INVALID",
            f"{label} is unavailable",
        ) from error
    if not resolved.is_dir():
        raise PluginBundleError("PLUGIN_BUNDLE_PATH_INVALID", f"{label} must be a directory")
    return resolved


def _stable_file(path: Path, label: str) -> Path:
    try:
        return assert_stable_path(path)
    except (OSError, RuntimeManifestError) as error:
        raise PluginBundleError(
            "PLUGIN_BUNDLE_PATH_INVALID",
            f"{label} is unavailable or unsafe",
        ) from error


def _stable_output_parent(output: Path) -> Path:
    if not output.is_absolute():
        raise PluginBundleError("PLUGIN_BUNDLE_OUTPUT_INVALID", "Bundle output must be absolute")
    return _stable_directory(output.parent, "Bundle output parent")


def _relative_path(value: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or value != unicodedata.normalize("NFC", value)
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise PluginBundleError("PLUGIN_BUNDLE_RESOURCE_INVALID", "Bundle resource path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise PluginBundleError("PLUGIN_BUNDLE_RESOURCE_INVALID", "Bundle resource path is invalid")
    for part in relative.parts:
        stem = part.rstrip(" .").split(".", 1)[0].upper()
        if part != part.rstrip(" .") or stem in _WINDOWS_RESERVED:
            raise PluginBundleError("PLUGIN_BUNDLE_RESOURCE_INVALID", "Bundle resource path is invalid")
    return relative


def _created_at(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PluginBundleError(
            "PLUGIN_BUNDLE_TIMESTAMP_INVALID",
            "createdAt must be an explicit UTC timestamp",
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise PluginBundleError("PLUGIN_BUNDLE_TIMESTAMP_INVALID", "createdAt is invalid") from error
    if parsed.tzinfo != timezone.utc or parsed.microsecond != 0:
        raise PluginBundleError(
            "PLUGIN_BUNDLE_TIMESTAMP_INVALID",
            "createdAt must use whole seconds in UTC",
        )
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_bounded(path: Path, maximum: int, label: str) -> bytes:
    stable = _stable_file(path, label)
    size = stable.stat().st_size
    if size <= 0 or size > maximum:
        raise PluginBundleError("PLUGIN_BUNDLE_METADATA_INVALID", f"{label} is empty or too large")
    with stable.open("rb") as handle:
        source = handle.read(maximum + 1)
    if not source or len(source) > maximum:
        raise PluginBundleError("PLUGIN_BUNDLE_METADATA_INVALID", f"{label} is empty or too large")
    return source


def _walk_files(root: Path, *, maximum_depth: int = MAX_BUNDLE_DEPTH) -> list[Path]:
    files: list[Path] = []

    def visit(directory: Path, depth: int) -> None:
        if depth > maximum_depth:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_TOO_LARGE",
                "Bundle directory depth exceeds its limit",
            )
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda item: item.name.encode("utf-8"),
            )
        except OSError as error:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_PATH_INVALID",
                "Bundle source directory cannot be read",
            ) from error
        for entry in entries:
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_PATH_INVALID",
                    "Bundle source entry is unavailable",
                ) from error
            if entry.is_symlink() or _has_reparse_attribute(entry):
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_REPARSE_BLOCKED",
                    "Bundle source contains a reparse point",
                )
            if stat.S_ISDIR(metadata.st_mode):
                visit(entry, depth + 1)
            elif stat.S_ISREG(metadata.st_mode):
                files.append(entry)
                if len(files) > MAX_BUNDLE_FILES:
                    raise PluginBundleError(
                        "PLUGIN_BUNDLE_TOO_LARGE",
                        "Bundle file count exceeds its limit",
                    )
            else:
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_RESOURCE_INVALID",
                    "Bundle source contains an unsupported entry",
                )

    visit(root, 0)
    return files


def _copy_verified(source: Path, target: Path) -> tuple[int, str]:
    stable = _stable_file(source, "Bundle resource")
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
        raise PluginBundleError(
            "PLUGIN_BUNDLE_SOURCE_CHANGED",
            "Bundle source changed while it was copied",
        )
    if os.name != "nt":
        target.chmod(stat.S_IMODE(before.st_mode))
    return target.stat().st_size, target_digest


def _outer_bundle_paths(root: Path) -> list[Path]:
    runtime_root = root.joinpath(*PurePosixPath(RUNTIME_PATH).parts)
    paths: list[Path] = []
    for path in [root, *root.rglob("*")]:
        if path == runtime_root or runtime_root in path.parents:
            continue
        paths.append(path)
    return sorted(paths, key=lambda item: (len(item.parts), item.as_posix().encode("utf-8")))


def _harden_bundle_dacl(root: Path, package_id: str) -> None:
    grants = service_root_grants()
    try:
        for path in _outer_bundle_paths(root):
            apply_exact_dacl(path, grants, inherit_to_children=path.is_dir())
        sandbox_sid = runtime_sandbox_sid(package_id)
        harden_runtime_tree(
            root.joinpath(*PurePosixPath(RUNTIME_PATH).parts),
            sandbox_sid,
        )
    except WindowsSandboxAclError as error:
        raise PluginBundleError(
            "PLUGIN_BUNDLE_DACL_FAILED",
            "Plugin release DACL could not be applied",
        ) from error


def _verify_bundle_dacl(root: Path, package_id: str) -> None:
    grants = service_root_grants()
    expected_file = tuple(sorted(DaclEntry(sid, mask, 0) for sid, mask in grants))
    expected_directory = tuple(
        sorted(
            DaclEntry(
                sid,
                mask,
                OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
            )
            for sid, mask in grants
        )
    )
    try:
        for path in _outer_bundle_paths(root):
            expected = expected_directory if path.is_dir() else expected_file
            if read_dacl(path) != expected:
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_DACL_MISMATCH",
                    "Plugin release outer DACL is not exact",
                )
        verify_runtime_tree_dacl(
            root.joinpath(*PurePosixPath(RUNTIME_PATH).parts),
            runtime_sandbox_sid(package_id),
        )
    except WindowsSandboxAclError as error:
        raise PluginBundleError(
            "PLUGIN_BUNDLE_DACL_MISMATCH",
            "Plugin release runtime DACL is not exact",
        ) from error


def _spdx_id(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24]
    return f"SPDXRef-File-{digest}"


def _plugin_manifest(plugin_root: Path, *, expected_version: str | None = None) -> tuple[Path, dict[str, object]]:
    manifest_path = plugin_root.joinpath(*PurePosixPath(PLUGIN_MANIFEST_PATH).parts)
    source = _read_bounded(manifest_path, MAX_PLUGIN_MANIFEST_BYTES, "Plugin manifest")
    try:
        value = json.loads(source)
    except ValueError as error:
        raise PluginBundleError("PLUGIN_BUNDLE_PLUGIN_INVALID", "Plugin manifest is invalid JSON") from error
    if not isinstance(value, dict):
        raise PluginBundleError("PLUGIN_BUNDLE_PLUGIN_INVALID", "Plugin manifest must be an object")
    if value.get("name") != "anki-study-agent":
        raise PluginBundleError("PLUGIN_BUNDLE_PLUGIN_INVALID", "Plugin identity is invalid")
    version = value.get("version")
    if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
        raise PluginBundleError("PLUGIN_BUNDLE_PLUGIN_INVALID", "Plugin version is invalid")
    if expected_version is not None and version != expected_version:
        raise PluginBundleError(
            "PLUGIN_BUNDLE_VERSION_MISMATCH",
            "Plugin manifest version does not match the bundle version",
        )
    if "mcpServers" in value or "apps" in value:
        raise PluginBundleError(
            "PLUGIN_BUNDLE_NOT_PASSIVE",
            "Unsigned candidate plugin must not declare MCP servers or apps",
        )
    if value.get("skills") != "./skills/" or not (plugin_root / "skills").is_dir():
        raise PluginBundleError("PLUGIN_BUNDLE_PLUGIN_INVALID", "Plugin skills directory is invalid")
    for forbidden in (".mcp.json", ".app.json"):
        if (plugin_root / forbidden).exists():
            raise PluginBundleError(
                "PLUGIN_BUNDLE_NOT_PASSIVE",
                "Unsigned candidate plugin must not contain MCP or app mappings",
            )
    return _stable_file(manifest_path, "Plugin manifest"), value


def _bundle_inputs(
    *,
    plugin_root: Path,
    launcher: Path,
    runtime_package: ManagedRuntimePackage,
    trust_policy: Path,
) -> list[_BundleInput]:
    values: list[_BundleInput] = []
    for source in _walk_files(plugin_root):
        relative = _relative_path(source.relative_to(plugin_root).as_posix())
        if relative.parts[0].casefold() == "server" or relative.as_posix().casefold() in {
            RELEASE_MANIFEST_NAME.casefold(),
            RELEASE_SBOM_NAME.casefold(),
            ".mcp.json",
            ".app.json",
        }:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_PATH_COLLISION",
                "Passive plugin source collides with generated release files",
            )
        values.append(
            _BundleInput(
                resource_id=f"plugin:{relative.as_posix()}",
                source=source,
                relative_path=relative,
            )
        )

    values.append(
        _BundleInput(
            resource_id="launcher:windows-x86_64",
            source=launcher,
            relative_path=_relative_path(LAUNCHER_PATH),
        )
    )
    values.append(
        _BundleInput(
            resource_id="runtime:publisher-trust-policy",
            source=trust_policy,
            relative_path=_relative_path(TRUST_POLICY_PATH),
        )
    )
    for source in _walk_files(runtime_package.root):
        relative = _relative_path(source.relative_to(runtime_package.root).as_posix())
        values.append(
            _BundleInput(
                resource_id=f"runtime:{relative.as_posix()}",
                source=source,
                relative_path=_relative_path(f"{RUNTIME_PATH}/{relative.as_posix()}"),
            )
        )
    return values


class PluginReleaseBundle:
    """Verify an unsigned, passive plugin release-candidate directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = _stable_directory(Path(root), "Plugin release bundle")
        source = _read_bounded(
            self.root / RELEASE_MANIFEST_NAME,
            MAX_RELEASE_MANIFEST_BYTES,
            "Plugin release manifest",
        )
        try:
            value = json.loads(source)
        except ValueError as error:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_MANIFEST_INVALID",
                "Plugin release manifest is invalid JSON",
            ) from error
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "packageId",
            "version",
            "createdAt",
            "releaseState",
            "components",
            "sbom",
            "resources",
        }:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_MANIFEST_INVALID",
                "Plugin release manifest shape is invalid",
            )
        if canonical_bytes(value) != source:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_MANIFEST_NONCANONICAL",
                "Plugin release manifest must use canonical JSON",
            )
        version = value.get("version")
        if (
            value.get("schemaVersion") != 1
            or value.get("packageId") != "anki-study-agent-plugin"
            or not isinstance(version, str)
            or _VERSION_RE.fullmatch(version) is None
        ):
            raise PluginBundleError(
                "PLUGIN_BUNDLE_IDENTITY_INVALID",
                "Plugin release identity is invalid",
            )
        _created_at(value.get("createdAt"))
        if value.get("releaseState") != _PASSIVE_RELEASE_STATE:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_RELEASE_STATE_INVALID",
                "Unsigned candidate must remain passive and non-installable",
            )
        if value.get("sbom") != {
            "format": "SPDX-2.3",
            "resourceId": "metadata:sbom-spdx",
        }:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_SBOM_INVALID",
                "Plugin release SBOM declaration is invalid",
            )

        resources = value.get("resources")
        if (
            not isinstance(resources, list)
            or not resources
            or len(resources) + 1 > MAX_BUNDLE_FILES
        ):
            raise PluginBundleError(
                "PLUGIN_BUNDLE_MANIFEST_INVALID",
                "Plugin release resources are invalid",
            )
        resource_ids = [
            entry.get("resourceId") if isinstance(entry, dict) else None
            for entry in resources
        ]
        if (
            not all(isinstance(resource_id, str) for resource_id in resource_ids)
            or resource_ids != sorted(resource_ids, key=lambda item: item.encode("utf-8"))
        ):
            raise PluginBundleError(
                "PLUGIN_BUNDLE_MANIFEST_NONCANONICAL",
                "Plugin release resources must be sorted by resource ID",
            )

        entries: dict[str, dict[str, object]] = {}
        path_keys: set[str] = set()
        total_bytes = 0
        for raw in resources:
            if not isinstance(raw, dict) or set(raw) != {
                "resourceId",
                "relativePath",
                "size",
                "sha256",
            }:
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_RESOURCE_INVALID",
                    "Plugin release resource entry is invalid",
                )
            resource_id = raw.get("resourceId")
            size = raw.get("size")
            digest = raw.get("sha256")
            if (
                not isinstance(resource_id, str)
                or _RESOURCE_ID_RE.fullmatch(resource_id) is None
                or resource_id in entries
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
                or not isinstance(digest, str)
                or _SHA256_RE.fullmatch(digest) is None
            ):
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_RESOURCE_INVALID",
                    "Plugin release resource identity is invalid",
                )
            relative = _relative_path(raw.get("relativePath"))
            path_key = relative.as_posix().casefold()
            if path_key in path_keys or path_key == RELEASE_MANIFEST_NAME.casefold():
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_PATH_COLLISION",
                    "Plugin release resource paths collide",
                )
            path_keys.add(path_key)
            file_path = _stable_file(
                self.root.joinpath(*relative.parts),
                "Plugin release resource",
            )
            if file_path.stat().st_size != size or file_sha256(file_path) != digest:
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_RESOURCE_CHANGED",
                    "Plugin release resource hash or size changed",
                )
            total_bytes += size
            if total_bytes > MAX_BUNDLE_BYTES:
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_TOO_LARGE",
                    "Plugin release exceeds its byte limit",
                )
            entries[resource_id] = {
                **raw,
                "relativePath": relative.as_posix(),
                "path": file_path,
            }

        required = {
            "launcher:windows-x86_64",
            "runtime:publisher-trust-policy",
            "runtime:runtime-package-v1.json",
            "runtime:runtime-package-v1.sig.json",
            "metadata:sbom-spdx",
            f"plugin:{PLUGIN_MANIFEST_PATH}",
        }
        if not required.issubset(entries):
            raise PluginBundleError(
                "PLUGIN_BUNDLE_RESOURCE_MISSING",
                "Plugin release is missing a required component",
            )
        actual_paths = {
            path.relative_to(self.root).as_posix().casefold()
            for path in _walk_files(self.root)
            if path.name != RELEASE_MANIFEST_NAME or path.parent != self.root
        }
        if actual_paths != path_keys:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_UNLISTED_RESOURCE",
                "Plugin release contains missing or unlisted files",
            )

        sbom_entry = entries["metadata:sbom-spdx"]
        if sbom_entry["relativePath"] != RELEASE_SBOM_NAME:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_SBOM_INVALID",
                "Plugin release SBOM path is invalid",
            )
        sbom_source = _read_bounded(
            sbom_entry["path"],
            MAX_RELEASE_SBOM_BYTES,
            "Plugin release SBOM",
        )
        try:
            sbom = json.loads(sbom_source)
        except ValueError as error:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_SBOM_INVALID",
                "Plugin release SBOM is invalid JSON",
            ) from error
        if canonical_bytes(sbom) != sbom_source or not isinstance(sbom, dict):
            raise PluginBundleError(
                "PLUGIN_BUNDLE_SBOM_INVALID",
                "Plugin release SBOM is not canonical",
            )
        files = sbom.get("files")
        if (
            sbom.get("spdxVersion") != "SPDX-2.3"
            or sbom.get("dataLicense") != "CC0-1.0"
            or sbom.get("SPDXID") != "SPDXRef-DOCUMENT"
            or not isinstance(files, list)
        ):
            raise PluginBundleError(
                "PLUGIN_BUNDLE_SBOM_INVALID",
                "Plugin release SBOM metadata is invalid",
            )
        expected_sbom = {
            f"./{entry['relativePath']}": entry["sha256"]
            for resource_id, entry in entries.items()
            if resource_id != "metadata:sbom-spdx"
        }
        observed_sbom: dict[str, str] = {}
        for item in files:
            checksums = item.get("checksums") if isinstance(item, dict) else None
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("fileName"), str)
                or not isinstance(checksums, list)
                or len(checksums) != 1
                or not isinstance(checksums[0], dict)
                or checksums[0].get("algorithm") != "SHA256"
                or not isinstance(checksums[0].get("checksumValue"), str)
            ):
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_SBOM_INVALID",
                    "Plugin release SBOM file is invalid",
                )
            if item["fileName"] in observed_sbom:
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_SBOM_INVALID",
                    "Plugin release SBOM contains duplicates",
                )
            observed_sbom[item["fileName"]] = checksums[0]["checksumValue"]
        if list(observed_sbom) != sorted(observed_sbom, key=lambda item: item.encode("utf-8")):
            raise PluginBundleError(
                "PLUGIN_BUNDLE_SBOM_INVALID",
                "Plugin release SBOM files must be sorted by path",
            )
        if observed_sbom != expected_sbom:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_SBOM_MISMATCH",
                "Plugin release SBOM does not cover the exact payload",
            )

        components = value.get("components")
        if not isinstance(components, dict) or set(components) != {
            "pluginManifest",
            "launcher",
            "runtime",
        }:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_COMPONENT_INVALID",
                "Plugin release components are invalid",
            )
        plugin_entry = entries[f"plugin:{PLUGIN_MANIFEST_PATH}"]
        if components["pluginManifest"] != {
            "relativePath": PLUGIN_MANIFEST_PATH,
            "sha256": plugin_entry["sha256"],
        }:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_COMPONENT_INVALID",
                "Plugin manifest component binding is invalid",
            )
        _plugin_manifest(self.root, expected_version=version)

        launcher_entry = entries["launcher:windows-x86_64"]
        runtime_manifest_entry = entries["runtime:runtime-package-v1.json"]
        trust_entry = entries["runtime:publisher-trust-policy"]
        expected_launcher_component = {
            "relativePath": LAUNCHER_PATH,
            "sha256": launcher_entry["sha256"],
            "runtimeManifestSha256": runtime_manifest_entry["sha256"],
            "runtimeTrustPolicySha256": trust_entry["sha256"],
        }
        if components["launcher"] != expected_launcher_component:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_COMPONENT_INVALID",
                "Launcher component binding is invalid",
            )
        try:
            trust_policy = RuntimePackageTrustPolicy.load(trust_entry["path"])
            runtime = ManagedRuntimePackage(
                self.root.joinpath(*PurePosixPath(RUNTIME_PATH).parts),
                trust_policy=trust_policy,
                require_signature=True,
            )
        except (RuntimePackageError, RuntimeTrustError) as error:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_RUNTIME_INVALID",
                "Plugin release runtime signature or contents are invalid",
            ) from error
        expected_runtime_component = {
            "relativePath": RUNTIME_PATH,
            "manifestSha256": runtime.digest,
            "publisherTrustPolicySha256": trust_entry["sha256"],
            "signatureVerified": True,
        }
        if components["runtime"] != expected_runtime_component:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_COMPONENT_INVALID",
                "Runtime component binding is invalid",
            )
        self.bundle_dacl_verified = False
        if os.name == "nt":
            _verify_bundle_dacl(self.root, runtime.package_id)
            self.bundle_dacl_verified = True

        self.value = value
        self.version = version
        self.resources = entries
        self.runtime = runtime
        self.digest = hashlib.sha256(source).hexdigest()
        self.total_bytes = total_bytes + len(source)

    def public_summary(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "packageId": "anki-study-agent-plugin",
            "version": self.version,
            "digest": f"sha256:{self.digest}",
            "resourceCount": len(self.resources),
            "totalBytes": self.total_bytes,
            "runtimeSignatureVerified": True,
            "sbomVerified": True,
            "bundleDaclVerified": self.bundle_dacl_verified,
            "runtimeDaclVerified": self.bundle_dacl_verified,
            "installable": False,
            "outerSignatureVerified": False,
            "complete": False,
        }


def build_plugin_release_candidate(
    output_root: Path,
    *,
    version: str,
    created_at: str,
    plugin_root: Path,
    launcher: Path,
    runtime_root: Path,
    runtime_trust_policy: Path,
    creator: str = "Organization: Anki Study Agent",
) -> PluginBundleBuildResult:
    """Build a deterministic passive candidate without release private keys."""

    if os.name != "nt":
        raise PluginBundleError(
            "PLUGIN_BUNDLE_PLATFORM_UNSUPPORTED",
            "The current release candidate targets Windows only",
        )
    if _VERSION_RE.fullmatch(version) is None:
        raise PluginBundleError("PLUGIN_BUNDLE_VERSION_INVALID", "Bundle version is invalid")
    if (
        not creator.startswith(("Organization: ", "Person: ", "Tool: "))
        or len(creator) > 256
        or any(ord(character) < 0x20 for character in creator)
    ):
        raise PluginBundleError("PLUGIN_BUNDLE_CREATOR_INVALID", "SPDX creator is invalid")
    timestamp = _created_at(created_at)
    parent = _stable_output_parent(output_root)
    if output_root.exists():
        raise PluginBundleError("PLUGIN_BUNDLE_OUTPUT_EXISTS", "Bundle output already exists")
    plugin_root = _stable_directory(plugin_root, "Plugin source")
    if (plugin_root / "server").exists():
        raise PluginBundleError(
            "PLUGIN_BUNDLE_PATH_COLLISION",
            "Passive plugin source must not contain a preassembled server directory",
        )
    _plugin_manifest(plugin_root, expected_version=version)
    launcher = _stable_file(launcher, "Plugin launcher")
    if launcher.stat().st_size <= 0 or launcher.stat().st_size > 64 * 1024 * 1024:
        raise PluginBundleError(
            "PLUGIN_BUNDLE_LAUNCHER_INVALID",
            "Plugin launcher size is invalid",
        )
    trust_path = _stable_file(runtime_trust_policy, "Runtime publisher trust policy")
    try:
        trust_policy = RuntimePackageTrustPolicy.load(trust_path)
        runtime = ManagedRuntimePackage(
            runtime_root,
            trust_policy=trust_policy,
            require_signature=True,
        )
    except (RuntimePackageError, RuntimeTrustError) as error:
        raise PluginBundleError(
            "PLUGIN_BUNDLE_RUNTIME_INVALID",
            "Signed runtime or publisher trust policy is invalid",
        ) from error

    prepared = _bundle_inputs(
        plugin_root=plugin_root,
        launcher=launcher,
        runtime_package=runtime,
        trust_policy=trust_path,
    )
    resource_ids: set[str] = set()
    path_keys: set[str] = set()
    for item in prepared:
        if _RESOURCE_ID_RE.fullmatch(item.resource_id) is None or item.resource_id in resource_ids:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_RESOURCE_INVALID",
                "Bundle resource ID is invalid or duplicated",
            )
        path_key = item.relative_path.as_posix().casefold()
        if path_key in path_keys or path_key in {
            RELEASE_MANIFEST_NAME.casefold(),
            RELEASE_SBOM_NAME.casefold(),
        }:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_PATH_COLLISION",
                "Bundle resource paths collide",
            )
        resource_ids.add(item.resource_id)
        path_keys.add(path_key)
    if not prepared or len(prepared) + 2 > MAX_BUNDLE_FILES:
        raise PluginBundleError("PLUGIN_BUNDLE_TOO_LARGE", "Bundle file count exceeds its limit")
    prepared.sort(key=lambda item: item.resource_id.encode("utf-8"))

    with tempfile.TemporaryDirectory(prefix=f".{output_root.name}.build-", dir=parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        manifest_resources: list[dict[str, object]] = []
        total_bytes = 0
        for item in prepared:
            size, digest = _copy_verified(
                item.source,
                staging.joinpath(*item.relative_path.parts),
            )
            total_bytes += size
            if total_bytes > MAX_BUNDLE_BYTES:
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_TOO_LARGE",
                    "Bundle exceeds its byte limit",
                )
            manifest_resources.append(
                {
                    "resourceId": item.resource_id,
                    "relativePath": item.relative_path.as_posix(),
                    "size": size,
                    "sha256": digest,
                }
            )

        by_path = sorted(
            manifest_resources,
            key=lambda item: str(item["relativePath"]).encode("utf-8"),
        )
        namespace_material = canonical_bytes(
            {
                "packageId": "anki-study-agent-plugin",
                "version": version,
                "releaseState": _PASSIVE_RELEASE_STATE,
                "resources": manifest_resources,
            }
        )
        namespace = uuid.uuid5(
            uuid.NAMESPACE_URL,
            hashlib.sha256(namespace_material).hexdigest(),
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
            "name": f"anki-study-agent-plugin-{version}-passive",
            "spdxVersion": "SPDX-2.3",
        }
        sbom_source = canonical_bytes(sbom)
        if len(sbom_source) > MAX_RELEASE_SBOM_BYTES:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_TOO_LARGE",
                "Bundle SBOM exceeds its limit",
            )
        sbom_path = staging / RELEASE_SBOM_NAME
        sbom_path.write_bytes(sbom_source)
        total_bytes += len(sbom_source)
        manifest_resources.append(
            {
                "resourceId": "metadata:sbom-spdx",
                "relativePath": RELEASE_SBOM_NAME,
                "size": len(sbom_source),
                "sha256": hashlib.sha256(sbom_source).hexdigest(),
            }
        )
        manifest_resources.sort(key=lambda item: str(item["resourceId"]).encode("utf-8"))
        by_id = {str(item["resourceId"]): item for item in manifest_resources}
        manifest = {
            "schemaVersion": 1,
            "packageId": "anki-study-agent-plugin",
            "version": version,
            "createdAt": timestamp,
            "releaseState": _PASSIVE_RELEASE_STATE,
            "components": {
                "pluginManifest": {
                    "relativePath": PLUGIN_MANIFEST_PATH,
                    "sha256": by_id[f"plugin:{PLUGIN_MANIFEST_PATH}"]["sha256"],
                },
                "launcher": {
                    "relativePath": LAUNCHER_PATH,
                    "sha256": by_id["launcher:windows-x86_64"]["sha256"],
                    "runtimeManifestSha256": runtime.digest,
                    "runtimeTrustPolicySha256": file_sha256(trust_path),
                },
                "runtime": {
                    "relativePath": RUNTIME_PATH,
                    "manifestSha256": runtime.digest,
                    "publisherTrustPolicySha256": file_sha256(trust_path),
                    "signatureVerified": True,
                },
            },
            "sbom": {
                "format": "SPDX-2.3",
                "resourceId": "metadata:sbom-spdx",
            },
            "resources": manifest_resources,
        }
        manifest_source = canonical_bytes(manifest)
        if len(manifest_source) > MAX_RELEASE_MANIFEST_BYTES:
            raise PluginBundleError(
                "PLUGIN_BUNDLE_TOO_LARGE",
                "Bundle manifest exceeds its limit",
            )
        manifest_path = staging / RELEASE_MANIFEST_NAME
        manifest_path.write_bytes(manifest_source)
        total_bytes += len(manifest_source)
        if total_bytes > MAX_BUNDLE_BYTES:
            raise PluginBundleError("PLUGIN_BUNDLE_TOO_LARGE", "Bundle exceeds its byte limit")
        _harden_bundle_dacl(staging, runtime.package_id)
        PluginReleaseBundle(staging)
        try:
            os.rename(staging, output_root)
        except OSError as error:
            if output_root.exists():
                raise PluginBundleError(
                    "PLUGIN_BUNDLE_OUTPUT_EXISTS",
                    "Bundle output already exists",
                ) from error
            raise PluginBundleError(
                "PLUGIN_BUNDLE_OUTPUT_INVALID",
                "Bundle could not be published atomically",
            ) from error

    verified = PluginReleaseBundle(output_root)
    return PluginBundleBuildResult(
        root=output_root,
        manifest_path=output_root / RELEASE_MANIFEST_NAME,
        sbom_path=output_root / RELEASE_SBOM_NAME,
        manifest_sha256=verified.digest,
        resource_count=len(verified.resources),
        total_bytes=verified.total_bytes,
    )


def result_json(result: PluginBundleBuildResult) -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "output": str(result.root),
            "manifestSha256": result.manifest_sha256,
            "resourceCount": result.resource_count,
            "totalBytes": result.total_bytes,
            "installable": False,
            "mcpDeclared": False,
            "outerSignatureVerified": False,
            "publisherKeyManaged": False,
            "bundleDaclVerified": True,
            "runtimeDaclVerified": True,
            "privateKeyRead": False,
            "networkUsed": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
