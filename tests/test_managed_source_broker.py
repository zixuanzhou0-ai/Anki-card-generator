from __future__ import annotations

import base64
import hashlib
from unittest.mock import patch

import pytest

from workers.acg import managed_source_broker


VIDEO_ID = "dQw4w9WgXcQ"


class FakeClient:
    def __init__(self, operations: set[str] | None = None) -> None:
        self.allowed_operations = frozenset(operations or {"source.youtube_subtitles"})
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.vtt = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n"

    def request(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation, payload))
        return {
            "schemaVersion": 1,
            "sourceKind": "youtube_subtitles",
            "videoId": VIDEO_ID,
            "title": "A title",
            "languageCode": "en-US",
            "captionKind": "manual",
            "mimeType": "text/vtt",
            "contentBase64": base64.b64encode(self.vtt).decode("ascii"),
            "byteLength": len(self.vtt),
            "sha256": hashlib.sha256(self.vtt).hexdigest(),
        }


def test_worker_sends_only_video_identity_language_and_format_to_source_broker() -> None:
    client = FakeClient()
    with patch.object(managed_source_broker, "configured_client", return_value=client):
        result = managed_source_broker.request_youtube_subtitles(
            f"https://youtu.be/{VIDEO_ID}?si=ignored",
            language="English",
            work_unit_base="extract:source-1",
        )
    assert result.vtt == client.vtt
    assert result.video_id == VIDEO_ID
    operation, payload = client.calls[0]
    assert operation == "source.youtube_subtitles"
    assert set(payload) == {"workUnitId", "request"}
    assert payload["request"] == {"videoId": VIDEO_ID, "language": "en", "format": "vtt"}
    assert "youtu.be" not in str(payload)
    assert str(payload["workUnitId"]).startswith("source:extract:source-1:")


def test_unauthorized_source_operation_is_blocked_before_ipc() -> None:
    client = FakeClient({"model.openai_chat"})
    with patch.object(managed_source_broker, "configured_client", return_value=client):
        assert managed_source_broker.operation_available() is False
        with pytest.raises(managed_source_broker.ManagedSourceBrokerError):
            managed_source_broker.request_youtube_subtitles(
                f"https://www.youtube.com/watch?v={VIDEO_ID}",
                language="English",
            )
    assert client.calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"videoId": "AAAAAAAAAAA"},
        {"languageCode": "fr"},
        {"captionKind": "unknown"},
        {"mimeType": "text/html"},
        {"byteLength": 999},
        {"sha256": "0" * 64},
        {"contentBase64": "not-base64"},
        {"extra": "untrusted"},
    ],
)
def test_source_response_shape_identity_and_integrity_are_verified(mutation: dict[str, object]) -> None:
    client = FakeClient()
    original = client.request

    def invalid(operation: str, payload: dict[str, object]) -> dict[str, object]:
        return {**original(operation, payload), **mutation}

    client.request = invalid  # type: ignore[method-assign]
    with patch.object(managed_source_broker, "configured_client", return_value=client):
        with pytest.raises(managed_source_broker.ManagedSourceBrokerError):
            managed_source_broker.request_youtube_subtitles(
                f"https://www.youtube.com/watch?v={VIDEO_ID}",
                language="English",
            )


@pytest.mark.parametrize(
    "url",
    [
        f"http://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://user:pass@www.youtube.com/watch?v={VIDEO_ID}",
        f"https://example.com/watch?v={VIDEO_ID}",
        "https://www.youtube.com/watch?v=bad",
    ],
)
def test_worker_rejects_noncanonical_source_url_before_ipc(url: str) -> None:
    client = FakeClient()
    with patch.object(managed_source_broker, "configured_client", return_value=client):
        with pytest.raises(managed_source_broker.ManagedSourceBrokerError):
            managed_source_broker.request_youtube_subtitles(url, language="English")
    assert client.calls == []
