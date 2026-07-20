from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import stat
import sys
from pathlib import Path


ERROR_PREFIX = "__ANKI_CARD_ERROR__"
ALLOWED_COMMANDS = frozenset(
    {
        "check_env",
        "test_api",
        "test_tts",
        "extract_learning_points",
        "generate_cards_from_learning_points",
        "generate",
        "export",
        "verify_anki_import",
        "parse_source_document",
    }
)
MAX_BOOTSTRAP_ENVELOPE_BYTES = 64 * 1024 * 1024
MAX_RUNTIME_MANIFEST_BYTES = 8 * 1024 * 1024
STDIN_RUNTIME_MANIFEST = "@stdin"
_WORKER_HANDOFF_COMPLETE = False
_BOOTSTRAP_STAGE = "arguments"


def _has_reparse_attribute(value: os.stat_result) -> bool:
    return bool(
        getattr(value, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _lexical_runtime_path(
    value: str | Path,
    *,
    runtime_root: Path | None,
    expect_directory: bool,
    checked_components: set[str],
) -> Path:
    """Validate an immutable runtime path without Win32 strict realpath handles.

    AppContainer tokens can open and hash files allowed by the runtime DACL while
    ``realpath(strict=True)`` still fails because it requests a stronger handle.
    The trusted host has already verified the signed tree.  The bootstrap repeats
    the security-critical lexical containment, no-reparse and file-kind checks
    using lstat-style metadata that the read-only token can obtain.
    """

    candidate = Path(value)
    if not candidate.is_absolute():
        raise SystemExit("managed runtime path is not absolute")
    normalized = Path(os.path.abspath(os.path.normpath(str(candidate))))
    if os.path.normcase(str(candidate)) != os.path.normcase(str(normalized)):
        raise SystemExit("managed runtime path is not canonical")
    components: list[Path]
    if runtime_root is None:
        components = [normalized]
    else:
        root_key = os.path.normcase(os.path.normpath(str(runtime_root)))
        candidate_key = os.path.normcase(os.path.normpath(str(normalized)))
        try:
            common = os.path.commonpath((root_key, candidate_key))
        except ValueError as error:
            raise SystemExit("managed runtime path escaped its root") from error
        if common != root_key:
            raise SystemExit("managed runtime path escaped its root")

        relative = Path(os.path.relpath(str(normalized), str(runtime_root)))
        current = runtime_root
        components = [runtime_root]
        if relative != Path("."):
            for part in relative.parts:
                current /= part
                components.append(current)
    latest: os.stat_result | None = None
    for component in components:
        component_key = os.path.normcase(os.path.normpath(str(component)))
        if component_key in checked_components:
            latest = None
            continue
        try:
            latest = os.stat(component, follow_symlinks=False)
        except OSError as error:
            raise SystemExit("managed runtime path is unavailable") from error
        if stat.S_ISLNK(latest.st_mode) or _has_reparse_attribute(latest):
            raise SystemExit("managed runtime path contains a reparse point")
        checked_components.add(component_key)
    if latest is None:
        try:
            latest = os.stat(normalized, follow_symlinks=False)
        except OSError as error:
            raise SystemExit("managed runtime path is unavailable") from error
    if expect_directory:
        if not stat.S_ISDIR(latest.st_mode):
            raise SystemExit("managed runtime directory is invalid")
    elif not stat.S_ISREG(latest.st_mode):
        raise SystemExit("managed runtime file is invalid")
    return normalized


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    global _BOOTSTRAP_STAGE, _WORKER_HANDOFF_COMPLETE
    if len(sys.argv) != 6:
        raise SystemExit("invalid managed worker bootstrap arguments")
    bootstrap_runtime_root = Path(os.path.abspath(os.path.normpath(str(Path(__file__).parent.parent))))
    checked_components: set[str] = set()
    managed_runtime = os.environ.get("ACG_MANAGED_RUNTIME") == "1"
    if managed_runtime:
        configured_runtime_root = str(os.environ.get("ACG_MANAGED_RUNTIME_ROOT") or "").strip()
        if not configured_runtime_root:
            raise SystemExit("managed runtime root is missing")
        runtime_root = _lexical_runtime_path(
            configured_runtime_root,
            runtime_root=bootstrap_runtime_root,
            expect_directory=True,
            checked_components=checked_components,
        )
        if os.path.normcase(str(runtime_root)) != os.path.normcase(str(bootstrap_runtime_root)):
            raise SystemExit("managed runtime root changed")
    else:
        # Development restricted-mode tests can intentionally stage a frozen Worker
        # outside the source tree. Its exact path and digest remain bound by the
        # service-owned manifest, but it is not a signed packaged-runtime subtree.
        runtime_root = None
    _BOOTSTRAP_STAGE = "worker_entry"
    worker_path = _lexical_runtime_path(
        sys.argv[1],
        runtime_root=runtime_root,
        expect_directory=False,
        checked_components=checked_components,
    )
    command = sys.argv[2]
    expected_sha256 = sys.argv[3].lower()
    runtime_manifest_reference = sys.argv[4]
    expected_manifest_sha256 = sys.argv[5].lower()
    if command not in ALLOWED_COMMANDS:
        raise SystemExit("managed worker command is not allowed")
    source = worker_path.read_bytes()
    actual_sha256 = hashlib.sha256(source).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise SystemExit("managed worker digest changed")
    _BOOTSTRAP_STAGE = "runtime_manifest_read"
    if runtime_manifest_reference == STDIN_RUNTIME_MANIFEST:
        manifest_line = sys.stdin.buffer.readline(MAX_RUNTIME_MANIFEST_BYTES + 1)
        if not manifest_line or len(manifest_line) > MAX_RUNTIME_MANIFEST_BYTES:
            raise SystemExit("managed runtime manifest is missing or too large")
        manifest_source = manifest_line.rstrip(b"\r\n")
    else:
        runtime_manifest_path = Path(runtime_manifest_reference).resolve(strict=True)
        manifest_source = runtime_manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_source).hexdigest()
    if not hmac.compare_digest(manifest_sha256, expected_manifest_sha256):
        raise SystemExit("managed runtime manifest digest changed")
    _BOOTSTRAP_STAGE = "runtime_manifest_parse"
    try:
        manifest = json.loads(manifest_source)
    except ValueError as error:
        raise SystemExit("managed runtime manifest is invalid") from error
    entries = manifest.get("entries") if isinstance(manifest, dict) and manifest.get("schemaVersion") == 1 else None
    if not isinstance(entries, list) or not entries:
        raise SystemExit("managed runtime manifest is invalid")
    declared_runtime_root = manifest.get("runtimeRoot")
    if declared_runtime_root is not None:
        if not isinstance(declared_runtime_root, str):
            raise SystemExit("managed runtime manifest root is invalid")
        declared_root = _lexical_runtime_path(
            declared_runtime_root,
            runtime_root=runtime_root,
            expect_directory=True,
            checked_components=checked_components,
        )
        if runtime_root is not None and os.path.normcase(str(declared_root)) != os.path.normcase(str(runtime_root)):
            raise SystemExit("managed runtime manifest root changed")
        entry_runtime_root: Path | None = declared_root
    else:
        if managed_runtime:
            raise SystemExit("managed runtime manifest root is missing")
        entry_runtime_root = None
    _BOOTSTRAP_STAGE = "runtime_entry_verification"
    worker_manifest_verified = False
    broker_client_path: Path | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("managed runtime manifest entry is invalid")
        path = _lexical_runtime_path(
            str(entry.get("path") or ""),
            runtime_root=entry_runtime_root,
            expect_directory=False,
            checked_components=checked_components,
        )
        try:
            size = path.stat().st_size
            digest = _file_sha256(path)
        except OSError as error:
            raise SystemExit("managed runtime entry is unavailable") from error
        if size != entry.get("size") or not hmac.compare_digest(digest, str(entry.get("sha256") or "")):
            raise SystemExit("managed runtime entry changed")
        if os.path.normcase(str(path)) == os.path.normcase(str(worker_path)):
            worker_manifest_verified = hmac.compare_digest(digest, expected_sha256)
        if entry.get("resourceId") == "card-service:broker-client":
            broker_client_path = path
    if not worker_manifest_verified:
        raise SystemExit("managed worker is missing from the runtime manifest")
    _BOOTSTRAP_STAGE = "worker_module_root"
    if runtime_root is not None:
        worker_module_root = runtime_root / "workers"
    else:
        if broker_client_path is None or broker_client_path.parent.name != "acg":
            raise SystemExit("managed broker client is missing from the runtime manifest")
        worker_module_root = broker_client_path.parent.parent
    managed_workers_root = _lexical_runtime_path(
        worker_module_root,
        runtime_root=runtime_root,
        expect_directory=True,
        checked_components=checked_components,
    )
    sys.path.insert(0, str(worker_path.parent))
    sys.path.insert(0, str(managed_workers_root))
    control_stdin = sys.stdin
    control_stderr = sys.stderr
    _BOOTSTRAP_STAGE = "launch_envelope"
    payload_line = control_stdin.readline(MAX_BOOTSTRAP_ENVELOPE_BYTES + 1)
    if not payload_line or len(payload_line.encode("utf-8")) > MAX_BOOTSTRAP_ENVELOPE_BYTES:
        raise SystemExit("managed worker bootstrap envelope is missing or too large")
    try:
        envelope = json.loads(payload_line)
    except ValueError:
        envelope = None
    if isinstance(envelope, dict) and envelope.get("schemaVersion") == 1 and isinstance(envelope.get("request"), dict):
        descriptor = envelope.get("brokerDescriptor")
        if descriptor is not None:
            _BOOTSTRAP_STAGE = "broker_configuration"
            if not isinstance(descriptor, dict):
                raise SystemExit("managed worker broker descriptor is invalid")
            from acg.broker_client import configure_stdio_broker

            configure_stdio_broker(
                descriptor,
                control_reader=control_stdin,
                control_writer=control_stderr,
            )
        payload = json.dumps(envelope["request"], ensure_ascii=False, separators=(",", ":"))
    else:
        payload = payload_line
    sys.stdin = io.StringIO(payload)
    sys.argv = [str(worker_path), command]
    namespace = {
        "__name__": "__main__",
        "__file__": str(worker_path),
        "__package__": None,
        "__cached__": None,
        "__builtins__": __builtins__,
    }
    _BOOTSTRAP_STAGE = "worker_handoff"
    _WORKER_HANDOFF_COMPLETE = True
    exec(compile(source, str(worker_path), "exec"), namespace, namespace)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as error:
        if not _WORKER_HANDOFF_COMPLETE and error.code not in {None, 0}:
            message = str(error.code or "Managed Worker bootstrap failed")[:500]
            print(
                ERROR_PREFIX
                + json.dumps(
                    {
                        "error_code": "WORKER_BOOTSTRAP_FAILED",
                        "message": message,
                        "retryable": False,
                        "stage": "runtime_bootstrap",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
        raise
    except Exception:
        if not _WORKER_HANDOFF_COMPLETE:
            print(
                ERROR_PREFIX
                + json.dumps(
                    {
                        "error_code": "WORKER_BOOTSTRAP_FAILED",
                        "message": f"Managed Worker bootstrap failed during {_BOOTSTRAP_STAGE}",
                        "retryable": False,
                        "stage": "runtime_bootstrap",
                    },
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
        raise
