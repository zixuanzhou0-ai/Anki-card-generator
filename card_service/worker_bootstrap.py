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
        "extract_learning_points",
        "generate_cards_from_learning_points",
        "generate",
        "export",
        "verify_anki_import",
    }
)
MAX_BOOTSTRAP_ENVELOPE_BYTES = 64 * 1024 * 1024


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("invalid managed worker bootstrap arguments")
    worker_path = Path(sys.argv[1]).resolve(strict=True)
    command = sys.argv[2]
    expected_sha256 = sys.argv[3].lower()
    if command not in ALLOWED_COMMANDS:
        raise SystemExit("managed worker command is not allowed")
    source = worker_path.read_bytes()
    actual_sha256 = hashlib.sha256(source).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise SystemExit("managed worker digest changed")
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
