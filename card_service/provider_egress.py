from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .credentials import PROFILE_REF_PATTERN


MAX_MODEL_RESPONSE_BYTES = 900 * 1024
MAX_TTS_RESPONSE_BYTES = 700 * 1024
MAX_TTS_WIRE_RESPONSE_BYTES = 1024 * 1024
MAX_PROMPT_CHARS = 400_000
MAX_TTS_CHARS = 20_000

PROVIDER_OPERATIONS = {
    "openai": frozenset({"model.openai_chat", "tts.synthesize"}),
    "openai-compatible": frozenset({"model.openai_chat", "tts.synthesize"}),
    "xai": frozenset({"model.openai_chat", "tts.synthesize"}),
    "hermes": frozenset({"model.openai_chat"}),
    "anthropic": frozenset({"model.anthropic_messages"}),
    "gemini": frozenset({"model.gemini_content", "tts.synthesize"}),
}
FIXED_PROVIDER_HOSTS = {
    "openai": "api.openai.com",
    "xai": "api.x.ai",
    "anthropic": "api.anthropic.com",
    "gemini": "generativelanguage.googleapis.com",
}
OPENAI_COMPATIBLE_HOSTS = frozenset(
    {
        "api.deepseek.com",
        "api.xiaomimimo.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope.aliyuncs.com",
        "token-plan-cn.xiaomimimo.com",
        "token-plan-sgp.xiaomimimo.com",
    }
)


class ProviderEgressError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProviderProfile:
    profile_ref: str
    capability: str
    provider: str
    base_url: str
    model: str
    voice: str = ""
    timeout_seconds: float = 120.0
    maximum_response_bytes: int = 512 * 1024

    def __post_init__(self) -> None:
        if not PROFILE_REF_PATTERN.fullmatch(self.profile_ref):
            raise ProviderEgressError("PROFILE_INVALID", "Provider profile reference is invalid")
        if self.capability not in {"model", "tts"}:
            raise ProviderEgressError("PROFILE_INVALID", "Provider capability is invalid")
        provider = self.provider.strip().casefold()
        if provider not in PROVIDER_OPERATIONS:
            raise ProviderEgressError("PROVIDER_NOT_ALLOWED", "Provider is not allowed")
        model = self.model.strip()
        voice = self.voice.strip()
        unsafe_categories = {"Cc", "Cf", "Cs", "Zl", "Zp"}
        if (
            not model
            or len(model) > 200
            or any(unicodedata.category(char) in unsafe_categories for char in model)
        ):
            raise ProviderEgressError("PROFILE_INVALID", "Provider model is invalid")
        if len(voice) > 120 or any(
            unicodedata.category(char) in unsafe_categories for char in voice
        ):
            raise ProviderEgressError("PROFILE_INVALID", "Provider voice is invalid")
        if self.capability == "tts" and not voice:
            raise ProviderEgressError("PROFILE_INVALID", "TTS provider voice is required")
        timeout = float(self.timeout_seconds)
        if not 1 <= timeout <= 180:
            raise ProviderEgressError("PROFILE_INVALID", "Provider timeout is outside the allowed range")
        response_limit = int(self.maximum_response_bytes)
        maximum = MAX_TTS_RESPONSE_BYTES if self.capability == "tts" else MAX_MODEL_RESPONSE_BYTES
        if not 1 <= response_limit <= maximum:
            raise ProviderEgressError("PROFILE_INVALID", "Provider response limit is outside the allowed range")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "voice", voice)
        object.__setattr__(self, "base_url", _normalized_base_url(provider, self.base_url))
        if self.capability == "tts" and _tts_adapter(self) is None:
            raise ProviderEgressError(
                "BROKER_OPERATION_BLOCKED",
                "The provider profile does not have an approved TTS adapter",
            )
        object.__setattr__(self, "timeout_seconds", timeout)
        object.__setattr__(self, "maximum_response_bytes", response_limit)


@dataclass(frozen=True)
class PreparedProviderRequest:
    operation: str
    url: str
    body: bytes = field(repr=False)
    headers: Mapping[str, str] = field(repr=False)
    timeout_seconds: float
    maximum_response_bytes: int
    response_adapter: str


@dataclass(frozen=True)
class ProviderTransportResponse:
    status: int
    url: str
    headers: Mapping[str, str]
    body: bytes = field(repr=False)


ProviderTransport = Callable[[PreparedProviderRequest], ProviderTransportResponse]


def _normalized_base_url(provider: str, value: str) -> str:
    raw = value.strip().rstrip("/")
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise ProviderEgressError("PROVIDER_ORIGIN_INVALID", "Provider origin is invalid") from error
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if (
        not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.scheme not in {"http", "https"}
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ProviderEgressError("PROVIDER_ORIGIN_INVALID", "Provider origin is invalid")
    decoded_path = urllib.parse.unquote(parsed.path)
    if "\\" in decoded_path or any(part in {".", ".."} for part in decoded_path.split("/")):
        raise ProviderEgressError("PROVIDER_ORIGIN_INVALID", "Provider origin path is invalid")
    if provider == "hermes":
        if parsed.scheme != "http" or hostname not in {"127.0.0.1", "::1"}:
            raise ProviderEgressError("PROVIDER_ORIGIN_BLOCKED", "Hermes must use an explicit loopback origin")
    else:
        if parsed.scheme != "https" or hostname == "localhost" or hostname.endswith(".local"):
            raise ProviderEgressError("PROVIDER_ORIGIN_BLOCKED", "Remote providers must use a public HTTPS origin")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ProviderEgressError("PROVIDER_ORIGIN_BLOCKED", "Remote provider IP literals are blocked")
    fixed_host = FIXED_PROVIDER_HOSTS.get(provider)
    if fixed_host is not None and hostname != fixed_host:
        raise ProviderEgressError("PROVIDER_ORIGIN_BLOCKED", "Provider origin does not match the fixed service host")
    if provider == "openai-compatible" and hostname not in OPENAI_COMPATIBLE_HOSTS:
        raise ProviderEgressError(
            "PROVIDER_ORIGIN_BLOCKED",
            "Custom OpenAI-compatible origins require the later trusted-origin authorization boundary",
        )
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _endpoint(profile: ProviderProfile, operation: str) -> str:
    if operation == "model.openai_chat":
        suffix = "chat/completions"
    elif operation == "tts.synthesize":
        adapter = _tts_adapter(profile)
        if adapter == "openai_binary":
            suffix = "audio/speech"
        elif adapter == "xai_binary":
            suffix = "tts"
        elif adapter == "mimo_json":
            suffix = "chat/completions"
        elif adapter == "qwen_json":
            suffix = "services/aigc/multimodal-generation/generation"
        elif adapter == "gemini_json":
            versioned = profile.base_url if profile.base_url.endswith(("/v1", "/v1beta")) else f"{profile.base_url}/v1beta"
            model = urllib.parse.quote(profile.model, safe="")
            return f"{versioned}/models/{model}:generateContent"
        else:
            raise ProviderEgressError("BROKER_OPERATION_BLOCKED", "TTS provider adapter is not allowed")
    elif operation == "model.anthropic_messages":
        suffix = "messages" if profile.base_url.endswith("/v1") else "v1/messages"
    elif operation == "model.gemini_content":
        versioned = profile.base_url if profile.base_url.endswith(("/v1", "/v1beta")) else f"{profile.base_url}/v1beta"
        model = urllib.parse.quote(profile.model, safe="")
        return f"{versioned}/models/{model}:generateContent"
    else:
        raise ProviderEgressError("BROKER_OPERATION_BLOCKED", "Provider operation is not allowed")
    return f"{profile.base_url}/{suffix}"


def _bounded_text(value: Any, *, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", f"Provider {name} is invalid")
    return value


def _number(value: Any, *, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", f"Provider {name} is invalid")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", f"Provider {name} is invalid")
    return result


def _provider_host(profile: ProviderProfile) -> str:
    return (urllib.parse.urlsplit(profile.base_url).hostname or "").casefold().rstrip(".")


def _tts_adapter(profile: ProviderProfile) -> str | None:
    if profile.provider == "openai":
        return "openai_binary"
    if profile.provider == "xai":
        return "xai_binary"
    if profile.provider == "gemini":
        return "gemini_json"
    if profile.provider != "openai-compatible":
        return None
    host = _provider_host(profile)
    if host in {
        "api.xiaomimimo.com",
        "token-plan-cn.xiaomimimo.com",
        "token-plan-sgp.xiaomimimo.com",
    }:
        return "mimo_json"
    if host in {"dashscope-intl.aliyuncs.com", "dashscope.aliyuncs.com"}:
        return "qwen_json"
    return None


def _tts_language(value: Any) -> str:
    language = _bounded_text(value, name="TTS language", maximum=32)
    if re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language) is None:
        raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider TTS language is invalid")
    return language


def _qwen_language_type(language: str) -> str:
    lower = language.casefold()
    if lower.startswith("zh") or lower.startswith("cmn"):
        return "Chinese"
    if lower.startswith("en"):
        return "English"
    if lower.startswith("ja"):
        return "Japanese"
    if lower.startswith("ko"):
        return "Korean"
    if lower.startswith("fr"):
        return "French"
    if lower.startswith("de"):
        return "German"
    if lower.startswith("es"):
        return "Spanish"
    if lower.startswith("pt"):
        return "Portuguese"
    if lower.startswith("it"):
        return "Italian"
    if lower.startswith("ru"):
        return "Russian"
    return "Auto"


def _exact_tts_prompt(text: str) -> str:
    return (
        "Read the following text aloud exactly once. Do not explain, translate, expand, "
        "add words, or add a preface. Text:\n" + text
    )


def _messages(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 200:
        raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider messages are invalid")
    result: list[dict[str, str]] = []
    total = 0
    for item in value:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider message shape is invalid")
        role = str(item.get("role") or "")
        if role not in {"system", "user", "assistant"}:
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider message role is invalid")
        content = _bounded_text(item.get("content"), name="message content", maximum=MAX_PROMPT_CHARS)
        total += len(content)
        if total > MAX_PROMPT_CHARS:
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider prompt is too large")
        result.append({"role": role, "content": content})
    return result


def _openai_body(profile: ProviderProfile, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "model", "messages", "temperature", "max_tokens", "max_completion_tokens",
        "response_format", "reasoning_effort", "thinking", "enable_thinking",
        "thinking_budget", "preserve_thinking", "stream",
    }
    if set(payload) - allowed:
        raise ProviderEgressError("PROVIDER_PAYLOAD_FIELD_BLOCKED", "Provider payload contains blocked fields")
    body: dict[str, Any] = {"model": profile.model, "messages": _messages(payload.get("messages"))}
    if "temperature" in payload:
        body["temperature"] = _number(payload["temperature"], name="temperature", minimum=0, maximum=2)
    for name in ("max_tokens", "max_completion_tokens"):
        if name in payload:
            body[name] = int(_number(payload[name], name=name, minimum=1, maximum=32768))
    if "response_format" in payload:
        if payload["response_format"] != {"type": "json_object"}:
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider response format is invalid")
        body["response_format"] = {"type": "json_object"}
    if "reasoning_effort" in payload:
        effort = str(payload["reasoning_effort"])
        if effort not in {"low", "medium", "high"}:
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider reasoning effort is invalid")
        body["reasoning_effort"] = effort
    if "thinking" in payload:
        if payload["thinking"] != {"type": "enabled"}:
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider thinking mode is invalid")
        body["thinking"] = {"type": "enabled"}
    if "enable_thinking" in payload:
        if not isinstance(payload["enable_thinking"], bool):
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider thinking flag is invalid")
        body["enable_thinking"] = payload["enable_thinking"]
    if "thinking_budget" in payload:
        body["thinking_budget"] = int(
            _number(payload["thinking_budget"], name="thinking_budget", minimum=1, maximum=4000)
        )
    if "preserve_thinking" in payload:
        if payload["preserve_thinking"] is not False:
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider thinking preservation is invalid")
        body["preserve_thinking"] = False
    stream = payload.get("stream")
    if stream is not None and stream is not False:
        raise ProviderEgressError("PROVIDER_STREAMING_BLOCKED", "Provider streaming is not enabled in this broker version")
    return body


def _anthropic_body(profile: ProviderProfile, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"model", "system", "messages", "temperature", "max_tokens"}
    if set(payload) - allowed:
        raise ProviderEgressError("PROVIDER_PAYLOAD_FIELD_BLOCKED", "Provider payload contains blocked fields")
    messages = _messages(payload.get("messages"))
    if any(item["role"] == "system" for item in messages):
        raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Anthropic system content must use the system field")
    body: dict[str, Any] = {
        "model": profile.model,
        "messages": messages,
        "max_tokens": int(_number(payload.get("max_tokens"), name="max_tokens", minimum=1, maximum=32768)),
    }
    if not body["messages"]:
        raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Anthropic user messages are required")
    if "system" in payload:
        body["system"] = _bounded_text(payload["system"], name="system prompt", maximum=MAX_PROMPT_CHARS)
    if "temperature" in payload:
        body["temperature"] = _number(payload["temperature"], name="temperature", minimum=0, maximum=1)
    return body


def _gemini_body(profile: ProviderProfile, payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) - {"contents", "generationConfig"}:
        raise ProviderEgressError("PROVIDER_PAYLOAD_FIELD_BLOCKED", "Provider payload contains blocked fields")
    contents = payload.get("contents")
    if not isinstance(contents, list) or not 1 <= len(contents) <= 200:
        raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Gemini contents are invalid")
    rebuilt: list[dict[str, Any]] = []
    total = 0
    for content in contents:
        if not isinstance(content, dict) or set(content) - {"role", "parts"}:
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Gemini content shape is invalid")
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Gemini parts are invalid")
        rebuilt_parts = []
        for part in parts:
            if not isinstance(part, dict) or set(part) != {"text"}:
                raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Gemini part is invalid")
            text = _bounded_text(part.get("text"), name="content text", maximum=MAX_PROMPT_CHARS)
            total += len(text)
            rebuilt_parts.append({"text": text})
        role = str(content.get("role") or "user")
        if role not in {"user", "model"} or total > MAX_PROMPT_CHARS:
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Gemini content is invalid")
        rebuilt.append({"role": role, "parts": rebuilt_parts})
    config = payload.get("generationConfig") or {}
    if not isinstance(config, dict) or set(config) - {"temperature", "maxOutputTokens", "responseMimeType"}:
        raise ProviderEgressError("PROVIDER_PAYLOAD_FIELD_BLOCKED", "Gemini generation config is invalid")
    rebuilt_config: dict[str, Any] = {}
    if "temperature" in config:
        rebuilt_config["temperature"] = _number(config["temperature"], name="temperature", minimum=0, maximum=2)
    if "maxOutputTokens" in config:
        rebuilt_config["maxOutputTokens"] = int(
            _number(config["maxOutputTokens"], name="maxOutputTokens", minimum=1, maximum=32768)
        )
    if "responseMimeType" in config:
        if config["responseMimeType"] != "application/json":
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Gemini response MIME type is invalid")
        rebuilt_config["responseMimeType"] = "application/json"
    return {"contents": rebuilt, "generationConfig": rebuilt_config}


def _tts_body(profile: ProviderProfile, payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) - {"input", "language", "response_format", "sample_rate", "bit_rate"}:
        raise ProviderEgressError("PROVIDER_PAYLOAD_FIELD_BLOCKED", "TTS payload contains blocked fields")
    text = _bounded_text(payload.get("input"), name="TTS text", maximum=MAX_TTS_CHARS)
    language = _tts_language(payload.get("language") or "en-US")
    response_format = str(payload.get("response_format") or "mp3")
    if response_format != "mp3":
        raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "TTS response format is invalid")
    sample_rate = int(_number(payload.get("sample_rate", 24000), name="sample_rate", minimum=8000, maximum=48000))
    bit_rate = int(_number(payload.get("bit_rate", 128000), name="bit_rate", minimum=16000, maximum=320000))
    adapter = _tts_adapter(profile)
    if adapter == "openai_binary":
        return {"model": profile.model, "voice": profile.voice, "input": text, "response_format": "mp3"}
    if adapter == "xai_binary":
        return {
            "text": text,
            "voice_id": profile.voice,
            "language": language,
            "output_format": {"codec": "mp3", "sample_rate": sample_rate, "bit_rate": bit_rate},
        }
    if adapter == "mimo_json":
        model_lower = profile.model.casefold()
        if "voicedesign" in model_lower:
            user_content = profile.voice
            audio: dict[str, str] = {"format": "wav"}
        elif "voiceclone" in model_lower:
            user_content = ""
            audio = {"format": "wav", "voice": profile.voice}
        else:
            user_content = (
                f"Read the assistant message aloud exactly for a {language} language-learning Anki card. "
                "Do not explain, translate, expand, add words, or add a preface."
            )
            audio = {"format": "wav", "voice": profile.voice}
        return {
            "model": profile.model,
            "messages": [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": text},
            ],
            "audio": audio,
            "stream": False,
        }
    if adapter == "qwen_json":
        input_value: dict[str, Any] = {
            "text": text,
            "voice": profile.voice,
            "language_type": _qwen_language_type(language),
        }
        if "instruct" in profile.model.casefold():
            input_value["instructions"] = (
                "Read the input text aloud exactly for a language-learning Anki card. "
                "Do not explain, translate, expand, add words, or add a preface. "
                "Use steady pacing and accurate pronunciation."
            )
            input_value["optimize_instructions"] = True
        return {"model": profile.model, "input": input_value}
    if adapter == "gemini_json":
        return {
            "contents": [{"role": "user", "parts": [{"text": _exact_tts_prompt(text)}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "languageCode": language,
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": profile.voice}},
                },
            },
        }
    raise ProviderEgressError("BROKER_OPERATION_BLOCKED", "TTS provider adapter is not allowed")


def _decode_audio_base64(value: Any, *, maximum: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Provider returned no inline audio")
    try:
        audio = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Provider returned invalid inline audio") from error
    if not audio or len(audio) > maximum:
        code = "PROVIDER_RESPONSE_LIMIT" if len(audio) > maximum else "PROVIDER_RESPONSE_INVALID"
        raise ProviderEgressError(code, "Provider inline audio is empty or exceeded its byte limit")
    return audio


def _json_object(response: ProviderTransportResponse) -> dict[str, Any]:
    try:
        result = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Provider response is not valid JSON") from error
    if not isinstance(result, dict):
        raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Provider JSON response must be an object")
    return result


def _audio_result(audio: bytes, mime_type: str, *, sample_rate: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "audioBase64": base64.b64encode(audio).decode("ascii"),
        "byteLength": len(audio),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "mimeType": mime_type,
    }
    if sample_rate is not None:
        result["sampleRate"] = sample_rate
    return result


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise ProviderEgressError("PROVIDER_REDIRECT_BLOCKED", "Provider redirects are blocked")


def _read_bounded(response: Any, maximum: int) -> bytes:
    content_length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
    if content_length:
        try:
            if int(content_length) > maximum:
                raise ProviderEgressError("PROVIDER_RESPONSE_LIMIT", "Provider response exceeded its byte limit")
        except ValueError:
            pass
    body = response.read(maximum + 1)
    if len(body) > maximum:
        raise ProviderEgressError("PROVIDER_RESPONSE_LIMIT", "Provider response exceeded its byte limit")
    return body


def _default_transport(request: PreparedProviderRequest) -> ProviderTransportResponse:
    handlers: list[Any] = [urllib.request.ProxyHandler({}), _NoRedirectHandler()]
    if urllib.parse.urlsplit(request.url).scheme == "https":
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    opener = urllib.request.build_opener(*handlers)
    outbound = urllib.request.Request(
        request.url,
        data=request.body,
        headers=dict(request.headers),
        method="POST",
    )
    try:
        with opener.open(outbound, timeout=request.timeout_seconds) as response:
            body = _read_bounded(response, request.maximum_response_bytes)
            return ProviderTransportResponse(
                status=int(getattr(response, "status", 200)),
                url=str(response.geturl()),
                headers={str(key).casefold(): str(value) for key, value in response.headers.items()},
                body=body,
            )
    except ProviderEgressError:
        raise
    except urllib.error.HTTPError as error:
        raise ProviderEgressError("PROVIDER_HTTP_ERROR", f"Provider returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ProviderEgressError("PROVIDER_UNAVAILABLE", "Provider connection failed") from error


class ProviderEgress:
    def __init__(self, profile: ProviderProfile, *, transport: ProviderTransport | None = None) -> None:
        self.profile = profile
        self.transport = transport or _default_transport

    def prepare(self, operation: str, payload: dict[str, Any], secret: str) -> PreparedProviderRequest:
        if operation not in PROVIDER_OPERATIONS[self.profile.provider]:
            raise ProviderEgressError("BROKER_OPERATION_BLOCKED", "Operation is not allowed for this provider")
        expected_capability = "tts" if operation == "tts.synthesize" else "model"
        if self.profile.capability != expected_capability:
            raise ProviderEgressError("BROKER_OPERATION_BLOCKED", "Operation does not match the provider capability")
        if not isinstance(payload, dict):
            raise ProviderEgressError("PROVIDER_PAYLOAD_INVALID", "Provider payload must be an object")
        if operation == "model.openai_chat":
            body = _openai_body(self.profile, payload)
        elif operation == "model.anthropic_messages":
            body = _anthropic_body(self.profile, payload)
        elif operation == "model.gemini_content":
            body = _gemini_body(self.profile, payload)
        else:
            body = _tts_body(self.profile, payload)
        adapter = _tts_adapter(self.profile) if operation == "tts.synthesize" else None
        if self.profile.provider == "hermes":
            headers = {"Content-Type": "application/json"}
        else:
            if not secret:
                raise ProviderEgressError("PROVIDER_CREDENTIAL_MISSING", "Provider credential is unavailable")
            if self.profile.provider == "anthropic":
                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": secret,
                    "anthropic-version": "2023-06-01",
                }
            elif self.profile.provider == "gemini":
                headers = {"Content-Type": "application/json", "x-goog-api-key": secret}
            elif adapter == "mimo_json":
                headers = {"Content-Type": "application/json", "api-key": secret}
            else:
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {secret}"}
        serialized = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        response_adapter = adapter or "json"
        wire_limit = self.profile.maximum_response_bytes
        if response_adapter in {"mimo_json", "qwen_json", "gemini_json"}:
            wire_limit = min(
                MAX_TTS_WIRE_RESPONSE_BYTES,
                int(self.profile.maximum_response_bytes * 4 / 3) + 64 * 1024,
            )
        return PreparedProviderRequest(
            operation=operation,
            url=_endpoint(self.profile, operation),
            body=serialized,
            headers=headers,
            timeout_seconds=self.profile.timeout_seconds,
            maximum_response_bytes=wire_limit,
            response_adapter=response_adapter,
        )

    def execute(self, operation: str, payload: dict[str, Any], secret: str) -> tuple[Any, int, int | None]:
        prepared = self.prepare(operation, payload, secret)
        response = self.transport(prepared)
        if response.url != prepared.url:
            raise ProviderEgressError("PROVIDER_REDIRECT_BLOCKED", "Provider response URL changed")
        if not 200 <= int(response.status) < 300:
            raise ProviderEgressError("PROVIDER_HTTP_ERROR", f"Provider returned HTTP {response.status}")
        if len(response.body) > prepared.maximum_response_bytes:
            raise ProviderEgressError("PROVIDER_RESPONSE_LIMIT", "Provider response exceeded its byte limit")
        if prepared.response_adapter == "json":
            result = _json_object(response)
            return result, len(response.body), None
        if prepared.response_adapter in {"openai_binary", "xai_binary"}:
            if not response.body or len(response.body) > self.profile.maximum_response_bytes:
                raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Provider returned invalid audio")
            mime_type = str(response.headers.get("content-type") or "").split(";", 1)[0].strip().casefold()
            if mime_type not in {"audio/mpeg", "audio/mp3"}:
                raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Provider returned an unexpected audio MIME type")
            return _audio_result(response.body, mime_type), len(response.body), None
        result = _json_object(response)
        if prepared.response_adapter == "mimo_json":
            try:
                data = result["choices"][0]["message"]["audio"]["data"]
            except (KeyError, IndexError, TypeError) as error:
                raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "MIMO returned no inline audio") from error
            audio = _decode_audio_base64(data, maximum=self.profile.maximum_response_bytes)
            return _audio_result(audio, "audio/wav"), len(audio), None
        if prepared.response_adapter == "qwen_json":
            try:
                audio_value = result["output"]["audio"]
            except (KeyError, TypeError) as error:
                raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Qwen returned no audio object") from error
            if not isinstance(audio_value, dict):
                raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Qwen returned an invalid audio object")
            if audio_value.get("url") and not audio_value.get("data"):
                raise ProviderEgressError(
                    "TTS_SECONDARY_URL_BLOCKED",
                    "Qwen returned a secondary media URL instead of task-bound inline audio",
                )
            audio = _decode_audio_base64(audio_value.get("data"), maximum=self.profile.maximum_response_bytes)
            return _audio_result(audio, "audio/wav"), len(audio), None
        if prepared.response_adapter == "gemini_json":
            inline: dict[str, Any] | None = None
            for candidate in result.get("candidates") or []:
                for part in ((candidate.get("content") or {}).get("parts") or []):
                    value = part.get("inlineData") or part.get("inline_data")
                    if isinstance(value, dict) and value.get("data"):
                        inline = value
                        break
                if inline is not None:
                    break
            if inline is None:
                raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Gemini returned no inline audio")
            mime_type = str(inline.get("mimeType") or inline.get("mime_type") or "audio/pcm").split(";", 1)[0].casefold()
            if mime_type not in {"audio/pcm", "audio/l16", "audio/raw"}:
                raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Gemini returned an unsupported audio MIME type")
            audio = _decode_audio_base64(inline.get("data"), maximum=self.profile.maximum_response_bytes)
            sample_rate = int(payload.get("sample_rate") or 24000)
            return _audio_result(audio, "audio/pcm", sample_rate=sample_rate), len(audio), None
        raise ProviderEgressError("PROVIDER_RESPONSE_INVALID", "Provider response adapter is invalid")
