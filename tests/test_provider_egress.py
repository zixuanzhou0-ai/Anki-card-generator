from __future__ import annotations

import base64
import hashlib
import http.server
import json
import threading

import pytest

from card_service.provider_egress import (
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
            "contents": [{"parts": [{"text": "hello"}]}],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 100},
        },
        "gemini-secret",
    )
    assert gemini.url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    assert gemini.headers["x-goog-api-key"] == "gemini-secret"


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
            "input": "hello",
            "model": "tts-test",
            "response_format": "mp3",
            "voice": "eve",
        }
        assert request.headers["Authorization"] == "Bearer tts-secret"
        return ProviderTransportResponse(200, request.url, {"content-type": "audio/mpeg"}, audio)

    result, response_bytes, cost = ProviderEgress(profile, transport=transport).execute(
        "tts.synthesize",
        {"input": "hello", "model": "spoofed", "voice": "spoofed", "response_format": "mp3"},
        "tts-secret",
    )
    assert result["audioBase64"] == base64.b64encode(audio).decode("ascii")
    assert result["byteLength"] == len(audio)
    assert result["sha256"] == hashlib.sha256(audio).hexdigest()
    assert result["mimeType"] == "audio/mpeg"
    assert response_bytes == len(audio)
    assert cost is None


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
