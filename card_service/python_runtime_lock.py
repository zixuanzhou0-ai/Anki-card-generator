from __future__ import annotations

import hashlib
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

from .runtime_manifest import RuntimeManifestError, assert_stable_path, file_sha256


MAX_WHEEL_METADATA_BYTES = 1024 * 1024
MAX_WHEEL_DESCRIPTOR_BYTES = 256 * 1024
MAX_REQUIREMENTS_LOCK_BYTES = 1024 * 1024
MAX_WHEEL_COUNT = 1024
_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[A-Za-z0-9._,-]+\])?"
    r"==(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)$"
)
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,127}$")
_WHEEL_TAG_RE = re.compile(r"^[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+$")
_LOCK_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[A-Za-z0-9._,-]+\])?"
    r"==(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)"
    r" --hash=sha256:(?P<sha256>[0-9a-f]{64})$"
)


class PythonRuntimeLockError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RootRequirement:
    name: str
    normalized_name: str
    extras: tuple[str, ...]
    version: str

    def lock_name(self) -> str:
        extras = f"[{','.join(self.extras)}]" if self.extras else ""
        return f"{self.name}{extras}"


@dataclass(frozen=True)
class LockedWheel:
    name: str
    normalized_name: str
    version: str
    filename: str
    size: int
    sha256: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class LockedRequirement:
    normalized_name: str
    version: str
    sha256: str


def normalize_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def parse_root_requirements(path: Path) -> dict[str, RootRequirement]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PythonRuntimeLockError("PYTHON_LOCK_REQUIREMENTS_INVALID", "Requirements file is unavailable") from error
    roots: dict[str, RootRequirement] = {}
    for line_number, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _REQUIREMENT_RE.fullmatch(line)
        if match is None:
            raise PythonRuntimeLockError(
                "PYTHON_LOCK_REQUIREMENTS_INVALID",
                f"Requirement line {line_number} must use an exact version without markers",
            )
        name = match.group("name")
        normalized = normalize_package_name(name)
        extras_source = match.group("extras")
        extras = (
            tuple(sorted(set(extras_source[1:-1].split(",")), key=lambda item: item.encode("utf-8")))
            if extras_source
            else ()
        )
        if normalized in roots:
            raise PythonRuntimeLockError("PYTHON_LOCK_REQUIREMENTS_INVALID", "Root requirement is duplicated")
        roots[normalized] = RootRequirement(
            name=name,
            normalized_name=normalized,
            extras=extras,
            version=match.group("version"),
        )
    if not roots:
        raise PythonRuntimeLockError("PYTHON_LOCK_REQUIREMENTS_INVALID", "Requirements file is empty")
    return roots


def _read_zip_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    maximum_bytes: int,
    *,
    label: str,
) -> bytes:
    if info.file_size <= 0 or info.file_size > maximum_bytes:
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEEL_INVALID", f"Wheel {label} is empty or too large")
    with archive.open(info, "r") as handle:
        source = handle.read(maximum_bytes + 1)
    if not source or len(source) > maximum_bytes:
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEEL_INVALID", f"Wheel {label} is empty or too large")
    return source


def inspect_wheel(path: Path) -> LockedWheel:
    if not path.is_absolute() or path.suffix.lower() != ".whl":
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEEL_INVALID", "Wheel path is invalid")
    try:
        path = assert_stable_path(path)
    except (OSError, RuntimeManifestError) as error:
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEEL_INVALID", "Wheel path is unsafe") from error
    try:
        with zipfile.ZipFile(path) as archive:
            metadata = [
                info
                for info in archive.infolist()
                if info.filename.endswith(".dist-info/METADATA") and not info.is_dir()
            ]
            descriptors = [
                info
                for info in archive.infolist()
                if info.filename.endswith(".dist-info/WHEEL") and not info.is_dir()
            ]
            if len(metadata) != 1 or len(descriptors) != 1:
                raise PythonRuntimeLockError(
                    "PYTHON_LOCK_WHEEL_INVALID",
                    "Wheel must contain one METADATA and one WHEEL descriptor",
                )
            metadata_source = _read_zip_member(
                archive,
                metadata[0],
                MAX_WHEEL_METADATA_BYTES,
                label="METADATA",
            )
            wheel_source = _read_zip_member(
                archive,
                descriptors[0],
                MAX_WHEEL_DESCRIPTOR_BYTES,
                label="descriptor",
            )
    except (OSError, zipfile.BadZipFile) as error:
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEEL_INVALID", "Wheel archive is invalid") from error
    message = BytesParser(policy=default).parsebytes(metadata_source)
    name = message.get("Name")
    version = message.get("Version")
    if (
        not isinstance(name, str)
        or _PACKAGE_NAME_RE.fullmatch(name) is None
        or not isinstance(version, str)
        or _VERSION_RE.fullmatch(version) is None
    ):
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEEL_INVALID", "Wheel package identity is invalid")
    wheel_message = BytesParser(policy=default).parsebytes(wheel_source)
    tags = tuple(
        sorted(
            set(wheel_message.get_all("Tag", [])),
            key=lambda item: item.encode("utf-8"),
        )
    )
    if not tags or any(_WHEEL_TAG_RE.fullmatch(tag) is None for tag in tags):
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEEL_INVALID", "Wheel compatibility tags are invalid")
    return LockedWheel(
        name=name,
        normalized_name=normalize_package_name(name),
        version=version,
        filename=path.name,
        size=path.stat().st_size,
        sha256=file_sha256(path),
        tags=tags,
    )


def collect_wheels(wheelhouse: Path) -> dict[str, LockedWheel]:
    if not wheelhouse.is_absolute() or not wheelhouse.is_dir():
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEELHOUSE_INVALID", "Wheelhouse is unavailable")
    try:
        resolved = wheelhouse.resolve(strict=True)
        current = Path(resolved.anchor)
        for part in resolved.parts[1:]:
            current /= part
            attributes = getattr(current.stat(follow_symlinks=False), "st_file_attributes", 0)
            if current.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise PythonRuntimeLockError(
                    "PYTHON_LOCK_WHEELHOUSE_INVALID",
                    "Wheelhouse contains a reparse point",
                )
    except OSError as error:
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEELHOUSE_INVALID", "Wheelhouse is unavailable") from error
    children = sorted(resolved.iterdir(), key=lambda item: item.name.encode("utf-8"))
    unexpected = [path.name for path in children if not path.is_file() or path.suffix.lower() != ".whl"]
    if unexpected:
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEELHOUSE_INVALID", "Wheelhouse contains non-wheel entries")
    if not children or len(children) > MAX_WHEEL_COUNT:
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEELHOUSE_INVALID", "Wheelhouse has an invalid wheel count")
    wheels: dict[str, LockedWheel] = {}
    for path in children:
        wheel = inspect_wheel(path.resolve())
        if wheel.normalized_name in wheels:
            raise PythonRuntimeLockError("PYTHON_LOCK_WHEEL_DUPLICATE", "Wheelhouse contains duplicate packages")
        wheels[wheel.normalized_name] = wheel
    return wheels


def parse_requirements_lock(path: Path) -> dict[str, LockedRequirement]:
    try:
        stable = assert_stable_path(path)
        if stable.stat().st_size > MAX_REQUIREMENTS_LOCK_BYTES:
            raise PythonRuntimeLockError("PYTHON_LOCK_INVALID", "Python runtime lock is too large")
        with stable.open("rb") as handle:
            source_bytes = handle.read(MAX_REQUIREMENTS_LOCK_BYTES + 1)
        if not source_bytes or len(source_bytes) > MAX_REQUIREMENTS_LOCK_BYTES:
            raise PythonRuntimeLockError("PYTHON_LOCK_INVALID", "Python runtime lock is empty or too large")
        source = source_bytes.decode("utf-8")
    except PythonRuntimeLockError:
        raise
    except (OSError, RuntimeManifestError, UnicodeDecodeError) as error:
        raise PythonRuntimeLockError("PYTHON_LOCK_INVALID", "Python runtime lock is unavailable") from error
    lines = source.splitlines()
    if len(lines) < 4 or lines[:1] != [
        "# Generated by scripts/generate_python_runtime_lock.py; do not edit by hand."
    ]:
        raise PythonRuntimeLockError("PYTHON_LOCK_INVALID", "Python runtime lock header is invalid")
    locked: dict[str, LockedRequirement] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE_RE.fullmatch(line)
        if match is None:
            raise PythonRuntimeLockError("PYTHON_LOCK_INVALID", "Python runtime lock line is invalid")
        normalized = normalize_package_name(match.group("name"))
        if normalized in locked:
            raise PythonRuntimeLockError("PYTHON_LOCK_INVALID", "Python runtime lock contains duplicate packages")
        locked[normalized] = LockedRequirement(
            normalized_name=normalized,
            version=match.group("version"),
            sha256=match.group("sha256"),
        )
    if not locked:
        raise PythonRuntimeLockError("PYTHON_LOCK_INVALID", "Python runtime lock is empty")
    return locked


def verify_wheelhouse_against_lock(lock_path: Path, wheelhouse: Path) -> dict[str, LockedWheel]:
    locked = parse_requirements_lock(lock_path)
    wheels = collect_wheels(wheelhouse)
    if set(locked) != set(wheels):
        raise PythonRuntimeLockError("PYTHON_LOCK_WHEELHOUSE_MISMATCH", "Wheelhouse package set does not match lock")
    for normalized, requirement in locked.items():
        wheel = wheels[normalized]
        if wheel.version != requirement.version or wheel.sha256 != requirement.sha256:
            raise PythonRuntimeLockError(
                "PYTHON_LOCK_WHEELHOUSE_MISMATCH",
                "Wheelhouse version or digest does not match lock",
            )
    return wheels


def generate_requirements_lock(
    requirements_path: Path,
    wheelhouse: Path,
    *,
    python_version: str,
    abi: str,
    platform_tag: str,
) -> str:
    if (
        re.fullmatch(r"[0-9]+\.[0-9]+", python_version) is None
        or re.fullmatch(r"[A-Za-z0-9_]+", abi) is None
        or re.fullmatch(r"[A-Za-z0-9_]+", platform_tag) is None
    ):
        raise PythonRuntimeLockError("PYTHON_LOCK_TARGET_INVALID", "Python runtime target is invalid")
    roots = parse_root_requirements(requirements_path)
    wheels = collect_wheels(wheelhouse)
    for normalized, root in roots.items():
        wheel = wheels.get(normalized)
        if wheel is None or wheel.version != root.version:
            raise PythonRuntimeLockError(
                "PYTHON_LOCK_ROOT_MISMATCH",
                "Wheelhouse does not satisfy an exact root requirement",
            )
    lines = [
        "# Generated by scripts/generate_python_runtime_lock.py; do not edit by hand.",
        f"# target: CPython {python_version} / {abi} / {platform_tag}",
        "# Every direct and transitive wheel is exact and SHA-256 pinned.",
    ]
    for normalized in sorted(wheels, key=lambda item: item.encode("utf-8")):
        wheel = wheels[normalized]
        root = roots.get(normalized)
        locked_name = root.lock_name() if root is not None else wheel.name
        lines.append(f"{locked_name}=={wheel.version} --hash=sha256:{wheel.sha256}")
    return "\n".join(lines) + "\n"


def write_lock_atomic(path: Path, source: str) -> None:
    if not path.is_absolute():
        raise PythonRuntimeLockError("PYTHON_LOCK_OUTPUT_INVALID", "Lock output path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(source.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise PythonRuntimeLockError("PYTHON_LOCK_OUTPUT_INVALID", "Lock output could not be written") from error
