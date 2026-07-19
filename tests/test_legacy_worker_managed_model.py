from __future__ import annotations

from unittest.mock import patch

import pytest

from workers.acg import legacy_worker


def managed_patches(result: dict[str, object], calls: list[tuple[str, dict[str, object], str]]):
    def request(operation: str, body: dict[str, object], *, work_unit_base: str):
        calls.append((operation, body, work_unit_base))
        return result

    return (
        patch.object(legacy_worker, "managed_model_broker_is_configured", return_value=True),
        patch.object(legacy_worker, "managed_model_operation_available", return_value=True),
        patch.object(legacy_worker, "managed_model_request", side_effect=request),
    )


def test_model_is_available_without_worker_secret_when_task_broker_authorizes_it() -> None:
    configured, available, _ = managed_patches({}, [])
    with configured, available:
        assert legacy_worker.model_api_available(
            {"provider": "openai-compatible", "model": "service-owned-model"}
        ) is True
        assert legacy_worker.model_api_available(
            {"provider": "gemini-vertex", "model": "vertex-model"}
        ) is False


@pytest.mark.parametrize(
    ("provider", "operation"),
    [
        ("openai", "model.openai_chat"),
        ("xai", "model.openai_chat"),
        ("hermes", "model.openai_chat"),
        ("anthropic", "model.anthropic_messages"),
    ],
)
def test_managed_model_operation_accepts_service_profile_provider_names(
    provider: str, operation: str
) -> None:
    assert legacy_worker.managed_model_operation({"provider": provider}) == operation


def test_openai_compatible_managed_call_uses_broker_without_url_header_secret_or_stream() -> None:
    calls: list[tuple[str, dict[str, object], str]] = []
    result = {"choices": [{"message": {"content": "{}"}}]}
    configured, _, request = managed_patches(result, calls)
    with configured, request, patch.object(legacy_worker, "http_json", side_effect=AssertionError("direct HTTP")), patch.object(
        legacy_worker, "stream_chat_completion", side_effect=AssertionError("direct stream")
    ):
        response = legacy_worker.compatible_chat_completion(
            {
                "provider": "openai-compatible",
                "model": "qwen3.1-max",
                "thinking_budget": 512,
            },
            [{"role": "user", "content": "hello"}],
            temperature=0.1,
            max_tokens=800,
            work_unit_id="learning-review:1",
        )
    assert response == result
    operation, body, work_unit = calls[0]
    assert operation == "model.openai_chat"
    assert work_unit == "learning-review:1:initial"
    assert body["model"] == "qwen3.1-max"
    assert body["enable_thinking"] is True
    assert body["thinking_budget"] == 512
    assert "stream" not in body
    assert "stream_options" not in body
    serialized = repr(body).casefold()
    assert "api_key" not in serialized
    assert "authorization" not in serialized
    assert "base_url" not in serialized


@pytest.mark.parametrize(
    "provider,operation,invoke,response",
    [
        (
            "claude",
            "model.anthropic_messages",
            lambda api: legacy_worker.model_anthropic_messages(
                api,
                {"model": "hint", "max_tokens": 100, "messages": [{"role": "user", "content": "hello"}]},
                work_unit_id="anthropic-1",
            ),
            {"content": [{"text": "{}"}]},
        ),
        (
            "gemini",
            "model.gemini_content",
            lambda api: legacy_worker.model_gemini_content(
                api,
                {"contents": [{"parts": [{"text": "hello"}]}]},
                work_unit_id="gemini-1",
            ),
            {"candidates": []},
        ),
    ],
)
def test_anthropic_and_gemini_managed_calls_never_use_worker_http(
    provider: str,
    operation: str,
    invoke,
    response: dict[str, object],
) -> None:
    calls: list[tuple[str, dict[str, object], str]] = []
    configured, _, request = managed_patches(response, calls)
    with configured, request, patch.object(legacy_worker, "http_json", side_effect=AssertionError("direct HTTP")):
        assert invoke({"provider": provider, "model": "service-model"}) == response
    assert calls[0][0] == operation
    assert calls[0][2].endswith(":initial")


def test_managed_vertex_is_blocked_before_gcloud_or_direct_http() -> None:
    with patch.object(legacy_worker, "managed_model_broker_is_configured", return_value=True), patch.object(
        legacy_worker, "gcloud_value", side_effect=AssertionError("gcloud")
    ), patch.object(legacy_worker, "http_json", side_effect=AssertionError("direct HTTP")):
        with pytest.raises(legacy_worker.ManagedModelBrokerError):
            legacy_worker.gemini_vertex_generate_content(
                {"provider": "gemini-vertex", "model": "gemini-test"},
                "hello",
            )


def test_outer_batch_retry_gets_a_new_service_work_unit() -> None:
    calls: list[str] = []

    def call_model(_project, _batch, *, work_unit_id=None):
        calls.append(str(work_unit_id))
        if len(calls) == 1:
            return {
                "error": "temporary",
                "error_code": "MODEL_CONNECTION_FAILED",
                "stage": "ai",
                "retryable": True,
            }
        return {"segments": [{"id": "seg-1", "cards": []}]}

    batch = [{"id": "seg-1", "text": "hello"}]
    with patch.object(legacy_worker, "call_model", side_effect=call_model), patch.object(legacy_worker.time, "sleep"):
        segments, errors, details = legacy_worker.call_model_batch_with_retry(
            {},
            batch,
            batch_index="2",
            total_batches=3,
        )
    assert calls == ["cards:2:try0", "cards:2:try1"]
    assert segments == [{"id": "seg-1", "cards": []}]
    assert errors == []
    assert details == []
