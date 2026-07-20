from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.development_runtime import (
    APP_FOLDER,
    LAUNCHER_NAME,
    PLUGIN_FOLDER,
    RUNTIME_FOLDER,
    DevelopmentRuntimeError,
    DevelopmentRuntimeSnapshot,
    build_development_plugin_snapshot,
    build_development_runtime,
    verify_development_plugin_snapshot,
    verify_development_runtime,
    verify_readonly_dependency_root,
)


MARKETPLACE_FILE = ROOT / ".agents" / "plugins" / "marketplace.json"
MARKETPLACE_NAME = "anki-study-agent-local"
PLUGIN_NAME = "anki-study-agent"
PLUGIN_SELECTOR = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
PLUGIN_ROOT = ROOT / "plugins" / PLUGIN_NAME
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
MCP_NAME = "anki-study-card-service"
DEV_LAUNCHER_SOURCE = (ROOT / "scripts" / "run_codex_study_mcp_dev.py").resolve()
MINIMUM_CODEX_VERSION = (0, 144, 1)
_CODEX_VERSION = re.compile(r"\bcodex-cli\s+(\d+)\.(\d+)\.(\d+)\b")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class DevelopmentInstallError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        partial: bool = False,
        failed_step: str | None = None,
        unrecovered: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.partial = partial
        self.failed_step = failed_step
        self.unrecovered = tuple(unrecovered)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str]], CommandResult]
CachebusterUpdater = Callable[[Path], CommandResult]


@contextmanager
def _installer_mutex():
    if os.name != "nt":
        raise DevelopmentInstallError(
            "Development plugin installation requires Windows"
        )
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateMutexW(
        None, False, "Global\\AnkiStudyAgent.CodexDevelopmentInstall.v1"
    )
    if not handle:
        raise DevelopmentInstallError("The development installer lock is unavailable")
    try:
        status = kernel32.WaitForSingleObject(handle, 60_000)
        if status not in {0x00000000, 0x00000080}:
            raise DevelopmentInstallError(
                "Another Anki Study Agent install transaction is still running"
            )
        try:
            yield
        finally:
            kernel32.ReleaseMutex(handle)
    finally:
        kernel32.CloseHandle(handle)


def _run_command(arguments: Sequence[str]) -> CommandResult:
    try:
        completed = subprocess.run(
            [str(value) for value in arguments],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DevelopmentInstallError(
            "A required Codex CLI command could not complete"
        ) from error
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _require_success(result: CommandResult, action: str) -> CommandResult:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = f": {detail[-1][:240]}" if detail else ""
        raise DevelopmentInstallError(f"{action} failed{suffix}")
    return result


def _json_object(result: CommandResult, action: str) -> dict[str, object]:
    _require_success(result, action)
    try:
        payload = json.loads(result.stdout)
    except ValueError as error:
        raise DevelopmentInstallError(f"{action} returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise DevelopmentInstallError(f"{action} returned an invalid result")
    return payload


def _canonical_path(value: str | Path) -> Path:
    raw = str(value)
    if raw.startswith("\\\\?\\"):
        raw = raw[4:]
    return Path(raw).expanduser().resolve()


def parse_marketplace_roots(output: str) -> dict[str, Path]:
    try:
        payload = json.loads(output)
    except ValueError as error:
        raise DevelopmentInstallError("Codex marketplace state is invalid") from error
    rows = payload.get("marketplaces") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise DevelopmentInstallError("Codex marketplace state is invalid")
    roots: dict[str, Path] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise DevelopmentInstallError("Codex marketplace state is invalid")
        name, root = row.get("name"), row.get("root")
        if not isinstance(name, str) or not isinstance(root, str):
            raise DevelopmentInstallError("Codex marketplace state is invalid")
        if name in roots:
            raise DevelopmentInstallError("Codex marketplace state is ambiguous")
        roots[name] = _canonical_path(root)
    return roots


def _marketplace_roots(codex: str, runner: Runner) -> dict[str, Path]:
    result = runner((codex, "plugin", "marketplace", "list", "--json"))
    _require_success(result, "Reading Codex marketplaces")
    return parse_marketplace_roots(result.stdout)


def _plugin_rows(codex: str, runner: Runner) -> list[dict[str, object]]:
    payload = _json_object(
        runner((codex, "plugin", "list", "--json")), "Reading Codex plugins"
    )
    rows = payload.get("installed")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise DevelopmentInstallError("Codex plugin state is invalid")
    return list(rows)


def _plugin_row(codex: str, runner: Runner) -> dict[str, object] | None:
    matches = [
        row
        for row in _plugin_rows(codex, runner)
        if row.get("pluginId") == PLUGIN_SELECTOR
    ]
    if len(matches) > 1:
        raise DevelopmentInstallError(
            "The installed Anki Study Agent plugin is ambiguous"
        )
    return matches[0] if matches else None


def _plugin_version() -> str:
    try:
        payload = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        value = payload["version"]
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise DevelopmentInstallError(
            "The plugin manifest version is invalid"
        ) from error
    if not isinstance(value, str) or not value.strip():
        raise DevelopmentInstallError("The plugin manifest version is invalid")
    return value


def _private_plugin_base(user_profile: Path) -> Path:
    return (user_profile.resolve() / APP_FOLDER / PLUGIN_FOLDER).resolve()


def _owned_plugin_details(
    row: Mapping[str, object] | None, *, user_profile: Path
) -> tuple[Path, Path, str] | None:
    if row is None or row.get("pluginId") != PLUGIN_SELECTOR:
        return None
    source = row.get("source")
    if not isinstance(source, dict) or source.get("source") != "local":
        return None
    path = source.get("path")
    if not isinstance(path, str):
        return None
    plugin_root = _canonical_path(path)
    if plugin_root.name != PLUGIN_NAME or plugin_root.parent.name != "plugins":
        return None
    snapshot = plugin_root.parent.parent
    if _DIGEST_RE.fullmatch(
        snapshot.name
    ) is None or snapshot.parent != _private_plugin_base(user_profile):
        return None
    try:
        payload = verify_development_plugin_snapshot(snapshot, verify_acl=True)
    except (DevelopmentRuntimeError, OSError):
        return None
    version = payload.get("pluginVersion")
    if not isinstance(version, str) or row.get("version") != version:
        return None
    return snapshot, plugin_root, version


def _owned_marketplace_root(root: Path, *, user_profile: Path) -> bool:
    if _DIGEST_RE.fullmatch(root.name) is None or root.parent != _private_plugin_base(
        user_profile
    ):
        return False
    try:
        verify_development_plugin_snapshot(root, verify_acl=True)
    except (DevelopmentRuntimeError, OSError):
        return False
    return True


def _ensure_repository_shape() -> None:
    required = (
        MARKETPLACE_FILE,
        PLUGIN_MANIFEST,
        ROOT / "workers" / "anki_worker.py",
        DEV_LAUNCHER_SOURCE,
    )
    if any(not path.is_file() for path in required):
        raise DevelopmentInstallError(
            "The repository plugin or Card Service files are incomplete"
        )
    try:
        marketplace = json.loads(MARKETPLACE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DevelopmentInstallError(
            "The repository marketplace manifest is invalid"
        ) from error
    if marketplace.get("name") != MARKETPLACE_NAME:
        raise DevelopmentInstallError(
            "The repository marketplace name is not canonical"
        )


def verify_codex_version(codex: str, runner: Runner = _run_command) -> str:
    result = _require_success(
        runner((codex, "--version")), "Reading the Codex CLI version"
    )
    match = _CODEX_VERSION.search(result.stdout)
    if match is None:
        raise DevelopmentInstallError("The Codex CLI version could not be verified")
    version = tuple(int(part) for part in match.groups())
    if version < MINIMUM_CODEX_VERSION:
        raise DevelopmentInstallError("Codex CLI 0.144.1 or newer is required")
    return ".".join(str(part) for part in version)


def verify_development_python(python: Path) -> str:
    probe = (
        "import json,sys,sysconfig;"
        "purelib=sysconfig.get_paths()['purelib'];sys.path.insert(0,purelib);"
        "import cryptography,cffi,_cffi_backend,pycparser,genanki,cached_property,chevron,"
        "frozendict,yaml,pypdf,yt_dlp,aiohttp,aiohappyeyeballs,aiosignal,attr,attrs,"
        "frozenlist,multidict,propcache,yarl,idna;"
        "mods=[cryptography,cffi,_cffi_backend,pycparser,genanki,cached_property,chevron,"
        "frozendict,yaml,pypdf,yt_dlp,aiohttp,aiohappyeyeballs,aiosignal,attr,attrs,"
        "frozenlist,multidict,propcache,yarl,idna];"
        "roots=[];"
        "[roots.extend(list(getattr(m,'__path__',[])) or [m.__file__]) for m in mods];"
        "print(json.dumps({'version':list(sys.version_info[:3]),'prefix':sys.base_prefix,"
        "'stdlib':sysconfig.get_paths()['stdlib'],'purelib':purelib,'modules':roots},"
        "separators=(',',':')))"
    )
    initial_root = python.resolve().parent
    initial_files = [
        python.resolve(),
        *(
            path
            for path in initial_root.iterdir()
            if path.is_file() and path.suffix.casefold() in {".dll", ".exe"}
        ),
    ]
    try:
        verify_readonly_dependency_root(initial_root, required_paths=initial_files)
    except (DevelopmentRuntimeError, OSError) as error:
        raise DevelopmentInstallError(str(error)) from error
    try:
        completed = subprocess.run(
            [str(python.resolve()), "-I", "-S", "-B", "-c", probe],
            cwd=Path.home(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DevelopmentInstallError(
            "The development Python could not be verified"
        ) from error
    if completed.returncode != 0:
        raise DevelopmentInstallError(
            "The development Python is missing a locked Worker dependency"
        )
    try:
        payload = json.loads(completed.stdout)
        version = tuple(payload["version"])
        prefix = _canonical_path(payload["prefix"])
        stdlib = _canonical_path(payload["stdlib"])
        purelib = _canonical_path(payload["purelib"])
        modules = [_canonical_path(path) for path in payload["modules"]]
    except (KeyError, TypeError, ValueError) as error:
        raise DevelopmentInstallError(
            "The development Python identity is invalid"
        ) from error
    if version[:2] != (3, 13):
        raise DevelopmentInstallError(
            "The development Card Service requires CPython 3.13"
        )
    executable = python.resolve()
    try:
        executable.relative_to(prefix)
        stdlib.relative_to(prefix)
        purelib.relative_to(prefix)
        for module in modules:
            module.relative_to(prefix)
    except ValueError as error:
        raise DevelopmentInstallError(
            "Development Python dependencies must come from its protected installation prefix"
        ) from error
    try:
        required_paths: set[Path] = {executable}
        required_paths.update(
            path
            for path in prefix.iterdir()
            if path.is_file() and path.suffix.casefold() in {".dll", ".exe"}
        )
        dll_root = prefix / "DLLs"
        if dll_root.is_dir():
            required_paths.update(
                path for path in dll_root.rglob("*") if path.is_file()
            )
        required_paths.update(
            path
            for path in stdlib.rglob("*")
            if path.is_file()
            and purelib not in path.parents
            and "__pycache__" not in path.parts
        )
        for module in modules:
            if module.is_dir():
                required_paths.update(
                    path
                    for path in module.rglob("*")
                    if path.is_file() and "__pycache__" not in path.parts
                )
            else:
                required_paths.add(module)
        verify_readonly_dependency_root(prefix, required_paths=required_paths)
    except DevelopmentRuntimeError as error:
        raise DevelopmentInstallError(str(error)) from error
    return ".".join(str(part) for part in version)


def _mcp_configuration(codex: str, runner: Runner) -> CommandResult | None:
    result = runner((codex, "mcp", "get", MCP_NAME, "--json"))
    if result.returncode == 0:
        return result
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if "no mcp server named" in combined or "not found" in combined:
        return None
    _require_success(result, "Reading the existing Card Service registration")
    return None


def _stdio_configuration(
    configuration: CommandResult,
) -> tuple[str, tuple[str, ...], dict[str, str]] | None:
    try:
        payload = json.loads(configuration.stdout)
        transport = payload["transport"]
        if transport.get("type") != "stdio" or transport.get("cwd") not in (None, ""):
            return None
        command = transport["command"]
        arguments = transport.get("args") or []
        environment = transport.get("env") or {}
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(command, str) or not command:
        return None
    if not isinstance(arguments, list) or any(
        not isinstance(item, str) for item in arguments
    ):
        return None
    if not isinstance(environment, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in environment.items()
    ):
        return None
    return command, tuple(arguments), dict(environment)


def _private_runtime_root(user_profile: Path) -> Path:
    return (user_profile.resolve() / APP_FOLDER / RUNTIME_FOLDER).resolve()


def _owned_mcp_details(
    configuration: CommandResult,
    *,
    python: Path,
    user_profile: Path,
) -> tuple[Path, int] | None:
    parsed = _stdio_configuration(configuration)
    if parsed is None:
        return None
    command, arguments, environment = parsed
    if (
        environment
        or _canonical_path(command) != python.resolve()
        or len(arguments) != 6
    ):
        return None
    if arguments[:3] != ("-I", "-S", "-B") or arguments[4] != "--anki-connect-port":
        return None
    try:
        port = int(arguments[5])
    except ValueError:
        return None
    if str(port) != arguments[5] or not 1 <= port <= 65535:
        return None
    launcher = _canonical_path(arguments[3])
    if launcher.name != LAUNCHER_NAME:
        return None
    snapshot = launcher.parent
    if _DIGEST_RE.fullmatch(
        snapshot.name
    ) is None or snapshot.parent != _private_runtime_root(user_profile):
        return None
    try:
        # A pre-fix trusted UI child could leave only CPython bytecode caches in
        # an otherwise intact private snapshot.  That snapshot remains invalid
        # for execution, but it is still safe to identify as our prior
        # registration so the installer can replace it transactionally.
        verify_development_runtime(
            snapshot,
            expected_python=python,
            verify_acl=True,
            allow_unexpected_bytecode_cache=True,
        )
    except (DevelopmentRuntimeError, OSError):
        return None
    return launcher, port


def _desired_mcp_configuration(
    python: Path, launcher: Path, anki_connect_port: int
) -> tuple[str, tuple[str, ...], dict[str, str]]:
    return (
        str(python.resolve()),
        (
            "-I",
            "-S",
            "-B",
            str(launcher.resolve()),
            "--anki-connect-port",
            str(anki_connect_port),
        ),
        {},
    )


def _add_mcp_configuration(
    codex: str,
    configuration: tuple[str, tuple[str, ...], dict[str, str]],
    runner: Runner,
) -> CommandResult:
    command, arguments, environment = configuration
    invocation: list[str] = [codex, "mcp", "add", MCP_NAME]
    for key in sorted(environment):
        invocation.extend(("--env", f"{key}={environment[key]}"))
    invocation.extend(("--", command, *arguments))
    return runner(tuple(invocation))


def register_development_mcp(
    *,
    codex: str,
    python: Path,
    launcher: Path,
    user_profile: Path,
    anki_connect_port: int,
    runner: Runner = _run_command,
) -> tuple[str, tuple[str, tuple[str, ...], dict[str, str]] | None]:
    existing = _mcp_configuration(codex, runner)
    desired = _desired_mcp_configuration(python, launcher, anki_connect_port)
    previous: tuple[str, tuple[str, ...], dict[str, str]] | None = None
    if existing is not None:
        previous = _stdio_configuration(existing)
        if previous == desired:
            return "already_configured", previous
        if (
            _owned_mcp_details(existing, python=python, user_profile=user_profile)
            is None
        ):
            raise DevelopmentInstallError(
                f"An unrelated MCP server already uses the name {MCP_NAME}"
            )
        assert previous is not None
        current = _mcp_configuration(codex, runner)
        if current is None or _stdio_configuration(current) != previous:
            raise DevelopmentInstallError(
                "The Card Service MCP changed during registration; replacement stopped"
            )
        _require_success(
            runner((codex, "mcp", "remove", MCP_NAME)),
            "Removing the prior Card Service MCP",
        )
    added = _add_mcp_configuration(codex, desired, runner)
    if added.returncode != 0:
        restored = previous is None
        if previous is not None:
            restored = _add_mcp_configuration(codex, previous, runner).returncode == 0
        raise DevelopmentInstallError(
            "Registering the development Card Service MCP failed"
            + (
                "; the previous registration was restored"
                if restored and previous
                else ""
            ),
            partial=not restored,
            failed_step="mcp_add",
            unrecovered=() if restored else (MCP_NAME,),
        )
    return ("replaced" if existing is not None else "added"), previous


def _probe_anki_connect(port: int) -> bool:
    body = json.dumps({"action": "version", "version": 6}).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=0.6) as response:
            payload = response.read(4097)
    except (OSError, urllib.error.URLError, TimeoutError):
        return False
    if len(payload) > 4096:
        return False
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    return isinstance(parsed, dict) and isinstance(parsed.get("result"), int)


def choose_anki_connect_port(explicit: int | None) -> tuple[int, str]:
    if explicit is not None:
        if not 1 <= explicit <= 65535:
            raise DevelopmentInstallError(
                "AnkiConnect port must be between 1 and 65535"
            )
        return explicit, "explicit"
    active = [port for port in (8765, 8785) if _probe_anki_connect(port)]
    if len(active) == 1:
        return active[0], "detected"
    if len(active) > 1:
        return 8765, "multiple_detected_defaulted"
    return 8765, "default_unverified"


def _default_cachebuster_updater(plugin_root: Path) -> CommandResult:
    helper = (
        Path.home()
        / ".codex"
        / "skills"
        / ".system"
        / "plugin-creator"
        / "scripts"
        / "update_plugin_cachebuster.py"
    )
    if not helper.is_file():
        raise DevelopmentInstallError(
            "The official Plugin Creator cachebuster helper is unavailable"
        )
    return _run_command((sys.executable, str(helper), str(plugin_root)))


def _restore_bytes(path: Path, source: bytes) -> None:
    handle, raw = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".restore", dir=path.parent
    )
    temporary = Path(raw)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _rollback_mcp(
    codex: str,
    previous: tuple[str, tuple[str, ...], dict[str, str]] | None,
    expected_current: tuple[str, tuple[str, ...], dict[str, str]],
    runner: Runner,
) -> bool:
    current = _mcp_configuration(codex, runner)
    if current is None or _stdio_configuration(current) != expected_current:
        return False
    removed = runner((codex, "mcp", "remove", MCP_NAME)).returncode == 0
    if not removed:
        return False
    return (
        previous is None
        or _add_mcp_configuration(codex, previous, runner).returncode == 0
    )


def register_development_marketplace(
    *,
    codex: str,
    marketplace_root: Path,
    user_profile: Path,
    runner: Runner = _run_command,
) -> tuple[str, Path | None]:
    desired = marketplace_root.resolve()
    if not _owned_marketplace_root(desired, user_profile=user_profile):
        raise DevelopmentInstallError(
            "The development marketplace snapshot failed verification"
        )
    roots = _marketplace_roots(codex, runner)
    previous = roots.get(MARKETPLACE_NAME)
    if previous == desired:
        return "already_configured", previous
    if previous is not None and not _owned_marketplace_root(
        previous, user_profile=user_profile
    ):
        raise DevelopmentInstallError(
            "The configured marketplace name points to an unrelated source"
        )
    current = _marketplace_roots(codex, runner).get(MARKETPLACE_NAME)
    if current != previous:
        raise DevelopmentInstallError(
            "The marketplace changed during registration; replacement stopped"
        )
    if previous is not None:
        _require_success(
            runner(
                (codex, "plugin", "marketplace", "remove", MARKETPLACE_NAME, "--json")
            ),
            "Removing the prior local Codex marketplace",
        )
    added = runner((codex, "plugin", "marketplace", "add", str(desired), "--json"))
    if added.returncode != 0:
        restored = previous is None or _restore_marketplace_registration(
            codex,
            runner,
            expected_root=previous,
            user_profile=user_profile,
        )
        raise DevelopmentInstallError(
            "Registering the private development marketplace failed",
            partial=not restored,
            failed_step="marketplace_add",
            unrecovered=() if restored else ("marketplace",),
        )
    return ("replaced" if previous is not None else "added"), previous


def _rollback_marketplace(
    codex: str,
    *,
    previous: Path | None,
    expected_current: Path,
    user_profile: Path,
    runner: Runner,
) -> bool:
    current = _marketplace_roots(codex, runner).get(MARKETPLACE_NAME)
    if current != expected_current:
        return False
    if not _remove_owned_marketplace(
        codex,
        runner,
        expected_root=expected_current,
        user_profile=user_profile,
    ):
        return False
    return previous is None or _restore_marketplace_registration(
        codex,
        runner,
        expected_root=previous,
        user_profile=user_profile,
    )


def _restore_mcp_registration(
    codex: str,
    previous: tuple[str, tuple[str, ...], dict[str, str]],
    runner: Runner,
) -> bool:
    try:
        current = _mcp_configuration(codex, runner)
        if current is not None:
            return _stdio_configuration(current) == previous
        if _add_mcp_configuration(codex, previous, runner).returncode != 0:
            return False
        restored = _mcp_configuration(codex, runner)
        return restored is not None and _stdio_configuration(restored) == previous
    except DevelopmentInstallError:
        return False


def _restore_marketplace_registration(
    codex: str,
    runner: Runner,
    *,
    expected_root: Path,
    user_profile: Path,
) -> bool:
    try:
        if not _owned_marketplace_root(expected_root, user_profile=user_profile):
            return False
        roots = _marketplace_roots(codex, runner)
        current = roots.get(MARKETPLACE_NAME)
        if current is not None:
            return current == expected_root
        if (
            runner(
                (codex, "plugin", "marketplace", "add", str(expected_root), "--json")
            ).returncode
            != 0
        ):
            return False
        return _marketplace_roots(codex, runner).get(MARKETPLACE_NAME) == expected_root
    except DevelopmentInstallError:
        return False


def _restore_plugin_registration(
    codex: str,
    runner: Runner,
    *,
    expected_snapshot: Path,
    expected_version: str,
    user_profile: Path,
) -> bool:
    def matches(row: Mapping[str, object] | None) -> bool:
        details = _owned_plugin_details(row, user_profile=user_profile)
        return (
            details is not None
            and details[0] == expected_snapshot
            and details[2] == expected_version
            and row is not None
            and row.get("installed") is True
        )

    try:
        current = _plugin_row(codex, runner)
        if current is not None:
            return matches(current)
        if _marketplace_roots(codex, runner).get(MARKETPLACE_NAME) != expected_snapshot:
            return False
        if runner((codex, "plugin", "add", PLUGIN_SELECTOR, "--json")).returncode != 0:
            return False
        restored = _plugin_row(codex, runner)
        return matches(restored)
    except DevelopmentInstallError:
        return False


def _remove_owned_plugin(
    codex: str,
    runner: Runner,
    *,
    expected_snapshot: Path,
    user_profile: Path,
) -> bool:
    try:
        current = _plugin_row(codex, runner)
        if current is None:
            return True
        details = _owned_plugin_details(current, user_profile=user_profile)
        if details is None or details[0] != expected_snapshot:
            return False
        if (
            runner((codex, "plugin", "remove", PLUGIN_SELECTOR, "--json")).returncode
            != 0
        ):
            return False
        return _plugin_row(codex, runner) is None
    except DevelopmentInstallError:
        return False


def _remove_owned_marketplace(
    codex: str,
    runner: Runner,
    *,
    expected_root: Path,
    user_profile: Path,
) -> bool:
    try:
        current = _marketplace_roots(codex, runner).get(MARKETPLACE_NAME)
        if current is None:
            return True
        if current != expected_root or not _owned_marketplace_root(
            current, user_profile=user_profile
        ):
            return False
        if (
            runner(
                (codex, "plugin", "marketplace", "remove", MARKETPLACE_NAME, "--json")
            ).returncode
            != 0
        ):
            return False
        return MARKETPLACE_NAME not in _marketplace_roots(codex, runner)
    except DevelopmentInstallError:
        return False


def _verify_installed_state(
    *,
    codex: str,
    runner: Runner,
    expected_version: str,
    expected_marketplace_root: Path,
    expected_launcher: Path,
    python: Path,
    user_profile: Path,
) -> None:
    roots = _marketplace_roots(codex, runner)
    if roots.get(MARKETPLACE_NAME) != expected_marketplace_root:
        raise DevelopmentInstallError(
            "The installed marketplace root failed verification"
        )
    row = _plugin_row(codex, runner)
    plugin_details = _owned_plugin_details(row, user_profile=user_profile)
    if (
        plugin_details is None
        or plugin_details[0] != expected_marketplace_root
        or row.get("installed") is not True
        or row.get("enabled") is not True
        or row.get("version") != expected_version
    ):
        raise DevelopmentInstallError("The installed plugin failed verification")
    mcp = _mcp_configuration(codex, runner)
    details = (
        _owned_mcp_details(mcp, python=python, user_profile=user_profile)
        if mcp is not None
        else None
    )
    if details is None or details[0] != expected_launcher.resolve():
        raise DevelopmentInstallError(
            "The installed Card Service MCP failed verification"
        )


def _install_or_upgrade_locked(
    *,
    action: str,
    codex: str,
    python: Path,
    anki_connect_port: int | None,
    stage_tools: bool,
    runner: Runner = _run_command,
    cachebuster_updater: CachebusterUpdater = _default_cachebuster_updater,
    user_profile: Path | None = None,
) -> dict[str, object]:
    if action not in {"install", "upgrade"}:
        raise DevelopmentInstallError("Development plugin action is invalid")
    _ensure_repository_shape()
    codex_version = verify_codex_version(codex, runner)
    python_version = verify_development_python(python)
    port, port_source = choose_anki_connect_port(anki_connect_port)
    profile = (user_profile or Path.home()).resolve(strict=True)
    roots_before = _marketplace_roots(codex, runner)
    configured_root = roots_before.get(MARKETPLACE_NAME)
    if configured_root is not None and not _owned_marketplace_root(
        configured_root, user_profile=profile
    ):
        raise DevelopmentInstallError(
            "The configured marketplace name points to an unrelated source"
        )
    plugin_before = _plugin_row(codex, runner)
    plugin_before_details = (
        _owned_plugin_details(plugin_before, user_profile=profile)
        if plugin_before is not None
        else None
    )
    if plugin_before is not None and plugin_before_details is None:
        raise DevelopmentInstallError(
            "The installed plugin selector belongs to another source"
        )
    if (
        plugin_before_details is not None
        and configured_root != plugin_before_details[0]
    ):
        raise DevelopmentInstallError(
            "The installed plugin and marketplace snapshots do not match"
        )
    if action == "upgrade" and plugin_before is None:
        raise DevelopmentInstallError(
            "The Anki Study Agent plugin must be installed before upgrade"
        )
    if action == "install" and plugin_before is not None:
        raise DevelopmentInstallError(
            "The Anki Study Agent plugin is already installed; use upgrade to refresh it"
        )
    mcp_before_result = _mcp_configuration(codex, runner)
    if (
        mcp_before_result is not None
        and _owned_mcp_details(mcp_before_result, python=python, user_profile=profile)
        is None
    ):
        raise DevelopmentInstallError(
            f"An unrelated MCP server already uses the name {MCP_NAME}"
        )

    try:
        snapshot = build_development_runtime(
            repository_root=ROOT,
            launcher_source=DEV_LAUNCHER_SOURCE,
            python_executable=python,
            user_profile=profile,
            include_tools=stage_tools,
        )
    except DevelopmentRuntimeError as error:
        raise DevelopmentInstallError(
            str(error), failed_step="runtime_snapshot"
        ) from error

    manifest_before: bytes | None = None
    old_version = _plugin_version()
    expected_version = old_version
    plugin_snapshot = None
    marketplace_state = "unknown"
    marketplace_changed = False
    previous_marketplace = configured_root
    mcp_changed = False
    desired_mcp = _desired_mcp_configuration(python, snapshot.launcher, port)
    previous_mcp = (
        _stdio_configuration(mcp_before_result) if mcp_before_result else None
    )
    plugin_write_attempted = False
    failed_step = "unknown"
    try:
        if action == "upgrade":
            failed_step = "cachebuster"
            manifest_before = PLUGIN_MANIFEST.read_bytes()
            _require_success(
                cachebuster_updater(PLUGIN_ROOT), "Updating the plugin cachebuster"
            )
            expected_version = _plugin_version()
            if expected_version == old_version:
                raise DevelopmentInstallError(
                    "The plugin cachebuster did not change the version"
                )
        failed_step = "plugin_snapshot"
        plugin_snapshot = build_development_plugin_snapshot(
            repository_root=ROOT, user_profile=profile
        )
        if plugin_snapshot.version != expected_version:
            raise DevelopmentInstallError(
                "The private plugin snapshot version failed verification"
            )
        failed_step = "marketplace_add"
        marketplace_state, previous_marketplace = register_development_marketplace(
            codex=codex,
            marketplace_root=plugin_snapshot.root,
            user_profile=profile,
            runner=runner,
        )
        marketplace_changed = marketplace_state != "already_configured"
        failed_step = "mcp_add"
        mcp_state, _ = register_development_mcp(
            codex=codex,
            python=python,
            launcher=snapshot.launcher,
            user_profile=profile,
            anki_connect_port=port,
            runner=runner,
        )
        mcp_changed = mcp_state != "already_configured"
        failed_step = "plugin_add"
        plugin_write_attempted = True
        _require_success(
            runner((codex, "plugin", "add", PLUGIN_SELECTOR, "--json")),
            "Installing the Anki Study Agent plugin",
        )
        failed_step = "verification"
        _verify_installed_state(
            codex=codex,
            runner=runner,
            expected_version=expected_version,
            expected_marketplace_root=plugin_snapshot.root,
            expected_launcher=snapshot.launcher,
            python=python,
            user_profile=profile,
        )
    except Exception as error:
        inherited = error if isinstance(error, DevelopmentInstallError) else None
        unrecovered: list[str] = list(inherited.unrecovered if inherited else ())
        manifest_restored = False
        if manifest_before is not None:
            try:
                _restore_bytes(PLUGIN_MANIFEST, manifest_before)
                manifest_restored = True
            except OSError:
                unrecovered.append("plugin_manifest")
        if plugin_snapshot is not None and plugin_write_attempted:
            try:
                current_plugin = _plugin_row(codex, runner)
                current_details = (
                    _owned_plugin_details(current_plugin, user_profile=profile)
                    if current_plugin is not None
                    else None
                )
                prior_snapshot = (
                    plugin_before_details[0]
                    if plugin_before_details is not None
                    else None
                )
                if (
                    current_details is not None
                    and current_details[0] == plugin_snapshot.root
                ):
                    if not _remove_owned_plugin(
                        codex,
                        runner,
                        expected_snapshot=plugin_snapshot.root,
                        user_profile=profile,
                    ):
                        unrecovered.append("plugin")
                elif current_plugin is not None and (
                    current_details is None or current_details[0] != prior_snapshot
                ):
                    unrecovered.append("plugin")
            except DevelopmentInstallError:
                unrecovered.append("plugin")
        if mcp_changed and not _rollback_mcp(codex, previous_mcp, desired_mcp, runner):
            unrecovered.append("mcp")
        if marketplace_changed and plugin_snapshot is not None:
            if not _rollback_marketplace(
                codex,
                previous=previous_marketplace,
                expected_current=plugin_snapshot.root,
                user_profile=profile,
                runner=runner,
            ):
                unrecovered.append("marketplace")
        if plugin_before_details is not None and (
            marketplace_changed or plugin_write_attempted
        ):
            if not _restore_plugin_registration(
                codex,
                runner,
                expected_snapshot=plugin_before_details[0],
                expected_version=plugin_before_details[2],
                user_profile=profile,
            ):
                unrecovered.append("plugin")
        unrecovered = list(dict.fromkeys(unrecovered))
        message = (
            str(error)
            if isinstance(error, DevelopmentInstallError)
            else "Installation transaction failed"
        )
        raise DevelopmentInstallError(
            message,
            partial=bool(unrecovered) or bool(inherited and inherited.partial),
            failed_step=(
                inherited.failed_step
                if inherited and inherited.failed_step
                else failed_step
            ),
            unrecovered=unrecovered,
        ) from error
    return {
        "ok": True,
        "mode": "development_private_snapshot",
        "productionSigned": False,
        "codexVersion": codex_version,
        "pythonVersion": python_version,
        "marketplace": marketplace_state,
        "pluginSnapshotRoot": str(plugin_snapshot.root),
        "pluginSnapshotManifestSha256": plugin_snapshot.manifest_sha256,
        "pluginSnapshotResourceCount": plugin_snapshot.resource_count,
        "plugin": PLUGIN_SELECTOR,
        "pluginVersion": expected_version,
        "mcp": mcp_state,
        "runtimeRoot": str(snapshot.root),
        "runtimeManifestSha256": snapshot.manifest_sha256,
        "runtimeResourceCount": snapshot.resource_count,
        "ankiConnectPort": port,
        "ankiConnectPortSource": port_source,
        "tools": {
            "staged": list(snapshot.tools),
            "missing": list(snapshot.missing_tools),
        },
        "newThreadRequired": True,
    }


def install_or_upgrade(
    *,
    action: str,
    codex: str,
    python: Path,
    anki_connect_port: int | None,
    stage_tools: bool,
    runner: Runner = _run_command,
    cachebuster_updater: CachebusterUpdater = _default_cachebuster_updater,
    user_profile: Path | None = None,
) -> dict[str, object]:
    with _installer_mutex():
        return _install_or_upgrade_locked(
            action=action,
            codex=codex,
            python=python,
            anki_connect_port=anki_connect_port,
            stage_tools=stage_tools,
            runner=runner,
            cachebuster_updater=cachebuster_updater,
            user_profile=user_profile,
        )


def _uninstall_locked(
    *,
    codex: str,
    python: Path,
    remove_marketplace: bool,
    runner: Runner = _run_command,
    user_profile: Path | None = None,
) -> dict[str, object]:
    profile = (user_profile or Path.home()).resolve(strict=True)
    roots = _marketplace_roots(codex, runner)
    configured_root = roots.get(MARKETPLACE_NAME)
    if configured_root is not None and not _owned_marketplace_root(
        configured_root, user_profile=profile
    ):
        raise DevelopmentInstallError(
            "The marketplace name belongs to an unrelated source"
        )
    plugin = _plugin_row(codex, runner)
    plugin_details = (
        _owned_plugin_details(plugin, user_profile=profile)
        if plugin is not None
        else None
    )
    if plugin is not None and plugin_details is None:
        raise DevelopmentInstallError("The plugin selector belongs to another source")
    if plugin_details is not None and configured_root != plugin_details[0]:
        raise DevelopmentInstallError(
            "The installed plugin and marketplace snapshots do not match"
        )
    mcp = _mcp_configuration(codex, runner)
    if (
        mcp is not None
        and _owned_mcp_details(mcp, python=python, user_profile=profile) is None
    ):
        raise DevelopmentInstallError(
            f"The same-name MCP is unrelated or damaged; nothing was removed"
        )

    plugin_removed = False
    mcp_removed = False
    if plugin is not None:
        _require_success(
            runner((codex, "plugin", "remove", PLUGIN_SELECTOR, "--json")),
            "Removing the Anki Study Agent plugin",
        )
        plugin_removed = True
    if mcp is not None:
        current = _mcp_configuration(codex, runner)
        if current is None or _stdio_configuration(current) != _stdio_configuration(
            mcp
        ):
            unrecovered = ["mcp"]
            if plugin_removed and not _restore_plugin_registration(
                codex,
                runner,
                expected_snapshot=plugin_details[0],
                expected_version=plugin_details[2],
                user_profile=profile,
            ):
                unrecovered.append("plugin")
            raise DevelopmentInstallError(
                "The MCP changed during uninstall; removal stopped",
                partial=True,
                failed_step="mcp_remove",
                unrecovered=unrecovered,
            )
        result = runner((codex, "mcp", "remove", MCP_NAME))
        if result.returncode != 0:
            previous_mcp = _stdio_configuration(mcp)
            assert previous_mcp is not None
            unrecovered = []
            if not _restore_mcp_registration(codex, previous_mcp, runner):
                unrecovered.append("mcp")
            if plugin_removed and not _restore_plugin_registration(
                codex,
                runner,
                expected_snapshot=plugin_details[0],
                expected_version=plugin_details[2],
                user_profile=profile,
            ):
                unrecovered.append("plugin")
            raise DevelopmentInstallError(
                "Removing the Card Service MCP failed",
                partial=bool(unrecovered),
                failed_step="mcp_remove",
                unrecovered=unrecovered,
            )
        mcp_removed = True
    marketplace_state = "kept"
    if remove_marketplace and configured_root is not None:
        current_roots = _marketplace_roots(codex, runner)
        if current_roots.get(MARKETPLACE_NAME) != configured_root:
            unrecovered = ["marketplace"]
            previous_mcp = _stdio_configuration(mcp) if mcp is not None else None
            if previous_mcp is not None and mcp_removed:
                if not _restore_mcp_registration(codex, previous_mcp, runner):
                    unrecovered.append("mcp")
            if plugin_removed and not _restore_plugin_registration(
                codex,
                runner,
                expected_snapshot=plugin_details[0],
                expected_version=plugin_details[2],
                user_profile=profile,
            ):
                unrecovered.append("plugin")
            raise DevelopmentInstallError(
                "The marketplace changed during uninstall; removal stopped",
                partial=True,
                failed_step="marketplace_remove",
                unrecovered=unrecovered,
            )
        removed = runner(
            (codex, "plugin", "marketplace", "remove", MARKETPLACE_NAME, "--json")
        )
        if removed.returncode != 0:
            unrecovered = []
            if not _restore_marketplace_registration(
                codex,
                runner,
                expected_root=configured_root,
                user_profile=profile,
            ):
                unrecovered.append("marketplace")
            previous_mcp = _stdio_configuration(mcp) if mcp is not None else None
            if previous_mcp is not None and mcp_removed:
                if not _restore_mcp_registration(codex, previous_mcp, runner):
                    unrecovered.append("mcp")
            if plugin_removed and not _restore_plugin_registration(
                codex,
                runner,
                expected_snapshot=plugin_details[0],
                expected_version=plugin_details[2],
                user_profile=profile,
            ):
                unrecovered.append("plugin")
            raise DevelopmentInstallError(
                "Removing the local marketplace failed",
                partial=bool(unrecovered),
                failed_step="marketplace_remove",
                unrecovered=unrecovered,
            )
        marketplace_state = "removed"
    return {
        "ok": True,
        "mode": "development_private_snapshot",
        "pluginRemoved": plugin_removed,
        "mcpRemoved": mcp_removed,
        "marketplace": marketplace_state,
        "runtimeAndUserDataPreserved": True,
    }


def uninstall(
    *,
    codex: str,
    python: Path,
    remove_marketplace: bool,
    runner: Runner = _run_command,
    user_profile: Path | None = None,
) -> dict[str, object]:
    with _installer_mutex():
        return _uninstall_locked(
            codex=codex,
            python=python,
            remove_marketplace=remove_marketplace,
            runner=runner,
            user_profile=user_profile,
        )


def _existing_executable(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError("Python executable does not exist")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Install the Anki Study Agent skill and an explicitly trusted, private development "
            "Card Service snapshot. This command never creates a production-signed package."
        )
    )
    parser.add_argument("action", choices=("install", "upgrade", "uninstall"))
    parser.add_argument("--codex", default=shutil.which("codex") or "codex")
    parser.add_argument(
        "--python", type=_existing_executable, default=Path(sys.executable).resolve()
    )
    parser.add_argument("--anki-connect-port", type=int)
    parser.add_argument("--skip-tool-staging", action="store_true")
    parser.add_argument("--remove-marketplace", action="store_true")
    options = parser.parse_args()
    try:
        if options.action == "uninstall":
            result = uninstall(
                codex=options.codex,
                python=options.python,
                remove_marketplace=options.remove_marketplace,
            )
        else:
            result = install_or_upgrade(
                action=options.action,
                codex=options.codex,
                python=options.python,
                anki_connect_port=options.anki_connect_port,
                stage_tools=not options.skip_tool_staging,
            )
    except (
        DevelopmentInstallError,
        DevelopmentRuntimeError,
        OSError,
        ValueError,
    ) as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "DEVELOPMENT_INSTALL_FAILED",
                    "message": str(error),
                    "partial": bool(getattr(error, "partial", False)),
                    "failedStep": getattr(error, "failed_step", None),
                    "unrecovered": list(getattr(error, "unrecovered", ())),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        raise SystemExit(2) from error
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
