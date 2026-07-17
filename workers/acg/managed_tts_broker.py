from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .broker_client import WorkerBrokerClient, WorkerBrokerError, configured_broker_client


TTS_OPERATION = "tts.synthesize"
MAX_AUDIO_BYTES = 700 * 1024
WORK_UNIT_PART = re.compile(r"[^A-Za-z0-9._:-]+")
FORBIDDEN_REQUEST_FIELDS = frozenset(
    {
        "url",
        "baseurl",
        "headers",
        "apikey",
        "authorization",
        "model",
        "voice",
        "provider",
        "profileref",
        "credentialrevision",
        "operationintentref",
        "budget",
        "reservedcostminorunits",
    }
)
ALLOWED_RESPONSE_KEYS = frozenset({"audioBase64", "byteLength", "sha256", "mimeType", "sampleRate"})
ALLOWED_MIME_TYPES = frozenset(
    {
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/vnd.wave",
        "audio/pcm",
        "audio/l16",
        "audio/raw",
    }
)


class ManagedTtsBrokerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManagedTtsAudio:
    data: bytes
    mime_type: str
    sample_rate: int | None = None


def configured_client() -> WorkerBrokerClient | None:
    return configured_broker_client()


def is_configured() -> bool:
    return configured_client() is not None


def operation_available() -> bool:
    client = configured_client()
    return client is not None and TTS_OPERATION in client.allowed_operations


def _normalized_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _assert_worker_request_is_unprivileged(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _normalized_field_name(key) in FORBIDDEN_REQUEST_FIELDS:
                raise ManagedTtsBrokerError("Worker TTS request contains a Service-owned field")
            _assert_worker_request_is_unprivileged(child)
    elif isinstance(value, list):
        for child in value:
            _assert_worker_request_is_unprivileged(child)


def _work_unit_id(base: str, request: dict[str, Any]) -> str:
    normalized_base = WORK_UNIT_PART.sub("-", str(base or "tts")).strip("-._:") or "tts"
    digest = hashlib.sha256(
        json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    prefix = f"tts:{normalized_base}"[:136].rstrip("-._:")
    return f"{prefix}:{digest}"


def request_tts(
    text: str,
    *,
    language: str,
    sample_rate: int = 24000,
    bit_rate: int = 128000,
    work_unit_base: str,
) -> ManagedTtsAudio:
    client = configured_client()
    if client is None:
        raise ManagedTtsBrokerError("Managed TTS broker is not configured")
    if TTS_OPERATION not in client.allowed_operations:
        raise ManagedTtsBrokerError("Managed TTS operation is not authorized for this task")
    request = {
        "input": str(text),
        "language": str(language),
        "response_format": "mp3",
        "sample_rate": int(sample_rate),
        "bit_rate": int(bit_rate),
    }
    if not request["input"] or not request["language"]:
        raise ManagedTtsBrokerError("Managed TTS request is invalid")
    _assert_worker_request_is_unprivileged(request)
    try:
        result = client.request(
            TTS_OPERATION,
            {"workUnitId": _work_unit_id(work_unit_base, request), "request": request},
        )
    except WorkerBrokerError as error:
        raise ManagedTtsBrokerError(str(error)) from error
    if not isinstance(result, dict) or not set(result) <= ALLOWED_RESPONSE_KEYS:
        raise ManagedTtsBrokerError("Managed TTS broker returned an invalid response")
    required = {"audioBase64", "byteLength", "sha256", "mimeType"}
    if not required <= set(result):
        raise ManagedTtsBrokerError("Managed TTS broker returned incomplete audio evidence")
    encoded = result.get("audioBase64")
    try:
        audio = base64.b64decode(encoded, validate=True) if isinstance(encoded, str) else b""
    except (binascii.Error, ValueError, TypeError) as error:
        raise ManagedTtsBrokerError("Managed TTS broker returned invalid audio encoding") from error
    if not audio or len(audio) > MAX_AUDIO_BYTES or result.get("byteLength") != len(audio):
        raise ManagedTtsBrokerError("Managed TTS broker returned invalid audio length")
    digest = str(result.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest != hashlib.sha256(audio).hexdigest():
        raise ManagedTtsBrokerError("Managed TTS broker returned invalid audio integrity evidence")
    mime_type = str(result.get("mimeType") or "").split(";", 1)[0].strip().casefold()
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ManagedTtsBrokerError("Managed TTS broker returned an unsupported audio MIME type")
    sample_rate_value = result.get("sampleRate")
    resolved_sample_rate: int | None = None
    if sample_rate_value is not None:
        if isinstance(sample_rate_value, bool) or not isinstance(sample_rate_value, int) or not 8000 <= sample_rate_value <= 48000:
            raise ManagedTtsBrokerError("Managed TTS broker returned an invalid sample rate")
        resolved_sample_rate = sample_rate_value
    if mime_type in {"audio/pcm", "audio/l16", "audio/raw"} and resolved_sample_rate is None:
        raise ManagedTtsBrokerError("Managed PCM audio is missing its sample rate")
    return ManagedTtsAudio(audio, mime_type, resolved_sample_rate)
