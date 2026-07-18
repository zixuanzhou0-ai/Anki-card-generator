from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .runtime_manifest import canonical_bytes
from .runtime_trust import RuntimeTrustError, compare_semver, encode_base64url


TRUST_POLICY_SCHEMA_VERSION = 1
SIGNATURE_SCHEMA_VERSION = 1
SIGNING_REQUEST_SCHEMA_VERSION = 1
SIGNATURE_ALGORITHM = "Ed25519"
SIGNATURE_DOMAIN = "study.plugin-release-manifest.v1"
SIGNATURE_FILE_NAME = "release-package-v1.sig.json"
SIGNING_REQUEST_FILE_NAME = "release-signing-request-v1.json"
MAX_TRUST_POLICY_BYTES = 256 * 1024
MAX_SIGNATURE_BYTES = 32 * 1024
MAX_SIGNING_REQUEST_BYTES = 64 * 1024
MAX_RELEASE_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_TRUST_FLOOR_BYTES = 256 * 1024
MAX_SIGNATURE_LIFETIME_SECONDS = 366 * 24 * 60 * 60
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class PluginReleaseTrustError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _stable_file(path: Path, *, code: str) -> Path:
    if not path.is_absolute():
        raise PluginReleaseTrustError(code, "Plugin release trust path must be absolute")
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if current.is_symlink() or (current.exists() and _has_reparse_attribute(current)):
                raise PluginReleaseTrustError(code, "Plugin release trust path contains a reparse point")
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PluginReleaseTrustError(code, "Plugin release trust file is unavailable") from error
    if not resolved.is_file():
        raise PluginReleaseTrustError(code, "Plugin release trust file is unavailable")
    return resolved


def _stable_directory(path: Path, *, code: str) -> Path:
    if not path.is_absolute():
        raise PluginReleaseTrustError(code, "Plugin release directory must be absolute")
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if current.is_symlink() or (current.exists() and _has_reparse_attribute(current)):
                raise PluginReleaseTrustError(code, "Plugin release directory contains a reparse point")
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PluginReleaseTrustError(code, "Plugin release directory is unavailable") from error
    if not resolved.is_dir():
        raise PluginReleaseTrustError(code, "Plugin release directory is unavailable")
    return resolved


def _read_bounded(path: Path, maximum: int, *, code: str, label: str) -> bytes:
    resolved = _stable_file(path, code=code)
    try:
        if resolved.stat().st_size <= 0 or resolved.stat().st_size > maximum:
            raise PluginReleaseTrustError(code, f"{label} is empty or too large")
        with resolved.open("rb") as handle:
            value = handle.read(maximum + 1)
    except PluginReleaseTrustError:
        raise
    except OSError as error:
        raise PluginReleaseTrustError(code, f"{label} is unavailable") from error
    if not value or len(value) > maximum:
        raise PluginReleaseTrustError(code, f"{label} is empty or too large")
    return value


def _decode_base64url(value: object, *, length: int, code: str) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise PluginReleaseTrustError(code, "Plugin release trust encoding is invalid")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    except (TypeError, ValueError) as error:
        raise PluginReleaseTrustError(code, "Plugin release trust encoding is invalid") from error
    if len(decoded) != length or encode_base64url(decoded) != value:
        raise PluginReleaseTrustError(code, "Plugin release trust encoding is invalid")
    return decoded


def _parse_utc(value: object, *, code: str) -> datetime:
    if not isinstance(value, str) or _UTC_RE.fullmatch(value) is None:
        raise PluginReleaseTrustError(code, "Plugin release signature timestamp is invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise PluginReleaseTrustError(code, "Plugin release signature timestamp is invalid") from error


def _validate_semver(value: object, *, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(ord(character) < 0x20 for character in value)
    ):
        raise PluginReleaseTrustError(code, "Plugin release version is invalid")
    try:
        compare_semver(value, value)
    except (RuntimeTrustError, ValueError) as error:
        raise PluginReleaseTrustError(code, "Plugin release version is invalid") from error
    return value


def _validate_output_leaf(name: str) -> None:
    stem = name.rstrip(" .").split(".", 1)[0].upper()
    if (
        not name
        or name != name.rstrip(" .")
        or stem in _WINDOWS_RESERVED
        or ":" in name
        or "\\" in name
        or "/" in name
        or any(ord(character) < 0x20 for character in name)
    ):
        raise PluginReleaseTrustError(
            "PLUGIN_RELEASE_SIGNING_REQUEST_PATH_INVALID",
            "Signing request filename is invalid",
        )


@dataclass(frozen=True)
class PluginReleaseTrustKey:
    key_id: str
    key_epoch: int
    public_key: bytes
    public_key_sha256: str
    status: str


class PluginReleaseTrustPolicy:
    """Publisher keys supplied independently from the plugin release payload."""

    def __init__(self, value: dict[str, Any], *, source_digest: str | None = None) -> None:
        expected = {
            "schemaVersion",
            "authority",
            "sequence",
            "minimumPluginVersion",
            "maximumSignatureLifetimeSeconds",
            "keys",
            "revokedPluginVersions",
            "revokedManifestSha256",
        }
        if set(value) != expected or value.get("schemaVersion") != TRUST_POLICY_SCHEMA_VERSION:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_INVALID", "Plugin release trust policy shape is invalid")
        authority = value.get("authority")
        sequence = value.get("sequence")
        minimum_version = _validate_semver(
            value.get("minimumPluginVersion"),
            code="PLUGIN_RELEASE_TRUST_POLICY_INVALID",
        )
        maximum_lifetime = value.get("maximumSignatureLifetimeSeconds")
        keys = value.get("keys")
        revoked_versions = value.get("revokedPluginVersions")
        revoked_manifests = value.get("revokedManifestSha256")
        if (
            not isinstance(authority, str)
            or _IDENTIFIER_RE.fullmatch(authority) is None
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
            or isinstance(maximum_lifetime, bool)
            or not isinstance(maximum_lifetime, int)
            or maximum_lifetime < 60
            or maximum_lifetime > MAX_SIGNATURE_LIFETIME_SECONDS
            or not isinstance(keys, list)
            or not keys
            or not isinstance(revoked_versions, list)
            or not isinstance(revoked_manifests, list)
        ):
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_INVALID", "Plugin release trust policy is invalid")
        for version in revoked_versions:
            _validate_semver(version, code="PLUGIN_RELEASE_TRUST_POLICY_INVALID")
        if revoked_versions != sorted(set(revoked_versions), key=lambda item: item.encode("utf-8")):
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_NONCANONICAL", "Revoked plugin versions must be sorted and unique")
        if (
            not all(isinstance(item, str) and _SHA256_RE.fullmatch(item) for item in revoked_manifests)
            or revoked_manifests != sorted(set(revoked_manifests), key=lambda item: item.encode("ascii"))
        ):
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_NONCANONICAL", "Revoked manifest digests must be sorted and unique")

        parsed_keys: dict[tuple[str, int], PluginReleaseTrustKey] = {}
        public_key_digests: set[str] = set()
        sort_keys: list[tuple[bytes, int]] = []
        for raw in keys:
            if not isinstance(raw, dict) or set(raw) != {
                "keyId",
                "keyEpoch",
                "publicKey",
                "publicKeySha256",
                "status",
            }:
                raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_INVALID", "Plugin release trust key is invalid")
            key_id = raw.get("keyId")
            key_epoch = raw.get("keyEpoch")
            digest = raw.get("publicKeySha256")
            status = raw.get("status")
            if (
                not isinstance(key_id, str)
                or _IDENTIFIER_RE.fullmatch(key_id) is None
                or isinstance(key_epoch, bool)
                or not isinstance(key_epoch, int)
                or key_epoch < 1
                or not isinstance(digest, str)
                or _SHA256_RE.fullmatch(digest) is None
                or status not in {"active", "revoked"}
            ):
                raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_INVALID", "Plugin release trust key is invalid")
            public_key = _decode_base64url(
                raw.get("publicKey"),
                length=32,
                code="PLUGIN_RELEASE_TRUST_POLICY_INVALID",
            )
            if hashlib.sha256(public_key).hexdigest() != digest:
                raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_KEY_DIGEST_MISMATCH", "Plugin release public key digest does not match")
            identity = (key_id, key_epoch)
            if identity in parsed_keys or digest in public_key_digests:
                raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_INVALID", "Plugin release trust key is duplicated")
            public_key_digests.add(digest)
            parsed_keys[identity] = PluginReleaseTrustKey(
                key_id=key_id,
                key_epoch=key_epoch,
                public_key=public_key,
                public_key_sha256=digest,
                status=status,
            )
            sort_keys.append((key_id.encode("utf-8"), key_epoch))
        if sort_keys != sorted(sort_keys):
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_NONCANONICAL", "Plugin release trust keys must be sorted")

        self.value = value
        self.authority = authority
        self.sequence = sequence
        self.minimum_plugin_version = minimum_version
        self.maximum_signature_lifetime_seconds = maximum_lifetime
        self.keys = parsed_keys
        self.revoked_plugin_versions = frozenset(revoked_versions)
        self.revoked_manifest_sha256 = frozenset(revoked_manifests)
        self.digest = source_digest or hashlib.sha256(canonical_bytes(value)).hexdigest()

    @classmethod
    def load(cls, path: str | Path) -> "PluginReleaseTrustPolicy":
        source = _read_bounded(
            Path(path),
            MAX_TRUST_POLICY_BYTES,
            code="PLUGIN_RELEASE_TRUST_POLICY_INVALID",
            label="Plugin release trust policy",
        )
        try:
            value = json.loads(source)
        except ValueError as error:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_INVALID", "Plugin release trust policy is invalid JSON") from error
        if not isinstance(value, dict) or canonical_bytes(value) != source:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_NONCANONICAL", "Plugin release trust policy must use canonical JSON")
        return cls(value, source_digest=hashlib.sha256(source).hexdigest())

    def active_key(self, key_id: str, key_epoch: int) -> PluginReleaseTrustKey:
        key = self.keys.get((key_id, key_epoch))
        if key is None:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNING_KEY_UNTRUSTED", "Plugin release signing key is not trusted")
        if key.status != "active":
            raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNING_KEY_REVOKED", "Plugin release signing key is revoked")
        return key


@dataclass(frozen=True)
class VerifiedPluginReleaseSignature:
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


def plugin_release_signature_message(unsigned_envelope: dict[str, Any]) -> bytes:
    digest = hashlib.sha256(canonical_bytes(unsigned_envelope)).digest()
    return SIGNATURE_DOMAIN.encode("ascii") + b"\x00" + digest


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
        "schemaVersion": SIGNATURE_SCHEMA_VERSION,
        "algorithm": SIGNATURE_ALGORITHM,
        "domain": SIGNATURE_DOMAIN,
        "authority": authority,
        "packageId": package_id,
        "pluginVersion": plugin_version,
        "keyId": key_id,
        "keyEpoch": key_epoch,
        "signedAt": signed_at,
        "expiresAt": expires_at,
        "manifestSha256": manifest_sha256,
    }


def _validate_signature_window(
    unsigned: dict[str, object],
    *,
    policy: PluginReleaseTrustPolicy,
    now: datetime | None,
    require_current: bool,
) -> tuple[datetime, datetime]:
    signed_at = _parse_utc(unsigned.get("signedAt"), code="PLUGIN_RELEASE_SIGNATURE_INVALID")
    expires_at = _parse_utc(unsigned.get("expiresAt"), code="PLUGIN_RELEASE_SIGNATURE_INVALID")
    lifetime = int((expires_at - signed_at).total_seconds())
    if lifetime <= 0 or lifetime > policy.maximum_signature_lifetime_seconds:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNATURE_WINDOW_INVALID", "Plugin release signature lifetime is invalid")
    if require_current:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNATURE_INVALID", "Plugin release verification time must include a timezone")
        current = current.astimezone(timezone.utc)
        if current < signed_at or current >= expires_at:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNATURE_EXPIRED", "Plugin release signature is not currently valid")
    return signed_at, expires_at


def verify_plugin_release_signature(
    signature_path: Path,
    *,
    manifest_sha256: str,
    package_id: str,
    plugin_version: str,
    trust_policy: PluginReleaseTrustPolicy,
    now: datetime | None = None,
) -> VerifiedPluginReleaseSignature:
    source = _read_bounded(
        signature_path,
        MAX_SIGNATURE_BYTES,
        code="PLUGIN_RELEASE_SIGNATURE_INVALID",
        label="Plugin release signature",
    )
    try:
        value = json.loads(source)
    except ValueError as error:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNATURE_INVALID", "Plugin release signature is invalid JSON") from error
    expected = set(_unsigned_envelope(
        authority="authority",
        package_id="package",
        plugin_version="0.0.0",
        key_id="key",
        key_epoch=1,
        signed_at="2000-01-01T00:00:00Z",
        expires_at="2000-01-01T00:01:00Z",
        manifest_sha256="0" * 64,
    )) | {"signature"}
    if not isinstance(value, dict) or set(value) != expected or canonical_bytes(value) != source:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNATURE_INVALID", "Plugin release signature shape is invalid")
    if (
        value.get("schemaVersion") != SIGNATURE_SCHEMA_VERSION
        or value.get("algorithm") != SIGNATURE_ALGORITHM
        or value.get("domain") != SIGNATURE_DOMAIN
        or value.get("authority") != trust_policy.authority
        or value.get("packageId") != package_id
        or value.get("pluginVersion") != plugin_version
        or value.get("manifestSha256") != manifest_sha256
        or not isinstance(value.get("keyId"), str)
        or isinstance(value.get("keyEpoch"), bool)
        or not isinstance(value.get("keyEpoch"), int)
        or _SHA256_RE.fullmatch(manifest_sha256) is None
    ):
        raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNATURE_INVALID", "Plugin release signature binding is invalid")
    _validate_semver(plugin_version, code="PLUGIN_RELEASE_SIGNATURE_INVALID")
    if compare_semver(plugin_version, trust_policy.minimum_plugin_version) < 0:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_VERSION_REVOKED", "Plugin release is below the minimum trusted version")
    if plugin_version in trust_policy.revoked_plugin_versions or manifest_sha256 in trust_policy.revoked_manifest_sha256:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_VERSION_REVOKED", "Plugin release is revoked")
    _validate_signature_window(value, policy=trust_policy, now=now, require_current=True)
    key = trust_policy.active_key(str(value["keyId"]), int(value["keyEpoch"]))
    signature = _decode_base64url(
        value.get("signature"),
        length=64,
        code="PLUGIN_RELEASE_SIGNATURE_INVALID",
    )
    unsigned = {name: child for name, child in value.items() if name != "signature"}
    try:
        Ed25519PublicKey.from_public_bytes(key.public_key).verify(
            signature,
            plugin_release_signature_message(unsigned),
        )
    except (InvalidSignature, ValueError) as error:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNATURE_INVALID", "Plugin release signature verification failed") from error
    return VerifiedPluginReleaseSignature(
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


def build_plugin_release_signing_request(
    manifest_path: Path,
    *,
    trust_policy: PluginReleaseTrustPolicy,
    key_id: str,
    key_epoch: int,
    signed_at: str,
    expires_at: str,
) -> dict[str, object]:
    from .plugin_bundle import PluginBundleError, PluginReleaseBundle

    if manifest_path.name != "release-package-v1.json":
        raise PluginReleaseTrustError(
            "PLUGIN_RELEASE_MANIFEST_INVALID",
            "Signing requests require the verified release manifest path",
        )
    try:
        bundle = PluginReleaseBundle(manifest_path.parent)
    except PluginBundleError as error:
        raise PluginReleaseTrustError(
            "PLUGIN_RELEASE_MANIFEST_INVALID",
            "Signing requests require a fully verified passive candidate",
        ) from error
    manifest_path = bundle.root / "release-package-v1.json"
    source = _read_bounded(
        manifest_path,
        MAX_RELEASE_MANIFEST_BYTES,
        code="PLUGIN_RELEASE_MANIFEST_INVALID",
        label="Plugin release manifest",
    )
    try:
        manifest = json.loads(source)
    except ValueError as error:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_MANIFEST_INVALID", "Plugin release manifest is invalid JSON") from error
    if not isinstance(manifest, dict) or canonical_bytes(manifest) != source:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_MANIFEST_INVALID", "Plugin release manifest must use canonical JSON")
    if hashlib.sha256(source).hexdigest() != bundle.digest:
        raise PluginReleaseTrustError(
            "PLUGIN_RELEASE_MANIFEST_CHANGED",
            "Plugin release manifest changed after candidate verification",
        )
    package_id = manifest.get("packageId")
    plugin_version = _validate_semver(manifest.get("version"), code="PLUGIN_RELEASE_MANIFEST_INVALID")
    if manifest.get("schemaVersion") != 1 or not isinstance(package_id, str) or _IDENTIFIER_RE.fullmatch(package_id) is None:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_MANIFEST_INVALID", "Plugin release manifest identity is invalid")
    trust_policy.active_key(key_id, key_epoch)
    digest = hashlib.sha256(source).hexdigest()
    if plugin_version in trust_policy.revoked_plugin_versions or digest in trust_policy.revoked_manifest_sha256:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_VERSION_REVOKED", "Plugin release is revoked")
    if compare_semver(plugin_version, trust_policy.minimum_plugin_version) < 0:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_VERSION_REVOKED", "Plugin release is below the minimum trusted version")
    unsigned = _unsigned_envelope(
        authority=trust_policy.authority,
        package_id=package_id,
        plugin_version=plugin_version,
        key_id=key_id,
        key_epoch=key_epoch,
        signed_at=signed_at,
        expires_at=expires_at,
        manifest_sha256=digest,
    )
    _validate_signature_window(unsigned, policy=trust_policy, now=None, require_current=False)
    message = plugin_release_signature_message(unsigned)
    return {
        "schemaVersion": SIGNING_REQUEST_SCHEMA_VERSION,
        "algorithm": SIGNATURE_ALGORITHM,
        "domain": SIGNATURE_DOMAIN,
        "trustPolicyDigest": trust_policy.digest,
        "unsignedEnvelope": unsigned,
        "signingMessage": encode_base64url(message),
        "signingMessageSha256": hashlib.sha256(message).hexdigest(),
        "privateKeyRead": False,
        "networkUsed": False,
    }


def write_plugin_release_signing_request(output_path: Path, request: dict[str, object]) -> str:
    if not output_path.is_absolute():
        raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNING_REQUEST_PATH_INVALID", "Signing request path must be absolute")
    _validate_output_leaf(output_path.name)
    parent = _stable_directory(output_path.parent, code="PLUGIN_RELEASE_SIGNING_REQUEST_PATH_INVALID")
    output = parent / output_path.name
    if output.exists():
        raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNING_REQUEST_EXISTS", "Signing request output already exists")
    payload = canonical_bytes(request)
    if len(payload) > MAX_SIGNING_REQUEST_BYTES:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNING_REQUEST_INVALID", "Signing request is too large")
    temporary = parent / f".{output.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output, follow_symlinks=False)
    except FileExistsError as error:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNING_REQUEST_EXISTS", "Signing request output already exists") from error
    except OSError as error:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_SIGNING_REQUEST_WRITE_FAILED", "Signing request could not be written atomically") from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return hashlib.sha256(payload).hexdigest()


def enforce_plugin_release_rollback_floor(
    state_root: Path,
    *,
    plugin_version: str,
    manifest_sha256: str,
    signature: VerifiedPluginReleaseSignature,
) -> None:
    if not state_root.is_absolute():
        raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_FLOOR_INVALID", "Plugin release state root must be absolute")
    floor_path = (state_root / "plugin-release" / "trust-floor-v1.json").resolve()
    floor_path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schemaVersion": 1,
        "authority": signature.authority,
        "packageId": signature.package_id,
        "trustSequence": signature.trust_sequence,
        "trustPolicyDigest": signature.trust_policy_digest,
        "pluginVersion": plugin_version,
        "manifestSha256": manifest_sha256,
    }
    if floor_path.is_file():
        source = _read_bounded(
            floor_path,
            MAX_TRUST_FLOOR_BYTES,
            code="PLUGIN_RELEASE_TRUST_FLOOR_INVALID",
            label="Plugin release trust floor",
        )
        try:
            previous = json.loads(source)
        except ValueError as error:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_FLOOR_INVALID", "Plugin release trust floor is unreadable") from error
        if not isinstance(previous, dict) or set(previous) != set(value) or canonical_bytes(previous) != source:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_FLOOR_INVALID", "Plugin release trust floor is invalid")
        if previous.get("authority") != signature.authority or previous.get("packageId") != signature.package_id:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_AUTHORITY_CHANGED", "Plugin release trust authority changed")
        previous_sequence = previous.get("trustSequence")
        previous_policy_digest = previous.get("trustPolicyDigest")
        previous_version = previous.get("pluginVersion")
        previous_digest = previous.get("manifestSha256")
        if (
            isinstance(previous_sequence, bool)
            or not isinstance(previous_sequence, int)
            or not isinstance(previous_policy_digest, str)
            or _SHA256_RE.fullmatch(previous_policy_digest) is None
            or not isinstance(previous_version, str)
            or not isinstance(previous_digest, str)
            or _SHA256_RE.fullmatch(previous_digest) is None
        ):
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_FLOOR_INVALID", "Plugin release trust floor is invalid")
        if signature.trust_sequence < previous_sequence:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_ROLLBACK", "Plugin release trust policy sequence moved backwards")
        if signature.trust_sequence == previous_sequence and signature.trust_policy_digest != previous_policy_digest:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_POLICY_FORK", "Plugin release trust policy sequence was reused")
        version_order = compare_semver(plugin_version, previous_version)
        if version_order < 0:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_ROLLBACK", "Plugin release version moved backwards")
        if version_order == 0 and manifest_sha256 != previous_digest:
            raise PluginReleaseTrustError("PLUGIN_RELEASE_VERSION_REUSED", "Plugin release version was reused with new content")
        if value == previous:
            return
    temporary = floor_path.with_name(floor_path.name + ".tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, floor_path)
    except OSError as error:
        raise PluginReleaseTrustError("PLUGIN_RELEASE_TRUST_FLOOR_WRITE_FAILED", "Plugin release trust floor could not be persisted") from error
