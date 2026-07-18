from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.plugin_launcher_builder import (
    PluginLauncherBuildError,
    build_plugin_launcher,
    result_json,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Build the pinned native Anki Study plugin launcher without release private keys.",
    )
    value.add_argument("--runtime-root", type=Path, required=True)
    value.add_argument("--runtime-trust-policy", type=Path, required=True)
    value.add_argument(
        "--plugin-install-trust-policy",
        type=Path,
        help="External canonical publisher policy to pin for installable builds; omit for passive builds.",
    )
    value.add_argument("--output", type=Path, required=True)
    value.add_argument(
        "--cargo-manifest",
        type=Path,
        default=ROOT / "runtime-tools" / "anki-study-launcher" / "Cargo.toml",
    )
    return value


def main() -> None:
    arguments = parser().parse_args()
    try:
        result = build_plugin_launcher(
            runtime_root=arguments.runtime_root.resolve(),
            runtime_trust_policy=arguments.runtime_trust_policy.resolve(),
            plugin_install_trust_policy=(
                arguments.plugin_install_trust_policy.resolve()
                if arguments.plugin_install_trust_policy is not None
                else None
            ),
            output=arguments.output.resolve(),
            cargo_manifest=arguments.cargo_manifest.resolve(),
        )
    except PluginLauncherBuildError as error:
        raise SystemExit(f"{error.code}: {error}") from error
    print(result_json(result))


if __name__ == "__main__":
    main()
