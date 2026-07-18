from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from card_service.runtime_manifest import canonical_bytes
from card_service.runtime_package import ManagedRuntimePackage
from card_service.runtime_trust import (
    SIGNATURE_ALGORITHM,
    SIGNATURE_DOMAIN,
    SIGNATURE_FILE_NAME,
    RuntimePackageTrustPolicy,
    encode_base64url,
    signature_message,
)


def _write_exclusive(path: Path, source: bytes) -> None:
    if not path.is_absolute() or path.exists() or not path.parent.is_dir():
        raise ValueError("Probe trust output must be a new absolute file")
    with path.open("xb") as handle:
        handle.write(source)
        handle.flush()
        os.fsync(handle.fileno())


def create_ephemeral_probe_signature(
    runtime_root: Path,
    trust_policy_path: Path,
    *,
    valid_hours: int = 24,
    now: datetime | None = None,
) -> dict[str, object]:
    if valid_hours < 1 or valid_hours > 24:
        raise ValueError("Probe signature validity must be between 1 and 24 hours")
    package = ManagedRuntimePackage(runtime_root)
    signature_path = package.root / SIGNATURE_FILE_NAME
    if signature_path.exists():
        raise ValueError("Runtime package already has a detached signature")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    expires = current + timedelta(hours=valid_hours)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    authority = "anki-study-local-probe"
    key_id = "ephemeral-probe-key"
    unsigned = {
        "schemaVersion": 1,
        "algorithm": SIGNATURE_ALGORITHM,
        "domain": SIGNATURE_DOMAIN,
        "authority": authority,
        "keyId": key_id,
        "keyEpoch": 1,
        "signedAt": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresAt": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifestSha256": package.digest,
    }
    signature = dict(unsigned)
    signature["signature"] = encode_base64url(private_key.sign(signature_message(unsigned)))
    trust = {
        "schemaVersion": 1,
        "authority": authority,
        "sequence": 1,
        "minimumRuntimeVersion": package.version,
        "keys": [
            {
                "keyId": key_id,
                "keyEpoch": 1,
                "publicKey": encode_base64url(public_key),
                "publicKeySha256": hashlib.sha256(public_key).hexdigest(),
                "status": "active",
            }
        ],
        "revokedPackageVersions": [],
    }
    _write_exclusive(signature_path, canonical_bytes(signature))
    _write_exclusive(trust_policy_path, canonical_bytes(trust))
    policy = RuntimePackageTrustPolicy.load(trust_policy_path)
    verified = ManagedRuntimePackage(
        package.root,
        trust_policy=policy,
        require_signature=True,
        now=current,
    )
    return {
        "schemaVersion": 1,
        "ephemeralProbeOnly": True,
        "packageVersion": verified.version,
        "manifestSha256": verified.digest,
        "publicKeySha256": hashlib.sha256(public_key).hexdigest(),
        "signatureVerified": verified.public_summary()["signatureVerified"],
        "expiresAt": unsigned["expiresAt"],
        "privateKeyPersisted": False,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Create a short-lived random trust envelope for local runtime probes only."
    )
    value.add_argument("--runtime-root", type=Path, required=True)
    value.add_argument("--trust-policy", type=Path, required=True)
    value.add_argument("--valid-hours", type=int, default=24)
    return value


def main() -> None:
    arguments = parser().parse_args()
    result = create_ephemeral_probe_signature(
        arguments.runtime_root.resolve(),
        arguments.trust_policy.resolve(),
        valid_hours=arguments.valid_hours,
    )
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()
