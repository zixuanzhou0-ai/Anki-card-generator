from __future__ import annotations

from unittest.mock import patch

import pytest

from workers.acg import managed_model_broker


class FakeClient:
    def __init__(self, operations: set[str] | None = None) -> None:
        self.allowed_operations = frozenset(operations or {"model.openai_chat"})
        self.calls: list[tuple[str, dict[str, object]]] = []

    def request(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation, payload))
        return {"ok": True}


def test_managed_model_request_contains_only_work_unit_and_provider_body() -> None:
    client = FakeClient()
    body = {"model": "worker-hint", "messages": [{"role": "user", "content": "hello"}]}
    with patch.object(managed_model_broker, "configured_client", return_value=client):
        assert managed_model_broker.request_model(
            "model.openai_chat",
            body,
            work_unit_base="cards:batch-1",
        ) == {"ok": True}
    operation, payload = client.calls[0]
    assert operation == "model.openai_chat"
    assert set(payload) == {"workUnitId", "request"}
    assert payload["request"] == body
    assert str(payload["workUnitId"]).startswith("openai-chat:cards:batch-1:")
    assert len(str(payload["workUnitId"])) <= 160


def test_work_unit_is_stable_for_same_body_and_changes_with_body() -> None:
    client = FakeClient()
    with patch.object(managed_model_broker, "configured_client", return_value=client):
        for content in ("same", "same", "changed"):
            managed_model_broker.request_model(
                "model.openai_chat",
                {"messages": [{"role": "user", "content": content}]},
                work_unit_base="review/unsafe label",
            )
    ids = [str(payload["workUnitId"]) for _, payload in client.calls]
    assert ids[0] == ids[1]
    assert ids[0] != ids[2]
    assert "/" not in ids[0]


@pytest.mark.parametrize(
    "blocked",
    [
        {"url": "https://attacker.invalid"},
        {"headers": {"Authorization": "secret"}},
        {"api_key": "secret"},
        {"nested": [{"profileRef": "attacker"}]},
        {"credential_revision": 7},
        {"budget": {"max": 999}},
    ],
)
def test_worker_cannot_add_service_owned_request_fields(blocked: dict[str, object]) -> None:
    client = FakeClient()
    with patch.object(managed_model_broker, "configured_client", return_value=client):
        with pytest.raises(managed_model_broker.ManagedModelBrokerError):
            managed_model_broker.request_model(
                "model.openai_chat",
                {"messages": [{"role": "user", "content": "hello"}], **blocked},
                work_unit_base="batch-1",
            )
    assert client.calls == []


def test_unknown_or_unauthorized_operation_is_blocked_before_ipc() -> None:
    client = FakeClient({"model.gemini_content"})
    with patch.object(managed_model_broker, "configured_client", return_value=client):
        assert managed_model_broker.operation_available("model.gemini_content") is True
        assert managed_model_broker.operation_available("model.openai_chat") is False
        with pytest.raises(managed_model_broker.ManagedModelBrokerError):
            managed_model_broker.request_model(
                "model.openai_chat",
                {"messages": [{"role": "user", "content": "hello"}]},
                work_unit_base="batch-1",
            )
    assert client.calls == []


def test_non_object_broker_response_is_rejected() -> None:
    client = FakeClient()
    client.request = lambda *_args, **_kwargs: ["not", "an", "object"]  # type: ignore[method-assign,return-value]
    with patch.object(managed_model_broker, "configured_client", return_value=client):
        with pytest.raises(managed_model_broker.ManagedModelBrokerError):
            managed_model_broker.request_model(
                "model.openai_chat",
                {"messages": [{"role": "user", "content": "hello"}]},
                work_unit_base="batch-1",
            )
