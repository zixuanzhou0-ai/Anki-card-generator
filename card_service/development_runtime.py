from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import secrets
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from .runtime_builder import RuntimeBuildError, _copy_verified
from .runtime_manifest import (
    RuntimeManifestError,
    assert_stable_path,
    canonical_bytes,
    file_sha256,
)
from .windows_sandbox_acl import (
    DaclEntry,
    OBJECT_INHERIT_ACE,
    CONTAINER_INHERIT_ACE,
    SE_DACL_PROTECTED,
    TRUSTED_INSTALLER_SID,
    WindowsSandboxAclError,
    apply_exact_dacl,
    read_dacl,
    read_security_descriptor_identity,
    service_root_grants,
)


APP_FOLDER = ".anki-study-agent"
RUNTIME_FOLDER = "codex-dev-runtime"
PLUGIN_FOLDER = "codex-dev-plugin"
STATE_FOLDER = "codex-card-service-dev"
MANIFEST_NAME = "dev-runtime-manifest-v1.json"
PLUGIN_SNAPSHOT_MANIFEST_NAME = "dev-plugin-manifest-v1.json"
INSTALL_IDENTITY_NAME = "install-identity-v1.txt"
LAUNCHER_NAME = "launcher.py"
ALLOWED_TOOL_NAMES = ("ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe")
MAX_MANIFEST_BYTES = 512 * 1024
MAX_RUNTIME_FILES = 10_000
MAX_RUNTIME_BYTES = 2 * 1024 * 1024 * 1024
MAX_TOOL_BYTES = 512 * 1024 * 1024
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_TRUSTED_SYSTEM_SIDS = frozenset({"S-1-5-18", "S-1-5-32-544", TRUSTED_INSTALLER_SID})
_MUTATION_MASK = (
    0x00000002
    | 0x00000004
    | 0x00000010
    | 0x00000040
    | 0x00000100
    | 0x00010000
    | 0x00040000
    | 0x00080000
    | 0x10000000
    | 0x40000000
)
_ANCESTOR_REPLACE_MASK = 0x00000040 | 0x00010000 | 0x00040000 | 0x00080000 | 0x10000000


class DevelopmentRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DevelopmentRuntimeSnapshot:
    root: Path
    launcher: Path
    state_root: Path
    manifest_sha256: str
    resource_count: int
    tools: tuple[str, ...]
    missing_tools: tuple[str, ...]


@dataclass(frozen=True)
class DevelopmentPluginSnapshot:
    root: Path
    plugin_root: Path
    manifest_sha256: str
    resource_count: int
    version: str


def _stable_directory(path: Path) -> Path:
    try:
        stable = _assert_stable_entry(path)
    except OSError as error:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_PATH_UNSAFE",
            "Development runtime path is unavailable or unsafe",
        ) from error
    if not stable.is_dir():
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_PATH_INVALID", "Development runtime path must be a directory"
        )
    return stable


def _assert_stable_entry(path: Path) -> Path:
    if not path.is_absolute():
        raise OSError("Development runtime path must be absolute")
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for part in absolute.parts[1:]:
        current /= part
        attributes = getattr(
            current.stat(follow_symlinks=False), "st_file_attributes", 0
        )
        if current.is_symlink() or attributes & reparse_flag:
            raise OSError("Development runtime path contains a reparse point")
    return absolute.resolve(strict=True)


def _relative_path(value: str) -> PurePosixPath:
    if not value or "\\" in value or ":" in value:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_MANIFEST_INVALID", "Runtime path is invalid"
        )
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_MANIFEST_INVALID", "Runtime path is invalid"
        )
    for part in relative.parts:
        stem = part.rstrip(" .").split(".", 1)[0].upper()
        if part != part.rstrip(" .") or stem in _WINDOWS_RESERVED:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_MANIFEST_INVALID", "Runtime path is invalid"
            )
    return relative


def _runtime_sources(
    repository_root: Path, launcher_source: Path
) -> list[tuple[Path, str, str]]:
    resources: list[tuple[Path, str, str]] = [
        (launcher_source, LAUNCHER_NAME, "development-launcher")
    ]
    for source_root, target_root in (
        (repository_root / "card_service", "card_service"),
        (repository_root / "workers", "workers"),
    ):
        if not source_root.is_dir():
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_SOURCE_INCOMPLETE",
                "Card Service runtime sources are incomplete",
            )
        for source in sorted(
            source_root.rglob("*"), key=lambda item: item.as_posix().encode("utf-8")
        ):
            include = source.is_file() and (
                source.suffix == ".py"
                or (
                    target_root == "workers"
                    and source.name == "worker-command-contract.v1.schema.json"
                )
            )
            if include:
                relative = source.relative_to(source_root).as_posix()
                if target_root == "card_service":
                    role = "card-service-module"
                elif source.name == "anki_worker.py":
                    role = "worker-entry"
                elif source.name == "worker-command-contract.v1.schema.json":
                    role = "worker-protocol-schema"
                else:
                    role = "worker-module"
                resources.append((source, f"{target_root}/{relative}", role))
    return resources


def _plugin_sources(repository_root: Path) -> tuple[list[tuple[Path, str, str]], str]:
    marketplace = repository_root / ".agents" / "plugins" / "marketplace.json"
    plugin_root = repository_root / "plugins" / "anki-study-agent"
    plugin_manifest = plugin_root / ".codex-plugin" / "plugin.json"
    if not marketplace.is_file() or not plugin_manifest.is_file():
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_SOURCE_INCOMPLETE",
            "Codex plugin or marketplace sources are incomplete",
        )
    try:
        marketplace_value = json.loads(marketplace.read_text(encoding="utf-8"))
        plugin_value = json.loads(plugin_manifest.read_text(encoding="utf-8"))
        plugins = marketplace_value["plugins"]
        source = plugins[0]["source"]
        version = plugin_value["version"]
    except (
        OSError,
        KeyError,
        IndexError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_SOURCE_INVALID",
            "Codex plugin or marketplace source metadata is invalid",
        ) from error
    if (
        marketplace_value.get("name") != "anki-study-agent-local"
        or not isinstance(plugins, list)
        or len(plugins) != 1
        or plugins[0].get("name") != "anki-study-agent"
        or source != {"source": "local", "path": "./plugins/anki-study-agent"}
        or plugin_value.get("name") != "anki-study-agent"
        or not isinstance(version, str)
        or not version.strip()
        or "mcpServers" in plugin_value
        or "apps" in plugin_value
        or (plugin_root / ".mcp.json").exists()
        or (plugin_root / ".app.json").exists()
    ):
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_SOURCE_INVALID",
            "Codex development plugin must remain a passive local plugin",
        )
    resources = [
        (marketplace, ".agents/plugins/marketplace.json", "marketplace-manifest")
    ]
    for source_path in sorted(
        plugin_root.rglob("*"), key=lambda item: item.as_posix().encode("utf-8")
    ):
        if source_path.is_file():
            relative = source_path.relative_to(plugin_root).as_posix()
            resources.append(
                (
                    source_path,
                    f"plugins/anki-study-agent/{relative}",
                    "plugin-resource",
                )
            )
    if not any(relative.endswith("/SKILL.md") for _, relative, _ in resources):
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_SOURCE_INCOMPLETE", "Codex development plugin skill is missing"
        )
    return resources, version


def _secure_directory(path: Path) -> Path:
    path.mkdir(parents=False, exist_ok=True)
    try:
        stable = _stable_directory(path)
        apply_exact_dacl(stable, service_root_grants(), inherit_to_children=True)
    except WindowsSandboxAclError as error:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_ACL_FAILED",
            "Development runtime private directory could not be secured",
        ) from error
    return stable


def _trusted_owner(owner_sid: str, current_sid: str) -> bool:
    return owner_sid == current_sid or owner_sid in _TRUSTED_SYSTEM_SIDS


def _verify_untrusted_mutation_blocked(
    path: Path,
    *,
    current_sid: str,
    dangerous_mask: int,
    require_protected: bool,
) -> None:
    descriptor = read_security_descriptor_identity(path)
    if not _trusted_owner(descriptor.owner_sid, current_sid) or (
        require_protected and descriptor.control & SE_DACL_PROTECTED == 0
    ):
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_PARENT_ACL_FAILED",
            "Development runtime trust path has an untrusted owner or inheritable DACL",
        )
    trusted_sids = {current_sid, *_TRUSTED_SYSTEM_SIDS}
    if any(
        entry.sid not in trusted_sids and entry.access_mask & dangerous_mask
        for entry in read_dacl(path, skip_inherit_only=True)
    ):
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_PARENT_WRITABLE",
            "Development runtime trust path is mutable by another principal",
        )


def _verify_ancestor_replace_safety(path: Path, *, current_sid: str) -> None:
    current = path.parent
    anchor = Path(path.anchor)
    while True:
        _verify_untrusted_mutation_blocked(
            current,
            current_sid=current_sid,
            dangerous_mask=_ANCESTOR_REPLACE_MASK,
            require_protected=False,
        )
        if current == anchor:
            return
        current = current.parent


def ensure_private_roots(user_profile: Path) -> tuple[Path, Path, Path, str]:
    if os.name != "nt":
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_WINDOWS_REQUIRED",
            "Secure development runtime installation requires Windows",
        )
    profile_root = user_profile.expanduser().resolve(strict=True)
    try:
        owner_sid = service_root_grants()[0][0]
        _verify_untrusted_mutation_blocked(
            profile_root,
            current_sid=owner_sid,
            dangerous_mask=_MUTATION_MASK,
            require_protected=True,
        )
        _verify_ancestor_replace_safety(profile_root, current_sid=owner_sid)
    except WindowsSandboxAclError as error:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_PARENT_ACL_FAILED",
            "Development runtime parent ACL could not be verified",
        ) from error
    app_root_path = profile_root / APP_FOLDER
    if app_root_path.exists():
        app_root = _stable_directory(app_root_path)
        try:
            apply_exact_dacl(app_root, service_root_grants(), inherit_to_children=True)
        except WindowsSandboxAclError as error:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_ACL_FAILED",
                "Development runtime application directory could not be secured",
            ) from error
    else:
        app_root = _secure_directory(app_root_path)
    runtime_base = _secure_directory(app_root / RUNTIME_FOLDER)
    state_root = _secure_directory(app_root / STATE_FOLDER)
    identity_path = state_root / INSTALL_IDENTITY_NAME
    if not identity_path.exists():
        try:
            with identity_path.open("x", encoding="ascii", newline="") as handle:
                handle.write(secrets.token_hex(32))
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_IDENTITY_FAILED",
                "Development runtime install identity could not be created",
            ) from error
    try:
        apply_exact_dacl(
            identity_path, service_root_grants(), inherit_to_children=False
        )
        identity = identity_path.read_text(encoding="ascii")
    except (OSError, UnicodeError, WindowsSandboxAclError) as error:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_IDENTITY_FAILED",
            "Development runtime install identity could not be secured",
        ) from error
    if _DIGEST_RE.fullmatch(identity) is None:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_IDENTITY_INVALID",
            "Development runtime install identity is invalid",
        )
    return app_root, runtime_base, state_root, identity


def _harden_private_tree(root: Path) -> None:
    try:
        stable = _stable_directory(root)
        paths = [
            stable,
            *sorted(
                stable.rglob("*"), key=lambda item: (len(item.parts), item.as_posix())
            ),
        ]
        for path in paths:
            _assert_stable_entry(path)
            apply_exact_dacl(
                path,
                service_root_grants(),
                inherit_to_children=path.is_dir(),
            )
    except (OSError, WindowsSandboxAclError) as error:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_ACL_FAILED", "Development runtime tree could not be secured"
        ) from error


def verify_private_tree_dacl(
    root: Path, *, ignore_bytecode_cache: bool = False
) -> None:
    grants = service_root_grants()
    expected_file = tuple(sorted(DaclEntry(sid, mask, 0) for sid, mask in grants))
    expected_directory = tuple(
        sorted(
            DaclEntry(sid, mask, OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE)
            for sid, mask in grants
        )
    )
    try:
        stable = _stable_directory(root)
        for path in [stable, *stable.rglob("*")]:
            if path != stable:
                relative = path.relative_to(stable)
                if ignore_bytecode_cache and "__pycache__" in relative.parts:
                    continue
            _assert_stable_entry(path)
            expected = expected_directory if path.is_dir() else expected_file
            descriptor = read_security_descriptor_identity(path)
            if (
                descriptor.owner_sid
                not in {
                    service_root_grants()[0][0],
                    "S-1-5-18",
                    "S-1-5-32-544",
                }
                or descriptor.control & SE_DACL_PROTECTED == 0
                or read_dacl(path, reject_unsupported_flags=True) != expected
            ):
                raise DevelopmentRuntimeError(
                    "DEV_RUNTIME_DACL_MISMATCH", "Development runtime DACL is not exact"
                )
    except (OSError, WindowsSandboxAclError) as error:
        if isinstance(error, DevelopmentRuntimeError):
            raise
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_DACL_MISMATCH",
            "Development runtime DACL could not be verified",
        ) from error


def verify_private_path_dacl(path: Path) -> None:
    grants = service_root_grants()
    expected = tuple(
        sorted(
            DaclEntry(
                sid,
                mask,
                OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE if path.is_dir() else 0,
            )
            for sid, mask in grants
        )
    )
    try:
        _assert_stable_entry(path)
        descriptor = read_security_descriptor_identity(path)
        if (
            descriptor.owner_sid
            not in {
                service_root_grants()[0][0],
                "S-1-5-18",
                "S-1-5-32-544",
            }
            or descriptor.control & SE_DACL_PROTECTED == 0
            or read_dacl(path, reject_unsupported_flags=True) != expected
        ):
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_DACL_MISMATCH", "Development runtime DACL is not exact"
            )
    except (OSError, WindowsSandboxAclError) as error:
        if isinstance(error, DevelopmentRuntimeError):
            raise
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_DACL_MISMATCH",
            "Development runtime DACL could not be verified",
        ) from error


def read_install_identity(state_root: Path) -> str:
    identity_path = state_root / INSTALL_IDENTITY_NAME
    verify_private_path_dacl(state_root)
    verify_private_path_dacl(identity_path)
    try:
        identity = identity_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_IDENTITY_INVALID",
            "Development runtime install identity is unavailable",
        ) from error
    if _DIGEST_RE.fullmatch(identity) is None:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_IDENTITY_INVALID",
            "Development runtime install identity is invalid",
        )
    return identity


def verify_readonly_dependency_root(
    root: Path, *, required_paths: Iterable[Path] = ()
) -> None:
    stable = _stable_directory(root)
    current_sid = service_root_grants()[0][0]
    try:
        _verify_untrusted_mutation_blocked(
            stable,
            current_sid=current_sid,
            dangerous_mask=_MUTATION_MASK,
            require_protected=True,
        )
        _verify_ancestor_replace_safety(stable, current_sid=current_sid)
        checked = {stable}
        for raw in required_paths:
            target = _assert_stable_entry(Path(raw).resolve(strict=True))
            try:
                target.relative_to(stable)
            except ValueError as error:
                raise DevelopmentRuntimeError(
                    "DEV_RUNTIME_DEPENDENCY_PATH_INVALID",
                    "Development Python dependency escapes its installation root",
                ) from error
            chain = [target]
            current = target.parent
            while current != stable:
                chain.append(current)
                current = current.parent
            for entry in reversed(chain):
                if entry in checked:
                    continue
                _verify_untrusted_mutation_blocked(
                    entry,
                    current_sid=current_sid,
                    dangerous_mask=_MUTATION_MASK,
                    require_protected=False,
                )
                checked.add(entry)
    except (OSError, WindowsSandboxAclError) as error:
        if isinstance(error, DevelopmentRuntimeError):
            raise
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_DEPENDENCY_WRITABLE",
            "Development Python installation trust could not be verified",
        ) from error


def _tool_sources(
    locator: Callable[[str], str | None]
) -> tuple[list[tuple[Path, str, str]], tuple[str, ...]]:
    resources: list[tuple[Path, str, str]] = []
    missing: list[str] = []
    for name in ALLOWED_TOOL_NAMES:
        raw = locator(name)
        if raw is None:
            missing.append(name)
            continue
        source = Path(os.path.abspath(Path(raw).expanduser()))
        try:
            _assert_stable_entry(source)
            stable = assert_stable_path(source)
            size = stable.stat().st_size
        except (OSError, RuntimeManifestError) as error:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_TOOL_UNSAFE",
                f"The discovered {name} is unavailable or unsafe",
            ) from error
        if size <= 0 or size > MAX_TOOL_BYTES:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_TOOL_INVALID", f"The discovered {name} has an invalid size"
            )
        if getattr(stable.stat(), "st_nlink", 1) != 1:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_TOOL_UNSAFE", f"The discovered {name} is hard-linked"
            )
        resources.append((stable, f"tools/{name}", "media-tool"))
    return resources, tuple(missing)


def _manifest_payload(
    resources: Iterable[dict[str, object]], *, python_executable: Path
) -> dict[str, object]:
    python_path = python_executable.resolve()
    return {
        "schemaVersion": 1,
        "runtimeKind": "codex-development-private-snapshot",
        "platform": "windows-"
        + (os.environ.get("PROCESSOR_ARCHITECTURE") or "unknown").lower(),
        "cardServiceProtocolVersion": 1,
        "python": {
            "executablePath": str(python_path),
            "executableSha256": file_sha256(python_path),
            "majorMinor": "3.13",
        },
        "resources": sorted(
            resources, key=lambda item: str(item["relativePath"]).encode("utf-8")
        ),
    }


def verify_development_runtime(
    root: Path,
    *,
    expected_python: Path | None = None,
    verify_acl: bool = True,
    allow_unexpected_bytecode_cache: bool = False,
) -> dict[str, object]:
    stable = _stable_directory(root)
    if _DIGEST_RE.fullmatch(stable.name) is None:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_DIGEST_INVALID",
            "Development runtime directory is not content-addressed",
        )
    manifest_path = stable / MANIFEST_NAME
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as error:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_MANIFEST_MISSING", "Development runtime manifest is missing"
        ) from error
    if not manifest_bytes or len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_MANIFEST_INVALID",
            "Development runtime manifest has an invalid size",
        )
    try:
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_MANIFEST_INVALID", "Development runtime manifest is invalid"
        ) from error
    if canonical_bytes(payload) != manifest_bytes:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_MANIFEST_INVALID",
            "Development runtime manifest is not canonical",
        )
    if hashlib.sha256(manifest_bytes).hexdigest() != stable.name:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_DIGEST_MISMATCH",
            "Development runtime digest does not match its manifest",
        )
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 1
        or payload.get("runtimeKind") != "codex-development-private-snapshot"
        or not isinstance(payload.get("platform"), str)
        or payload.get("cardServiceProtocolVersion") != 1
        or not isinstance(payload.get("python"), dict)
        or not isinstance(payload.get("resources"), list)
    ):
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_MANIFEST_INVALID",
            "Development runtime manifest contract is invalid",
        )
    python_value = payload["python"]
    assert isinstance(python_value, dict)
    if set(python_value) != {"executablePath", "executableSha256", "majorMinor"}:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_MANIFEST_INVALID",
            "Development runtime Python contract is invalid",
        )
    python_path = Path(str(python_value.get("executablePath"))).resolve()
    python_digest = python_value.get("executableSha256")
    if (
        python_value.get("majorMinor") != "3.13"
        or not isinstance(python_digest, str)
        or _DIGEST_RE.fullmatch(python_digest) is None
        or not python_path.is_file()
        or file_sha256(python_path) != python_digest
    ):
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_PYTHON_MISMATCH", "Development runtime Python identity changed"
        )
    if expected_python is not None and python_path != expected_python.resolve():
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_PYTHON_MISMATCH", "Development runtime Python identity changed"
        )
    resources = payload["resources"]
    if not resources or len(resources) > MAX_RUNTIME_FILES:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_MANIFEST_INVALID",
            "Development runtime resource count is invalid",
        )
    expected_files = {MANIFEST_NAME}
    seen: set[str] = set()
    total_bytes = len(manifest_bytes)
    for item in resources:
        if not isinstance(item, dict) or set(item) != {
            "relativePath",
            "role",
            "sha256",
            "size",
        }:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_MANIFEST_INVALID",
                "Development runtime resource entry is invalid",
            )
        relative_raw = item["relativePath"]
        digest = item["sha256"]
        role = item["role"]
        size = item["size"]
        if (
            not isinstance(relative_raw, str)
            or not isinstance(digest, str)
            or _DIGEST_RE.fullmatch(digest) is None
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or role
            not in {
                "development-launcher",
                "card-service-module",
                "worker-entry",
                "worker-module",
                "worker-protocol-schema",
                "media-tool",
            }
        ):
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_MANIFEST_INVALID",
                "Development runtime resource entry is invalid",
            )
        relative = _relative_path(relative_raw)
        key = relative.as_posix().casefold()
        if key in seen or relative.as_posix() == MANIFEST_NAME:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_MANIFEST_INVALID",
                "Development runtime resource path is duplicated",
            )
        seen.add(key)
        expected_files.add(relative.as_posix())
        target = stable.joinpath(*relative.parts)
        try:
            verified = assert_stable_path(target)
        except (OSError, RuntimeManifestError) as error:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_RESOURCE_UNSAFE",
                "Development runtime resource is unavailable or unsafe",
            ) from error
        if (
            verified.stat().st_size != size
            or getattr(verified.stat(), "st_nlink", 1) != 1
            or file_sha256(verified) != digest
        ):
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_RESOURCE_MISMATCH",
                "Development runtime resource failed integrity verification",
            )
        total_bytes += size
        if total_bytes > MAX_RUNTIME_BYTES:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_TOO_LARGE", "Development runtime exceeds its byte limit"
            )
    actual_files = {
        path.relative_to(stable).as_posix()
        for path in stable.rglob("*")
        if path.is_file()
    }
    missing_files = expected_files - actual_files
    unexpected_files = actual_files - expected_files
    recoverable_bytecode = bool(unexpected_files) and all(
        "__pycache__" in PurePosixPath(path).parts and path.endswith(".pyc")
        for path in unexpected_files
    )
    if missing_files or (
        unexpected_files
        and not (allow_unexpected_bytecode_cache and recoverable_bytecode)
    ):
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_FILE_SET_MISMATCH",
            "Development runtime contains an unexpected or missing file",
        )
    if (
        LAUNCHER_NAME not in expected_files
        or "workers/anki_worker.py" not in expected_files
    ):
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_SOURCE_INCOMPLETE",
            "Development runtime entry points are missing",
        )
    if verify_acl:
        verify_private_tree_dacl(
            stable,
            ignore_bytecode_cache=(
                allow_unexpected_bytecode_cache and recoverable_bytecode
            ),
        )
    return payload


def build_development_runtime(
    *,
    repository_root: Path,
    launcher_source: Path,
    python_executable: Path,
    user_profile: Path,
    include_tools: bool,
    tool_locator: Callable[[str], str | None] = shutil.which,
) -> DevelopmentRuntimeSnapshot:
    repository = _stable_directory(repository_root.resolve())
    try:
        launcher = assert_stable_path(launcher_source)
    except (OSError, RuntimeManifestError) as error:
        raise DevelopmentRuntimeError(
            "DEV_RUNTIME_SOURCE_INCOMPLETE",
            "Development runtime launcher is unavailable or unsafe",
        ) from error
    _, runtime_base, state_root, _ = ensure_private_roots(user_profile)
    sources = _runtime_sources(repository, launcher)
    missing_tools: tuple[str, ...] = ()
    if include_tools:
        tool_resources, missing_tools = _tool_sources(tool_locator)
        sources.extend(tool_resources)
    staging = runtime_base / f".staging-{uuid.uuid4()}"
    staging.mkdir(exist_ok=False)
    _harden_private_tree(staging)
    resources: list[dict[str, object]] = []
    published: Path | None = None
    try:
        for source, relative_raw, role in sources:
            relative = _relative_path(relative_raw)
            target = staging.joinpath(*relative.parts)
            try:
                _assert_stable_entry(source)
                if getattr(source.stat(), "st_nlink", 1) != 1:
                    raise DevelopmentRuntimeError(
                        "DEV_RUNTIME_SOURCE_HARDLINK",
                        "Development runtime source must not be hard-linked",
                    )
                size, digest = _copy_verified(source, target)
                if getattr(target.stat(), "st_nlink", 1) != 1:
                    raise DevelopmentRuntimeError(
                        "DEV_RUNTIME_TARGET_HARDLINK",
                        "Development runtime target must not be hard-linked",
                    )
            except RuntimeBuildError as error:
                raise DevelopmentRuntimeError(
                    "DEV_RUNTIME_COPY_FAILED",
                    "Development runtime source changed during copy",
                ) from error
            resources.append(
                {
                    "relativePath": relative.as_posix(),
                    "role": role,
                    "size": size,
                    "sha256": digest,
                }
            )
        manifest = _manifest_payload(resources, python_executable=python_executable)
        manifest_bytes = canonical_bytes(manifest)
        if len(manifest_bytes) > MAX_MANIFEST_BYTES:
            raise DevelopmentRuntimeError(
                "DEV_RUNTIME_MANIFEST_INVALID",
                "Development runtime manifest exceeds its byte limit",
            )
        (staging / MANIFEST_NAME).write_bytes(manifest_bytes)
        digest = hashlib.sha256(manifest_bytes).hexdigest()
        _harden_private_tree(staging)
        destination = runtime_base / digest
        if destination.exists():
            verify_development_runtime(
                destination, expected_python=python_executable, verify_acl=True
            )
            shutil.rmtree(staging)
        else:
            try:
                os.rename(staging, destination)
            except FileExistsError:
                verify_development_runtime(
                    destination, expected_python=python_executable, verify_acl=True
                )
                shutil.rmtree(staging)
            published = destination
        published = destination
        _harden_private_tree(runtime_base)
        verify_private_path_dacl(state_root)
        read_install_identity(state_root)
        verify_development_runtime(
            published, expected_python=python_executable, verify_acl=True
        )
        tools = tuple(
            Path(str(item["relativePath"])).name
            for item in resources
            if str(item["relativePath"]).startswith("tools/")
        )
        return DevelopmentRuntimeSnapshot(
            root=published,
            launcher=published / LAUNCHER_NAME,
            state_root=state_root,
            manifest_sha256=digest,
            resource_count=len(resources),
            tools=tools,
            missing_tools=missing_tools,
        )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _plugin_snapshot_manifest_payload(
    resources: Iterable[dict[str, object]], *, version: str
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "snapshotKind": "codex-development-private-plugin",
        "marketplaceName": "anki-study-agent-local",
        "pluginName": "anki-study-agent",
        "pluginVersion": version,
        "resources": sorted(
            resources, key=lambda item: str(item["relativePath"]).encode("utf-8")
        ),
    }


def verify_development_plugin_snapshot(
    root: Path, *, verify_acl: bool = True
) -> dict[str, object]:
    stable = _stable_directory(root)
    if _DIGEST_RE.fullmatch(stable.name) is None:
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_DIGEST_INVALID",
            "Development plugin directory is not content-addressed",
        )
    manifest_path = stable / PLUGIN_SNAPSHOT_MANIFEST_NAME
    try:
        manifest_bytes = manifest_path.read_bytes()
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_MANIFEST_INVALID",
            "Development plugin snapshot manifest is invalid",
        ) from error
    if (
        not manifest_bytes
        or len(manifest_bytes) > MAX_MANIFEST_BYTES
        or canonical_bytes(payload) != manifest_bytes
        or hashlib.sha256(manifest_bytes).hexdigest() != stable.name
        or not isinstance(payload, dict)
        or payload.get("schemaVersion") != 1
        or payload.get("snapshotKind") != "codex-development-private-plugin"
        or payload.get("marketplaceName") != "anki-study-agent-local"
        or payload.get("pluginName") != "anki-study-agent"
        or not isinstance(payload.get("pluginVersion"), str)
        or not isinstance(payload.get("resources"), list)
    ):
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_MANIFEST_INVALID",
            "Development plugin snapshot identity is invalid",
        )
    resources = payload["resources"]
    if not resources or len(resources) > MAX_RUNTIME_FILES:
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_MANIFEST_INVALID",
            "Development plugin snapshot resource count is invalid",
        )
    expected_files = {PLUGIN_SNAPSHOT_MANIFEST_NAME}
    seen: set[str] = set()
    total_bytes = len(manifest_bytes)
    for item in resources:
        if not isinstance(item, dict) or set(item) != {
            "relativePath",
            "role",
            "sha256",
            "size",
        }:
            raise DevelopmentRuntimeError(
                "DEV_PLUGIN_MANIFEST_INVALID",
                "Development plugin resource entry is invalid",
            )
        relative_raw = item["relativePath"]
        digest = item["sha256"]
        size = item["size"]
        if (
            not isinstance(relative_raw, str)
            or item["role"] not in {"marketplace-manifest", "plugin-resource"}
            or not isinstance(digest, str)
            or _DIGEST_RE.fullmatch(digest) is None
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise DevelopmentRuntimeError(
                "DEV_PLUGIN_MANIFEST_INVALID",
                "Development plugin resource entry is invalid",
            )
        relative = _relative_path(relative_raw)
        key = relative.as_posix().casefold()
        if key in seen or relative.as_posix() == PLUGIN_SNAPSHOT_MANIFEST_NAME:
            raise DevelopmentRuntimeError(
                "DEV_PLUGIN_MANIFEST_INVALID",
                "Development plugin resource path is duplicated",
            )
        seen.add(key)
        expected_files.add(relative.as_posix())
        target = stable.joinpath(*relative.parts)
        try:
            verified = assert_stable_path(target)
        except (OSError, RuntimeManifestError) as error:
            raise DevelopmentRuntimeError(
                "DEV_PLUGIN_RESOURCE_UNSAFE",
                "Development plugin resource is unavailable or unsafe",
            ) from error
        if (
            verified.stat().st_size != size
            or getattr(verified.stat(), "st_nlink", 1) != 1
            or file_sha256(verified) != digest
        ):
            raise DevelopmentRuntimeError(
                "DEV_PLUGIN_RESOURCE_MISMATCH",
                "Development plugin resource failed integrity verification",
            )
        total_bytes += size
        if total_bytes > MAX_RUNTIME_BYTES:
            raise DevelopmentRuntimeError(
                "DEV_PLUGIN_TOO_LARGE", "Development plugin exceeds its byte limit"
            )
    actual_files = {
        path.relative_to(stable).as_posix()
        for path in stable.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_FILE_SET_MISMATCH",
            "Development plugin contains an unexpected or missing file",
        )
    marketplace_path = stable / ".agents" / "plugins" / "marketplace.json"
    plugin_root = stable / "plugins" / "anki-study-agent"
    plugin_manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    try:
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        plugin = json.loads(plugin_manifest_path.read_text(encoding="utf-8"))
        source = marketplace["plugins"][0]["source"]
    except (
        OSError,
        KeyError,
        IndexError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_CONTENT_INVALID",
            "Development plugin metadata is invalid",
        ) from error
    if (
        marketplace.get("name") != payload["marketplaceName"]
        or len(marketplace.get("plugins", [])) != 1
        or marketplace["plugins"][0].get("name") != payload["pluginName"]
        or source != {"source": "local", "path": "./plugins/anki-study-agent"}
        or plugin.get("name") != payload["pluginName"]
        or plugin.get("version") != payload["pluginVersion"]
        or "mcpServers" in plugin
        or "apps" in plugin
        or (plugin_root / ".mcp.json").exists()
        or (plugin_root / ".app.json").exists()
        or not (plugin_root / "skills" / "anki-study-agent" / "SKILL.md").is_file()
    ):
        raise DevelopmentRuntimeError(
            "DEV_PLUGIN_CONTENT_INVALID",
            "Development plugin snapshot is not the expected passive plugin",
        )
    if verify_acl:
        verify_private_tree_dacl(stable)
    return payload


def build_development_plugin_snapshot(
    *, repository_root: Path, user_profile: Path
) -> DevelopmentPluginSnapshot:
    repository = _stable_directory(repository_root.resolve())
    app_root, _, _, _ = ensure_private_roots(user_profile)
    plugin_base = _secure_directory(app_root / PLUGIN_FOLDER)
    sources, version = _plugin_sources(repository)
    staging = plugin_base / f".staging-{uuid.uuid4()}"
    staging.mkdir(exist_ok=False)
    _harden_private_tree(staging)
    resources: list[dict[str, object]] = []
    try:
        for source, relative_raw, role in sources:
            relative = _relative_path(relative_raw)
            target = staging.joinpath(*relative.parts)
            try:
                _assert_stable_entry(source)
                if getattr(source.stat(), "st_nlink", 1) != 1:
                    raise DevelopmentRuntimeError(
                        "DEV_PLUGIN_SOURCE_HARDLINK",
                        "Development plugin source must not be hard-linked",
                    )
                size, digest = _copy_verified(source, target)
            except RuntimeBuildError as error:
                raise DevelopmentRuntimeError(
                    "DEV_PLUGIN_COPY_FAILED",
                    "Development plugin source changed during copy",
                ) from error
            resources.append(
                {
                    "relativePath": relative.as_posix(),
                    "role": role,
                    "size": size,
                    "sha256": digest,
                }
            )
        manifest = _plugin_snapshot_manifest_payload(resources, version=version)
        manifest_bytes = canonical_bytes(manifest)
        if len(manifest_bytes) > MAX_MANIFEST_BYTES:
            raise DevelopmentRuntimeError(
                "DEV_PLUGIN_MANIFEST_INVALID",
                "Development plugin snapshot manifest exceeds its byte limit",
            )
        (staging / PLUGIN_SNAPSHOT_MANIFEST_NAME).write_bytes(manifest_bytes)
        digest = hashlib.sha256(manifest_bytes).hexdigest()
        _harden_private_tree(staging)
        destination = plugin_base / digest
        if destination.exists():
            verify_development_plugin_snapshot(destination, verify_acl=True)
            shutil.rmtree(staging)
        else:
            try:
                os.rename(staging, destination)
            except FileExistsError:
                verify_development_plugin_snapshot(destination, verify_acl=True)
                shutil.rmtree(staging)
        _harden_private_tree(plugin_base)
        verify_development_plugin_snapshot(destination, verify_acl=True)
        return DevelopmentPluginSnapshot(
            root=destination,
            plugin_root=destination / "plugins" / "anki-study-agent",
            manifest_sha256=digest,
            resource_count=len(resources),
            version=version,
        )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
