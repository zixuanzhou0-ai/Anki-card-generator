from __future__ import annotations

import base64
import hashlib
from unittest.mock import patch

import pytest

from workers.acg import managed_tts_broker


class FakeClient:
    def __init__(self, operations: set[str] | None = None) -> None:
        self.allowed_operations = frozenset(operations or {"tts.synthesize"})
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.audio = b"ID3" + b"\x00" * 64

    def request(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation, payload))
        return {
            "audioBase64": base64.b64encode(self.audio).decode("ascii"),
            "byteLength": len(self.audio),
            "sha256": hashlib.sha256(self.audio).hexdigest(),
            "mimeType": "audio/mpeg",
        }


def test_managed_tts_request_contains_only_generic_audio_intent() -> None:
    client = FakeClient()
    with patch.object(managed_tts_broker, "configured_client", return_value=client):
        audio = managed_tts_broker.request_tts(
            "hello",
            language="en-US",
            sample_rate=24000,
            bit_rate=128000,
            work_unit_base="sentence:segment-1",
        )
    assert audio.data == client.audio
    assert audio.mime_type == "audio/mpeg"
    operation, payload = client.calls[0]
    assert operation == "tts.synthesize"
    assert set(payload) == {"workUnitId", "request"}
    assert payload["request"] == {
        "input": "hello",
        "language": "en-US",
        "response_format": "mp3",
        "sample_rate": 24000,
        "bit_rate": 128000,
    }
    assert str(payload["workUnitId"]).startswith("tts:sentence:segment-1:")
    forbidden = {"url", "base_url", "headers", "api_key", "model", "voice", "provider", "profileRef", "budget"}
    assert forbidden.isdisjoint(payload["request"])


def test_tts_work_unit_is_stable_for_same_audio_intent() -> None:
    client = FakeClient()
    with patch.object(managed_tts_broker, "configured_client", return_value=client):
        for text in ("same", "same", "changed"):
            managed_tts_broker.request_tts(text, language="en-US", work_unit_base="phrase/unsafe")
    ids = [str(payload["workUnitId"]) for _, payload in client.calls]
    assert ids[0] == ids[1]
    assert ids[0] != ids[2]
    assert "/" not in ids[0]


def test_unauthorized_tts_operation_is_blocked_before_ipc() -> None:
    client = FakeClient({"model.openai_chat"})
    with patch.object(managed_tts_broker, "configured_client", return_value=client):
        assert managed_tts_broker.operation_available() is False
        with pytest.raises(managed_tts_broker.ManagedTtsBrokerError):
            managed_tts_broker.request_tts("hello", language="en-US", work_unit_base="test")
    assert client.calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"byteLength": 999},
        {"sha256": "0" * 64},
        {"mimeType": "text/html"},
        {"audioBase64": "not-valid-base64"},
        {"extra": "untrusted"},
    ],
)
def test_tts_response_integrity_and_shape_are_verified(mutation: dict[str, object]) -> None:
    client = FakeClient()
    original = client.request

    def invalid(operation: str, payload: dict[str, object]) -> dict[str, object]:
        return {**original(operation, payload), **mutation}

    client.request = invalid  # type: ignore[method-assign]
    with patch.object(managed_tts_broker, "configured_client", return_value=client):
        with pytest.raises(managed_tts_broker.ManagedTtsBrokerError):
            managed_tts_broker.request_tts("hello", language="en-US", work_unit_base="test")


def test_pcm_response_requires_bounded_sample_rate() -> None:
    client = FakeClient()
    original = client.request

    def pcm(operation: str, payload: dict[str, object]) -> dict[str, object]:
        return {**original(operation, payload), "mimeType": "audio/pcm", "sampleRate": 24000}

    client.request = pcm  # type: ignore[method-assign]
    with patch.object(managed_tts_broker, "configured_client", return_value=client):
        result = managed_tts_broker.request_tts("hello", language="en-US", work_unit_base="test")
    assert result.sample_rate == 24000
