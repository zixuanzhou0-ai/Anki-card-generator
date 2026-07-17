from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("invalid trusted surface bootstrap arguments")
    if sys.stdin.readline().strip() != "START":
        raise SystemExit("trusted surface start handshake missing")
    surface_path = Path(sys.argv[1]).resolve(strict=True)
    expected_sha256 = sys.argv[2].lower()
    source = surface_path.read_bytes()
    if not hmac.compare_digest(hashlib.sha256(source).hexdigest(), expected_sha256):
        raise SystemExit("trusted surface digest changed")
    sys.path.insert(0, str(surface_path.parent.parent))
    sys.argv = [str(surface_path), *sys.argv[3:]]
    namespace = {
        "__name__": "__main__", "__file__": str(surface_path),
        "__package__": "card_service", "__cached__": None,
        "__builtins__": __builtins__,
    }
    exec(compile(source, str(surface_path), "exec"), namespace, namespace)


if __name__ == "__main__":
    main()
