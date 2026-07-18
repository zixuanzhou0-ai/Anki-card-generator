from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.runtime_builder import (
    RuntimeBuildError,
    RuntimeBuildResource,
    build_runtime_package,
)


def _tree_resources(
    source_root: Path,
    *,
    target_root: str,
    id_prefix: str,
    special_ids: dict[str, str],
    include,
) -> list[RuntimeBuildResource]:
    resources: list[RuntimeBuildResource] = []
    for source in sorted(source_root.rglob("*"), key=lambda value: value.as_posix().encode("utf-8")):
        if not source.is_file() or not include(source):
            continue
        relative = source.relative_to(source_root).as_posix()
        resource_id = special_ids.get(relative, f"{id_prefix}:{relative}")
        resources.append(
            RuntimeBuildResource(
                resource_id=resource_id,
                source=source.resolve(),
                relative_path=f"{target_root}/{relative}",
            )
        )
    return resources


def _repository_resources(root: Path) -> list[RuntimeBuildResource]:
    card_service_root = (root / "card_service").resolve()
    worker_root = (root / "workers").resolve()
    resources = _tree_resources(
        card_service_root,
        target_root="card_service",
        id_prefix="card-service:module",
        special_ids={
            "worker_bootstrap.py": "card-service:worker-bootstrap",
            "windows_restricted_launcher.py": "card-service:windows-restricted-launcher",
            "windows_sandbox_acl.py": "card-service:windows-sandbox-acl",
        },
        include=lambda path: path.suffix == ".py",
    )
    resources.extend(
        _tree_resources(
            worker_root,
            target_root="workers",
            id_prefix="legacy-worker:module",
            special_ids={
                "anki_worker.py": "legacy-worker:entry",
                "acg/broker_client.py": "card-service:broker-client",
                "acg/media_tool_policy.py": "legacy-worker:module:acg/media_tool_policy.py",
            },
            include=lambda path: path.suffix == ".py"
            or path.name == "worker-command-contract.v1.schema.json",
        )
    )
    return resources


def _python_resources(root: Path) -> list[RuntimeBuildResource]:
    resources = _tree_resources(
        root,
        target_root="python",
        id_prefix="managed-python:file",
        special_ids={"python.exe": "managed-python:executable"},
        include=lambda path: "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"},
    )
    if not any(resource.resource_id == "managed-python:executable" for resource in resources):
        raise RuntimeBuildError("RUNTIME_BUILD_RESOURCE_MISSING", "Managed Python root has no python.exe")
    return resources


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Build an unsigned, deterministic Anki Study managed runtime package.",
    )
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--version", required=True)
    value.add_argument("--created-at", required=True)
    value.add_argument("--repository-root", type=Path, required=True)
    value.add_argument("--python-root", type=Path, required=True)
    value.add_argument("--python-lock", type=Path, required=True)
    value.add_argument("--ffmpeg", type=Path, required=True)
    value.add_argument("--ffprobe", type=Path, required=True)
    value.add_argument("--yt-dlp", type=Path, required=True)
    return value


def main() -> None:
    arguments = parser().parse_args()
    try:
        resources = _repository_resources(arguments.repository_root.resolve())
        resources.extend(_python_resources(arguments.python_root.resolve()))
        resources.extend(
            [
                RuntimeBuildResource(
                    "metadata:python-runtime-lock",
                    arguments.python_lock.resolve(),
                    "metadata/python-runtime-requirements.lock",
                ),
                RuntimeBuildResource("managed-tool:ffmpeg", arguments.ffmpeg.resolve(), "tools/ffmpeg.exe"),
                RuntimeBuildResource("managed-tool:ffprobe", arguments.ffprobe.resolve(), "tools/ffprobe.exe"),
                RuntimeBuildResource("managed-tool:yt-dlp", arguments.yt_dlp.resolve(), "tools/yt-dlp.exe"),
            ]
        )
        result = build_runtime_package(
            arguments.output.resolve(),
            version=arguments.version,
            resources=resources,
            created_at=arguments.created_at,
        )
    except RuntimeBuildError as error:
        raise SystemExit(f"{error.code}: {error}") from error
    print(
        json.dumps(
            {
                "schemaVersion": 1,
                "output": str(result.root),
                "manifestSha256": result.manifest_sha256,
                "resourceCount": result.resource_count,
                "totalBytes": result.total_bytes,
                "signed": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
