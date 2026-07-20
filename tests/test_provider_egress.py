from __future__ import annotations

import base64
import hashlib
import http.server
import json
import threading

import pytest

from card_service.provider_egress import (
    MAX_PROMPT_CHARS,
    ProviderEgress,
    ProviderEgressError,
    ProviderProfile,
    ProviderTransportResponse,
)


def model_profile(**overrides: object) -> ProviderProfile:
    values: dict[str, object] = {
        "profile_ref": "model.primary",
        "capability": "model",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-test",
        "maximum_response_bytes": 4096,
    }
    values.update(overrides)
    return ProviderProfile(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("provider", "base_url", "expected_code"),
    [
        ("openai", "http://api.openai.com/v1", "PROVIDER_ORIGIN_BLOCKED"),
        ("openai", "https://api.x.ai/v1", "PROVIDER_ORIGIN_BLOCKED"),
        ("openai-compatible", "https://127.0.0.1/v1", "PROVIDER_ORIGIN_BLOCKED"),
        ("openai-compatible", "https://localhost/v1", "PROVIDER_ORIGIN_BLOCKED"),
        ("openai-compatible", "https://api.example.test/v1", "PROVIDER_ORIGIN_BLOCKED"),
        ("openai-compatible", "https://user:pass@example.test/v1", "PROVIDER_ORIGIN_INVALID"),
        ("openai-compatible", "https://example.test/v1?token=secret", "PROVIDER_ORIGIN_INVALID"),
        ("hermes", "https://127.0.0.1:8317/v1", "PROVIDER_ORIGIN_BLOCKED"),
        ("hermes", "http://192.168.1.10:8317/v1", "PROVIDER_ORIGIN_BLOCKED"),
    ],
)
def test_provider_origins_fail_closed(provider: str, base_url: str, expected_code: str) -> None:
    with pytest.raises(ProviderEgressError) as caught:
        model_profile(provider=provider, base_url=base_url)
    assert caught.value.code == expected_code


def test_openai_request_rebuilds_model_headers_and_endpoint() -> None:
    egress = ProviderEgress(model_profile())
    prepared = egress.prepare(
        "model.openai_chat",
        {
            "model": "attacker-selected-model",
            "messages": [
                {"role": "system", "content": "Return JSON"},
                {"role": "user", "content": "hello"},
            ],
            "temperature": 0.2,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
            "reasoning_effort": "low",
        },
        "provider-secret-canary",
    )
    body = json.loads(prepared.body)
    assert prepared.url == "https://api.openai.com/v1/chat/completions"
    assert body["model"] == "gpt-test"
    assert body["messages"][1]["content"] == "hello"
    assert prepared.headers["Authorization"] == "Bearer provider-secret-canary"
    assert "provider-secret-canary" not in repr(prepared)
    assert "hello" not in repr(prepared)


def test_openai_style_thinking_controls_are_bounded_and_rebuilt() -> None:
    prepared = ProviderEgress(model_profile()).prepare(
        "model.openai_chat",
        {
            "messages": [{"role": "user", "content": "hello"}],
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "enable_thinking": True,
            "thinking_budget": 4000,
            "preserve_thinking": False,
        },
        "secret",
    )
    body = json.loads(prepared.body)
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"
    assert body["enable_thinking"] is True
    assert body["thinking_budget"] == 4000
    assert body["preserve_thinking"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("thinking", {"type": "disabled"}),
        ("enable_thinking", "true"),
        ("thinking_budget", 4001),
        ("preserve_thinking", True),
    ],
)
def test_openai_style_thinking_controls_reject_unbounded_values(field: str, value: object) -> None:
    with pytest.raises(ProviderEgressError) as caught:
        ProviderEgress(model_profile()).prepare(
            "model.openai_chat",
            {"messages": [{"role": "user", "content": "hello"}], field: value},
            "secret",
        )
    assert caught.value.code == "PROVIDER_PAYLOAD_INVALID"


def test_known_openai_compatible_gateway_is_explicitly_allowlisted() -> None:
    profile = model_profile(
        profile_ref="model.deepseek",
        provider="openai-compatible",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-test",
    )
    prepared = ProviderEgress(profile).prepare(
        "model.openai_chat",
        {"messages": [{"role": "user", "content": "hello"}]},
        "secret",
    )
    assert prepared.url == "https://api.deepseek.com/v1/chat/completions"


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": [{"role": "user", "content": "hello"}], "tools": []},
        {"messages": [{"role": "user", "content": "hello"}], "stream": True},
        {"messages": [{"role": "tool", "content": "hello"}]},
        {"messages": [{"role": "user", "content": "hello"}], "response_format": {"type": "text"}},
    ],
)
def test_openai_arbitrary_tools_streams_and_message_shapes_are_blocked(payload: dict[str, object]) -> None:
    with pytest.raises(ProviderEgressError):
        ProviderEgress(model_profile()).prepare("model.openai_chat", payload, "secret")


def test_hermes_is_the_only_explicit_loopback_profile_and_needs_no_auth_header() -> None:
    profile = model_profile(
        profile_ref="model.hermes",
        provider="hermes",
        base_url="http://127.0.0.1:8317/v1",
        model="grok-4.5",
    )
    prepared = ProviderEgress(profile).prepare(
        "model.openai_chat",
        {"messages": [{"role": "user", "content": "hello"}]},
        "",
    )
    assert prepared.url == "http://127.0.0.1:8317/v1/chat/completions"
    assert set(prepared.headers) == {"Content-Type"}


def test_anthropic_and_gemini_have_fixed_origins_and_service_built_auth() -> None:
    anthropic = ProviderEgress(
        model_profile(
            profile_ref="model.anthropic",
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-test",
        )
    ).prepare(
        "model.anthropic_messages",
        {
            "system": "Return JSON",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 200,
        },
        "anthropic-secret",
    )
    assert anthropic.url == "https://api.anthropic.com/v1/messages"
    assert anthropic.headers["x-api-key"] == "anthropic-secret"
    assert anthropic.headers["anthropic-version"] == "2023-06-01"

    gemini = ProviderEgress(
        model_profile(
            profile_ref="model.gemini",
            provider="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-test",
        )
    ).prepare(
        "model.gemini_content",
        {
            "systemInstruction": {"parts": [{"text": "Return JSON"}]},
            "contents": [
                {"role": "user", "parts": [{"text": "INPUT_JSON\n{\"value\":1}"}]}
            ],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 100},
        },
        "gemini-secret",
    )
    assert gemini.url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    assert gemini.headers["x-goog-api-key"] == "gemini-secret"
    gemini_body = json.loads(gemini.body)
    assert gemini_body["systemInstruction"] == {
        "parts": [{"text": "Return JSON"}]
    }
    assert gemini_body["contents"] == [
        {"role": "user", "parts": [{"text": "INPUT_JSON\n{\"value\":1}"}]}
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "contents": [
                {"role": "user", "parts": [{"text": "INPUT_JSON\n{}"}]}
            ]
        },
        {
            "systemInstruction": {
                "parts": [{"text": "fixed"}],
                "role": "system",
            },
            "contents": [
                {"role": "user", "parts": [{"text": "INPUT_JSON\n{}"}]}
            ],
        },
        {
            "systemInstruction": {
                "parts": [{"text": "fixed"}, {"text": "second"}]
            },
            "contents": [
                {"role": "user", "parts": [{"text": "INPUT_JSON\n{}"}]}
            ],
        },
        {
            "systemInstruction": {"parts": [{"text": "fixed", "tool": {}}]},
            "contents": [
                {"role": "user", "parts": [{"text": "INPUT_JSON\n{}"}]}
            ],
        },
        {
            "systemInstruction": {"parts": [{"text": "fixed"}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "INPUT_JSON\n{}"}, {"text": "extra"}],
                }
            ],
        },
        {
            "systemInstruction": {"parts": [{"text": "fixed"}]},
            "contents": [
                {"role": "model", "parts": [{"text": "INPUT_JSON\n{}"}]}
            ],
        },
        {
            "systemInstruction": {"parts": [{"text": "fixed"}]},
            "contents": [
                {"role": "user", "parts": [{"text": "not input json"}]}
            ],
        },
        {
            "systemInstruction": {"parts": [{"text": "fixed"}]},
            "contents": [
                {"role": "user", "parts": [{"text": "INPUT_JSON\n{} trailing"}]}
            ],
        },
        {
            "systemInstruction": {"parts": [{"text": "fixed"}]},
            "contents": [
                {"role": "user", "parts": [{"text": "INPUT_JSON\n[]"}]}
            ],
        },
        {
            "systemInstruction": {"parts": [{"text": "fixed"}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": 'INPUT_JSON\n{"a":1,"a":2}'}],
                }
            ],
        },
        {
            "systemInstruction": {"parts": [{"text": "fixed"}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "INPUT_JSON\n{}", "toolCall": {}}],
                }
            ],
        },
    ],
)
def test_gemini_system_and_user_boundaries_fail_closed(
    payload: dict[str, object],
) -> None:
    profile = model_profile(
        profile_ref="model.gemini",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-test",
    )
    with pytest.raises(ProviderEgressError) as caught:
        ProviderEgress(profile).prepare("model.gemini_content", payload, "secret")
    assert caught.value.code in {
        "PROVIDER_PAYLOAD_INVALID",
        "PROVIDER_PAYLOAD_FIELD_BLOCKED",
    }


def test_gemini_prompt_limit_counts_system_and_user_text_together() -> None:
    profile = model_profile(
        profile_ref="model.gemini",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-test",
    )
    input_prefix = 'INPUT_JSON\n{"value":"'
    input_suffix = '"}'
    desired_content_length = MAX_PROMPT_CHARS - 10
    content_text = (
        input_prefix
        + "x"
        * (desired_content_length - len(input_prefix) - len(input_suffix))
        + input_suffix
    )
    assert len(content_text) == desired_content_length
    payload = {
        "systemInstruction": {"parts": [{"text": "s" * 20}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": content_text}],
            }
        ],
    }
    with pytest.raises(ProviderEgressError) as caught:
        ProviderEgress(profile).prepare("model.gemini_content", payload, "secret")
    assert caught.value.code == "PROVIDER_PAYLOAD_INVALID"


def test_operation_must_match_provider_and_capability() -> None:
    with pytest.raises(ProviderEgressError) as provider_error:
        ProviderEgress(model_profile()).prepare(
            "model.anthropic_messages",
            {"messages": [{"role": "user", "content": "hello"}], "max_tokens": 10},
            "secret",
        )
    assert provider_error.value.code == "BROKER_OPERATION_BLOCKED"

    tts_profile = ProviderProfile(
        profile_ref="tts.primary",
        capability="tts",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="tts-test",
        voice="alloy",
        maximum_response_bytes=4096,
    )
    with pytest.raises(ProviderEgressError) as capability_error:
        ProviderEgress(tts_profile).prepare(
            "model.openai_chat",
            {"messages": [{"role": "user", "content": "hello"}]},
            "secret",
        )
    assert capability_error.value.code == "BROKER_OPERATION_BLOCKED"


def test_json_response_is_bounded_and_redirects_are_rejected() -> None:
    profile = model_profile(maximum_response_bytes=128)
    payload = {"messages": [{"role": "user", "content": "hello"}]}

    def ok_transport(request):
        return ProviderTransportResponse(200, request.url, {"content-type": "application/json"}, b'{"ok":true}')

    result, response_bytes, cost = ProviderEgress(profile, transport=ok_transport).execute(
        "model.openai_chat", payload, "secret"
    )
    assert result == {"ok": True}
    assert response_bytes == 11
    assert cost is None

    def redirect_transport(request):
        return ProviderTransportResponse(200, "https://evil.example/redirect", {}, b"{}")

    with pytest.raises(ProviderEgressError) as redirected:
        ProviderEgress(profile, transport=redirect_transport).execute("model.openai_chat", payload, "secret")
    assert redirected.value.code == "PROVIDER_REDIRECT_BLOCKED"

    def oversized_transport(request):
        return ProviderTransportResponse(200, request.url, {}, b"x" * 129)

    with pytest.raises(ProviderEgressError) as oversized:
        ProviderEgress(profile, transport=oversized_transport).execute("model.openai_chat", payload, "secret")
    assert oversized.value.code == "PROVIDER_RESPONSE_LIMIT"


def test_tts_response_is_returned_as_bounded_authenticated_audio_evidence() -> None:
    profile = ProviderProfile(
        profile_ref="tts.xai",
        capability="tts",
        provider="xai",
        base_url="https://api.x.ai/v1",
        model="tts-test",
        voice="eve",
        maximum_response_bytes=4096,
    )
    audio = b"ID3" + b"\x00" * 64

    def transport(request):
        body = json.loads(request.body)
        assert body == {
            "text": "hello",
            "voice_id": "eve",
            "language": "en-US",
            "output_format": {"codec": "mp3", "sample_rate": 24000, "bit_rate": 128000},
        }
        assert request.url == "https://api.x.ai/v1/tts"
        assert request.headers["Authorization"] == "Bearer tts-secret"
        return ProviderTransportResponse(200, request.url, {"content-type": "audio/mpeg"}, audio)

    result, response_bytes, cost = ProviderEgress(profile, transport=transport).execute(
        "tts.synthesize",
        {
            "input": "hello",
            "language": "en-US",
            "response_format": "mp3",
            "sample_rate": 24000,
            "bit_rate": 128000,
        },
        "tts-secret",
    )
    assert result["audioBase64"] == base64.b64encode(audio).decode("ascii")
    assert result["byteLength"] == len(audio)
    assert result["sha256"] == hashlib.sha256(audio).hexdigest()
    assert result["mimeType"] == "audio/mpeg"
    assert response_bytes == len(audio)
    assert cost is None


def test_worker_cannot_select_tts_model_voice_or_origin() -> None:
    profile = ProviderProfile(
        profile_ref="tts.openai",
        capability="tts",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini-tts",
        voice="alloy",
        maximum_response_bytes=4096,
    )
    for blocked in ({"model": "spoofed"}, {"voice": "spoofed"}, {"base_url": "https://evil.invalid"}):
        with pytest.raises(ProviderEgressError) as caught:
            ProviderEgress(profile).prepare(
                "tts.synthesize",
                {"input": "hello", "language": "en-US", **blocked},
                "secret",
            )
        assert caught.value.code == "PROVIDER_PAYLOAD_FIELD_BLOCKED"


def test_binary_tts_rejects_non_mp3_mime_even_when_body_is_nonempty() -> None:
    profile = ProviderProfile(
        profile_ref="tts.openai",
        capability="tts",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini-tts",
        voice="alloy",
        maximum_response_bytes=4096,
    )

    def transport(request):
        return ProviderTransportResponse(200, request.url, {"content-type": "text/html"}, b"not audio")

    with pytest.raises(ProviderEgressError) as caught:
        ProviderEgress(profile, transport=transport).execute(
            "tts.synthesize",
            {"input": "hello", "language": "en-US"},
            "secret",
        )
    assert caught.value.code == "PROVIDER_RESPONSE_INVALID"


def test_mimo_tts_uses_service_profile_api_key_header_and_inline_wav() -> None:
    profile = ProviderProfile(
        profile_ref="tts.mimo",
        capability="tts",
        provider="openai-compatible",
        base_url="https://token-plan-sgp.xiaomimimo.com/v1",
        model="mimo-v2.5-tts",
        voice="mimo_default",
        maximum_response_bytes=4096,
    )
    audio = b"RIFF" + b"\x00" * 64

    def transport(request):
        body = json.loads(request.body)
        assert request.url == "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"
        assert request.headers["api-key"] == "mimo-secret"
        assert "Authorization" not in request.headers
        assert body["model"] == "mimo-v2.5-tts"
        assert body["audio"] == {"format": "wav", "voice": "mimo_default"}
        assert body["messages"][1] == {"role": "assistant", "content": "hello"}
        response = {"choices": [{"message": {"audio": {"data": base64.b64encode(audio).decode("ascii")}}}]}
        return ProviderTransportResponse(200, request.url, {"content-type": "application/json"}, json.dumps(response).encode())

    result, response_bytes, _ = ProviderEgress(profile, transport=transport).execute(
        "tts.synthesize",
        {"input": "hello", "language": "en-US", "response_format": "mp3"},
        "mimo-secret",
    )
    assert base64.b64decode(result["audioBase64"]) == audio
    assert result["mimeType"] == "audio/wav"
    assert response_bytes == len(audio)


def test_qwen_secondary_audio_url_is_blocked_instead_of_fetched_by_worker() -> None:
    profile = ProviderProfile(
        profile_ref="tts.qwen",
        capability="tts",
        provider="openai-compatible",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        model="qwen3-tts-flash",
        voice="Cherry",
        maximum_response_bytes=4096,
    )

    def transport(request):
        assert request.url.endswith("/api/v1/services/aigc/multimodal-generation/generation")
        return ProviderTransportResponse(
            200,
            request.url,
            {"content-type": "application/json"},
            b'{"output":{"audio":{"url":"https://secondary.example/audio.wav"}}}',
        )

    with pytest.raises(ProviderEgressError) as caught:
        ProviderEgress(profile, transport=transport).execute(
            "tts.synthesize",
            {"input": "hello", "language": "en-US"},
            "qwen-secret",
        )
    assert caught.value.code == "TTS_SECONDARY_URL_BLOCKED"


def test_gemini_tts_returns_validated_pcm_with_sample_rate() -> None:
    profile = ProviderProfile(
        profile_ref="tts.gemini",
        capability="tts",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.5-flash-preview-tts",
        voice="Kore",
        maximum_response_bytes=4096,
    )
    audio = b"\x01\x02" * 32

    def transport(request):
        body = json.loads(request.body)
        assert request.url.endswith("/models/gemini-2.5-flash-preview-tts:generateContent")
        assert request.headers["x-goog-api-key"] == "gemini-secret"
        assert body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"
        response = {
            "candidates": [{"content": {"parts": [{"inlineData": {
                "mimeType": "audio/pcm;rate=24000",
                "data": base64.b64encode(audio).decode("ascii"),
            }}]}}]
        }
        return ProviderTransportResponse(200, request.url, {}, json.dumps(response).encode())

    result, response_bytes, _ = ProviderEgress(profile, transport=transport).execute(
        "tts.synthesize",
        {"input": "hello", "language": "en-US", "sample_rate": 24000},
        "gemini-secret",
    )
    assert base64.b64decode(result["audioBase64"]) == audio
    assert result["mimeType"] == "audio/pcm"
    assert result["sampleRate"] == 24000
    assert response_bytes == len(audio)


def test_tts_profiles_without_approved_adapter_fail_closed() -> None:
    with pytest.raises(ProviderEgressError) as caught:
        ProviderProfile(
            profile_ref="tts.deepseek",
            capability="tts",
            provider="openai-compatible",
            base_url="https://api.deepseek.com/v1",
            model="not-a-tts-model",
            voice="alloy",
        )
    assert caught.value.code == "BROKER_OPERATION_BLOCKED"


def test_default_transport_reaches_fixed_hermes_loopback_and_blocks_redirects() -> None:
    observed = []

    class Handler(http.server.BaseHTTPRequestHandler):
        redirect = False

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            observed.append((self.path, dict(self.headers), self.rfile.read(length)))
            if self.redirect:
                self.send_response(302)
                self.send_header("Location", "/redirected")
                self.end_headers()
                return
            payload = b'{"choices":[{"message":{"content":"local ok"}}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        profile = model_profile(
            profile_ref="model.hermes",
            provider="hermes",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            model="grok-4.5",
        )
        egress = ProviderEgress(profile)
        result, _, _ = egress.execute(
            "model.openai_chat",
            {"messages": [{"role": "user", "content": "hello"}]},
            "",
        )
        assert result["choices"][0]["message"]["content"] == "local ok"
        assert observed[0][0] == "/v1/chat/completions"
        assert "Authorization" not in observed[0][1]
        assert json.loads(observed[0][2])["model"] == "grok-4.5"

        Handler.redirect = True
        with pytest.raises(ProviderEgressError) as redirected:
            egress.execute(
                "model.openai_chat",
                {"messages": [{"role": "user", "content": "hello again"}]},
                "",
            )
        assert redirected.value.code in {"PROVIDER_REDIRECT_BLOCKED", "PROVIDER_HTTP_ERROR"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
