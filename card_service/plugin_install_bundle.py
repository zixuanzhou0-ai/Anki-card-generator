from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .plugin_bundle import (
    LAUNCHER_PATH,
    MAX_BUNDLE_BYTES,
    MAX_BUNDLE_FILES,
    MAX_PLUGIN_MANIFEST_BYTES,
    MAX_RELEASE_MANIFEST_BYTES,
    MAX_RELEASE_SBOM_BYTES,
    PLUGIN_MANIFEST_PATH,
    RELEASE_SBOM_NAME,
    RUNTIME_PATH,
    TRUST_POLICY_PATH,
    PluginBundleError,
    _copy_verified,
    _created_at,
    _harden_bundle_dacl,
    _read_bounded,
    _relative_path,
    _spdx_id,
    _stable_directory,
    _stable_file,
    _stable_output_parent,
    _verify_bundle_dacl,
    _walk_files,
)
from .plugin_release_trust import PluginReleaseTrustError, PluginReleaseTrustPolicy
from .runtime_manifest import canonical_bytes, file_sha256
from .runtime_package import ManagedRuntimePackage, RuntimePackageError
from .runtime_trust import (
    RuntimePackageTrustPolicy,
    RuntimeTrustError,
    compare_semver,
    encode_base64url,
)
from .windows_authenticode import (
    AuthenticodeError,
    AuthenticodePolicy,
    VerifiedAuthenticode,
    verify_authenticode,
)


INSTALL_MANIFEST_NAME = "install-package-v1.json"
INSTALL_SIGNATURE_NAME = "install-package-v1.sig.json"
INSTALL_SIGNING_REQUEST_NAME = "install-signing-request-v1.json"
INSTALL_POLICY_PATH = "server/plugin-publisher-trust-v1.json"
MCP_CONFIG_PATH = ".mcp.json"
INSTALL_SIGNATURE_DOMAIN = "study.plugin-install-manifest.v1"
INSTALL_SIGNATURE_ALGORITHM = "Ed25519"
MAX_INSTALL_SIGNATURE_BYTES = 32 * 1024
MAX_INSTALL_SIGNING_REQUEST_BYTES = 64 * 1024
MAX_LAUNCHER_BYTES = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/+-]{0,511}$")
_STABLE_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_INSTALL_RELEASE_STATE = {
    "channel": "advanced-preview",
    "installable": True,
    "mcpDeclared": True,
    "outerSignatureVerified": True,
    "publisherKeyManaged": True,
}
_MCP_CONFIG = {
    "mcpServers": {
        "anki-study-agent": {
            "command": "./server/launcher/anki-study-agent.exe",
            "args": ["--stdio"],
            "cwd": ".",
            "tool_timeout_sec": 900,
        }
    }
}


class PluginInstallError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VerifiedPluginInstallSignature:
    authority: str
    package_id: str
    plugin_version: str
    key_id: str
    key_epoch: int
    signed_at: str
    expires_at: str
    manifest_sha256: str
    trust_sequence: int
    trust_policy_digest: str


@dataclass(frozen=True)
class PluginInstallBuildResult:
    root: Path
    manifest_path: Path
    sbom_path: Path
    manifest_sha256: str
    resource_count: int
    total_bytes: int
    authenticode: VerifiedAuthenticode


@dataclass(frozen=True)
class PluginInstallFinalizeResult:
    root: Path
    manifest_sha256: str
    resource_count: int
    total_bytes: int
    signature: VerifiedPluginInstallSignature
    authenticode: VerifiedAuthenticode
    native_verification: bool


AuthenticodeVerifier = Callable[[Path, AuthenticodePolicy], VerifiedAuthenticode]
NativeInstallVerifier = Callable[[Path], None]


def _raise(code: str, message: str, error: Exception | None = None) -> None:
    failure = PluginInstallError(code, message)
    if error is None:
        raise failure
    raise failure from error


def _stable_version(value: object) -> str:
    if not isinstance(value, str) or _STABLE_VERSION_RE.fullmatch(value) is None:
        _raise("PLUGIN_INSTALL_VERSION_INVALID", "Install plugin version must use stable semantic version syntax")
    return value


def _utc(value: object, *, code: str) -> datetime:
    if not isinstance(value, str) or _UTC_RE.fullmatch(value) is None:
        _raise(code, "Install signature timestamp is invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        _raise(code, "Install signature timestamp is invalid", error)


def _decode_base64url(value: object, *, length: int) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        _raise("PLUGIN_INSTALL_SIGNATURE_INVALID", "Install signature encoding is invalid")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    except (TypeError, ValueError) as error:
        _raise("PLUGIN_INSTALL_SIGNATURE_INVALID", "Install signature encoding is invalid", error)
    if len(decoded) != length or encode_base64url(decoded) != value:
        _raise("PLUGIN_INSTALL_SIGNATURE_INVALID", "Install signature encoding is invalid")
    return decoded


def _unsigned_envelope(
    *,
    authority: str,
    package_id: str,
    plugin_version: str,
    key_id: str,
    key_epoch: int,
    signed_at: str,
    expires_at: str,
    manifest_sha256: str,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "algorithm": INSTALL_SIGNATURE_ALGORITHM,
        "domain": INSTALL_SIGNATURE_DOMAIN,
        "authority": authority,
        "packageId": package_id,
        "pluginVersion": plugin_version,
        "keyId": key_id,
        "keyEpoch": key_epoch,
        "signedAt": signed_at,
        "expiresAt": expires_at,
        "manifestSha256": manifest_sha256,
    }


def plugin_install_signature_message(unsigned_envelope: dict[str, object]) -> bytes:
    digest = hashlib.sha256(canonical_bytes(unsigned_envelope)).digest()
    return INSTALL_SIGNATURE_DOMAIN.encode("ascii") + b"\x00" + digest


def _validate_signature_window(
    unsigned: dict[str, object],
    *,
    policy: PluginReleaseTrustPolicy,
    now: datetime | None,
    require_current: bool,
) -> None:
    signed_at = _utc(unsigned.get("signedAt"), code="PLUGIN_INSTALL_SIGNATURE_INVALID")
    expires_at = _utc(unsigned.get("expiresAt"), code="PLUGIN_INSTALL_SIGNATURE_INVALID")
    lifetime = int((expires_at - signed_at).total_seconds())
    if lifetime <= 0 or lifetime > policy.maximum_signature_lifetime_seconds:
        _raise("PLUGIN_INSTALL_SIGNATURE_WINDOW_INVALID", "Install signature lifetime is invalid")
    if require_current:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            _raise("PLUGIN_INSTALL_SIGNATURE_INVALID", "Install verification time must include a timezone")
        current = current.astimezone(timezone.utc)
        if current < signed_at or current >= expires_at:
            _raise("PLUGIN_INSTALL_SIGNATURE_EXPIRED", "Install signature is not currently valid")


def verify_plugin_install_signature(
    signature_path: Path,
    *,
    manifest_sha256: str,
    package_id: str,
    plugin_version: str,
    trust_policy: PluginReleaseTrustPolicy,
    now: datetime | None = None,
) -> VerifiedPluginInstallSignature:
    try:
        source = _read_bounded(signature_path, MAX_INSTALL_SIGNATURE_BYTES, "Plugin install signature")
    except PluginBundleError as error:
        _raise("PLUGIN_INSTALL_SIGNATURE_INVALID", "Install signature is unavailable", error)
    try:
        value = json.loads(source)
    except ValueError as error:
        _raise("PLUGIN_INSTALL_SIGNATURE_INVALID", "Install signature is invalid JSON", error)
    expected = set(
        _unsigned_envelope(
            authority="authority",
            package_id="package",
            plugin_version="0.0.0",
            key_id="key",
            key_epoch=1,
            signed_at="2000-01-01T00:00:00Z",
            expires_at="2000-01-01T00:01:00Z",
            manifest_sha256="0" * 64,
        )
    ) | {"signature"}
    if not isinstance(value, dict) or set(value) != expected or canonical_bytes(value) != source:
        _raise("PLUGIN_INSTALL_SIGNATURE_INVALID", "Install signature shape is invalid")
    if (
        value.get("schemaVersion") != 1
        or value.get("algorithm") != INSTALL_SIGNATURE_ALGORITHM
        or value.get("domain") != INSTALL_SIGNATURE_DOMAIN
        or value.get("authority") != trust_policy.authority
        or value.get("packageId") != package_id
        or value.get("pluginVersion") != plugin_version
        or value.get("manifestSha256") != manifest_sha256
        or not isinstance(value.get("keyId"), str)
        or isinstance(value.get("keyEpoch"), bool)
        or not isinstance(value.get("keyEpoch"), int)
        or not isinstance(manifest_sha256, str)
        or _SHA256_RE.fullmatch(manifest_sha256) is None
    ):
        _raise("PLUGIN_INSTALL_SIGNATURE_INVALID", "Install signature binding is invalid")
    _stable_version(plugin_version)
    if compare_semver(plugin_version, trust_policy.minimum_plugin_version) < 0:
        _raise("PLUGIN_INSTALL_VERSION_REVOKED", "Install plugin version is below the trust floor")
    if plugin_version in trust_policy.revoked_plugin_versions or manifest_sha256 in trust_policy.revoked_manifest_sha256:
        _raise("PLUGIN_INSTALL_VERSION_REVOKED", "Install plugin version or manifest is revoked")
    _validate_signature_window(value, policy=trust_policy, now=now, require_current=True)
    try:
        key = trust_policy.active_key(str(value["keyId"]), int(value["keyEpoch"]))
    except PluginReleaseTrustError as error:
        _raise("PLUGIN_INSTALL_SIGNING_KEY_UNTRUSTED", "Install signing key is not active", error)
    signature = _decode_base64url(value.get("signature"), length=64)
    unsigned = {name: child for name, child in value.items() if name != "signature"}
    try:
        Ed25519PublicKey.from_public_bytes(key.public_key).verify(
            signature,
            plugin_install_signature_message(unsigned),
        )
    except (InvalidSignature, ValueError) as error:
        _raise("PLUGIN_INSTALL_SIGNATURE_INVALID", "Install signature verification failed", error)
    return VerifiedPluginInstallSignature(
        authority=trust_policy.authority,
        package_id=package_id,
        plugin_version=plugin_version,
        key_id=key.key_id,
        key_epoch=key.key_epoch,
        signed_at=str(value["signedAt"]),
        expires_at=str(value["expiresAt"]),
        manifest_sha256=manifest_sha256,
        trust_sequence=trust_policy.sequence,
        trust_policy_digest=trust_policy.digest,
    )


def _install_relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value.isascii():
        _raise("PLUGIN_INSTALL_RESOURCE_INVALID", "Install resource paths must use portable ASCII")
    try:
        return _relative_path(value)
    except PluginBundleError as error:
        _raise("PLUGIN_INSTALL_RESOURCE_INVALID", "Install resource path is invalid", error)


def _canonical_json(path: Path, maximum: int, label: str) -> tuple[bytes, dict[str, object]]:
    try:
        source = _read_bounded(path, maximum, label)
    except PluginBundleError as error:
        _raise("PLUGIN_INSTALL_METADATA_INVALID", f"{label} is unavailable", error)
    try:
        value = json.loads(source)
    except ValueError as error:
        _raise("PLUGIN_INSTALL_METADATA_INVALID", f"{label} is invalid JSON", error)
    if not isinstance(value, dict) or canonical_bytes(value) != source:
        _raise("PLUGIN_INSTALL_METADATA_INVALID", f"{label} must be a canonical JSON object")
    return source, value


def _load_install_manifest(root: Path) -> tuple[bytes, dict[str, object]]:
    source, value = _canonical_json(
        root / INSTALL_MANIFEST_NAME,
        MAX_RELEASE_MANIFEST_BYTES,
        "Plugin install manifest",
    )
    if set(value) != {
        "schemaVersion",
        "packageId",
        "version",
        "createdAt",
        "releaseState",
        "delegatedComponents",
        "sbom",
        "resources",
    }:
        _raise("PLUGIN_INSTALL_MANIFEST_INVALID", "Install manifest shape is invalid")
    version = _stable_version(value.get("version"))
    if value.get("schemaVersion") != 1 or value.get("packageId") != "anki-study-agent-plugin":
        _raise("PLUGIN_INSTALL_MANIFEST_INVALID", "Install manifest identity is invalid")
    try:
        _created_at(value.get("createdAt"))
    except PluginBundleError as error:
        _raise("PLUGIN_INSTALL_MANIFEST_INVALID", "Install manifest creation time is invalid", error)
    if value.get("releaseState") != _INSTALL_RELEASE_STATE:
        _raise("PLUGIN_INSTALL_MANIFEST_INVALID", "Install manifest release state is not authorized")
    if value.get("sbom") != {"format": "SPDX-2.3", "resourceId": "metadata:sbom-spdx"}:
        _raise("PLUGIN_INSTALL_MANIFEST_INVALID", "Install manifest SBOM declaration is invalid")
    value["version"] = version
    return source, value


def _verify_plugin_metadata(root: Path, version: str) -> None:
    _, plugin = _canonical_json(
        root.joinpath(*PurePosixPath(PLUGIN_MANIFEST_PATH).parts),
        MAX_PLUGIN_MANIFEST_BYTES,
        "Plugin manifest",
    )
    if (
        plugin.get("name") != "anki-study-agent"
        or plugin.get("version") != version
        or plugin.get("mcpServers") != "./.mcp.json"
        or plugin.get("apps") is not None
        or plugin.get("skills") != "./skills/"
    ):
        _raise("PLUGIN_INSTALL_PLUGIN_INVALID", "Install plugin manifest is not wired to the signed MCP config")
    _, mcp = _canonical_json(root / MCP_CONFIG_PATH, MAX_PLUGIN_MANIFEST_BYTES, "Plugin MCP config")
    if mcp != _MCP_CONFIG:
        _raise("PLUGIN_INSTALL_MCP_INVALID", "Install MCP config is not the fixed native launcher mapping")


def _verify_sbom(sbom_path: Path, entries: dict[str, dict[str, object]]) -> None:
    _, sbom = _canonical_json(sbom_path, MAX_RELEASE_SBOM_BYTES, "Plugin install SBOM")
    files = sbom.get("files")
    if (
        sbom.get("spdxVersion") != "SPDX-2.3"
        or sbom.get("dataLicense") != "CC0-1.0"
        or sbom.get("SPDXID") != "SPDXRef-DOCUMENT"
        or not isinstance(files, list)
    ):
        _raise("PLUGIN_INSTALL_SBOM_INVALID", "Install SBOM metadata is invalid")
    expected = {
        f"./{entry['relativePath']}": entry["sha256"]
        for resource_id, entry in entries.items()
        if resource_id != "metadata:sbom-spdx"
    }
    observed: dict[str, str] = {}
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
            _raise("PLUGIN_INSTALL_SBOM_INVALID", "Install SBOM file entry is invalid")
        name = str(item["fileName"])
        if name in observed:
            _raise("PLUGIN_INSTALL_SBOM_INVALID", "Install SBOM contains duplicate files")
        observed[name] = str(checksums[0]["checksumValue"])
    if list(observed) != sorted(observed, key=lambda item: item.encode("utf-8")) or observed != expected:
        _raise("PLUGIN_INSTALL_SBOM_INVALID", "Install SBOM does not cover the exact outer payload")


class PluginInstallBundle:
    """Verify an MCP-wired install candidate or a signed install package."""

    def __init__(
        self,
        root: str | Path,
        *,
        publisher_policy: PluginReleaseTrustPolicy,
        require_signature: bool,
        now: datetime | None = None,
    ) -> None:
        try:
            self.root = _stable_directory(Path(root), "Plugin install bundle")
        except PluginBundleError as error:
            _raise("PLUGIN_INSTALL_PATH_INVALID", "Install bundle root is unavailable", error)
        source, value = _load_install_manifest(self.root)
        version = str(value["version"])
        resources = value.get("resources")
        if not isinstance(resources, list) or not resources or len(resources) > MAX_BUNDLE_FILES:
            _raise("PLUGIN_INSTALL_MANIFEST_INVALID", "Install resources are invalid")
        identifiers: list[str] = []
        entries: dict[str, dict[str, object]] = {}
        path_keys: set[str] = set()
        total_bytes = len(source)
        for raw in resources:
            if not isinstance(raw, dict) or set(raw) != {"resourceId", "relativePath", "size", "sha256"}:
                _raise("PLUGIN_INSTALL_RESOURCE_INVALID", "Install resource entry is invalid")
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
                _raise("PLUGIN_INSTALL_RESOURCE_INVALID", "Install resource identity is invalid")
            relative = _install_relative(raw.get("relativePath"))
            relative_name = relative.as_posix()
            lower = relative_name.casefold()
            if lower in {INSTALL_MANIFEST_NAME.casefold(), INSTALL_SIGNATURE_NAME.casefold()} or lower == RUNTIME_PATH.casefold() or lower.startswith(f"{RUNTIME_PATH.casefold()}/"):
                _raise("PLUGIN_INSTALL_RESOURCE_INVALID", "Install resource overlaps signed or delegated metadata")
            if lower in path_keys:
                _raise("PLUGIN_INSTALL_RESOURCE_INVALID", "Install resource paths collide")
            path_keys.add(lower)
            try:
                path = _stable_file(self.root.joinpath(*relative.parts), "Plugin install resource")
            except PluginBundleError as error:
                _raise("PLUGIN_INSTALL_RESOURCE_INVALID", "Install resource is unavailable", error)
            if path.stat().st_size != size or file_sha256(path) != digest:
                _raise("PLUGIN_INSTALL_RESOURCE_CHANGED", "Install resource hash or size changed")
            total_bytes += size
            if total_bytes > MAX_BUNDLE_BYTES:
                _raise("PLUGIN_INSTALL_TOO_LARGE", "Install bundle exceeds its byte limit")
            identifiers.append(resource_id)
            entries[resource_id] = {**raw, "relativePath": relative_name, "path": path}
        if identifiers != sorted(identifiers, key=lambda item: item.encode("utf-8")):
            _raise("PLUGIN_INSTALL_MANIFEST_INVALID", "Install resources must be sorted by resource ID")
        required_paths = {
            MCP_CONFIG_PATH,
            PLUGIN_MANIFEST_PATH,
            LAUNCHER_PATH,
            INSTALL_POLICY_PATH,
            TRUST_POLICY_PATH,
            RELEASE_SBOM_NAME,
        }
        if not {item.casefold() for item in required_paths}.issubset(path_keys):
            _raise("PLUGIN_INSTALL_RESOURCE_MISSING", "Install bundle is missing a required outer resource")
        actual_paths = {
            path.relative_to(self.root).as_posix().casefold()
            for path in _walk_files(self.root)
            if not (
                path.relative_to(self.root).as_posix().casefold() == RUNTIME_PATH.casefold()
                or path.relative_to(self.root).as_posix().casefold().startswith(f"{RUNTIME_PATH.casefold()}/")
            )
        }
        expected_paths = set(path_keys) | {INSTALL_MANIFEST_NAME.casefold()}
        if require_signature:
            expected_paths.add(INSTALL_SIGNATURE_NAME.casefold())
        if actual_paths != expected_paths:
            _raise("PLUGIN_INSTALL_UNLISTED_RESOURCE", "Install bundle contains missing or unlisted outer files")
        sbom_entry = entries.get("metadata:sbom-spdx")
        if sbom_entry is None or sbom_entry["relativePath"] != RELEASE_SBOM_NAME:
            _raise("PLUGIN_INSTALL_SBOM_INVALID", "Install bundle is missing the declared SBOM")
        _verify_sbom(Path(sbom_entry["path"]), entries)
        _verify_plugin_metadata(self.root, version)

        components = value.get("delegatedComponents")
        if not isinstance(components, list) or len(components) != 1 or not isinstance(components[0], dict):
            _raise("PLUGIN_INSTALL_RUNTIME_INVALID", "Install delegated runtime declaration is invalid")
        embedded_policy_path = self.root.joinpath(*PurePosixPath(INSTALL_POLICY_PATH).parts)
        try:
            embedded_policy = PluginReleaseTrustPolicy.load(embedded_policy_path)
        except PluginReleaseTrustError as error:
            _raise("PLUGIN_INSTALL_POLICY_INVALID", "Embedded install publisher policy is invalid", error)
        if embedded_policy.digest != publisher_policy.digest:
            _raise("PLUGIN_INSTALL_POLICY_MISMATCH", "Embedded install publisher policy differs from the external policy")
        runtime_policy_path = self.root.joinpath(*PurePosixPath(TRUST_POLICY_PATH).parts)
        try:
            runtime_policy = RuntimePackageTrustPolicy.load(runtime_policy_path)
            runtime = ManagedRuntimePackage(
                self.root.joinpath(*PurePosixPath(RUNTIME_PATH).parts),
                trust_policy=runtime_policy,
                require_signature=True,
            )
        except (RuntimePackageError, RuntimeTrustError) as error:
            _raise("PLUGIN_INSTALL_RUNTIME_INVALID", "Install delegated runtime is invalid", error)
        expected_component = {
            "componentId": "managed-runtime",
            "root": RUNTIME_PATH,
            "manifestPath": "runtime-package-v1.json",
            "manifestSha256": runtime.digest,
            "signaturePath": "runtime-package-v1.sig.json",
            "trustPolicyPath": TRUST_POLICY_PATH,
            "trustPolicySha256": file_sha256(runtime_policy_path),
        }
        if components != [expected_component]:
            _raise("PLUGIN_INSTALL_RUNTIME_INVALID", "Install delegated runtime does not match its signed payload")
        if os.name == "nt":
            try:
                _verify_bundle_dacl(self.root, runtime.package_id)
            except PluginBundleError as error:
                _raise("PLUGIN_INSTALL_DACL_INVALID", "Install bundle DACL is not exact", error)
        signature = None
        digest = hashlib.sha256(source).hexdigest()
        if require_signature:
            signature = verify_plugin_install_signature(
                self.root / INSTALL_SIGNATURE_NAME,
                manifest_sha256=digest,
                package_id="anki-study-agent-plugin",
                plugin_version=version,
                trust_policy=publisher_policy,
                now=now,
            )
        self.value = value
        self.version = version
        self.resources = entries
        self.runtime = runtime
        self.publisher_policy = publisher_policy
        self.signature = signature
        self.digest = digest
        self.total_bytes = total_bytes + ((self.root / INSTALL_SIGNATURE_NAME).stat().st_size if require_signature else 0)
        self.bundle_dacl_verified = os.name == "nt"

    def public_summary(self) -> dict[str, object]:
        signed = self.signature is not None
        return {
            "schemaVersion": 1,
            "packageId": "anki-study-agent-plugin",
            "version": self.version,
            "manifestSha256": self.digest,
            "resourceCount": len(self.resources),
            "totalBytes": self.total_bytes,
            "mcpDeclared": True,
            "runtimeSignatureVerified": True,
            "sbomVerified": True,
            "bundleDaclVerified": self.bundle_dacl_verified,
            "outerSignatureVerified": signed,
            "publisherKeyManaged": signed,
            "installable": False,
            "complete": False,
        }


def _default_authenticode_verifier(path: Path, policy: AuthenticodePolicy) -> VerifiedAuthenticode:
    return verify_authenticode(path, policy=policy)


def _verify_authenticode(
    launcher: Path,
    policy: AuthenticodePolicy,
    verifier: AuthenticodeVerifier,
) -> VerifiedAuthenticode:
    try:
        evidence = verifier(launcher, policy)
    except AuthenticodeError as error:
        _raise("PLUGIN_INSTALL_AUTHENTICODE_INVALID", "Launcher Authenticode verification failed", error)
    if not isinstance(evidence, VerifiedAuthenticode):
        _raise("PLUGIN_INSTALL_AUTHENTICODE_INVALID", "Launcher verifier returned invalid evidence")
    if evidence.file_sha256 != file_sha256(launcher) or evidence.policy_digest != policy.digest:
        _raise("PLUGIN_INSTALL_AUTHENTICODE_INVALID", "Launcher Authenticode evidence is not bound to its inputs")
    return evidence


def _source_plugin_manifest(plugin_root: Path, version: str) -> dict[str, object]:
    path = plugin_root.joinpath(*PurePosixPath(PLUGIN_MANIFEST_PATH).parts)
    try:
        source = _read_bounded(path, MAX_PLUGIN_MANIFEST_BYTES, "Plugin source manifest")
    except PluginBundleError as error:
        _raise("PLUGIN_INSTALL_PLUGIN_INVALID", "Plugin source manifest is unavailable", error)
    try:
        value = json.loads(source)
    except ValueError as error:
        _raise("PLUGIN_INSTALL_PLUGIN_INVALID", "Plugin source manifest is invalid JSON", error)
    if (
        not isinstance(value, dict)
        or value.get("name") != "anki-study-agent"
        or value.get("version") != version
        or value.get("skills") != "./skills/"
        or "mcpServers" in value
        or "apps" in value
    ):
        _raise("PLUGIN_INSTALL_PLUGIN_INVALID", "Plugin source must be the passive plugin for this version")
    if not (plugin_root / "skills").is_dir():
        _raise("PLUGIN_INSTALL_PLUGIN_INVALID", "Plugin source skills directory is missing")
    for forbidden in ("server", MCP_CONFIG_PATH, ".app.json"):
        if (plugin_root / forbidden).exists():
            _raise("PLUGIN_INSTALL_PLUGIN_INVALID", "Plugin source collides with generated install wiring")
    installed = dict(value)
    installed["mcpServers"] = "./.mcp.json"
    return installed


def _resource_id(relative: str) -> str:
    fixed = {
        MCP_CONFIG_PATH: "plugin:mcp-config",
        PLUGIN_MANIFEST_PATH: f"plugin:{PLUGIN_MANIFEST_PATH}",
        LAUNCHER_PATH: "launcher:windows-x86_64",
        INSTALL_POLICY_PATH: "metadata:plugin-publisher-trust",
        TRUST_POLICY_PATH: "metadata:runtime-publisher-trust",
    }
    return fixed.get(relative, f"plugin:{relative}")


def _copy_tree(source_root: Path, target_root: Path, *, skip: set[str] | None = None) -> None:
    skipped = {value.casefold() for value in (skip or set())}
    for source in _walk_files(source_root):
        relative = source.relative_to(source_root).as_posix()
        if relative.casefold() in skipped:
            continue
        _install_relative(relative)
        _copy_verified(source, target_root.joinpath(*PurePosixPath(relative).parts))


def _outer_resource_entries(staging: Path) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    ids: set[str] = set()
    paths: set[str] = set()
    for path in _walk_files(staging):
        relative = path.relative_to(staging).as_posix()
        lower = relative.casefold()
        if lower == RUNTIME_PATH.casefold() or lower.startswith(f"{RUNTIME_PATH.casefold()}/"):
            continue
        if lower in {
            INSTALL_MANIFEST_NAME.casefold(),
            INSTALL_SIGNATURE_NAME.casefold(),
            RELEASE_SBOM_NAME.casefold(),
        }:
            continue
        _install_relative(relative)
        resource_id = _resource_id(relative)
        if _RESOURCE_ID_RE.fullmatch(resource_id) is None or resource_id in ids or lower in paths:
            _raise("PLUGIN_INSTALL_RESOURCE_INVALID", "Generated install resource identity collides")
        ids.add(resource_id)
        paths.add(lower)
        values.append(
            {
                "resourceId": resource_id,
                "relativePath": relative,
                "size": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    values.sort(key=lambda item: str(item["resourceId"]).encode("utf-8"))
    return values


def _write_install_sbom(
    staging: Path,
    *,
    version: str,
    timestamp: str,
    creator: str,
    resources: list[dict[str, object]],
) -> dict[str, object]:
    namespace_material = canonical_bytes(
        {
            "packageId": "anki-study-agent-plugin",
            "version": version,
            "releaseState": _INSTALL_RELEASE_STATE,
            "resources": resources,
        }
    )
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha256(namespace_material).hexdigest())
    by_path = sorted(resources, key=lambda item: str(item["relativePath"]).encode("utf-8"))
    sbom = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {"created": timestamp, "creators": [creator]},
        "dataLicense": "CC0-1.0",
        "documentNamespace": f"urn:uuid:{namespace}",
        "files": [
            {
                "SPDXID": _spdx_id(str(resource["relativePath"])),
                "checksums": [{"algorithm": "SHA256", "checksumValue": resource["sha256"]}],
                "fileName": f"./{resource['relativePath']}",
            }
            for resource in by_path
        ],
        "name": f"anki-study-agent-plugin-{version}-install",
        "spdxVersion": "SPDX-2.3",
    }
    source = canonical_bytes(sbom)
    if len(source) > MAX_RELEASE_SBOM_BYTES:
        _raise("PLUGIN_INSTALL_TOO_LARGE", "Install SBOM exceeds its byte limit")
    path = staging / RELEASE_SBOM_NAME
    path.write_bytes(source)
    return {
        "resourceId": "metadata:sbom-spdx",
        "relativePath": RELEASE_SBOM_NAME,
        "size": len(source),
        "sha256": hashlib.sha256(source).hexdigest(),
    }


def _build_plugin_install_candidate(
    output_root: Path,
    *,
    version: str,
    created_at: str,
    plugin_root: Path,
    launcher: Path,
    runtime_root: Path,
    runtime_trust_policy: Path,
    plugin_publisher_trust_policy: Path,
    launcher_authenticode_policy: Path,
    creator: str = "Organization: Anki Study Agent",
    authenticode_verifier: AuthenticodeVerifier = _default_authenticode_verifier,
) -> PluginInstallBuildResult:
    """Build an unsigned signing candidate; it is never reported as installable."""

    if os.name != "nt":
        _raise("PLUGIN_INSTALL_PLATFORM_UNSUPPORTED", "The install candidate currently targets Windows only")
    version = _stable_version(version)
    try:
        timestamp = _created_at(created_at)
        parent = _stable_output_parent(output_root)
        plugin_root = _stable_directory(plugin_root, "Plugin source")
        launcher = _stable_file(launcher, "Plugin launcher")
        runtime_trust_path = _stable_file(runtime_trust_policy, "Runtime publisher trust policy")
        publisher_path = _stable_file(plugin_publisher_trust_policy, "Plugin publisher trust policy")
        authenticode_path = _stable_file(launcher_authenticode_policy, "Launcher Authenticode policy")
    except PluginBundleError as error:
        _raise("PLUGIN_INSTALL_INPUT_INVALID", "Install candidate input is unavailable or unsafe", error)
    if output_root.exists():
        _raise("PLUGIN_INSTALL_OUTPUT_EXISTS", "Install candidate output already exists")
    if launcher.stat().st_size <= 0 or launcher.stat().st_size > MAX_LAUNCHER_BYTES:
        _raise("PLUGIN_INSTALL_INPUT_INVALID", "Install launcher size is invalid")
    if (
        not creator.startswith(("Organization: ", "Person: ", "Tool: "))
        or len(creator) > 256
        or any(ord(character) < 0x20 for character in creator)
    ):
        _raise("PLUGIN_INSTALL_INPUT_INVALID", "Install SPDX creator is invalid")
    installed_manifest = _source_plugin_manifest(plugin_root, version)
    try:
        publisher_policy = PluginReleaseTrustPolicy.load(publisher_path)
        if compare_semver(version, publisher_policy.minimum_plugin_version) < 0:
            _raise("PLUGIN_INSTALL_VERSION_REVOKED", "Install version is below the publisher trust floor")
        runtime_policy = RuntimePackageTrustPolicy.load(runtime_trust_path)
        runtime = ManagedRuntimePackage(runtime_root, trust_policy=runtime_policy, require_signature=True)
        authenticode_policy = AuthenticodePolicy.load(authenticode_path)
    except (PluginReleaseTrustError, RuntimePackageError, RuntimeTrustError, AuthenticodeError) as error:
        _raise("PLUGIN_INSTALL_INPUT_INVALID", "Install trust policy, runtime, or Authenticode policy is invalid", error)
    authenticode = _verify_authenticode(launcher, authenticode_policy, authenticode_verifier)

    with tempfile.TemporaryDirectory(prefix=f".{output_root.name}.build-", dir=parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        _copy_tree(plugin_root, staging, skip={PLUGIN_MANIFEST_PATH})
        manifest_path = staging.joinpath(*PurePosixPath(PLUGIN_MANIFEST_PATH).parts)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(canonical_bytes(installed_manifest))
        (staging / MCP_CONFIG_PATH).write_bytes(canonical_bytes(_MCP_CONFIG))
        _copy_verified(launcher, staging.joinpath(*PurePosixPath(LAUNCHER_PATH).parts))
        _copy_verified(publisher_path, staging.joinpath(*PurePosixPath(INSTALL_POLICY_PATH).parts))
        _copy_verified(runtime_trust_path, staging.joinpath(*PurePosixPath(TRUST_POLICY_PATH).parts))
        _copy_tree(runtime.root, staging.joinpath(*PurePosixPath(RUNTIME_PATH).parts))

        resources = _outer_resource_entries(staging)
        resources.append(
            _write_install_sbom(
                staging,
                version=version,
                timestamp=timestamp,
                creator=creator,
                resources=resources,
            )
        )
        resources.sort(key=lambda item: str(item["resourceId"]).encode("utf-8"))
        manifest = {
            "schemaVersion": 1,
            "packageId": "anki-study-agent-plugin",
            "version": version,
            "createdAt": timestamp,
            "releaseState": _INSTALL_RELEASE_STATE,
            "delegatedComponents": [
                {
                    "componentId": "managed-runtime",
                    "root": RUNTIME_PATH,
                    "manifestPath": "runtime-package-v1.json",
                    "manifestSha256": runtime.digest,
                    "signaturePath": "runtime-package-v1.sig.json",
                    "trustPolicyPath": TRUST_POLICY_PATH,
                    "trustPolicySha256": file_sha256(runtime_trust_path),
                }
            ],
            "sbom": {"format": "SPDX-2.3", "resourceId": "metadata:sbom-spdx"},
            "resources": resources,
        }
        source = canonical_bytes(manifest)
        if len(source) > MAX_RELEASE_MANIFEST_BYTES:
            _raise("PLUGIN_INSTALL_TOO_LARGE", "Install manifest exceeds its byte limit")
        (staging / INSTALL_MANIFEST_NAME).write_bytes(source)
        if len(_walk_files(staging)) > MAX_BUNDLE_FILES:
            _raise("PLUGIN_INSTALL_TOO_LARGE", "Install bundle exceeds its file limit")
        _harden_bundle_dacl(staging, runtime.package_id)
        PluginInstallBundle(staging, publisher_policy=publisher_policy, require_signature=False)
        copied_launcher = staging.joinpath(*PurePosixPath(LAUNCHER_PATH).parts)
        _verify_authenticode(copied_launcher, authenticode_policy, authenticode_verifier)
        try:
            os.rename(staging, output_root)
        except OSError as error:
            if output_root.exists():
                _raise("PLUGIN_INSTALL_OUTPUT_EXISTS", "Install candidate output already exists", error)
            _raise("PLUGIN_INSTALL_OUTPUT_INVALID", "Install candidate could not be published atomically", error)

    verified = PluginInstallBundle(output_root, publisher_policy=publisher_policy, require_signature=False)
    final_authenticode = _verify_authenticode(
        output_root.joinpath(*PurePosixPath(LAUNCHER_PATH).parts),
        authenticode_policy,
        authenticode_verifier,
    )
    return PluginInstallBuildResult(
        root=output_root,
        manifest_path=output_root / INSTALL_MANIFEST_NAME,
        sbom_path=output_root / RELEASE_SBOM_NAME,
        manifest_sha256=verified.digest,
        resource_count=len(verified.resources),
        total_bytes=verified.total_bytes,
        authenticode=final_authenticode,
    )


def build_plugin_install_candidate(
    output_root: Path,
    *,
    version: str,
    created_at: str,
    plugin_root: Path,
    launcher: Path,
    runtime_root: Path,
    runtime_trust_policy: Path,
    plugin_publisher_trust_policy: Path,
    launcher_authenticode_policy: Path,
    creator: str = "Organization: Anki Study Agent",
) -> PluginInstallBuildResult:
    return _build_plugin_install_candidate(
        output_root,
        version=version,
        created_at=created_at,
        plugin_root=plugin_root,
        launcher=launcher,
        runtime_root=runtime_root,
        runtime_trust_policy=runtime_trust_policy,
        plugin_publisher_trust_policy=plugin_publisher_trust_policy,
        launcher_authenticode_policy=launcher_authenticode_policy,
        creator=creator,
        authenticode_verifier=_default_authenticode_verifier,
    )


def build_plugin_install_signing_request(
    candidate_root: Path,
    *,
    trust_policy: PluginReleaseTrustPolicy,
    key_id: str,
    key_epoch: int,
    signed_at: str,
    expires_at: str,
) -> dict[str, object]:
    candidate = PluginInstallBundle(
        candidate_root,
        publisher_policy=trust_policy,
        require_signature=False,
    )
    try:
        trust_policy.active_key(key_id, key_epoch)
    except PluginReleaseTrustError as error:
        _raise("PLUGIN_INSTALL_SIGNING_KEY_UNTRUSTED", "Install signing key is not active", error)
    if compare_semver(candidate.version, trust_policy.minimum_plugin_version) < 0:
        _raise("PLUGIN_INSTALL_VERSION_REVOKED", "Install version is below the publisher trust floor")
    if (
        candidate.version in trust_policy.revoked_plugin_versions
        or candidate.digest in trust_policy.revoked_manifest_sha256
    ):
        _raise("PLUGIN_INSTALL_VERSION_REVOKED", "Install version or manifest is revoked")
    unsigned = _unsigned_envelope(
        authority=trust_policy.authority,
        package_id="anki-study-agent-plugin",
        plugin_version=candidate.version,
        key_id=key_id,
        key_epoch=key_epoch,
        signed_at=signed_at,
        expires_at=expires_at,
        manifest_sha256=candidate.digest,
    )
    _validate_signature_window(unsigned, policy=trust_policy, now=None, require_current=False)
    message = plugin_install_signature_message(unsigned)
    return {
        "schemaVersion": 1,
        "algorithm": INSTALL_SIGNATURE_ALGORITHM,
        "domain": INSTALL_SIGNATURE_DOMAIN,
        "trustPolicyDigest": trust_policy.digest,
        "unsignedEnvelope": unsigned,
        "signingMessage": encode_base64url(message),
        "signingMessageSha256": hashlib.sha256(message).hexdigest(),
        "privateKeyRead": False,
        "networkUsed": False,
    }


def write_plugin_install_signing_request(output_path: Path, request: dict[str, object]) -> str:
    if not output_path.is_absolute():
        _raise("PLUGIN_INSTALL_SIGNING_REQUEST_PATH_INVALID", "Install signing request path must be absolute")
    name = output_path.name
    if (
        not name
        or name != name.rstrip(" .")
        or ":" in name
        or "\\" in name
        or "/" in name
        or any(ord(character) < 0x20 for character in name)
    ):
        _raise("PLUGIN_INSTALL_SIGNING_REQUEST_PATH_INVALID", "Install signing request filename is invalid")
    try:
        parent = _stable_directory(output_path.parent, "Install signing request parent")
    except PluginBundleError as error:
        _raise("PLUGIN_INSTALL_SIGNING_REQUEST_PATH_INVALID", "Install signing request parent is unsafe", error)
    output = parent / name
    if output.exists():
        _raise("PLUGIN_INSTALL_SIGNING_REQUEST_EXISTS", "Install signing request output already exists")
    source = canonical_bytes(request)
    if len(source) > MAX_INSTALL_SIGNING_REQUEST_BYTES:
        _raise("PLUGIN_INSTALL_SIGNING_REQUEST_INVALID", "Install signing request is too large")
    temporary = parent / f".{name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(source)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output, follow_symlinks=False)
    except FileExistsError as error:
        _raise("PLUGIN_INSTALL_SIGNING_REQUEST_EXISTS", "Install signing request output already exists", error)
    except OSError as error:
        _raise("PLUGIN_INSTALL_SIGNING_REQUEST_WRITE_FAILED", "Install signing request was not written atomically", error)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return hashlib.sha256(source).hexdigest()


def _default_native_install_verifier(root: Path) -> None:
    launcher = root.joinpath(*PurePosixPath(LAUNCHER_PATH).parts)
    environment = dict(os.environ)
    for name in (
        "ANKI_STUDY_PLUGIN_ROOT",
        "ANKI_STUDY_RUNTIME_MANIFEST_SHA256",
        "ANKI_STUDY_RUNTIME_TRUST_POLICY_SHA256",
        "ANKI_STUDY_PLUGIN_INSTALL_TRUST_POLICY_SHA256",
        "ANKI_STUDY_LAUNCHER_TRACE",
    ):
        environment.pop(name, None)
    try:
        process = subprocess.run(
            [str(launcher), "--verify-install-only"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _raise("PLUGIN_INSTALL_NATIVE_VERIFICATION_FAILED", "Native launcher verification could not run", error)
    if process.returncode != 0:
        diagnostic = "\n".join(process.stderr.splitlines()[-12:])[:2000]
        _raise(
            "PLUGIN_INSTALL_NATIVE_VERIFICATION_FAILED",
            f"Native launcher rejected the install package: {diagnostic}",
        )


def _copy_candidate(candidate: PluginInstallBundle, staging: Path) -> None:
    staging.mkdir()
    for source in _walk_files(candidate.root):
        relative = source.relative_to(candidate.root).as_posix()
        _copy_verified(source, staging.joinpath(*PurePosixPath(relative).parts))


def _finalize_plugin_install_package(
    output_root: Path,
    *,
    candidate_root: Path,
    signature_path: Path,
    plugin_publisher_trust_policy: Path,
    launcher_authenticode_policy: Path,
    now: datetime | None = None,
    authenticode_verifier: AuthenticodeVerifier = _default_authenticode_verifier,
    native_install_verifier: NativeInstallVerifier = _default_native_install_verifier,
) -> PluginInstallFinalizeResult:
    """Publish only after detached signature, Authenticode, DACL and native verification pass."""

    if os.name != "nt":
        _raise("PLUGIN_INSTALL_PLATFORM_UNSUPPORTED", "The install package currently targets Windows only")
    try:
        parent = _stable_output_parent(output_root)
        policy_path = _stable_file(plugin_publisher_trust_policy, "Plugin publisher trust policy")
        authenticode_path = _stable_file(launcher_authenticode_policy, "Launcher Authenticode policy")
        signature_path = _stable_file(signature_path, "Plugin install signature")
        publisher_policy = PluginReleaseTrustPolicy.load(policy_path)
        authenticode_policy = AuthenticodePolicy.load(authenticode_path)
    except (PluginBundleError, PluginReleaseTrustError, AuthenticodeError) as error:
        _raise("PLUGIN_INSTALL_INPUT_INVALID", "Install finalization input is invalid", error)
    candidate = PluginInstallBundle(
        candidate_root,
        publisher_policy=publisher_policy,
        require_signature=False,
    )
    if candidate.root == signature_path.parent or candidate.root in signature_path.parents:
        _raise("PLUGIN_INSTALL_SIGNATURE_INVALID", "Detached install signature must stay outside the candidate")
    if output_root.exists():
        _raise("PLUGIN_INSTALL_OUTPUT_EXISTS", "Final install package output already exists")
    verified_signature = verify_plugin_install_signature(
        signature_path,
        manifest_sha256=candidate.digest,
        package_id="anki-study-agent-plugin",
        plugin_version=candidate.version,
        trust_policy=publisher_policy,
        now=now,
    )
    candidate_launcher = candidate.root.joinpath(*PurePosixPath(LAUNCHER_PATH).parts)
    _verify_authenticode(candidate_launcher, authenticode_policy, authenticode_verifier)

    with tempfile.TemporaryDirectory(prefix=f".{output_root.name}.finalize-", dir=parent) as temporary:
        staging = Path(temporary) / "bundle"
        _copy_candidate(candidate, staging)
        _copy_verified(signature_path, staging / INSTALL_SIGNATURE_NAME)
        _harden_bundle_dacl(staging, candidate.runtime.package_id)
        signed = PluginInstallBundle(
            staging,
            publisher_policy=publisher_policy,
            require_signature=True,
            now=now,
        )
        staged_authenticode = _verify_authenticode(
            staging.joinpath(*PurePosixPath(LAUNCHER_PATH).parts),
            authenticode_policy,
            authenticode_verifier,
        )
        try:
            native_install_verifier(staging)
        except PluginInstallError:
            raise
        except Exception as error:
            _raise("PLUGIN_INSTALL_NATIVE_VERIFICATION_FAILED", "Native launcher verification failed", error)
        try:
            os.rename(staging, output_root)
        except OSError as error:
            if output_root.exists():
                _raise("PLUGIN_INSTALL_OUTPUT_EXISTS", "Final install package output already exists", error)
            _raise("PLUGIN_INSTALL_OUTPUT_INVALID", "Final install package could not be published atomically", error)

    published = PluginInstallBundle(
        output_root,
        publisher_policy=publisher_policy,
        require_signature=True,
        now=now,
    )
    published_authenticode = _verify_authenticode(
        output_root.joinpath(*PurePosixPath(LAUNCHER_PATH).parts),
        authenticode_policy,
        authenticode_verifier,
    )
    try:
        native_install_verifier(output_root)
    except PluginInstallError:
        raise
    except Exception as error:
        _raise("PLUGIN_INSTALL_NATIVE_VERIFICATION_FAILED", "Published native verification failed", error)
    if published.digest != signed.digest or published.signature != verified_signature:
        _raise("PLUGIN_INSTALL_PUBLISH_CHANGED", "Final install package changed while it was published")
    return PluginInstallFinalizeResult(
        root=output_root,
        manifest_sha256=published.digest,
        resource_count=len(published.resources),
        total_bytes=published.total_bytes,
        signature=verified_signature,
        authenticode=published_authenticode,
        native_verification=True,
    )


def finalize_plugin_install_package(
    output_root: Path,
    *,
    candidate_root: Path,
    signature_path: Path,
    plugin_publisher_trust_policy: Path,
    launcher_authenticode_policy: Path,
) -> PluginInstallFinalizeResult:
    return _finalize_plugin_install_package(
        output_root,
        candidate_root=candidate_root,
        signature_path=signature_path,
        plugin_publisher_trust_policy=plugin_publisher_trust_policy,
        launcher_authenticode_policy=launcher_authenticode_policy,
        now=None,
        authenticode_verifier=_default_authenticode_verifier,
        native_install_verifier=_default_native_install_verifier,
    )


def build_result_json(result: PluginInstallBuildResult) -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "output": str(result.root),
            "manifestSha256": result.manifest_sha256,
            "resourceCount": result.resource_count,
            "totalBytes": result.total_bytes,
            "mcpDeclared": True,
            "authenticodeVerified": True,
            "outerSignatureVerified": False,
            "publisherKeyManaged": False,
            "nativeVerificationPassed": False,
            "installable": False,
            "privateKeyRead": False,
            "networkUsed": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def finalize_result_json(result: PluginInstallFinalizeResult) -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "output": str(result.root),
            "manifestSha256": result.manifest_sha256,
            "resourceCount": result.resource_count,
            "totalBytes": result.total_bytes,
            "mcpDeclared": True,
            "authenticodeVerified": True,
            "outerSignatureVerified": True,
            "publisherKeyManaged": True,
            "nativeVerificationPassed": result.native_verification,
            "installable": True,
            "privateKeyRead": False,
            "networkUsed": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
