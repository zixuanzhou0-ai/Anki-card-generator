from __future__ import annotations

import json
import os
import sys
import base64
import hashlib
import hmac
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pathlib import Path


def decode_key(value: str) -> bytes:
    return base64.b64decode(value + "=", altchars=b"-_", validate=True)


def sign(value: dict[str, object], key: bytes) -> dict[str, object]:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    mac = base64.urlsafe_b64encode(
        hmac.new(key, b"study.trusted-surface-response.v1\x00" + canonical, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return {**value, "responseMac": mac}


def seal_private(
    request: dict[str, object],
    key: bytes,
    *,
    surface: str,
    payload: dict[str, object],
) -> dict[str, object]:
    aad = json.dumps(
        {
            "schema": "study.trusted-surface-private-payload-aad",
            "schemaVersion": 1,
            "sessionRef": request["sessionRef"],
            "requestNonce": request["requestNonce"],
            "surface": surface,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    derived = hmac.new(
        key, b"study.trusted-surface-private-payload-key.v1\x00" + aad, hashlib.sha256
    ).digest()
    nonce = os.urandom(12)
    plaintext = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    ciphertext = AESGCM(derived).encrypt(nonce, plaintext, aad)
    return {
        "schemaVersion": 1,
        "algorithm": "A256GCM",
        "nonce": base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
        "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii").rstrip("="),
    }


def main() -> None:
    surface, request_path = sys.argv[1:]
    request_path = Path(request_path)
    request = json.loads(sys.stdin.read())
    response_key = decode_key(request["responseAuthKey"])
    if surface == "local_resource_picker":
        kind = request["selectionKind"]
        selected = (
            request_path.parents[3] / f"trusted-picker-{request['sessionRef']}.txt"
            if kind == "file"
            else request_path.parents[3] / f"trusted-picker-{request['sessionRef']}-dir"
        )
        response = sign(
            {
                "schemaVersion": 1,
                "sessionRef": request["sessionRef"],
                "requestNonce": request["requestNonce"],
                "state": "selected",
                "userGestureRecorded": True,
                "privatePayload": seal_private(
                    request,
                    response_key,
                    surface="local_resource_picker",
                    payload={"schemaVersion": 1, "selectedPath": str(selected)},
                ),
            },
            response_key,
        )
    elif surface == "authorization_manager":
        selected_refs = [
            item["selectionRef"]
            for item in request.get("authorizationItems", [])
            if isinstance(item, dict) and isinstance(item.get("selectionRef"), str)
        ]
        response = sign(
            {
                "schemaVersion": 1,
                "sessionRef": request["sessionRef"],
                "requestNonce": request["requestNonce"],
                "state": "approved",
                "userGestureRecorded": True,
                "privatePayload": seal_private(
                    request,
                    response_key,
                    surface="authorization_manager",
                    payload={"schemaVersion": 1, "selectedRefs": selected_refs},
                ),
            },
            response_key,
        )
    else:
        response = sign({
            "schemaVersion": 1,
            "sessionRef": request["sessionRef"],
            "requestNonce": request["requestNonce"],
            "state": "approved" if surface == "consent" else "completed",
            "userGestureRecorded": surface == "consent",
        }, response_key)
    temporary = Path(request["responsePath"] + ".tmp")
    temporary.write_text(json.dumps(response), encoding="utf-8")
    os.replace(temporary, request["responsePath"])


if __name__ == "__main__":
    main()
