from __future__ import annotations

import base64
import hashlib
import json
import socket
import time
from pathlib import Path

import pytest

from card_service.source_acquisition import (
    MAX_SUBTITLE_BYTES,
    PinnedHttpsFetcher,
    SourceAcquisitionError,
    SourceFetchResponse,
    YouTubeSubtitleAcquirer,
    make_source_acquisition_handler,
    canonical_youtube_watch_url,
    resolve_public_addresses,
    youtube_video_id,
)
from card_service.broker import BrokerBudget, BrokerReservationLedger, ModelTtsBroker
from card_service.broker_ipc import BrokerIpcError
from card_service.credentials import CredentialStore, InMemoryCredentialBackend


VIDEO_ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtube.com/watch?v={VIDEO_ID}&list=ignored",
        f"https://m.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}?si=ignored",
    ],
)
def test_youtube_url_is_reduced_to_one_fixed_video_identity(url: str) -> None:
    assert youtube_video_id(url) == VIDEO_ID
    assert canonical_youtube_watch_url(url) == f"https://www.youtube.com/watch?v={VIDEO_ID}&hl=en"


@pytest.mark.parametrize(
    "url",
    [
        f"http://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://user:pass@www.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com:444/watch?v={VIDEO_ID}",
        "https://www.youtube.com/playlist?list=PL123",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://127.0.0.1/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=too-short",
        f"https://www.youtube.com/watch?v={VIDEO_ID}#fragment",
    ],
)
def test_youtube_url_rejects_noncanonical_or_private_targets(url: str) -> None:
    with pytest.raises(SourceAcquisitionError):
        youtube_video_id(url)


def _player_page(caption_url: str) -> bytes:
    player = {
        "captions": {
            "playerCaptionsTracklistRenderer": {
                "captionTracks": [
                    {
                        "baseUrl": "https://www.youtube.com/api/timedtext?v=x&lang=en&kind=asr",
                        "languageCode": "en",
                        "kind": "asr",
                    },
                    {
                        "baseUrl": caption_url,
                        "languageCode": "en-US",
                    },
                    {
                        "baseUrl": "https://www.youtube.com/api/timedtext?v=x&lang=ja",
                        "languageCode": "ja",
                    },
                ]
            }
        },
        "videoDetails": {"title": "A reliable title"},
    }
    return ("<script>ytInitialPlayerResponse = " + json.dumps(player) + ";</script>").encode("utf-8")


def test_acquirer_selects_manual_language_track_and_returns_integrity_evidence_without_locator() -> None:
    secret_caption_url = (
        "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en&sig=secret-query-canary"
    )
    vtt = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nNever gonna give you up\n"
    observed: list[tuple[str, int, float]] = []

    def transport(url: str, maximum_bytes: int, timeout_seconds: float) -> SourceFetchResponse:
        observed.append((url, maximum_bytes, timeout_seconds))
        body = _player_page(secret_caption_url) if "/watch?" in url else vtt
        return SourceFetchResponse(200, url, {"content-type": "text/plain"}, body, "142.250.1.1")

    result, network_bytes = YouTubeSubtitleAcquirer(transport=transport).acquire(
        f"https://youtu.be/{VIDEO_ID}",
        "English",
    )
    decoded = base64.b64decode(result["contentBase64"], validate=True)
    assert decoded.startswith(b"WEBVTT\n\n")
    assert result["videoId"] == VIDEO_ID
    assert result["title"] == "A reliable title"
    assert result["languageCode"] == "en-US"
    assert result["captionKind"] == "manual"
    assert result["byteLength"] == len(decoded)
    assert result["sha256"] == hashlib.sha256(decoded).hexdigest()
    assert network_bytes == len(_player_page(secret_caption_url)) + len(vtt)
    serialized = json.dumps(result, ensure_ascii=False)
    assert "secret-query-canary" not in serialized
    assert "timedtext" not in serialized
    assert observed[1][0].endswith("&fmt=vtt")


def test_acquirer_converts_timedtext_xml_to_bounded_vtt() -> None:
    caption_url = "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en"
    xml = b'<transcript><text start="1.25" dur="2.5">Tom &amp;amp; Jerry</text></transcript>'

    def transport(url: str, _maximum_bytes: int, _timeout_seconds: float) -> SourceFetchResponse:
        body = _player_page(caption_url) if "/watch?" in url else xml
        return SourceFetchResponse(200, url, {}, body, "142.250.1.1")

    result, _ = YouTubeSubtitleAcquirer(transport=transport).acquire(
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "en-US",
    )
    decoded = base64.b64decode(result["contentBase64"], validate=True).decode("utf-8")
    assert "00:00:01.250 --> 00:00:03.750" in decoded
    assert "Tom & Jerry" in decoded


def test_acquirer_blocks_redirect_oversize_wrong_language_and_untrusted_caption_endpoint() -> None:
    caption_url = "https://evil.example/api/timedtext?v=x&lang=en&sig=secret-canary"
    page = _player_page(caption_url)

    for response in (
        SourceFetchResponse(302, "https://www.youtube.com/watch", {"location": "https://evil.example"}, b"", "1.1.1.1"),
        SourceFetchResponse(200, "https://www.youtube.com/watch", {}, b"x" * (3 * 1024 * 1024 + 1), "1.1.1.1"),
    ):
        with pytest.raises(SourceAcquisitionError):
            YouTubeSubtitleAcquirer(transport=lambda *_args, value=response: value).acquire(
                f"https://www.youtube.com/watch?v={VIDEO_ID}",
                "English",
            )

    with pytest.raises(SourceAcquisitionError) as wrong_language:
        YouTubeSubtitleAcquirer(
            transport=lambda url, *_args: SourceFetchResponse(200, url, {}, page, "1.1.1.1")
        ).acquire(f"https://www.youtube.com/watch?v={VIDEO_ID}", "French")
    assert wrong_language.value.code == "SOURCE_CAPTION_LANGUAGE_UNAVAILABLE"

    with pytest.raises(SourceAcquisitionError) as blocked_endpoint:
        YouTubeSubtitleAcquirer(
            transport=lambda url, *_args: SourceFetchResponse(200, url, {}, page, "1.1.1.1")
        ).acquire(f"https://www.youtube.com/watch?v={VIDEO_ID}", "English")
    assert blocked_endpoint.value.code == "SOURCE_FETCH_HOST_BLOCKED" or blocked_endpoint.value.code == "SOURCE_CAPTION_URL_BLOCKED"
    assert "secret-canary" not in str(blocked_endpoint.value)


def test_subtitle_response_byte_limit_is_enforced_even_for_injected_transport() -> None:
    caption_url = "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en"
    page = _player_page(caption_url)

    def transport(url: str, _maximum_bytes: int, _timeout_seconds: float) -> SourceFetchResponse:
        body = page if "/watch?" in url else b"x" * (MAX_SUBTITLE_BYTES + 1)
        return SourceFetchResponse(200, url, {}, body, "1.1.1.1")

    with pytest.raises(SourceAcquisitionError) as caught:
        YouTubeSubtitleAcquirer(transport=transport).acquire(
            f"https://www.youtube.com/watch?v={VIDEO_ID}",
            "English",
        )
    assert caught.value.code == "SOURCE_SUBTITLE_LIMIT"


@pytest.mark.parametrize(
    "invalid_vtt",
    [
        b"WEBVTT\n\nThis is not a timed cue\n",
        b"WEBVTT\n\n\x00\n00:00:00.000 --> 00:00:01.000\nHello\n",
        b"WEBVTT\n\n00:00:broken --> 00:00:01.000\nHello\n",
    ],
)
def test_vtt_without_one_valid_bounded_cue_is_rejected(invalid_vtt: bytes) -> None:
    caption_url = "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en"
    page = _player_page(caption_url)

    def transport(url: str, _maximum_bytes: int, _timeout_seconds: float) -> SourceFetchResponse:
        return SourceFetchResponse(200, url, {}, page if "/watch?" in url else invalid_vtt, "1.1.1.1")

    with pytest.raises(SourceAcquisitionError) as caught:
        YouTubeSubtitleAcquirer(transport=transport).acquire(
            f"https://www.youtube.com/watch?v={VIDEO_ID}",
            "English",
        )
    assert caught.value.code in {"SOURCE_SUBTITLE_EMPTY", "SOURCE_SUBTITLE_FORMAT_INVALID"}


def test_dns_resolution_rejects_any_non_public_answer_before_socket_use() -> None:
    private_records = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ]
    with pytest.raises(SourceAcquisitionError) as caught:
        resolve_public_addresses("www.youtube.com", resolver=lambda *_args, **_kwargs: private_records)
    assert caught.value.code == "SOURCE_DNS_PRIVATE_BLOCKED"

    fetcher = PinnedHttpsFetcher(resolver=lambda *_args, **_kwargs: private_records)
    with pytest.raises(SourceAcquisitionError) as fetch_error:
        fetcher.fetch(
            f"https://www.youtube.com/watch?v={VIDEO_ID}",
            1024,
            1,
        )
    assert fetch_error.value.code == "SOURCE_DNS_PRIVATE_BLOCKED"


def _source_broker(tmp_path: Path):
    credentials = CredentialStore(
        state_dir=(tmp_path / "credentials").resolve(),
        backend=InMemoryCredentialBackend(),
    )
    ledger = BrokerReservationLedger((tmp_path / "source-ledger.json").resolve())
    return ledger, ModelTtsBroker(credential_store=credentials, ledger=ledger)


def test_task_source_handler_binds_video_language_intent_budget_and_ledger(tmp_path: Path) -> None:
    ledger, broker = _source_broker(tmp_path)
    caption_url = "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en&sig=secret-canary"
    vtt = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n"
    sends: list[str] = []

    def transport(url: str, _maximum_bytes: int, _timeout_seconds: float) -> SourceFetchResponse:
        sends.append(url)
        body = _player_page(caption_url) if "/watch?" in url else vtt
        return SourceFetchResponse(200, url, {}, body, "142.250.1.1")

    handler = make_source_acquisition_handler(
        task_id="task-source-1",
        task_request={
            "source_mode": "url",
            "source_url": f"https://youtu.be/{VIDEO_ID}",
            "language": "English",
        },
        operation_intent_ref="intent-approved-source-1",
        budget=BrokerBudget(2, 100_000, 8 * 1024 * 1024, 0),
        broker=broker,
        expires_at_unix_ms=int(time.time() * 1000) + 60_000,
        transport=transport,
    )
    result = handler(
        {
            "workUnitId": "source:subtitle:1",
            "request": {"videoId": VIDEO_ID, "language": "en", "format": "vtt"},
        }
    )
    assert base64.b64decode(result["contentBase64"], validate=True).startswith(b"WEBVTT")
    assert len(sends) == 2
    record = ledger.list_records()[0]
    assert record["capability"] == "source"
    assert record["profileRef"] == "source.youtube_subtitles"
    assert record["credentialRevision"] == 0
    assert record["credentialRequired"] is False
    assert record["operationIntentRef"] == "intent-approved-source-1"
    assert record["state"] == "settled"
    persisted = (tmp_path / "source-ledger.json").read_text(encoding="utf-8")
    assert "secret-canary" not in persisted
    assert "youtu.be" not in persisted


@pytest.mark.parametrize(
    "worker_request",
    [
        {"videoId": "AAAAAAAAAAA", "language": "en", "format": "vtt"},
        {"videoId": VIDEO_ID, "language": "fr", "format": "vtt"},
        {"videoId": VIDEO_ID, "language": "en", "format": "srt"},
        {"videoId": VIDEO_ID, "language": "en", "format": "vtt", "url": "https://evil.example"},
    ],
)
def test_task_source_handler_rejects_worker_scope_changes_before_network(
    tmp_path: Path,
    worker_request: dict[str, str],
) -> None:
    ledger, broker = _source_broker(tmp_path)
    sends = []
    handler = make_source_acquisition_handler(
        task_id="task-source-1",
        task_request={
            "source_mode": "url",
            "source_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
            "language": "English",
        },
        operation_intent_ref="intent-approved-source-1",
        budget=BrokerBudget(2, 100_000, 8 * 1024 * 1024, 0),
        broker=broker,
        expires_at_unix_ms=int(time.time() * 1000) + 60_000,
        transport=lambda *_args: sends.append(1),
    )
    with pytest.raises(BrokerIpcError):
        handler({"workUnitId": "source:subtitle:1", "request": worker_request})
    assert sends == []
    assert ledger.list_records() == []


def test_task_source_handler_expiry_blocks_before_network_or_reservation(tmp_path: Path) -> None:
    ledger, broker = _source_broker(tmp_path)
    sends = []
    handler = make_source_acquisition_handler(
        task_id="task-source-1",
        task_request={
            "source_mode": "url",
            "source_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
            "language": "English",
        },
        operation_intent_ref="intent-approved-source-1",
        budget=BrokerBudget(2, 100_000, 8 * 1024 * 1024, 0),
        broker=broker,
        expires_at_unix_ms=int(time.time() * 1000) - 1,
        transport=lambda *_args: sends.append(1),
    )
    with pytest.raises(BrokerIpcError) as caught:
        handler(
            {
                "workUnitId": "source:subtitle:1",
                "request": {"videoId": VIDEO_ID, "language": "en", "format": "vtt"},
            }
        )
    assert caught.value.code == "SOURCE_AUTHORIZATION_EXPIRED"
    assert sends == []
    assert ledger.list_records() == []
