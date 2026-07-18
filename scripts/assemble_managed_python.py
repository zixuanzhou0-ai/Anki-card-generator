from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.python_runtime_assembler import (
    PythonRuntimeAssemblyError,
    assemble_python_runtime,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Assemble an offline, movable Windows CPython runtime from a hashed wheelhouse.",
    )
    value.add_argument("--source-python-root", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--lock", type=Path, required=True)
    value.add_argument("--wheelhouse", type=Path, required=True)
    value.add_argument("--expected-version", required=True)
    value.add_argument("--expected-architecture", default="amd64")
    return value


def main() -> None:
    arguments = parser().parse_args()
    try:
        result = assemble_python_runtime(
            arguments.source_python_root.resolve(),
            arguments.output.resolve(),
            lock_path=arguments.lock.resolve(),
            wheelhouse=arguments.wheelhouse.resolve(),
            expected_version=arguments.expected_version,
            expected_architecture=arguments.expected_architecture,
        )
    except PythonRuntimeAssemblyError as error:
        raise SystemExit(f"{error.code}: {error}") from error
    print(
        json.dumps(
            {
                "schemaVersion": 1,
                "output": str(result.root),
                "implementation": result.identity.implementation,
                "pythonVersion": result.identity.version,
                "architecture": result.identity.architecture,
                "requirementsLockSha256": result.lock_sha256,
                "wheelCount": result.wheel_count,
                "coreFileCount": result.core_file_count,
                "totalBytes": result.total_bytes,
                "networkUsedDuringAssembly": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
