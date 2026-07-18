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
    build_plugin_release_signing_request,
    write_plugin_release_signing_request,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Create a public-key-only signing request for a verified plugin release manifest.",
    )
    value.add_argument("--candidate", type=Path, required=True)
    value.add_argument("--trust-policy", type=Path, required=True)
    value.add_argument("--key-id", required=True)
    value.add_argument("--key-epoch", type=int, required=True)
    value.add_argument("--signed-at", required=True)
    value.add_argument("--expires-at", required=True)
    value.add_argument("--output", type=Path, required=True)
    return value


def main() -> None:
    arguments = parser().parse_args()
    try:
        candidate = PluginReleaseBundle(arguments.candidate.resolve())
        output = arguments.output.resolve()
        if output == candidate.root or candidate.root in output.parents:
            raise PluginReleaseTrustError(
                "PLUGIN_RELEASE_SIGNING_REQUEST_PATH_INVALID",
                "Signing request output must stay outside the verified candidate",
            )
        policy = PluginReleaseTrustPolicy.load(arguments.trust_policy.resolve())
        request = build_plugin_release_signing_request(
            candidate.root / "release-package-v1.json",
            trust_policy=policy,
            key_id=arguments.key_id,
            key_epoch=arguments.key_epoch,
            signed_at=arguments.signed_at,
            expires_at=arguments.expires_at,
        )
        digest = write_plugin_release_signing_request(output, request)
    except (PluginBundleError, PluginReleaseTrustError) as error:
        code = getattr(error, "code", "PLUGIN_RELEASE_SIGNING_REQUEST_FAILED")
        raise SystemExit(f"{code}: {error}") from error
    print(
        json.dumps(
            {
                "schemaVersion": 1,
                "requestSha256": digest,
                "manifestSha256": request["unsignedEnvelope"]["manifestSha256"],
                "trustPolicyDigest": request["trustPolicyDigest"],
                "privateKeyRead": False,
                "networkUsed": False,
                "signatureCreated": False,
                "installable": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
