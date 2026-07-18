from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.plugin_bundle import PluginBundleError, PluginReleaseBundle
from card_service.plugin_release_trust import (
    SIGNATURE_FILE_NAME,
    SIGNING_REQUEST_FILE_NAME,
    PluginReleaseTrustError,
    PluginReleaseTrustPolicy,
    build_plugin_release_signing_request,
    plugin_release_signature_message,
    verify_plugin_release_signature,
)
from card_service.runtime_manifest import canonical_bytes
from card_service.runtime_trust import encode_base64url


TRUST_POLICY_FILE_NAME = "plugin-publisher-trust-v1.json"
MAX_PROBE_LIFETIME_SECONDS = 24 * 60 * 60


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Create a short-lived local probe signature without persisting its private key.",
    )
    value.add_argument("--candidate", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--lifetime-seconds", type=int, default=MAX_PROBE_LIFETIME_SECONDS)
    return value


def _write(path: Path, value: dict[str, object]) -> None:
    with path.open("xb") as handle:
        handle.write(canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())


def main() -> None:
    arguments = parser().parse_args()
    if not 60 <= arguments.lifetime_seconds <= MAX_PROBE_LIFETIME_SECONDS:
        raise SystemExit("PLUGIN_PROBE_LIFETIME_INVALID: probe lifetime must be between 60 and 86400 seconds")
    candidate_path = arguments.candidate.resolve()
    output = arguments.output.resolve()
    if output == candidate_path or candidate_path in output.parents:
        raise SystemExit("PLUGIN_PROBE_OUTPUT_INVALID: probe output must stay outside the candidate")
    parent = output.parent.resolve(strict=True)
    if output.exists():
        raise SystemExit("PLUGIN_PROBE_OUTPUT_EXISTS: output directory already exists")
    temporary = parent / f".{output.name}.{uuid.uuid4().hex}.tmp"
    temporary.mkdir()
    private_key = Ed25519PrivateKey.generate()
    try:
        bundle = PluginReleaseBundle(candidate_path)
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        expires = now + timedelta(seconds=arguments.lifetime_seconds)
        policy_value = {
            "schemaVersion": 1,
            "authority": "anki-study-agent.local-probe",
            "sequence": int(now.timestamp()),
            "minimumPluginVersion": bundle.version,
            "maximumSignatureLifetimeSeconds": MAX_PROBE_LIFETIME_SECONDS,
            "keys": [
                {
                    "keyId": "ephemeral-probe",
                    "keyEpoch": 1,
                    "publicKey": encode_base64url(public_key),
                    "publicKeySha256": hashlib.sha256(public_key).hexdigest(),
                    "status": "active",
                }
            ],
            "revokedPluginVersions": [],
            "revokedManifestSha256": [],
        }
        policy_path = (temporary / TRUST_POLICY_FILE_NAME).resolve()
        _write(policy_path, policy_value)
        policy = PluginReleaseTrustPolicy.load(policy_path)
        request = build_plugin_release_signing_request(
            bundle.root / "release-package-v1.json",
            trust_policy=policy,
            key_id="ephemeral-probe",
            key_epoch=1,
            signed_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_at=expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        _write((temporary / SIGNING_REQUEST_FILE_NAME).resolve(), request)
        unsigned = dict(request["unsignedEnvelope"])
        signature = dict(unsigned)
        signature["signature"] = encode_base64url(
            private_key.sign(plugin_release_signature_message(unsigned))
        )
        signature_path = (temporary / SIGNATURE_FILE_NAME).resolve()
        _write(signature_path, signature)
        verified = verify_plugin_release_signature(
            signature_path,
            manifest_sha256=bundle.digest,
            package_id=str(bundle.value["packageId"]),
            plugin_version=bundle.version,
            trust_policy=policy,
            now=now,
        )
        os.rename(temporary, output)
    except (OSError, PluginBundleError, PluginReleaseTrustError) as error:
        shutil.rmtree(temporary, ignore_errors=True)
        code = getattr(error, "code", "PLUGIN_PROBE_SIGNATURE_FAILED")
        raise SystemExit(f"{code}: {error}") from error
    finally:
        private_key = None

    print(
        json.dumps(
            {
                "schemaVersion": 1,
                "authority": verified.authority,
                "manifestSha256": verified.manifest_sha256,
                "trustPolicyDigest": verified.trust_policy_digest,
                "signatureVerified": True,
                "privateKeyPersisted": False,
                "networkUsed": False,
                "probeOnly": True,
                "installable": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
