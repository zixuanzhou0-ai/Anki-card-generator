from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.plugin_install_bundle import (
    PluginInstallError,
    finalize_plugin_install_package,
    finalize_result_json,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Finalize a plugin install package after detached and Authenticode verification.",
    )
    value.add_argument("--candidate", type=Path, required=True)
    value.add_argument("--signature", type=Path, required=True)
    value.add_argument("--plugin-publisher-trust-policy", type=Path, required=True)
    value.add_argument("--launcher-authenticode-policy", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    return value


def main() -> None:
    arguments = parser().parse_args()
    try:
        result = finalize_plugin_install_package(
            arguments.output.resolve(),
            candidate_root=arguments.candidate.resolve(),
            signature_path=arguments.signature.resolve(),
            plugin_publisher_trust_policy=arguments.plugin_publisher_trust_policy.resolve(),
            launcher_authenticode_policy=arguments.launcher_authenticode_policy.resolve(),
        )
    except PluginInstallError as error:
        raise SystemExit(f"{error.code}: {error}") from error
    print(finalize_result_json(result))


if __name__ == "__main__":
    main()
