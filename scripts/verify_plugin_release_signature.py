from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.plugin_bundle import PluginBundleError, PluginReleaseBundle
from card_service.plugin_release_trust import (
    PluginReleaseTrustError,
    PluginReleaseTrustPolicy,
    verify_plugin_release_signature,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Verify a detached plugin release signature against an external publisher policy.",
    )
    value.add_argument("--candidate", type=Path, required=True)
    value.add_argument("--trust-policy", type=Path, required=True)
    value.add_argument("--signature", type=Path, required=True)
    return value


def main() -> None:
    arguments = parser().parse_args()
    try:
        bundle = PluginReleaseBundle(arguments.candidate.resolve())
        policy = PluginReleaseTrustPolicy.load(arguments.trust_policy.resolve())
        signature = verify_plugin_release_signature(
            arguments.signature.resolve(),
            manifest_sha256=bundle.digest,
            package_id=str(bundle.value["packageId"]),
            plugin_version=bundle.version,
            trust_policy=policy,
        )
    except (PluginBundleError, PluginReleaseTrustError) as error:
        code = getattr(error, "code", "PLUGIN_RELEASE_SIGNATURE_VERIFY_FAILED")
        raise SystemExit(f"{code}: {error}") from error
    print(
        json.dumps(
            {
                "schemaVersion": 1,
                "packageId": signature.package_id,
                "pluginVersion": signature.plugin_version,
                "manifestSha256": signature.manifest_sha256,
                "authority": signature.authority,
                "keyId": signature.key_id,
                "keyEpoch": signature.key_epoch,
                "signedAt": signature.signed_at,
                "expiresAt": signature.expires_at,
                "trustSequence": signature.trust_sequence,
                "trustPolicyDigest": signature.trust_policy_digest,
                "signatureVerified": True,
                "payloadVerified": True,
                "privateKeyRead": False,
                "networkUsed": False,
                "installable": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
