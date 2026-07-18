from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .python_runtime_lock import (
    PythonRuntimeLockError,
    verify_wheelhouse_against_lock,
)
from .runtime_manifest import RuntimeManifestError, assert_stable_path, canonical_bytes, file_sha256


MAX_CORE_FILES = 50_000
MAX_CORE_BYTES = 4 * 1024 * 1024 * 1024
BUILD_METADATA_NAME = "python-runtime-build-v1.json"
_ROOT_EXCLUSIONS = frozenset(
    {
        "doc",
        "include",
        "libs",
        "scripts",
        "share",
        "__pycache__",
    }
)
_ROOT_FILE_EXCLUSIONS = frozenset(
    {
        "ffmpeg.exe",
        "ffplay.exe",
        "ffprobe.exe",
        "pyvenv.cfg",
    }
)
_LIB_EXCLUSIONS = frozenset(
    {
        "site-packages",
        "test",
        "tests",
        "idlelib",
        "ensurepip",
        "__pycache__",
    }
)


class PythonRuntimeAssemblyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PythonRuntimeIdentity:
    implementation: str
    version: str
    architecture: str


@dataclass(frozen=True)
class PythonRuntimeAssemblyResult:
    root: Path
    identity: PythonRuntimeIdentity
    lock_sha256: str
    wheel_count: int
    core_file_count: int
    total_bytes: int


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _stable_directory(path: Path, *, code: str, label: str) -> Path:
    if not path.is_absolute():
        raise PythonRuntimeAssemblyError(code, f"{label} must be absolute")
    try:
        resolved = path.resolve(strict=True)
        current = Path(resolved.anchor)
        for part in resolved.parts[1:]:
            current /= part
            if current.is_symlink() or _has_reparse_attribute(current):
                raise PythonRuntimeAssemblyError(code, f"{label} contains a reparse point")
    except OSError as error:
        raise PythonRuntimeAssemblyError(code, f"{label} is unavailable") from error
    if not resolved.is_dir():
        raise PythonRuntimeAssemblyError(code, f"{label} is not a directory")
    return resolved


def _default_probe(executable: Path) -> PythonRuntimeIdentity:
    program = (
        "import json,platform,sys;"
        "print(json.dumps({'implementation':sys.implementation.name,"
        "'version':platform.python_version(),'architecture':platform.machine()}))"
    )
    try:
        process = subprocess.run(
            [str(executable), "-I", "-B", "-c", program],
            cwd=str(executable.parent),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        value = json.loads(process.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise PythonRuntimeAssemblyError("PYTHON_RUNTIME_PROBE_FAILED", "Python runtime probe failed") from error
    if (
        process.returncode != 0
        or not isinstance(value, dict)
        or value.get("implementation") != "cpython"
        or not isinstance(value.get("version"), str)
        or not isinstance(value.get("architecture"), str)
    ):
        raise PythonRuntimeAssemblyError("PYTHON_RUNTIME_PROBE_FAILED", "Python runtime identity is invalid")
    return PythonRuntimeIdentity(
        implementation=str(value["implementation"]),
        version=str(value["version"]),
        architecture=str(value["architecture"]).lower(),
    )


def _default_install(
    source_python: Path,
    target_root: Path,
    lock_path: Path,
    wheelhouse: Path,
) -> None:
    site_packages = target_root / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    command = [
        str(source_python),
        "-I",
        "-m",
        "pip",
        "install",
        "--no-index",
        "--require-hashes",
        "--only-binary=:all:",
        "--no-compile",
        "--no-warn-script-location",
        "--find-links",
        str(wheelhouse),
        "--target",
        str(site_packages),
        "--requirement",
        str(lock_path),
    ]
    try:
        process = subprocess.run(
            command,
            cwd=str(target_root),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PythonRuntimeAssemblyError("PYTHON_RUNTIME_INSTALL_FAILED", "Offline wheel install failed") from error
    if process.returncode != 0:
        diagnostic = "\n".join(process.stderr.splitlines()[-8:])
        raise PythonRuntimeAssemblyError(
            "PYTHON_RUNTIME_INSTALL_FAILED",
            f"Offline wheel install failed: {diagnostic[:1000]}",
        )


def _include_core_file(source_root: Path, path: Path) -> bool:
    relative = path.relative_to(source_root)
    parts = relative.parts
    if not parts:
        return False
    if parts[0].casefold() in _ROOT_EXCLUSIONS:
        return False
    if len(parts) == 1 and parts[0].casefold() in _ROOT_FILE_EXCLUSIONS:
        return False
    if parts[0].casefold() == "lib" and len(parts) > 1 and parts[1].casefold() in _LIB_EXCLUSIONS:
        return False
    return path.suffix.casefold() not in {".pyc", ".pyo"}


def _copy_core(source_root: Path, target_root: Path) -> tuple[int, int]:
    count = 0
    total_bytes = 0
    for source in sorted(source_root.rglob("*"), key=lambda item: item.as_posix().encode("utf-8")):
        if not source.is_file() or not _include_core_file(source_root, source):
            continue
        try:
            stable = assert_stable_path(source)
        except (OSError, RuntimeManifestError) as error:
            raise PythonRuntimeAssemblyError("PYTHON_RUNTIME_SOURCE_INVALID", "Python core file is unsafe") from error
        relative = stable.relative_to(source_root)
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(stable, target)
        if file_sha256(stable) != file_sha256(target):
            raise PythonRuntimeAssemblyError("PYTHON_RUNTIME_COPY_MISMATCH", "Python core copy digest mismatch")
        count += 1
        total_bytes += target.stat().st_size
        if count > MAX_CORE_FILES or total_bytes > MAX_CORE_BYTES:
            raise PythonRuntimeAssemblyError("PYTHON_RUNTIME_TOO_LARGE", "Python core exceeds build limits")
    if not (target_root / "python.exe").is_file() or not (target_root / "Lib").is_dir():
        raise PythonRuntimeAssemblyError("PYTHON_RUNTIME_SOURCE_INVALID", "Python core is incomplete")
    return count, total_bytes


def _reject_generated_bytecode(root: Path) -> None:
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if "__pycache__" in {part.casefold() for part in relative.parts} or path.suffix.casefold() in {
            ".pyc",
            ".pyo",
        }:
            raise PythonRuntimeAssemblyError(
                "PYTHON_RUNTIME_BYTECODE_PRESENT",
                "Portable Python contains generated bytecode",
            )


def assemble_python_runtime(
    source_root: Path,
    output_root: Path,
    *,
    lock_path: Path,
    wheelhouse: Path,
    expected_version: str,
    expected_architecture: str = "amd64",
    probe: Callable[[Path], PythonRuntimeIdentity] = _default_probe,
    installer: Callable[[Path, Path, Path, Path], None] = _default_install,
) -> PythonRuntimeAssemblyResult:
    source_root = _stable_directory(
        source_root,
        code="PYTHON_RUNTIME_SOURCE_INVALID",
        label="Python source root",
    )
    output_parent = _stable_directory(
        output_root.parent,
        code="PYTHON_RUNTIME_OUTPUT_INVALID",
        label="Python output parent",
    )
    if output_root.exists():
        raise PythonRuntimeAssemblyError("PYTHON_RUNTIME_OUTPUT_EXISTS", "Python output already exists")
    source_python = source_root / "python.exe"
    try:
        source_python = assert_stable_path(source_python)
    except (OSError, RuntimeManifestError) as error:
        raise PythonRuntimeAssemblyError("PYTHON_RUNTIME_SOURCE_INVALID", "Python executable is unsafe") from error
    before = probe(source_python)
    if (
        before.implementation != "cpython"
        or before.version != expected_version
        or before.architecture not in {expected_architecture.lower(), "x86_64"}
    ):
        raise PythonRuntimeAssemblyError("PYTHON_RUNTIME_IDENTITY_MISMATCH", "Python source identity is unexpected")
    try:
        wheels = verify_wheelhouse_against_lock(lock_path.resolve(), wheelhouse.resolve())
    except PythonRuntimeLockError as error:
        raise PythonRuntimeAssemblyError(error.code, str(error)) from error

    with tempfile.TemporaryDirectory(prefix=f".{output_root.name}.build-", dir=output_parent) as temporary:
        staging = Path(temporary) / "python"
        staging.mkdir()
        core_count, _ = _copy_core(source_root, staging)
        installer(source_python, staging, lock_path.resolve(), wheelhouse.resolve())
        after = probe((staging / "python.exe").resolve())
        if after != before:
            raise PythonRuntimeAssemblyError(
                "PYTHON_RUNTIME_IDENTITY_MISMATCH",
                "Assembled Python identity differs from its source",
            )
        _reject_generated_bytecode(staging)
        metadata = {
            "schemaVersion": 1,
            "implementation": after.implementation,
            "pythonVersion": after.version,
            "architecture": after.architecture,
            "requirementsLockSha256": file_sha256(lock_path.resolve()),
            "wheelCount": len(wheels),
            "coreFileCount": core_count,
            "networkUsedDuringAssembly": False,
        }
        (staging / BUILD_METADATA_NAME).write_bytes(canonical_bytes(metadata))
        total_bytes = sum(
            path.stat().st_size
            for path in staging.rglob("*")
            if path.is_file()
        )
        os.replace(staging, output_root)

    return PythonRuntimeAssemblyResult(
        root=output_root,
        identity=after,
        lock_sha256=str(metadata["requirementsLockSha256"]),
        wheel_count=len(wheels),
        core_file_count=core_count,
        total_bytes=total_bytes,
    )
