from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .broker_client import WorkerBrokerClient, WorkerBrokerError, configured_broker_client


MODEL_OPERATIONS = frozenset(
    {"model.openai_chat", "model.anthropic_messages", "model.gemini_content"}
)
FORBIDDEN_REQUEST_FIELDS = frozenset(
    {
        "url",
        "baseurl",
        "headers",
        "apikey",
        "authorization",
        "profileref",
        "credentialrevision",
        "operationintentref",
        "budget",
        "reservedcostminorunits",
    }
)
WORK_UNIT_PART = re.compile(r"[^A-Za-z0-9._:-]+")


class ManagedModelBrokerError(RuntimeError):
    pass


def configured_client() -> WorkerBrokerClient | None:
    return configured_broker_client()


def is_configured() -> bool:
    return configured_client() is not None


def operation_available(operation: str) -> bool:
    client = configured_client()
    return client is not None and operation in MODEL_OPERATIONS and operation in client.allowed_operations


def _normalized_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _assert_worker_request_is_unprivileged(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _normalized_field_name(key) in FORBIDDEN_REQUEST_FIELDS:
                raise ManagedModelBrokerError("Worker model request contains a Service-owned field")
            _assert_worker_request_is_unprivileged(child)
    elif isinstance(value, list):
        for child in value:
            _assert_worker_request_is_unprivileged(child)


def _work_unit_id(operation: str, base: str, request: dict[str, Any]) -> str:
    normalized_base = WORK_UNIT_PART.sub("-", str(base or "model")).strip("-._:") or "model"
    operation_part = operation.removeprefix("model.").replace("_", "-")
    digest = hashlib.sha256(
        json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    prefix = f"{operation_part}:{normalized_base}"[:136].rstrip("-._:")
    return f"{prefix}:{digest}"


def request_model(
    operation: str,
    request: dict[str, Any],
    *,
    work_unit_base: str,
) -> dict[str, Any]:
    client = configured_client()
    if client is None:
        raise ManagedModelBrokerError("Managed model broker is not configured")
    if operation not in MODEL_OPERATIONS or operation not in client.allowed_operations:
        raise ManagedModelBrokerError("Managed model operation is not authorized for this task")
    if not isinstance(request, dict) or not request:
        raise ManagedModelBrokerError("Managed model request is invalid")
    _assert_worker_request_is_unprivileged(request)
    try:
        result = client.request(
            operation,
            {
                "workUnitId": _work_unit_id(operation, work_unit_base, request),
                "request": request,
            },
        )
    except WorkerBrokerError as error:
        raise ManagedModelBrokerError(str(error)) from error
    if not isinstance(result, dict):
        raise ManagedModelBrokerError("Managed model broker returned an invalid response")
    return result
