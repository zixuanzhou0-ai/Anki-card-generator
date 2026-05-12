from __future__ import annotations

import json
import sys
from typing import Any


PROGRESS_PREFIX = "__ANKI_CARD_PROGRESS__"
ERROR_PREFIX = "__ANKI_CARD_ERROR__"


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().lstrip("\ufeff")
    if not raw.strip():
        return {}
    return json.loads(raw)


def emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def emit_progress(command: str, stage: str, percent: int, message: str) -> None:
    payload = {
        "command": command,
        "stage": stage,
        "percent": max(0, min(100, int(percent))),
        "message": message,
    }
    print(f"{PROGRESS_PREFIX}{json.dumps(payload, ensure_ascii=False)}", file=sys.stderr, flush=True)


def worker_error_payload(
    message: str,
    *,
    error_code: str | None = None,
    stage: str | None = None,
    retryable: bool = False,
    fallbacks: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message": message,
        "retryable": retryable,
        "fallbacks": fallbacks or [],
    }
    if error_code:
        payload["error_code"] = error_code
    if stage:
        payload["stage"] = stage
    return payload


def fail(
    message: str,
    code: int = 1,
    *,
    error_code: str | None = None,
    stage: str | None = None,
    retryable: bool = False,
    fallbacks: list[str] | None = None,
) -> None:
    payload = worker_error_payload(
        message,
        error_code=error_code,
        stage=stage,
        retryable=retryable,
        fallbacks=fallbacks,
    )
    print(f"{ERROR_PREFIX}{json.dumps(payload, ensure_ascii=False)}", file=sys.stderr, flush=True)
    print(message, file=sys.stderr)
    raise SystemExit(code)
