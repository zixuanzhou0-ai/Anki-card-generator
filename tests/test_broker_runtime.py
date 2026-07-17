from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from card_service.broker import BrokerBudget, BrokerError, BrokerReservationLedger, ModelTtsBroker
from card_service.broker_ipc import BrokerIpcError
from card_service.broker_runtime import (
    AuthorizedProviderCall,
    TaskBrokerAuthorization,
    make_task_broker_handler,
)
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.provider_egress import ProviderProfile, ProviderTransportResponse


def runtime(tmp_path: Path):
    backend = InMemoryCredentialBackend()
    credentials = CredentialStore(state_dir=(tmp_path / "credentials").resolve(), backend=backend)
    ledger = BrokerReservationLedger((tmp_path / "broker-ledger.json").resolve())
    return credentials, backend, ledger, ModelTtsBroker(credential_store=credentials, ledger=ledger)


def openai_profile() -> ProviderProfile:
    return ProviderProfile(
        profile_ref="model.primary",
        capability="model",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-test",
        maximum_response_bytes=4096,
    )


def authorization(binding: AuthorizedProviderCall, **budget_overrides: int) -> TaskBrokerAuthorization:
    budget_values = {
        "max_remote_calls": 4,
        "max_request_bytes": 100_000,
        "max_response_bytes": 100_000,
        "max_cost_minor_units": 100,
        **budget_overrides,
    }
    return TaskBrokerAuthorization(
        operation_intent_ref="intent-approved-1",
        budget=BrokerBudget(**budget_values),
        operations={"model.openai_chat": binding},
    )


def test_task_handler_uses_only_service_authorized_profile_secret_and_budget(tmp_path: Path) -> None:
    credentials, _, ledger, broker = runtime(tmp_path)
    metadata = credentials.set_secret("model.primary", "provider-secret-canary")
    observed = []

    def transport(request):
        observed.append(request)
        body = json.loads(request.body)
        assert body["model"] == "gpt-test"
        assert request.headers["Authorization"] == "Bearer provider-secret-canary"
        return ProviderTransportResponse(
            200,
            request.url,
            {"content-type": "application/json"},
            b'{"choices":[{"message":{"content":"ok"}}]}',
        )

    binding = AuthorizedProviderCall(
        profile=openai_profile(),
        credential_revision=int(metadata["credentialRevision"]),
        reserved_cost_minor_units=9,
        transport=transport,
    )
    handler = make_task_broker_handler(
        task_id="task-1",
        authorization=authorization(binding),
        broker=broker,
    )
    result = handler(
        "model.openai_chat",
        {
            "workUnitId": "batch-1",
            "request": {
                "model": "worker-spoofed-model",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 50,
            },
        },
    )
    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(observed) == 1
    record = ledger.list_records()[0]
    assert record["taskId"] == "task-1"
    assert record["workUnitId"] == "batch-1"
    assert record["profileRef"] == "model.primary"
    assert record["operationIntentRef"] == "intent-approved-1"
    assert record["actualCostMinorUnits"] == 9
    assert record["actualCostWasEstimated"] is True
    assert "provider-secret-canary" not in (tmp_path / "broker-ledger.json").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "payload",
    [
        {"workUnitId": "batch-1", "request": {}, "profileRef": "attacker"},
        {"workUnitId": "../escape", "request": {}},
        {"workUnitId": "batch-1", "request": "not-an-object"},
    ],
)
def test_worker_cannot_self_declare_profile_scope_or_invalid_work_unit(tmp_path: Path, payload: dict[str, object]) -> None:
    credentials, _, _, broker = runtime(tmp_path)
    metadata = credentials.set_secret("model.primary", "secret")
    binding = AuthorizedProviderCall(
        profile=openai_profile(),
        credential_revision=int(metadata["credentialRevision"]),
        reserved_cost_minor_units=1,
        transport=lambda request: ProviderTransportResponse(200, request.url, {}, b"{}"),
    )
    handler = make_task_broker_handler(task_id="task-1", authorization=authorization(binding), broker=broker)
    with pytest.raises(BrokerIpcError) as caught:
        handler("model.openai_chat", payload)
    assert caught.value.code == "BROKER_PAYLOAD_INVALID"


def test_same_work_unit_cannot_change_payload_under_a_new_ipc_request(tmp_path: Path) -> None:
    credentials, _, ledger, broker = runtime(tmp_path)
    metadata = credentials.set_secret("model.primary", "secret")
    sends = []

    def transport(request):
        sends.append(1)
        return ProviderTransportResponse(200, request.url, {}, b"{}")

    binding = AuthorizedProviderCall(
        profile=openai_profile(),
        credential_revision=int(metadata["credentialRevision"]),
        reserved_cost_minor_units=1,
        transport=transport,
    )
    handler = make_task_broker_handler(task_id="task-1", authorization=authorization(binding), broker=broker)
    handler(
        "model.openai_chat",
        {"workUnitId": "batch-1", "request": {"messages": [{"role": "user", "content": "first"}]}},
    )
    with pytest.raises(BrokerIpcError) as caught:
        handler(
            "model.openai_chat",
            {"workUnitId": "batch-1", "request": {"messages": [{"role": "user", "content": "changed"}]}},
        )
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    assert sends == [1]
    assert len(ledger.list_records()) == 1


def test_hermes_loopback_call_uses_revision_zero_without_a_secret(tmp_path: Path) -> None:
    _, backend, ledger, broker = runtime(tmp_path)
    observed = []

    def transport(request):
        observed.append(dict(request.headers))
        return ProviderTransportResponse(200, request.url, {}, b'{"ok":true}')

    profile = ProviderProfile(
        profile_ref="model.hermes",
        capability="model",
        provider="hermes",
        base_url="http://127.0.0.1:8317/v1",
        model="grok-4.5",
        maximum_response_bytes=4096,
    )
    binding = AuthorizedProviderCall(
        profile=profile,
        credential_revision=0,
        reserved_cost_minor_units=0,
        transport=transport,
    )
    handler = make_task_broker_handler(task_id="task-hermes", authorization=authorization(binding), broker=broker)
    assert handler(
        "model.openai_chat",
        {"workUnitId": "batch-1", "request": {"messages": [{"role": "user", "content": "hello"}]}},
    ) == {"ok": True}
    assert backend.values == {}
    assert observed == [{"Content-Type": "application/json"}]
    assert ledger.list_records()[0]["credentialRequired"] is False


def test_budget_is_service_owned_and_blocks_before_transport(tmp_path: Path) -> None:
    credentials, _, ledger, broker = runtime(tmp_path)
    metadata = credentials.set_secret("model.primary", "secret")
    sends = []
    binding = AuthorizedProviderCall(
        profile=openai_profile(),
        credential_revision=int(metadata["credentialRevision"]),
        reserved_cost_minor_units=9,
        transport=lambda request: sends.append(request) or ProviderTransportResponse(200, request.url, {}, b"{}"),
    )
    handler = make_task_broker_handler(
        task_id="task-1",
        authorization=authorization(binding, max_cost_minor_units=8),
        broker=broker,
    )
    with pytest.raises(BrokerIpcError) as caught:
        handler(
            "model.openai_chat",
            {"workUnitId": "batch-1", "request": {"messages": [{"role": "user", "content": "hello"}]}},
        )
    assert caught.value.code == "COST_BUDGET_EXCEEDED"
    assert sends == []
    assert ledger.list_records() == []


def test_expired_task_authorization_blocks_before_transport_or_reservation(tmp_path: Path) -> None:
    credentials, _, ledger, broker = runtime(tmp_path)
    metadata = credentials.set_secret("model.primary", "secret")
    sends = []
    binding = AuthorizedProviderCall(
        profile=openai_profile(),
        credential_revision=int(metadata["credentialRevision"]),
        reserved_cost_minor_units=1,
        transport=lambda request: sends.append(request) or ProviderTransportResponse(200, request.url, {}, b"{}"),
    )
    expired = TaskBrokerAuthorization(
        operation_intent_ref="intent-approved-1",
        budget=BrokerBudget(4, 100_000, 100_000, 100),
        operations={"model.openai_chat": binding},
        expires_at_unix_ms=int(time.time() * 1000) - 1,
    )
    handler = make_task_broker_handler(task_id="task-1", authorization=expired, broker=broker)
    with pytest.raises(BrokerIpcError) as caught:
        handler(
            "model.openai_chat",
            {"workUnitId": "batch-1", "request": {"messages": [{"role": "user", "content": "hello"}]}},
        )
    assert caught.value.code == "BROKER_AUTHORIZATION_EXPIRED"
    assert sends == []
    assert ledger.list_records() == []


def test_task_authorization_copies_operation_bindings_before_use(tmp_path: Path) -> None:
    credentials, _, _, broker = runtime(tmp_path)
    metadata = credentials.set_secret("model.primary", "secret")
    sends = []
    binding = AuthorizedProviderCall(
        profile=openai_profile(),
        credential_revision=int(metadata["credentialRevision"]),
        reserved_cost_minor_units=1,
        transport=lambda request: sends.append(request) or ProviderTransportResponse(200, request.url, {}, b"{}"),
    )
    mutable_operations = {"model.openai_chat": binding}
    task_authorization = TaskBrokerAuthorization(
        operation_intent_ref="intent-approved-1",
        budget=BrokerBudget(4, 100_000, 100_000, 100),
        operations=mutable_operations,
    )
    mutable_operations.clear()
    handler = make_task_broker_handler(task_id="task-1", authorization=task_authorization, broker=broker)
    assert handler(
        "model.openai_chat",
        {"workUnitId": "batch-1", "request": {"messages": [{"role": "user", "content": "hello"}]}},
    ) == {}
    assert len(sends) == 1


@pytest.mark.parametrize(
    "values",
    [
        (-1, 0, 0, None),
        (0, -1, 0, None),
        (0, 0, -1, None),
        (0, 0, 0, -1),
    ],
)
def test_negative_broker_budgets_are_rejected(values: tuple[int, int, int, int | None]) -> None:
    with pytest.raises(BrokerError) as caught:
        BrokerBudget(*values)
    assert caught.value.code == "INVALID_BUDGET"
