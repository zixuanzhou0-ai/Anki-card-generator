from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.plugin_install_bundle import (
    PluginInstallError,
    build_plugin_install_signing_request,
    write_plugin_install_signing_request,
)
from card_service.plugin_release_trust import PluginReleaseTrustError, PluginReleaseTrustPolicy


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Create a public-key-only signing request for a verified install candidate.",
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
    candidate = arguments.candidate.resolve()
    output = arguments.output.resolve()
    try:
        if output == candidate or candidate in output.parents:
            raise PluginInstallError(
                "PLUGIN_INSTALL_SIGNING_REQUEST_PATH_INVALID",
                "Install signing request must stay outside the verified candidate",
            )
        policy = PluginReleaseTrustPolicy.load(arguments.trust_policy.resolve())
        request = build_plugin_install_signing_request(
            candidate,
            trust_policy=policy,
            key_id=arguments.key_id,
            key_epoch=arguments.key_epoch,
            signed_at=arguments.signed_at,
            expires_at=arguments.expires_at,
        )
        digest = write_plugin_install_signing_request(output, request)
    except (PluginInstallError, PluginReleaseTrustError) as error:
        code = getattr(error, "code", "PLUGIN_INSTALL_SIGNING_REQUEST_FAILED")
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
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
