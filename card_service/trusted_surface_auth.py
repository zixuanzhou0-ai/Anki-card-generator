from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any, Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


RESPONSE_AUTH_DOMAIN = b"study.trusted-surface-response.v1\x00"
PRIVATE_PAYLOAD_KEY_DOMAIN = b"study.trusted-surface-private-payload-key.v1\x00"
PRIVATE_PAYLOAD_AAD_SCHEMA = "study.trusted-surface-private-payload-aad"
RESPONSE_KEY_BYTES = 32
PRIVATE_PAYLOAD_NONCE_BYTES = 12
MAX_PRIVATE_PAYLOAD_BYTES = 64 * 1024


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


def _decode_base64url(value: Any, *, label: str, expected_bytes: int | None = None) -> bytes:
    raw = str(value or "")
    try:
        decoded = base64.b64decode(raw + ("=" * (-len(raw) % 4)), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError(f"Trusted surface {label} is invalid") from error
    if expected_bytes is not None and len(decoded) != expected_bytes:
        raise ValueError(f"Trusted surface {label} has an invalid length")
    return decoded


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


def _private_payload_aad(*, session_ref: str, request_nonce: str, surface: str) -> bytes:
    if not session_ref or len(session_ref) > 160:
        raise ValueError("Trusted surface session reference is invalid")
    if len(request_nonce) != 64:
        raise ValueError("Trusted surface request nonce is invalid")
    if surface != "local_resource_picker":
        raise ValueError("Trusted surface private payload kind is invalid")
    return canonical_response_bytes(
        {
            "schema": PRIVATE_PAYLOAD_AAD_SCHEMA,
            "schemaVersion": 1,
            "sessionRef": session_ref,
            "requestNonce": request_nonce,
            "surface": surface,
        }
    )


def _private_payload_key(response_key: bytes, aad: bytes) -> bytes:
    if len(response_key) != RESPONSE_KEY_BYTES:
        raise ValueError("Trusted surface response key has an invalid length")
    return hmac.new(response_key, PRIVATE_PAYLOAD_KEY_DOMAIN + aad, hashlib.sha256).digest()


def seal_private_payload(
    value: Mapping[str, Any],
    response_key: bytes,
    *,
    session_ref: str,
    request_nonce: str,
    surface: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Trusted surface private payload must be an object")
    plaintext = canonical_response_bytes(value)
    if not plaintext or len(plaintext) > MAX_PRIVATE_PAYLOAD_BYTES:
        raise ValueError("Trusted surface private payload exceeds its size limit")
    aad = _private_payload_aad(
        session_ref=session_ref, request_nonce=request_nonce, surface=surface
    )
    nonce = os.urandom(PRIVATE_PAYLOAD_NONCE_BYTES)
    ciphertext = AESGCM(_private_payload_key(response_key, aad)).encrypt(
        nonce, plaintext, aad
    )
    return {
        "schemaVersion": 1,
        "algorithm": "A256GCM",
        "nonce": base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
        "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii").rstrip("="),
    }


def open_private_payload(
    value: Mapping[str, Any],
    response_key: bytes,
    *,
    session_ref: str,
    request_nonce: str,
    surface: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schemaVersion", "algorithm", "nonce", "ciphertext"
    }:
        raise ValueError("Trusted surface private payload envelope is invalid")
    if value.get("schemaVersion") != 1 or value.get("algorithm") != "A256GCM":
        raise ValueError("Trusted surface private payload envelope is unsupported")
    nonce = _decode_base64url(
        value.get("nonce"), label="private payload nonce", expected_bytes=PRIVATE_PAYLOAD_NONCE_BYTES
    )
    ciphertext = _decode_base64url(value.get("ciphertext"), label="private payload ciphertext")
    if len(ciphertext) < 16 or len(ciphertext) > MAX_PRIVATE_PAYLOAD_BYTES + 16:
        raise ValueError("Trusted surface private payload ciphertext exceeds its size limit")
    aad = _private_payload_aad(
        session_ref=session_ref, request_nonce=request_nonce, surface=surface
    )
    try:
        plaintext = AESGCM(_private_payload_key(response_key, aad)).decrypt(
            nonce, ciphertext, aad
        )
    except InvalidTag as error:
        raise ValueError("Trusted surface private payload authentication failed") from error
    try:
        decoded = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Trusted surface private payload is invalid JSON") from error
    if not isinstance(decoded, dict):
        raise ValueError("Trusted surface private payload must decode to an object")
    return decoded
