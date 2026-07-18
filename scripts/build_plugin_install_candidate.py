from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.plugin_install_bundle import (
    PluginInstallError,
    build_plugin_install_candidate,
    build_result_json,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Build a signed-launcher, MCP-wired plugin install signing candidate.",
    )
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--version", required=True)
    value.add_argument("--created-at", required=True)
    value.add_argument("--plugin-root", type=Path, default=ROOT / "plugins" / "anki-study-agent")
    value.add_argument("--launcher", type=Path, required=True)
    value.add_argument("--runtime-root", type=Path, required=True)
    value.add_argument("--runtime-trust-policy", type=Path, required=True)
    value.add_argument("--plugin-publisher-trust-policy", type=Path, required=True)
    value.add_argument("--launcher-authenticode-policy", type=Path, required=True)
    value.add_argument("--creator", default="Organization: Anki Study Agent")
    return value


def main() -> None:
    arguments = parser().parse_args()
    try:
        result = build_plugin_install_candidate(
            arguments.output.resolve(),
            version=arguments.version,
            created_at=arguments.created_at,
            plugin_root=arguments.plugin_root.resolve(),
            launcher=arguments.launcher.resolve(),
            runtime_root=arguments.runtime_root.resolve(),
            runtime_trust_policy=arguments.runtime_trust_policy.resolve(),
            plugin_publisher_trust_policy=arguments.plugin_publisher_trust_policy.resolve(),
            launcher_authenticode_policy=arguments.launcher_authenticode_policy.resolve(),
            creator=arguments.creator,
        )
    except PluginInstallError as error:
        raise SystemExit(f"{error.code}: {error}") from error
    print(build_result_json(result))


if __name__ == "__main__":
    main()
