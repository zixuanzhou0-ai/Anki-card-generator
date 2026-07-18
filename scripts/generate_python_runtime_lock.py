from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.python_runtime_lock import (
    PythonRuntimeLockError,
    generate_requirements_lock,
    write_lock_atomic,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Generate or verify the hashed Windows CPython runtime requirements lock.",
    )
    value.add_argument("--requirements", type=Path, required=True)
    value.add_argument("--wheelhouse", type=Path, required=True)
    value.add_argument("--output", type=Path)
    value.add_argument("--check", type=Path)
    value.add_argument("--python-version", default="3.13")
    value.add_argument("--abi", default="cp313")
    value.add_argument("--platform", default="win_amd64")
    return value


def main() -> None:
    arguments = parser().parse_args()
    if (arguments.output is None) == (arguments.check is None):
        raise SystemExit("Exactly one of --output or --check is required")
    try:
        source = generate_requirements_lock(
            arguments.requirements.resolve(),
            arguments.wheelhouse.resolve(),
            python_version=arguments.python_version,
            abi=arguments.abi,
            platform_tag=arguments.platform,
        )
        if arguments.output is not None:
            write_lock_atomic(arguments.output.resolve(), source)
            print(f"wrote {arguments.output.resolve()}")
            return
        assert arguments.check is not None
        try:
            current = arguments.check.resolve().read_text(encoding="utf-8")
        except OSError as error:
            raise PythonRuntimeLockError("PYTHON_LOCK_CHECK_FAILED", "Lock file is unavailable") from error
        if current != source:
            raise PythonRuntimeLockError("PYTHON_LOCK_CHECK_FAILED", "Lock file does not match wheelhouse")
        print(f"verified {arguments.check.resolve()}")
    except PythonRuntimeLockError as error:
        raise SystemExit(f"{error.code}: {error}") from error


if __name__ == "__main__":
    main()
