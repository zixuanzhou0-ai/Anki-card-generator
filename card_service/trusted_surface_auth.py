from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any, Mapping


RESPONSE_AUTH_DOMAIN = b"study.trusted-surface-response.v1\x00"
RESPONSE_KEY_BYTES = 32


def new_response_key() -> bytes:
    return os.urandom(RESPONSE_KEY_BYTES)


def encode_response_key(key: bytes) -> str:
    if len(key) != RESPONSE_KEY_BYTES:
        raise ValueError("Trusted surface response key has an invalid length")
    return base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")


def decode_response_key(value: str) -> bytes:
    raw = str(value or "")
    if len(raw) != 43:
        raise ValueError("Trusted surface response key is invalid")
    try:
        key = base64.b64decode(raw + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("Trusted surface response key is invalid") from error
    if len(key) != RESPONSE_KEY_BYTES:
        raise ValueError("Trusted surface response key has an invalid length")
    return key


def canonical_response_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def response_mac(value: Mapping[str, Any], key: bytes) -> str:
    if len(key) != RESPONSE_KEY_BYTES:
        raise ValueError("Trusted surface response key has an invalid length")
    return base64.urlsafe_b64encode(
        hmac.new(key, RESPONSE_AUTH_DOMAIN + canonical_response_bytes(value), hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")


def sign_response(value: Mapping[str, Any], key: bytes) -> dict[str, Any]:
    if "responseMac" in value:
        raise ValueError("Trusted surface response is already signed")
    signed = dict(value)
    signed["responseMac"] = response_mac(value, key)
    return signed


def verify_response(value: Mapping[str, Any], key: bytes) -> dict[str, Any]:
    supplied = str(value.get("responseMac") or "")
    unsigned = {name: child for name, child in value.items() if name != "responseMac"}
    if not supplied or not hmac.compare_digest(supplied, response_mac(unsigned, key)):
        raise ValueError("Trusted surface response authentication failed")
    return unsigned
