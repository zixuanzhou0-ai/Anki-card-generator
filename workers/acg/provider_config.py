from __future__ import annotations

from typing import Any


MIMO_OPENAI_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_TOKEN_PLAN_SGP_BASE_URL = "https://token-plan-sgp.xiaomimimo.com/v1"
DEEPSEEK_OPENAI_BASE_URL = "https://api.deepseek.com"
QWEN_DASHSCOPE_CN_TTS_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
QWEN_TTS_DEFAULT_MODEL = "qwen3-tts-flash"
QWEN_TTS_DEFAULT_VOICE = "Jennifer"
GEMINI_VERTEX_TTS_GLOBAL_BASE_URL = "https://aiplatform.googleapis.com"
GEMINI_VERTEX_TTS_DEFAULT_MODEL = "gemini-3.1-flash-tts-preview"
GEMINI_VERTEX_TTS_DEFAULT_VOICE = "Kore"
MIMO_PROVIDERS = {"mimo", "xiaomi-mimo"}
QWEN_TTS_PROVIDERS = {"qwen", "dashscope", "aliyun-dashscope"}
GEMINI_VERTEX_TTS_PROVIDERS = {"gemini-vertex", "vertex-gemini", "gemini-vertex-tts", "vertex-gemini-tts"}
OPENAI_COMPATIBLE_PROVIDERS = {"openai-compatible", *MIMO_PROVIDERS}
GEMINI_VERTEX_PROVIDERS = {"gemini-vertex", "vertex-gemini"}
GEMINI_VERTEX_GLOBAL_BASE_URL = "https://aiplatform.googleapis.com"
GEMINI_VERTEX_DEFAULT_MODEL = "gemini-3.5-flash"
GEMINI_VERTEX_PRO_PREVIEW_MODEL = "gemini-3.1-pro-preview"
GEMINI_VERTEX_UNAVAILABLE_MODEL_ALIASES = {"gemini-3.1-pro"}
GEMINI_VERTEX_MODEL_ALIASES = {
    "gemini-3.5": "gemini-3.5-flash",
    "gemini-3.5-flash-latest": "gemini-3.5-flash",
}
DEEPSEEK_THINKING_MODELS = {"deepseek-v4-pro", "deepseek-v4-flash", "deepseek-reasoner"}


def provider_name(config: dict[str, Any]) -> str:
    return str(config.get("provider", "")).strip().lower()


def is_mimo_config(config: dict[str, Any]) -> bool:
    base_url = str(config.get("base_url") or "").lower()
    return provider_name(config) in MIMO_PROVIDERS or "xiaomimimo.com" in base_url


def is_qwen_config(config: dict[str, Any]) -> bool:
    base_url = str(config.get("base_url") or "").lower()
    model = str(config.get("model") or "").strip().lower()
    return (
        provider_name(config) in QWEN_TTS_PROVIDERS
        or "dashscope" in base_url
        or "qwencloud" in base_url
        or model.startswith("qwen")
    )


def is_deepseek_config(config: dict[str, Any]) -> bool:
    base_url = str(config.get("base_url") or "").lower()
    model = str(config.get("model") or "").strip().lower()
    return "deepseek.com" in base_url or model.startswith("deepseek-")


def is_deepseek_thinking_config(config: dict[str, Any]) -> bool:
    model = str(config.get("model") or "").strip().lower()
    return is_deepseek_config(config) and model in DEEPSEEK_THINKING_MODELS


def is_gemini_vertex_config(config: dict[str, Any]) -> bool:
    return provider_name(config) in GEMINI_VERTEX_PROVIDERS


def is_gemini_vertex_tts_config(config: dict[str, Any]) -> bool:
    return provider_name(config) in GEMINI_VERTEX_TTS_PROVIDERS


def is_gemini_vertex_thinking_config(config: dict[str, Any]) -> bool:
    model = str(config.get("model") or "").strip().lower()
    return is_gemini_vertex_config(config) and model.startswith("gemini-3.")


def is_thinking_model_config(config: dict[str, Any]) -> bool:
    return (
        is_qwen_config(config)
        or is_mimo_config(config)
        or is_deepseek_thinking_config(config)
        or is_gemini_vertex_thinking_config(config)
    )


def compatible_base_url(config: dict[str, Any], default_url: str = "") -> str:
    provider = provider_name(config)
    api_key = str(config.get("api_key") or "").strip().lower()
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    if is_mimo_config(config) and api_key.startswith("tp-") and "token-plan-" not in base_url.lower():
        return MIMO_TOKEN_PLAN_SGP_BASE_URL
    if base_url:
        return base_url
    if is_deepseek_config(config):
        return DEEPSEEK_OPENAI_BASE_URL
    if provider in MIMO_PROVIDERS:
        return MIMO_TOKEN_PLAN_SGP_BASE_URL if api_key.startswith("tp-") else MIMO_OPENAI_BASE_URL
    return default_url.rstrip("/")


def thinking_budget(config: dict[str, Any], default_value: int = 800) -> int:
    for key in ("thinking_budget", "reasoning_budget"):
        value = config.get(key)
        try:
            budget = int(value)
        except (TypeError, ValueError):
            continue
        if budget > 0:
            return min(budget, 4000)
    return default_value


def should_stream_reasoning(config: dict[str, Any]) -> bool:
    return is_thinking_model_config(config)


def api_key_header(config: dict[str, Any]) -> dict[str, str]:
    api_key = str(config.get("api_key") or "").strip()
    if is_mimo_config(config):
        return {"api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def model_api_available(api: dict[str, Any]) -> bool:
    provider = provider_name(api) or "local"
    if provider == "local":
        return False
    if not str(api.get("model") or "").strip():
        return False
    if is_gemini_vertex_config(api):
        return True
    return bool(str(api.get("api_key") or "").strip())
