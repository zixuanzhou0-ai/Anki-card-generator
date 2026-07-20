from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath


APP_FOLDER = ".anki-study-agent"
RUNTIME_FOLDER = "codex-dev-runtime"
STATE_FOLDER = "codex-card-service-dev"
MANIFEST_NAME = "dev-runtime-manifest-v1.json"
ALLOWED_TOOL_NAMES = frozenset(("ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe"))
MAX_MANIFEST_BYTES = 512 * 1024
MAX_FILES = 10_000
MAX_BYTES = 2 * 1024 * 1024 * 1024


def _bounded_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _has_reparse_point(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _stable_file(root: Path, relative: PurePosixPath) -> Path:
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current /= part
        if _has_reparse_point(current):
            raise RuntimeError("Development runtime contains a reparse point")
    target = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current /= part
        if _has_reparse_point(current):
            raise RuntimeError("Development runtime contains a reparse point")
    resolved = target.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise RuntimeError(
            "Development runtime resource escapes its snapshot"
        ) from error
    if not resolved.is_file():
        raise RuntimeError("Development runtime resource is not a file")
    return resolved


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_snapshot_before_import() -> tuple[Path, dict[str, object]]:
    root = Path(__file__).resolve().parent
    manifest_path = root / MANIFEST_NAME
    try:
        source = manifest_path.read_bytes()
    except OSError as error:
        raise RuntimeError(
            "The development launcher must run from a private installed runtime snapshot"
        ) from error
    if not source or len(source) > MAX_MANIFEST_BYTES:
        raise RuntimeError("Development runtime manifest has an invalid size")
    try:
        payload = json.loads(source.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise RuntimeError("Development runtime manifest is invalid") from error
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if canonical != source or hashlib.sha256(source).hexdigest() != root.name:
        raise RuntimeError("Development runtime manifest identity is invalid")
    resources = payload.get("resources") if isinstance(payload, dict) else None
    if (
        payload.get("schemaVersion") != 1
        or payload.get("runtimeKind") != "codex-development-private-snapshot"
        or not isinstance(payload.get("platform"), str)
        or payload.get("cardServiceProtocolVersion") != 1
        or not isinstance(payload.get("python"), dict)
        or not isinstance(resources, list)
        or not resources
        or len(resources) > MAX_FILES
    ):
        raise RuntimeError("Development runtime manifest contract is invalid")
    python_value = payload["python"]
    assert isinstance(python_value, dict)
    python_path = Path(str(python_value.get("executablePath"))).resolve()
    python_digest = python_value.get("executableSha256")
    if (
        set(python_value) != {"executablePath", "executableSha256", "majorMinor"}
        or python_value.get("majorMinor") != "3.13"
        or python_path != Path(sys.executable).resolve()
        or not isinstance(python_digest, str)
        or _hash(python_path) != python_digest
    ):
        raise RuntimeError("Development runtime Python identity changed")
    expected_files = {MANIFEST_NAME}
    total_bytes = len(source)
    seen: set[str] = set()
    for item in resources:
        if not isinstance(item, dict) or set(item) != {
            "relativePath",
            "role",
            "sha256",
            "size",
        }:
            raise RuntimeError("Development runtime resource entry is invalid")
        relative_raw = item.get("relativePath")
        size = item.get("size")
        expected_hash = item.get("sha256")
        role = item.get("role")
        if (
            not isinstance(relative_raw, str)
            or not relative_raw
            or "\\" in relative_raw
            or ":" in relative_raw
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or any(character not in "0123456789abcdef" for character in expected_hash)
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
            raise RuntimeError("Development runtime resource entry is invalid")
        relative = PurePosixPath(relative_raw)
        if relative.is_absolute() or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise RuntimeError("Development runtime resource path is invalid")
        key = relative.as_posix().casefold()
        if key in seen or relative.as_posix() == MANIFEST_NAME:
            raise RuntimeError("Development runtime resource path is duplicated")
        seen.add(key)
        target = _stable_file(root, relative)
        if (
            target.stat().st_size != size
            or getattr(target.stat(), "st_nlink", 1) != 1
            or _hash(target) != expected_hash
        ):
            raise RuntimeError(
                "Development runtime resource failed integrity verification"
            )
        expected_files.add(relative.as_posix())
        total_bytes += size
        if total_bytes > MAX_BYTES:
            raise RuntimeError("Development runtime exceeds its byte limit")
    actual_files = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    if actual_files != expected_files:
        raise RuntimeError("Development runtime contains an unexpected or missing file")
    if (
        "launcher.py" not in expected_files
        or "workers/anki_worker.py" not in expected_files
    ):
        raise RuntimeError("Development runtime entry points are missing")
    return root, payload


def _user_profile(environment: dict[str, str] | None = None) -> Path:
    values = os.environ if environment is None else environment
    raw = values.get("USERPROFILE")
    if not raw:
        raise RuntimeError("USERPROFILE is required for the development Card Service")
    root = Path(raw).expanduser().resolve(strict=True)
    if not root.is_absolute():
        raise RuntimeError("USERPROFILE must resolve to an absolute path")
    return root


def _prepare_verified_python_path(runtime_root: Path) -> Path:
    import importlib.util
    import sysconfig

    acl_path = runtime_root / "card_service" / "windows_sandbox_acl.py"
    spec = importlib.util.spec_from_file_location(
        "_anki_verified_windows_acl", acl_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Development Python ACL verifier is unavailable")
    acl = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = acl
    spec.loader.exec_module(acl)
    prefix = Path(sys.base_prefix).resolve(strict=True)
    purelib = Path(sysconfig.get_paths()["purelib"]).resolve(strict=True)
    try:
        purelib.relative_to(prefix)
    except ValueError as error:
        raise RuntimeError(
            "Development Python site-packages escapes its prefix"
        ) from error
    current_sid = acl.service_root_grants()[0][0]
    trusted = {
        current_sid,
        "S-1-5-18",
        "S-1-5-32-544",
        acl.TRUSTED_INSTALLER_SID,
    }
    mutation_mask = (
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
    ancestor_mask = 0x00000040 | 0x00010000 | 0x00040000 | 0x00080000 | 0x10000000

    def verify(path: Path, mask: int, *, protected: bool) -> None:
        descriptor = acl.read_security_descriptor_identity(path)
        owner = descriptor.owner_sid
        if (
            owner not in trusted
            or (protected and descriptor.control & acl.SE_DACL_PROTECTED == 0)
            or any(
                entry.sid not in trusted and entry.access_mask & mask
                for entry in acl.read_dacl(path, skip_inherit_only=True)
            )
        ):
            raise RuntimeError("Development Python trust path is mutable")

    verify(prefix, mutation_mask, protected=True)
    for path in (
        Path(sys.executable).resolve(strict=True),
        prefix / "Lib",
        purelib,
        *((prefix / "DLLs",) if (prefix / "DLLs").is_dir() else ()),
    ):
        verify(path, mutation_mask, protected=False)
    current = prefix.parent
    anchor = Path(prefix.anchor)
    while True:
        verify(current, ancestor_mask, protected=False)
        if current == anchor:
            break
        current = current.parent
    if str(purelib) not in sys.path:
        sys.path.append(str(purelib))
    return purelib


def development_service_arguments(
    *,
    runtime_root: Path,
    python_executable: str | Path,
    anki_connect_port: int,
    environment: dict[str, str] | None = None,
) -> list[str]:
    python_path = Path(python_executable).resolve()
    local_root = _user_profile(environment) / APP_FOLDER
    expected_runtime_base = (local_root / RUNTIME_FOLDER).resolve()
    if runtime_root.resolve().parent != expected_runtime_base:
        raise RuntimeError(
            "Development runtime is outside its private installation root"
        )
    state_dir = (local_root / STATE_FOLDER).resolve()
    worker = (runtime_root / "workers" / "anki_worker.py").resolve()
    if not python_path.is_file() or not worker.is_file() or not state_dir.is_dir():
        raise RuntimeError(
            "The development Python, Worker, or state root is unavailable"
        )
    tool_dir = runtime_root / "tools"
    if tool_dir.exists():
        entries = list(tool_dir.iterdir())
        names = {entry.name.casefold() for entry in entries}
        if (
            not tool_dir.is_dir()
            or tool_dir.is_symlink()
            or not entries
            or not names.issubset(ALLOWED_TOOL_NAMES)
            or any(not entry.is_file() or entry.is_symlink() for entry in entries)
        ):
            raise RuntimeError("Development media tool directory is invalid")
    arguments = [
        "--state-dir",
        str(state_dir),
        "--development-unpackaged-runtime",
        "--development-trusted-mcp-session",
        "--worker",
        str(worker),
        "--python",
        str(python_path),
        "--anki-connect-url",
        f"http://127.0.0.1:{anki_connect_port}",
    ]
    if tool_dir.is_dir():
        arguments.extend(("--tool-dir", str(tool_dir.resolve())))
    return arguments


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the private, content-addressed Card Service development MCP. "
            "This is not the signed production launcher."
        )
    )
    parser.add_argument("--anki-connect-port", type=_bounded_port, default=8765)
    options = parser.parse_args()

    runtime_root, _ = _verify_snapshot_before_import()
    _prepare_verified_python_path(runtime_root)
    if str(runtime_root) not in sys.path:
        sys.path.insert(0, str(runtime_root))
    from card_service.development_runtime import (
        APP_FOLDER as VERIFIED_APP_FOLDER,
        RUNTIME_FOLDER as VERIFIED_RUNTIME_FOLDER,
        STATE_FOLDER as VERIFIED_STATE_FOLDER,
        read_install_identity,
        verify_development_runtime,
        verify_private_path_dacl,
        verify_readonly_dependency_root,
    )
    from card_service.mcp_stdio import serve
    from card_service.stdio import build_parser, create_service
    from card_service.trusted_mcp_audience import create_development_mcp_audience

    user_profile = _user_profile()
    app_root = user_profile / VERIFIED_APP_FOLDER
    runtime_base = app_root / VERIFIED_RUNTIME_FOLDER
    state_root = app_root / VERIFIED_STATE_FOLDER
    verify_development_runtime(
        runtime_root, expected_python=Path(sys.executable), verify_acl=True
    )
    verify_readonly_dependency_root(Path(sys.base_prefix))
    verify_private_path_dacl(app_root)
    verify_private_path_dacl(runtime_base)
    install_identity = read_install_identity(state_root)
    service_parser = build_parser("Anki Study Agent development Card Service")
    service_arguments = service_parser.parse_args(
        development_service_arguments(
            runtime_root=runtime_root,
            python_executable=sys.executable,
            anki_connect_port=options.anki_connect_port,
        )
    )
    service = create_service(service_arguments, service_parser)
    serve(
        service,
        audience_session=create_development_mcp_audience(
            installation_identity=install_identity
        ),
    )


if __name__ == "__main__":
    main()
