from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .runtime_manifest import canonical_bytes


TRUST_POLICY_SCHEMA_VERSION = 1
SIGNATURE_SCHEMA_VERSION = 1
SIGNATURE_ALGORITHM = "Ed25519"
SIGNATURE_DOMAIN = "study.runtime-package-manifest.v1"
SIGNATURE_FILE_NAME = "runtime-package-v1.sig.json"
MAX_TRUST_POLICY_BYTES = 256 * 1024
MAX_SIGNATURE_BYTES = 32 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class RuntimeTrustError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _stable_file(path: Path, *, code: str) -> Path:
    if not path.is_absolute():
        raise RuntimeTrustError(code, "Runtime trust file path must be absolute")
    original = path
    current = Path(original.anchor)
    for part in original.parts[1:]:
        current /= part
        if current.is_symlink() or (current.exists() and _has_reparse_attribute(current)):
            raise RuntimeTrustError(code, "Runtime trust file path contains a reparse point")
    try:
        resolved = original.resolve(strict=True)
    except OSError as error:
        raise RuntimeTrustError(code, "Runtime trust file is unavailable") from error
    if not resolved.is_file():
        raise RuntimeTrustError(code, "Runtime trust file is unavailable")
    return resolved


def _decode_base64url(value: Any, *, expected_length: int, code: str) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise RuntimeTrustError(code, "Runtime trust encoding is invalid")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    except (ValueError, TypeError) as error:
        raise RuntimeTrustError(code, "Runtime trust encoding is invalid") from error
    if len(decoded) != expected_length or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise RuntimeTrustError(code, "Runtime trust encoding is invalid")
    return decoded


def encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _parse_semver(value: str) -> tuple[tuple[int, int, int], tuple[str, ...] | None]:
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        raise RuntimeTrustError("RUNTIME_PACKAGE_VERSION_INVALID", "Runtime package version is invalid")
    prerelease = tuple(match.group(4).split(".")) if match.group(4) is not None else None
    if prerelease is not None:
        for identifier in prerelease:
            if identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0"):
                raise RuntimeTrustError("RUNTIME_PACKAGE_VERSION_INVALID", "Runtime package version is invalid")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))), prerelease


def compare_semver(left: str, right: str) -> int:
    left_core, left_pre = _parse_semver(left)
    right_core, right_pre = _parse_semver(right)
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    if left_pre is None or right_pre is None:
        if left_pre is right_pre:
            return 0
        return 1 if left_pre is None else -1
    for left_item, right_item in zip(left_pre, right_pre):
        if left_item == right_item:
            continue
        left_numeric = left_item.isdigit()
        right_numeric = right_item.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_item) < int(right_item) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_item < right_item else 1
    if len(left_pre) == len(right_pre):
        return 0
    return -1 if len(left_pre) < len(right_pre) else 1


def _parse_utc(value: Any, *, code: str) -> datetime:
    if not isinstance(value, str) or _UTC_RE.fullmatch(value) is None:
        raise RuntimeTrustError(code, "Runtime package signature timestamp is invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise RuntimeTrustError(code, "Runtime package signature timestamp is invalid") from error


@dataclass(frozen=True)
class RuntimeTrustKey:
    key_id: str
    key_epoch: int
    public_key: bytes
    public_key_sha256: str
    status: str


class RuntimePackageTrustPolicy:
    """Immutable publisher keys supplied by the trusted Card Service launcher."""

    def __init__(self, value: dict[str, Any], *, source_digest: str | None = None) -> None:
        expected = {
            "schemaVersion",
            "authority",
            "sequence",
            "minimumRuntimeVersion",
            "keys",
            "revokedPackageVersions",
        }
        if set(value) != expected or value.get("schemaVersion") != TRUST_POLICY_SCHEMA_VERSION:
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_INVALID", "Runtime trust policy shape is invalid")
        authority = value.get("authority")
        sequence = value.get("sequence")
        minimum_version = value.get("minimumRuntimeVersion")
        keys = value.get("keys")
        revoked_versions = value.get("revokedPackageVersions")
        if (
            not isinstance(authority, str)
            or _IDENTIFIER_RE.fullmatch(authority) is None
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
            or not isinstance(minimum_version, str)
            or not isinstance(keys, list)
            or not keys
            or not isinstance(revoked_versions, list)
        ):
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_INVALID", "Runtime trust policy is invalid")
        _parse_semver(minimum_version)
        for version in revoked_versions:
            if not isinstance(version, str):
                raise RuntimeTrustError("RUNTIME_TRUST_POLICY_INVALID", "Revoked package version is invalid")
            _parse_semver(version)
        if revoked_versions != sorted(set(revoked_versions), key=lambda item: item.encode("utf-8")):
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_NONCANONICAL", "Revoked versions must be sorted and unique")

        parsed_keys: dict[tuple[str, int], RuntimeTrustKey] = {}
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
                raise RuntimeTrustError("RUNTIME_TRUST_POLICY_INVALID", "Runtime trust key is invalid")
            key_id = raw.get("keyId")
            key_epoch = raw.get("keyEpoch")
            status = raw.get("status")
            public_key_sha256 = raw.get("publicKeySha256")
            if (
                not isinstance(key_id, str)
                or _IDENTIFIER_RE.fullmatch(key_id) is None
                or isinstance(key_epoch, bool)
                or not isinstance(key_epoch, int)
                or key_epoch < 1
                or status not in {"active", "revoked"}
                or not isinstance(public_key_sha256, str)
                or _SHA256_RE.fullmatch(public_key_sha256) is None
            ):
                raise RuntimeTrustError("RUNTIME_TRUST_POLICY_INVALID", "Runtime trust key is invalid")
            public_key = _decode_base64url(
                raw.get("publicKey"),
                expected_length=32,
                code="RUNTIME_TRUST_POLICY_INVALID",
            )
            if hashlib.sha256(public_key).hexdigest() != public_key_sha256:
                raise RuntimeTrustError("RUNTIME_TRUST_KEY_DIGEST_MISMATCH", "Runtime trust key digest does not match")
            identity = (key_id, key_epoch)
            if identity in parsed_keys or public_key_sha256 in public_key_digests:
                raise RuntimeTrustError("RUNTIME_TRUST_POLICY_INVALID", "Runtime trust key is duplicated")
            public_key_digests.add(public_key_sha256)
            parsed_keys[identity] = RuntimeTrustKey(
                key_id=key_id,
                key_epoch=key_epoch,
                public_key=public_key,
                public_key_sha256=public_key_sha256,
                status=status,
            )
            sort_keys.append((key_id.encode("utf-8"), key_epoch))
        if sort_keys != sorted(sort_keys):
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_NONCANONICAL", "Runtime trust keys must be sorted")
        self.value = value
        self.authority = authority
        self.sequence = sequence
        self.minimum_runtime_version = minimum_version
        self.keys = parsed_keys
        self.revoked_package_versions = frozenset(revoked_versions)
        self.digest = source_digest or hashlib.sha256(canonical_bytes(value)).hexdigest()

    @classmethod
    def load(cls, path: str | Path) -> "RuntimePackageTrustPolicy":
        resolved = _stable_file(Path(path), code="RUNTIME_TRUST_POLICY_INVALID")
        try:
            source = resolved.read_bytes()
        except OSError as error:
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_INVALID", "Runtime trust policy is unavailable") from error
        if not source or len(source) > MAX_TRUST_POLICY_BYTES:
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_INVALID", "Runtime trust policy is empty or too large")
        try:
            value = json.loads(source)
        except ValueError as error:
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_INVALID", "Runtime trust policy is invalid JSON") from error
        if not isinstance(value, dict):
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_INVALID", "Runtime trust policy must be an object")
        if canonical_bytes(value) != source:
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_NONCANONICAL", "Runtime trust policy must use canonical JSON")
        return cls(value, source_digest=hashlib.sha256(source).hexdigest())

    def active_key(self, key_id: str, key_epoch: int) -> RuntimeTrustKey:
        key = self.keys.get((key_id, key_epoch))
        if key is None:
            raise RuntimeTrustError("RUNTIME_SIGNING_KEY_UNTRUSTED", "Runtime package signing key is not trusted")
        if key.status != "active":
            raise RuntimeTrustError("RUNTIME_SIGNING_KEY_REVOKED", "Runtime package signing key is revoked")
        return key


@dataclass(frozen=True)
class VerifiedRuntimeSignature:
    authority: str
    key_id: str
    key_epoch: int
    signed_at: str
    expires_at: str
    manifest_sha256: str
    trust_sequence: int
    trust_policy_digest: str


def signature_message(unsigned_envelope: dict[str, Any]) -> bytes:
    digest = hashlib.sha256(canonical_bytes(unsigned_envelope)).digest()
    return SIGNATURE_DOMAIN.encode("ascii") + b"\x00" + digest


def verify_runtime_signature(
    signature_path: Path,
    *,
    manifest_sha256: str,
    package_version: str,
    trust_policy: RuntimePackageTrustPolicy,
    now: datetime | None = None,
) -> VerifiedRuntimeSignature:
    resolved = _stable_file(signature_path, code="RUNTIME_PACKAGE_SIGNATURE_INVALID")
    try:
        source = resolved.read_bytes()
    except OSError as error:
        raise RuntimeTrustError("RUNTIME_PACKAGE_SIGNATURE_INVALID", "Runtime package signature is unavailable") from error
    if not source or len(source) > MAX_SIGNATURE_BYTES:
        raise RuntimeTrustError("RUNTIME_PACKAGE_SIGNATURE_INVALID", "Runtime package signature is empty or too large")
    try:
        value = json.loads(source)
    except ValueError as error:
        raise RuntimeTrustError("RUNTIME_PACKAGE_SIGNATURE_INVALID", "Runtime package signature is invalid JSON") from error
    expected = {
        "schemaVersion",
        "algorithm",
        "domain",
        "authority",
        "keyId",
        "keyEpoch",
        "signedAt",
        "expiresAt",
        "manifestSha256",
        "signature",
    }
    if not isinstance(value, dict) or set(value) != expected or canonical_bytes(value) != source:
        raise RuntimeTrustError("RUNTIME_PACKAGE_SIGNATURE_INVALID", "Runtime package signature shape is invalid")
    if (
        value.get("schemaVersion") != SIGNATURE_SCHEMA_VERSION
        or value.get("algorithm") != SIGNATURE_ALGORITHM
        or value.get("domain") != SIGNATURE_DOMAIN
        or value.get("authority") != trust_policy.authority
        or value.get("manifestSha256") != manifest_sha256
        or not isinstance(value.get("keyId"), str)
        or isinstance(value.get("keyEpoch"), bool)
        or not isinstance(value.get("keyEpoch"), int)
    ):
        raise RuntimeTrustError("RUNTIME_PACKAGE_SIGNATURE_INVALID", "Runtime package signature binding is invalid")
    if compare_semver(package_version, trust_policy.minimum_runtime_version) < 0:
        raise RuntimeTrustError("RUNTIME_PACKAGE_VERSION_REVOKED", "Runtime package is below the minimum trusted version")
    if package_version in trust_policy.revoked_package_versions:
        raise RuntimeTrustError("RUNTIME_PACKAGE_VERSION_REVOKED", "Runtime package version is revoked")
    signed_at = _parse_utc(value.get("signedAt"), code="RUNTIME_PACKAGE_SIGNATURE_INVALID")
    expires_at = _parse_utc(value.get("expiresAt"), code="RUNTIME_PACKAGE_SIGNATURE_INVALID")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise RuntimeTrustError("RUNTIME_PACKAGE_SIGNATURE_INVALID", "Signature verification time must include a timezone")
    current = current.astimezone(timezone.utc)
    if expires_at <= signed_at or current < signed_at or current >= expires_at:
        raise RuntimeTrustError("RUNTIME_PACKAGE_SIGNATURE_EXPIRED", "Runtime package signature is not currently valid")
    key = trust_policy.active_key(str(value["keyId"]), int(value["keyEpoch"]))
    signature = _decode_base64url(
        value.get("signature"),
        expected_length=64,
        code="RUNTIME_PACKAGE_SIGNATURE_INVALID",
    )
    unsigned = {name: child for name, child in value.items() if name != "signature"}
    try:
        Ed25519PublicKey.from_public_bytes(key.public_key).verify(signature, signature_message(unsigned))
    except (InvalidSignature, ValueError) as error:
        raise RuntimeTrustError("RUNTIME_PACKAGE_SIGNATURE_INVALID", "Runtime package signature verification failed") from error
    return VerifiedRuntimeSignature(
        authority=trust_policy.authority,
        key_id=key.key_id,
        key_epoch=key.key_epoch,
        signed_at=str(value["signedAt"]),
        expires_at=str(value["expiresAt"]),
        manifest_sha256=manifest_sha256,
        trust_sequence=trust_policy.sequence,
        trust_policy_digest=trust_policy.digest,
    )


def enforce_runtime_rollback_floor(
    state_root: Path,
    *,
    package_version: str,
    manifest_sha256: str,
    signature: VerifiedRuntimeSignature,
) -> None:
    floor_path = (state_root / "runtime" / "trust-floor-v1.json").resolve()
    floor_path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schemaVersion": 1,
        "authority": signature.authority,
        "trustSequence": signature.trust_sequence,
        "trustPolicyDigest": signature.trust_policy_digest,
        "packageVersion": package_version,
        "manifestSha256": manifest_sha256,
    }
    if floor_path.is_file():
        try:
            source = floor_path.read_bytes()
            previous = json.loads(source)
        except (OSError, ValueError) as error:
            raise RuntimeTrustError("RUNTIME_TRUST_FLOOR_INVALID", "Runtime trust floor is unreadable") from error
        if not isinstance(previous, dict) or set(previous) != set(value) or canonical_bytes(previous) != source:
            raise RuntimeTrustError("RUNTIME_TRUST_FLOOR_INVALID", "Runtime trust floor is invalid")
        if previous.get("authority") != signature.authority:
            raise RuntimeTrustError("RUNTIME_TRUST_AUTHORITY_CHANGED", "Runtime trust authority changed")
        previous_sequence = previous.get("trustSequence")
        previous_policy_digest = previous.get("trustPolicyDigest")
        previous_version = previous.get("packageVersion")
        previous_digest = previous.get("manifestSha256")
        if (
            isinstance(previous_sequence, bool)
            or not isinstance(previous_sequence, int)
            or not isinstance(previous_policy_digest, str)
            or _SHA256_RE.fullmatch(previous_policy_digest) is None
            or not isinstance(previous_version, str)
            or not isinstance(previous_digest, str)
        ):
            raise RuntimeTrustError("RUNTIME_TRUST_FLOOR_INVALID", "Runtime trust floor is invalid")
        if signature.trust_sequence < previous_sequence:
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_ROLLBACK", "Runtime trust policy sequence moved backwards")
        if signature.trust_sequence == previous_sequence and signature.trust_policy_digest != previous_policy_digest:
            raise RuntimeTrustError("RUNTIME_TRUST_POLICY_FORK", "Runtime trust policy sequence was reused")
        version_order = compare_semver(package_version, previous_version)
        if version_order < 0:
            raise RuntimeTrustError("RUNTIME_PACKAGE_ROLLBACK", "Runtime package version moved backwards")
        if version_order == 0 and manifest_sha256 != previous_digest:
            raise RuntimeTrustError("RUNTIME_PACKAGE_VERSION_REUSED", "Runtime package version was reused with new content")
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
        raise RuntimeTrustError("RUNTIME_TRUST_FLOOR_WRITE_FAILED", "Runtime trust floor could not be persisted") from error
