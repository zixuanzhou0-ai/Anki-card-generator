from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.windows_authenticode import (
    AuthenticodeError,
    AuthenticodePolicy,
    verify_authenticode,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Verify a Windows launcher Authenticode signature against an external publisher policy.",
    )
    value.add_argument("--launcher", type=Path, required=True)
    value.add_argument("--policy", type=Path, required=True)
    return value


def main() -> None:
    arguments = parser().parse_args()
    try:
        policy = AuthenticodePolicy.load(arguments.policy.resolve())
        verified = verify_authenticode(arguments.launcher.resolve(), policy=policy)
    except AuthenticodeError as error:
        raise SystemExit(f"{error.code}: {error}") from error
    print(
        json.dumps(
            verified.public_summary(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
