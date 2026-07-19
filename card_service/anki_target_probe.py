"""Read-only, bounded inspection of the current local AnkiConnect target."""

from __future__ import annotations

import hashlib
import json
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .artifact_registry import canonical_json_bytes


ANKI_CONNECT_URL = "http://127.0.0.1:8765"
ANKI_CONNECT_API_VERSION = 6
MAX_RESPONSE_BYTES = 1024 * 1024


class AnkiTargetProbeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AnkiTargetInspector(Protocol):
    def __call__(self) -> Mapping[str, Any]: ...


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _text(value: Any, label: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise AnkiTargetProbeError("ANKI_TARGET_INVALID", f"{label} is invalid")
    normalized = unicodedata.normalize("NFC", value).strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(ord(char) < 32 for char in normalized)
    ):
        raise AnkiTargetProbeError("ANKI_TARGET_INVALID", f"{label} is invalid")
    return normalized


@dataclass(frozen=True)
class _Response:
    result: Any


class LocalAnkiConnectTargetProbe:
    """Probe the fixed loopback AnkiConnect endpoint without using environment proxies."""

    def __init__(
        self,
        *,
        endpoint: str = ANKI_CONNECT_URL,
        timeout_seconds: float = 5.0,
    ) -> None:
        if endpoint != ANKI_CONNECT_URL:
            raise AnkiTargetProbeError(
                "ANKI_TARGET_INVALID",
                "Anki target must use the fixed loopback endpoint",
            )
        if (
            not isinstance(timeout_seconds, (int, float))
            or not 0.1 <= float(timeout_seconds) <= 30
        ):
            raise AnkiTargetProbeError("ANKI_TARGET_INVALID", "Anki timeout is invalid")
        self._endpoint = endpoint
        self._timeout_seconds = float(timeout_seconds)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _call(self, action: str) -> _Response:
        body = canonical_json_bytes(
            {
                "action": action,
                "version": ANKI_CONNECT_API_VERSION,
                "params": {},
            }
        )
        request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                if response.status != 200:
                    raise AnkiTargetProbeError(
                        "ANKI_OFFLINE", "AnkiConnect returned an unexpected status"
                    )
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared = int(content_length)
                    except ValueError as error:
                        raise AnkiTargetProbeError(
                            "ANKI_TARGET_INVALID",
                            "AnkiConnect response length is invalid",
                        ) from error
                    if declared < 0 or declared > MAX_RESPONSE_BYTES:
                        raise AnkiTargetProbeError(
                            "ANKI_TARGET_INVALID", "AnkiConnect response is too large"
                        )
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except AnkiTargetProbeError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError) as error:
            raise AnkiTargetProbeError(
                "ANKI_OFFLINE", "Anki or AnkiConnect is not available"
            ) from error
        if len(raw) > MAX_RESPONSE_BYTES:
            raise AnkiTargetProbeError(
                "ANKI_TARGET_INVALID", "AnkiConnect response is too large"
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AnkiTargetProbeError(
                "ANKI_TARGET_INVALID", "AnkiConnect returned invalid JSON"
            ) from error
        if not isinstance(value, dict) or set(value) != {"result", "error"}:
            raise AnkiTargetProbeError(
                "ANKI_TARGET_INVALID", "AnkiConnect response fields are invalid"
            )
        if value["error"] is not None:
            raise AnkiTargetProbeError(
                "ANKI_OFFLINE", "AnkiConnect rejected target inspection"
            )
        return _Response(value["result"])

    def __call__(self) -> Mapping[str, Any]:
        version = self._call("version").result
        profile = _text(self._call("getActiveProfile").result, "active profile")
        media_directory = _text(
            self._call("getMediaDirPath").result, "media directory", maximum=4096
        )
        decks = self._call("deckNames").result
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version < 5
            or version > ANKI_CONNECT_API_VERSION
            or not isinstance(decks, list)
            or len(decks) > 100_000
        ):
            raise AnkiTargetProbeError(
                "ANKI_TARGET_INVALID", "AnkiConnect target capabilities are invalid"
            )
        normalized_decks = sorted(
            {_text(value, "deck name", maximum=1024) for value in decks},
            key=lambda value: value.encode("utf-8"),
        )
        configuration = {
            "endpoint": ANKI_CONNECT_URL,
            "apiVersion": ANKI_CONNECT_API_VERSION,
            "authentication": "none",
        }
        target_identity = {
            "activeProfile": profile,
            "mediaDirectory": media_directory,
        }
        return {
            "schemaVersion": 1,
            "profileRef": "anki_current_" + _digest(profile)[:32],
            "configurationFingerprint": _digest(configuration),
            "credentialRevision": 0,
            "ankiConnectVersion": version,
            "profileIdentityDigest": _digest(profile),
            "collectionIdentityDigest": _digest(target_identity),
            "deckInventoryDigest": _digest(normalized_decks),
            "deckCount": len(normalized_decks),
            "transportAuthentication": "none",
            "observedAt": int(time.time() * 1000),
        }


__all__ = [
    "ANKI_CONNECT_API_VERSION",
    "ANKI_CONNECT_URL",
    "AnkiTargetInspector",
    "AnkiTargetProbeError",
    "LocalAnkiConnectTargetProbe",
]
