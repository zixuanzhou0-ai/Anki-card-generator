from __future__ import annotations

import json
import os
import sys
import base64
import hashlib
import hmac
from pathlib import Path


def decode_key(value: str) -> bytes:
    return base64.b64decode(value + "=", altchars=b"-_", validate=True)


def sign(value: dict[str, object], key: bytes) -> dict[str, object]:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    mac = base64.urlsafe_b64encode(
        hmac.new(key, b"study.trusted-surface-response.v1\x00" + canonical, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return {**value, "responseMac": mac}


def main() -> None:
    surface, request_path = sys.argv[1:]
    request = json.loads(sys.stdin.read())
    response = sign({
        "schemaVersion": 1,
        "sessionRef": request["sessionRef"],
        "requestNonce": request["requestNonce"],
        "state": "approved" if surface == "consent" else "completed",
        "userGestureRecorded": surface == "consent",
    }, decode_key(request["responseAuthKey"]))
    temporary = Path(request["responsePath"] + ".tmp")
    temporary.write_text(json.dumps(response), encoding="utf-8")
    os.replace(temporary, request["responsePath"])


if __name__ == "__main__":
    main()
