from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from workers.acg import legacy_worker
from workers.acg.managed_tts_broker import ManagedTtsAudio


def tts_payload() -> dict[str, object]:
    return {
        "language": "English",
        "api_config": {
            "tts_config": {
                "enabled": True,
                "provider": "xai",
                "model": "",
                "voice": "",
                "base_url": "",
                "api_key": "",
                "language": "auto",
                "sample_rate": 24000,
                "bit_rate": 128000,
            }
        },
    }


def test_call_tts_audio_uses_broker_without_worker_secret_or_direct_http() -> None:
    observed: list[dict[str, object]] = []

    def request(text: str, **kwargs: object) -> ManagedTtsAudio:
        observed.append({"text": text, **kwargs})
        return ManagedTtsAudio(b"ID3managed", "audio/mpeg")

    tts = legacy_worker.normalized_tts_config(tts_payload())
    with (
        patch.object(legacy_worker, "managed_tts_broker_is_configured", return_value=True),
        patch.object(legacy_worker, "managed_tts_request", side_effect=request),
        patch.object(legacy_worker, "http_binary", side_effect=AssertionError("direct HTTP must not run")),
        patch.object(legacy_worker, "http_json", side_effect=AssertionError("direct HTTP must not run")),
        patch.object(legacy_worker, "gcloud_value", side_effect=AssertionError("gcloud must not run")),
    ):
        result = legacy_worker.call_tts_audio(tts, "hello", "English", work_unit_base="sentence:seg-1")
    assert result == b"ID3managed"
    assert observed == [{
        "text": "hello",
        "language": "en-US",
        "sample_rate": 24000,
        "bit_rate": 128000,
        "work_unit_base": "sentence:seg-1",
    }]


def test_tts_test_uses_broker_without_api_key_or_provider_specific_branch() -> None:
    with (
        patch.object(legacy_worker, "managed_tts_broker_is_configured", return_value=True),
        patch.object(legacy_worker, "managed_tts_operation_available", return_value=True),
        patch.object(
            legacy_worker,
            "managed_tts_request",
            return_value=ManagedTtsAudio(b"ID3test", "audio/mpeg"),
        ) as request,
        patch.object(legacy_worker, "http_binary", side_effect=AssertionError("direct HTTP must not run")),
        patch.object(legacy_worker, "http_json", side_effect=AssertionError("direct HTTP must not run")),
    ):
        result = legacy_worker.handle_test_tts(tts_payload())
    assert result["ok"] is True
    assert result["bytes"] == len(b"ID3test")
    assert request.call_args.kwargs["work_unit_base"] == "tts-test"


def test_synthesize_tts_uses_mime_driven_managed_audio_path(tmp_path: Path) -> None:
    project = {**tts_payload(), "disable_tts_cache_read": True}
    output = tmp_path / "tts.mp3"
    segment = {"id": "segment-7", "text": "Study this sentence."}
    with (
        patch.object(legacy_worker, "managed_tts_broker_is_configured", return_value=True),
        patch.object(legacy_worker, "managed_tts_operation_available", return_value=True),
        patch.object(
            legacy_worker,
            "managed_tts_request",
            return_value=ManagedTtsAudio(b"ID3production", "audio/mpeg"),
        ) as request,
        patch.object(legacy_worker, "apply_tts_output_volume") as apply_volume,
        patch.object(legacy_worker, "validate_tts_audio_duration"),
        patch.object(legacy_worker, "tts_semantic_verification_enabled", return_value=False),
        patch.object(legacy_worker, "store_cached_file"),
        patch.object(legacy_worker, "http_binary", side_effect=AssertionError("direct HTTP must not run")),
        patch.object(legacy_worker, "http_json", side_effect=AssertionError("direct HTTP must not run")),
    ):
        result = legacy_worker.synthesize_tts(project, segment, output, tts_kind="sentence")
    assert result and result["ok"] is True
    assert output.read_bytes() == b"ID3production"
    assert request.call_args.kwargs["work_unit_base"] == "sentence:segment-7"
    apply_volume.assert_called_once()


def test_synthesize_tts_fails_closed_when_task_has_no_tts_authorization(tmp_path: Path) -> None:
    project = {**tts_payload(), "disable_tts_cache_read": True}
    with (
        patch.object(legacy_worker, "managed_tts_broker_is_configured", return_value=True),
        patch.object(legacy_worker, "managed_tts_operation_available", return_value=False),
        patch.object(legacy_worker, "tts_cache_read_enabled", return_value=False),
    ):
        try:
            legacy_worker.synthesize_tts(
                project,
                {"id": "segment-1", "text": "hello"},
                tmp_path / "tts.mp3",
            )
        except legacy_worker.ManagedTtsBrokerError as error:
            assert "not authorized" in str(error)
        else:
            raise AssertionError("managed TTS must fail closed without task authorization")
