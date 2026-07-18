from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .runtime_manifest import RuntimeManifestError, assert_stable_path, file_sha256
from .runtime_package import ManagedRuntimePackage, RuntimePackageError
from .runtime_trust import RuntimePackageTrustPolicy, RuntimeTrustError


MAX_LAUNCHER_BYTES = 64 * 1024 * 1024
LAUNCHER_BINARY_NAME = "anki-study-launcher.exe" if os.name == "nt" else "anki-study-launcher"


class PluginLauncherBuildError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PluginLauncherBuildResult:
    path: Path
    sha256: str
    size: int
    runtime_manifest_sha256: str
    runtime_trust_policy_sha256: str


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _stable_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise PluginLauncherBuildError("PLUGIN_LAUNCHER_PATH_INVALID", f"{label} must be absolute")
    try:
        resolved = path.resolve(strict=True)
        current = Path(resolved.anchor)
        for part in resolved.parts[1:]:
            current /= part
            if current.is_symlink() or _has_reparse_attribute(current):
                raise PluginLauncherBuildError(
                    "PLUGIN_LAUNCHER_PATH_INVALID",
                    f"{label} contains a reparse point",
                )
    except OSError as error:
        raise PluginLauncherBuildError(
            "PLUGIN_LAUNCHER_PATH_INVALID",
            f"{label} is unavailable",
        ) from error
    if not resolved.is_dir():
        raise PluginLauncherBuildError("PLUGIN_LAUNCHER_PATH_INVALID", f"{label} is not a directory")
    return resolved


def _publish_without_overwrite(staging: Path, output: Path) -> None:
    try:
        os.link(staging, output)
    except OSError as error:
        if os.path.lexists(output):
            raise PluginLauncherBuildError(
                "PLUGIN_LAUNCHER_OUTPUT_EXISTS",
                "Launcher output already exists",
            ) from error
        raise PluginLauncherBuildError(
            "PLUGIN_LAUNCHER_BUILD_FAILED",
            "Launcher could not be published atomically",
        ) from error


def build_plugin_launcher(
    *,
    runtime_root: Path,
    runtime_trust_policy: Path,
    output: Path,
    cargo_manifest: Path,
    runner: Runner = subprocess.run,
) -> PluginLauncherBuildResult:
    output_parent = _stable_directory(output.parent, "Launcher output parent")
    if output.exists():
        raise PluginLauncherBuildError("PLUGIN_LAUNCHER_OUTPUT_EXISTS", "Launcher output already exists")
    try:
        trust_path = assert_stable_path(runtime_trust_policy)
        policy = RuntimePackageTrustPolicy.load(trust_path)
        package = ManagedRuntimePackage(
            runtime_root,
            trust_policy=policy,
            require_signature=True,
        )
        manifest_path = assert_stable_path(cargo_manifest)
    except (OSError, RuntimeManifestError, RuntimePackageError, RuntimeTrustError) as error:
        raise PluginLauncherBuildError(
            "PLUGIN_LAUNCHER_INPUT_INVALID",
            "Signed runtime, trust policy, or launcher source is invalid",
        ) from error
    if manifest_path.name != "Cargo.toml":
        raise PluginLauncherBuildError(
            "PLUGIN_LAUNCHER_INPUT_INVALID",
            "Launcher Cargo manifest is invalid",
        )

    manifest_digest = package.digest
    trust_digest = file_sha256(trust_path)
    environment = {
        **os.environ,
        "ANKI_STUDY_RUNTIME_MANIFEST_SHA256": manifest_digest,
        "ANKI_STUDY_RUNTIME_TRUST_POLICY_SHA256": trust_digest,
        "CARGO_INCREMENTAL": "0",
        "CARGO_NET_OFFLINE": "true",
        "SOURCE_DATE_EPOCH": "0",
    }
    if os.name == "nt":
        environment["RUSTFLAGS"] = "-C link-arg=/Brepro"
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.build-", dir=output_parent) as temporary:
        temporary_root = Path(temporary)
        target = temporary_root / "target"
        command: Sequence[str] = (
            "cargo",
            "build",
            "--manifest-path",
            str(manifest_path),
            "--release",
            "--locked",
            "--offline",
            "--target-dir",
            str(target),
        )
        try:
            process = runner(
                command,
                cwd=manifest_path.parent,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise PluginLauncherBuildError(
                "PLUGIN_LAUNCHER_BUILD_FAILED",
                "Launcher compiler could not run",
            ) from error
        if process.returncode != 0:
            diagnostic = "\n".join(process.stderr.splitlines()[-12:])[:2000]
            raise PluginLauncherBuildError(
                "PLUGIN_LAUNCHER_BUILD_FAILED",
                f"Launcher compilation failed: {diagnostic}",
            )
        binary = target / "release" / LAUNCHER_BINARY_NAME
        try:
            binary = assert_stable_path(binary)
        except (OSError, RuntimeManifestError) as error:
            raise PluginLauncherBuildError(
                "PLUGIN_LAUNCHER_BUILD_FAILED",
                "Launcher compiler did not produce the expected binary",
            ) from error
        size = binary.stat().st_size
        if size <= 0 or size > MAX_LAUNCHER_BYTES:
            raise PluginLauncherBuildError(
                "PLUGIN_LAUNCHER_BUILD_FAILED",
                "Launcher binary size is invalid",
            )
        staging = temporary_root / output.name
        shutil.copyfile(binary, staging)
        if file_sha256(staging) != file_sha256(binary):
            raise PluginLauncherBuildError(
                "PLUGIN_LAUNCHER_BUILD_FAILED",
                "Launcher copy digest mismatch",
            )
        _publish_without_overwrite(staging, output)

    return PluginLauncherBuildResult(
        path=output,
        sha256=file_sha256(output),
        size=output.stat().st_size,
        runtime_manifest_sha256=manifest_digest,
        runtime_trust_policy_sha256=trust_digest,
    )


def result_json(result: PluginLauncherBuildResult) -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "output": str(result.path),
            "sha256": result.sha256,
            "size": result.size,
            "runtimeManifestSha256": result.runtime_manifest_sha256,
            "runtimeTrustPolicySha256": result.runtime_trust_policy_sha256,
            "privateKeyRead": False,
            "networkUsed": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
