from __future__ import annotations

import hashlib
import hmac
import io
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
    payload = sys.stdin.read()
    sys.path.insert(0, str(worker_path.parent))
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
