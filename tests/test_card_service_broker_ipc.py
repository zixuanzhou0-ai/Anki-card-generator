from __future__ import annotations

import base64
import json
import os
import threading
import uuid

import pytest

from card_service.broker_ipc import BrokerIpcError, TaskBrokerChannel
from workers.acg.broker_client import WorkerBrokerClient, WorkerBrokerError


def test_channel_is_loopback_task_scoped_and_exposes_no_generic_operation() -> None:
    with TaskBrokerChannel(task_id="task-1", handler=lambda operation, payload: {"operation": operation, **payload}) as channel:
        descriptor = channel.descriptor()
        assert descriptor["host"] == "127.0.0.1"
        assert descriptor["transport"] == "authenticated_loopback_json"
        assert "http" not in json.dumps(descriptor["allowedOperations"]).lower()
        assert "shell" not in json.dumps(descriptor["allowedOperations"]).lower()
        assert "provider-secret-canary" not in json.dumps(descriptor)
        client = WorkerBrokerClient(descriptor)
        assert client.request("model.openai_chat", {"value": 1}) == {
            "operation": "model.openai_chat",
            "value": 1,
        }


def test_wrong_channel_proof_cannot_read_response() -> None:
    with TaskBrokerChannel(task_id="task-1", handler=lambda *_: {"ok": True}) as channel:
        descriptor = channel.descriptor()
        descriptor["channelProof"] = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
        client = WorkerBrokerClient(descriptor)
        with pytest.raises(WorkerBrokerError, match="authentication"):
            client.request("model.openai_chat", {})


def test_cross_task_binding_and_unlisted_operation_fail_closed() -> None:
    with TaskBrokerChannel(task_id="task-1", handler=lambda *_: {"ok": True}) as channel:
        descriptor = channel.descriptor()
        crossed = {**descriptor, "taskId": "task-2"}
        with pytest.raises(WorkerBrokerError, match="binding mismatch"):
            WorkerBrokerClient(crossed).request("model.openai_chat", {})
        client = WorkerBrokerClient(descriptor)
        with pytest.raises(WorkerBrokerError, match="not allowed"):
            client.request("http.request", {"url": "https://example.invalid"})


def test_same_request_id_is_replayed_from_cache_without_duplicate_side_effect() -> None:
    calls: list[int] = []

    def handler(_: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append(1)
        return payload

    with TaskBrokerChannel(task_id="task-1", handler=handler) as channel:
        client = WorkerBrokerClient(channel.descriptor())
        request_id = str(uuid.uuid4())
        assert client.request("model.openai_chat", {"value": 1}, request_id=request_id) == {"value": 1}
        assert client.request("model.openai_chat", {"value": 1}, request_id=request_id) == {"value": 1}
        with pytest.raises(WorkerBrokerError, match="IPC_REPLAY_CONFLICT"):
            client.request("model.openai_chat", {"value": 2}, request_id=request_id)
    assert calls == [1]


def test_handler_failure_is_structured_and_authenticated() -> None:
    def blocked(_: str, __: dict[str, object]) -> object:
        raise BrokerIpcError("BUDGET_EXCEEDED", "budget is exhausted")

    with TaskBrokerChannel(task_id="task-1", handler=blocked) as channel:
        with pytest.raises(WorkerBrokerError, match="BUDGET_EXCEEDED"):
            WorkerBrokerClient(channel.descriptor()).request("tts.synthesize", {})


def test_request_and_response_size_limits_are_enforced() -> None:
    with TaskBrokerChannel(task_id="task-1", handler=lambda *_: {"data": "x" * 10_000}, max_message_bytes=2_048) as channel:
        client = WorkerBrokerClient(channel.descriptor())
        with pytest.raises(WorkerBrokerError, match="request exceeded"):
            client.request("model.openai_chat", {"data": "x" * 10_000})
        with pytest.raises(WorkerBrokerError, match="ended early"):
            client.request("model.openai_chat", {})


def test_concurrent_distinct_requests_are_each_processed_once() -> None:
    lock = threading.Lock()
    observed: list[int] = []

    def handler(_: str, payload: dict[str, object]) -> dict[str, object]:
        with lock:
            observed.append(int(payload["index"]))
        return payload

    with TaskBrokerChannel(task_id="task-1", handler=handler) as channel:
        client = WorkerBrokerClient(channel.descriptor())
        results: list[object] = []
        threads = [threading.Thread(target=lambda index=index: results.append(client.request("model.openai_chat", {"index": index}))) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert sorted(observed) == list(range(12))
    assert sorted(int(result["index"]) for result in results) == list(range(12))


def test_descriptor_cannot_expand_the_clients_compiled_operation_allowlist() -> None:
    with TaskBrokerChannel(task_id="task-1", handler=lambda *_: {"ok": True}) as channel:
        descriptor = channel.descriptor()
        descriptor["allowedOperations"] = [*descriptor["allowedOperations"], "http.request"]
        with pytest.raises(WorkerBrokerError, match="unknown operations"):
            WorkerBrokerClient(descriptor)


def test_request_cache_has_a_hard_limit_but_still_allows_exact_replay() -> None:
    with TaskBrokerChannel(task_id="task-1", handler=lambda _operation, payload: payload, max_requests=2) as channel:
        client = WorkerBrokerClient(channel.descriptor())
        request_ids = [str(uuid.uuid4()) for _ in range(3)]
        assert client.request("model.openai_chat", {"value": 1}, request_id=request_ids[0]) == {"value": 1}
        assert client.request("model.openai_chat", {"value": 2}, request_id=request_ids[1]) == {"value": 2}
        assert client.request("model.openai_chat", {"value": 1}, request_id=request_ids[0]) == {"value": 1}
        with pytest.raises(WorkerBrokerError, match="IPC_REQUEST_LIMIT"):
            client.request("model.openai_chat", {"value": 3}, request_id=request_ids[2])


def test_unknown_handler_failure_and_invalid_result_are_structured() -> None:
    def crash(_operation: str, _payload: dict[str, object]) -> object:
        raise RuntimeError("must-not-leak")

    with TaskBrokerChannel(task_id="task-1", handler=crash) as channel:
        with pytest.raises(WorkerBrokerError, match="BROKER_HANDLER_FAILED") as failure:
            WorkerBrokerClient(channel.descriptor()).request("model.openai_chat", {})
        assert "must-not-leak" not in str(failure.value)

    with TaskBrokerChannel(task_id="task-2", handler=lambda *_: {"bad": object()}) as channel:
        with pytest.raises(WorkerBrokerError, match="IPC_RESULT_INVALID"):
            WorkerBrokerClient(channel.descriptor()).request("model.openai_chat", {})
