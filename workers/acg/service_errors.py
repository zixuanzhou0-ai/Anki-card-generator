from __future__ import annotations

import re
import socket
import urllib.error
from typing import Any

from acg import errors as worker_errors


def http_status_from_error_message(message: str) -> int | None:
    for pattern in (r"\b(?:API|TTS(?: download)?) HTTP\s+(\d{3})\b", r"\bHTTP(?: Error)?\s+(\d{3})\b"):
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def service_error_codes(kind: str) -> dict[str, str]:
    if kind == "tts":
        return {
            "auth": worker_errors.TTS_AUTH_FAILED,
            "connection": worker_errors.TTS_CONNECTION_FAILED,
            "not_found": worker_errors.TTS_NOT_FOUND,
            "quota": worker_errors.TTS_QUOTA_EXCEEDED,
            "timeout": worker_errors.TTS_TIMEOUT,
        }
    return {
        "auth": worker_errors.MODEL_AUTH_FAILED,
        "connection": worker_errors.MODEL_CONNECTION_FAILED,
        "not_found": worker_errors.MODEL_NOT_FOUND,
        "quota": worker_errors.MODEL_QUOTA_EXCEEDED,
        "timeout": worker_errors.MODEL_TIMEOUT,
    }


def service_stage(kind: str) -> str:
    return "tts" if kind == "tts" else "model_api"


def service_label(kind: str) -> str:
    return "TTS" if kind == "tts" else "模型"


def service_error_message(kind: str, category: str, detail: str) -> str:
    label = service_label(kind)
    if category == "timeout":
        return f"{label}请求超时：{detail}。通常是单批内容太多、模型 thinking 时间过长，或网络代理不稳定。"
    if category == "auth":
        return f"{label}授权或权限失败：{detail}。请检查 gcloud 登录、Vertex AI 项目、API Key 或服务权限。"
    if category == "quota":
        return f"{label}配额或限流：{detail}。请稍后重试，或检查 Vertex AI 配额、并发限制和账单状态。"
    if category == "not_found":
        return f"{label}模型或端点不存在：{detail}。请检查模型名、Base URL、区域和项目是否支持该模型。"
    if category == "connection":
        return f"{label}网络连接异常：{detail}。请检查代理、DNS、Base URL 和本机网络。"
    return f"{label}请求失败：{detail}"


def classify_service_error(error: Exception, *, kind: str = "model") -> dict[str, Any]:
    detail = str(error).strip() or error.__class__.__name__
    lower = detail.lower()
    status = http_status_from_error_message(detail)
    codes = service_error_codes(kind)

    category = "unknown"
    retryable = False
    if (
        "max_tokens" in lower
        or "maxoutputtokens" in lower
        or "max_tokens" in detail
        or "MAX_TOKENS" in detail
        or "输出预算" in detail
        or "thinking 消耗完" in detail
    ):
        category = "timeout"
        retryable = True
    elif isinstance(error, (TimeoutError, socket.timeout)) or "timed out" in lower or "timeout" in lower or "超时" in detail:
        category = "timeout"
        retryable = True
    elif status in {401, 403} or any(term in lower for term in ("unauthorized", "unauthenticated", "forbidden", "permission", "invalid api key", "oauth")) or "权限" in detail:
        category = "auth"
    elif status == 429 or any(term in lower for term in ("resource exhausted", "quota", "rate limit", "too many requests")) or "限流" in detail or "配额" in detail:
        category = "quota"
        retryable = True
    elif status == 404 or any(term in lower for term in ("not found", "model not found", "publisher model")) or "不存在" in detail:
        category = "not_found"
    elif (
        isinstance(error, urllib.error.URLError)
        or status is not None and status >= 500
        or any(
            term in lower
            for term in (
                "urlopen error",
                "connection",
                "network",
                "proxy",
                "dns",
                "getaddrinfo",
                "remote end closed",
            )
        )
        or "连接" in detail
    ):
        category = "connection"
        retryable = True

    code = codes.get(category, worker_errors.UNKNOWN_WORKER_ERROR)
    return {
        "message": service_error_message(kind, category, detail),
        "error_code": code,
        "stage": service_stage(kind),
        "retryable": retryable,
    }


def classify_worker_exception(error: Exception, *, command: str = "") -> dict[str, Any]:
    detail = str(error)
    lower = detail.lower()
    if command == "test_tts" or "tts" in lower or "audio" in lower or "语音" in detail:
        return classify_service_error(error, kind="tts")
    if command in {"test_api", "generate"} or "api" in lower or "模型" in detail or "gemini" in lower or "vertex" in lower:
        return classify_service_error(error, kind="model")
    return {
        "message": detail.strip() or error.__class__.__name__,
        "error_code": worker_errors.UNKNOWN_WORKER_ERROR,
        "stage": command or None,
        "retryable": False,
    }
