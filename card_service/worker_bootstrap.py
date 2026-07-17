from __future__ import annotations

import hashlib
import hmac
import io
import json
import sys
from pathlib import Path


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
    }
)
MAX_BOOTSTRAP_ENVELOPE_BYTES = 64 * 1024 * 1024
MAX_RUNTIME_MANIFEST_BYTES = 8 * 1024 * 1024
STDIN_RUNTIME_MANIFEST = "@stdin"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if len(sys.argv) != 6:
        raise SystemExit("invalid managed worker bootstrap arguments")
    worker_path = Path(sys.argv[1]).resolve(strict=True)
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
    try:
        manifest = json.loads(manifest_source)
    except ValueError as error:
        raise SystemExit("managed runtime manifest is invalid") from error
    entries = manifest.get("entries") if isinstance(manifest, dict) and manifest.get("schemaVersion") == 1 else None
    if not isinstance(entries, list) or not entries:
        raise SystemExit("managed runtime manifest is invalid")
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("managed runtime manifest entry is invalid")
        path = Path(str(entry.get("path") or ""))
        if not path.is_absolute():
            raise SystemExit("managed runtime manifest path is invalid")
        try:
            resolved = path.resolve(strict=True)
            size = resolved.stat().st_size
            digest = _file_sha256(resolved)
        except OSError as error:
            raise SystemExit("managed runtime entry is unavailable") from error
        if size != entry.get("size") or not hmac.compare_digest(digest, str(entry.get("sha256") or "")):
            raise SystemExit("managed runtime entry changed")
    managed_workers_root = (Path(__file__).resolve().parent.parent / "workers").resolve(strict=True)
    sys.path.insert(0, str(worker_path.parent))
    sys.path.insert(0, str(managed_workers_root))
    control_stdin = sys.stdin
    control_stderr = sys.stderr
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
    exec(compile(source, str(worker_path), "exec"), namespace, namespace)


if __name__ == "__main__":
    main()
