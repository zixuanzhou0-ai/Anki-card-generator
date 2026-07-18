from __future__ import annotations

import json
import multiprocessing
import threading
from pathlib import Path

import pytest

from card_service.broker import BrokerBudget, BrokerCall, BrokerError, BrokerReservationLedger, ModelTtsBroker, canonical_digest
from card_service.credentials import CredentialStore, CredentialStoreError, InMemoryCredentialBackend


def make_credentials(tmp_path: Path) -> tuple[CredentialStore, InMemoryCredentialBackend]:
    backend = InMemoryCredentialBackend()
    return CredentialStore(state_dir=(tmp_path / "credentials").resolve(), backend=backend), backend


def make_call(payload: dict[str, object], **overrides: object) -> BrokerCall:
    values: dict[str, object] = {
        "task_id": "task-1", "work_unit_id": "unit-1", "capability": "model",
        "profile_ref": "model.primary", "credential_revision": 1,
        "operation_intent_ref": "intent-1", "idempotency_key": "idempotency-1",
        "request_payload_digest": canonical_digest(payload),
        "request_bytes": len(json.dumps(payload).encode("utf-8")),
        "maximum_response_bytes": 1_024, "reserved_cost_minor_units": 10,
    }
    values.update(overrides)
    return BrokerCall(**values)  # type: ignore[arg-type]


def make_budget(**overrides: object) -> BrokerBudget:
    values: dict[str, object] = {
        "max_remote_calls": 2, "max_request_bytes": 10_000,
        "max_response_bytes": 10_000, "max_cost_minor_units": 100,
    }
    values.update(overrides)
    return BrokerBudget(**values)  # type: ignore[arg-type]


def _reserve_from_process(ledger_path: str, task_id: str, start, results) -> None:
    ledger = BrokerReservationLedger(Path(ledger_path))
    start.wait(10)
    try:
        ledger.reserve(
            make_call(
                {"messages": [task_id]},
                task_id=task_id,
                work_unit_id=f"unit-{task_id}",
                idempotency_key=f"idempotency-{task_id}",
            ),
            make_budget(max_remote_calls=1),
        )
    except BrokerError as error:
        results.put(error.code)
    else:
        results.put("reserved")


def test_credential_revision_is_monotonic_for_add_replace_delete_and_rollback(tmp_path: Path) -> None:
    store, backend = make_credentials(tmp_path)
    assert store.metadata("model.primary")["credentialRevision"] == 0
    revisions = [
        store.set_secret("model.primary", "first")["credentialRevision"],
        store.set_secret("model.primary", "second")["credentialRevision"],
        store.delete_secret("model.primary")["credentialRevision"],
        store.set_secret("model.primary", "first")["credentialRevision"],
    ]
    assert revisions == [1, 2, 3, 4]
    assert backend.read("CodexStudy/model.primary") == "first"
    assert store.resolve_secret("model.primary", expected_revision=4) == "first"
    with pytest.raises(CredentialStoreError, match="stale"):
        store.resolve_secret("model.primary", expected_revision=1)


def test_credential_metadata_never_contains_secret_material(tmp_path: Path) -> None:
    store, _ = make_credentials(tmp_path)
    store.set_secret("tts.primary", "credential-canary-value")
    metadata = "".join(path.read_text(encoding="utf-8") for path in store.root.glob("*.json"))
    assert "credential-canary-value" not in metadata
    assert "CredentialBlob" not in metadata


def test_concurrent_credential_updates_receive_unique_revisions(tmp_path: Path) -> None:
    store, _ = make_credentials(tmp_path)
    revisions: list[int] = []

    def update(index: int) -> None:
        result = store.set_secret("model.concurrent", f"value-{index}")
        revisions.append(int(result["credentialRevision"]))

    threads = [threading.Thread(target=update, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(revisions) == list(range(1, 9))


def test_pending_credential_revision_is_reconciled_without_reuse(tmp_path: Path) -> None:
    store, backend = make_credentials(tmp_path)
    store.set_secret("model.primary", "first")
    path = next(store.root.glob("*.json"))
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata.update(state="pending", credentialRevision=2)
    from card_service.storage import AtomicJsonStore

    AtomicJsonStore._write_atomic(path, metadata)
    backend.write("CodexStudy/model.primary", "second")
    recovered = CredentialStore(state_dir=store.root, backend=backend)
    assert recovered.metadata("model.primary")["credentialRevision"] == 2
    assert recovered.set_secret("model.primary", "third")["credentialRevision"] == 3


def test_reserve_is_idempotent_but_rejects_key_reuse_for_another_payload(tmp_path: Path) -> None:
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    payload = {"messages": ["hello"]}
    first = ledger.reserve(make_call(payload), make_budget())
    repeated = ledger.reserve(make_call(payload), make_budget())
    assert repeated["reservationId"] == first["reservationId"]
    with pytest.raises(BrokerError) as conflict:
        ledger.reserve(make_call({"messages": ["different"]}), make_budget())
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    assert len(ledger.list_records()) == 1
    with pytest.raises(BrokerError) as crossed:
        ledger.reserve(make_call(payload, task_id="another-task"), make_budget())
    assert crossed.value.code == "IDEMPOTENCY_SCOPE_CONFLICT"


@pytest.mark.parametrize(
    ("call_overrides", "budget_overrides", "expected_code"),
    [
        ({}, {"max_remote_calls": 0}, "CALL_BUDGET_EXCEEDED"),
        ({"request_bytes": 101}, {"max_request_bytes": 100}, "REQUEST_BUDGET_EXCEEDED"),
        ({"maximum_response_bytes": 101}, {"max_response_bytes": 100}, "RESPONSE_BUDGET_EXCEEDED"),
        ({"reserved_cost_minor_units": 101}, {"max_cost_minor_units": 100}, "COST_BUDGET_EXCEEDED"),
        ({"reserved_cost_minor_units": None}, {"max_cost_minor_units": 100}, "UNKNOWN_COST_BLOCKED"),
    ],
)
def test_limits_fail_before_send(tmp_path: Path, call_overrides: dict[str, object], budget_overrides: dict[str, object], expected_code: str) -> None:
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    with pytest.raises(BrokerError) as caught:
        ledger.reserve(make_call({"messages": ["hello"]}, **call_overrides), make_budget(**budget_overrides))
    assert caught.value.code == expected_code
    assert ledger.list_records() == []


def test_budget_is_cumulative_across_tasks_bound_to_the_same_operation_intent(tmp_path: Path) -> None:
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    budget = make_budget(max_remote_calls=1)
    first = make_call({"messages": ["first"]})
    ledger.reserve(first, budget)

    with pytest.raises(BrokerError) as exceeded:
        ledger.reserve(
            make_call(
                {"messages": ["second"]},
                task_id="task-2",
                work_unit_id="unit-2",
                idempotency_key="idempotency-2",
            ),
            budget,
        )
    assert exceeded.value.code == "CALL_BUDGET_EXCEEDED"

    independent = ledger.reserve(
        make_call(
            {"messages": ["independent"]},
            task_id="task-3",
            work_unit_id="unit-3",
            operation_intent_ref="intent-2",
            idempotency_key="idempotency-3",
        ),
        budget,
    )
    assert independent["operationIntentRef"] == "intent-2"


def test_interprocess_ledger_lock_allows_only_one_budget_winner(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    ledger_path = str((tmp_path / "ledger.json").resolve())
    processes = [
        context.Process(target=_reserve_from_process, args=(ledger_path, f"task-{index}", start, results))
        for index in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    outcomes = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    assert sorted(outcomes) == ["CALL_BUDGET_EXCEEDED", "reserved"]
    assert len(BrokerReservationLedger(Path(ledger_path)).list_records()) == 1


def test_revocation_blocks_new_reservations(tmp_path: Path) -> None:
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    ledger.revoke_profile("model.primary")
    with pytest.raises(BrokerError) as caught:
        ledger.reserve(make_call({"messages": ["hello"]}), make_budget())
    assert caught.value.code == "PROFILE_REVOKED"


def test_revocation_between_reserve_and_send_is_rechecked(tmp_path: Path) -> None:
    store, _ = make_credentials(tmp_path)
    metadata = store.set_secret("model.primary", "provider-secret")
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    payload = {"messages": ["hello"]}
    bound_call = make_call(payload, credential_revision=metadata["credentialRevision"])
    ledger.reserve(bound_call, make_budget())
    ledger.revoke_profile("model.primary")
    broker = ModelTtsBroker(credential_store=store, ledger=ledger)
    with pytest.raises(BrokerError) as caught:
        broker.execute(call=bound_call, budget=make_budget(), provider_payload=payload, sender=lambda *_: ({}, 0, 0))
    assert caught.value.code == "PROFILE_REVOKED"
    assert ledger.list_records()[0]["state"] == "released_before_send"


def test_stale_credential_releases_reservation_before_send(tmp_path: Path) -> None:
    store, _ = make_credentials(tmp_path)
    store.set_secret("model.primary", "first")
    store.set_secret("model.primary", "second")
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    broker = ModelTtsBroker(credential_store=store, ledger=ledger)
    payload = {"messages": ["hello"]}
    with pytest.raises(CredentialStoreError, match="stale"):
        broker.execute(call=make_call(payload, credential_revision=1), budget=make_budget(), provider_payload=payload, sender=lambda *_: ({}, 0, 0))
    assert ledger.list_records()[0]["state"] == "released_before_send"


def test_execute_resolves_secret_only_inside_broker_and_settles(tmp_path: Path) -> None:
    store, _ = make_credentials(tmp_path)
    metadata = store.set_secret("model.primary", "provider-secret-canary")
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    broker = ModelTtsBroker(credential_store=store, ledger=ledger)
    payload = {"messages": [{"role": "user", "content": "hello"}]}
    observed: list[tuple[dict[str, object], str]] = []

    def sender(body: dict[str, object], secret: str) -> tuple[object, int, int | None]:
        observed.append((body, secret))
        return {"text": "ok", "authorization": "remove-me"}, 20, 7

    result = broker.execute(
        call=make_call(payload, credential_revision=metadata["credentialRevision"]),
        budget=make_budget(), provider_payload=payload, sender=sender,
    )
    assert observed == [(payload, "provider-secret-canary")]
    assert result == {"text": "ok", "authorization": ""}
    assert ledger.list_records()[0]["state"] == "settled"
    assert "provider-secret-canary" not in (tmp_path / "ledger.json").read_text(encoding="utf-8")


def test_crash_after_send_is_possible_incurred_and_never_auto_replayed(tmp_path: Path) -> None:
    store, _ = make_credentials(tmp_path)
    metadata = store.set_secret("model.primary", "provider-secret")
    ledger_path = (tmp_path / "ledger.json").resolve()
    broker = ModelTtsBroker(credential_store=store, ledger=BrokerReservationLedger(ledger_path))
    payload = {"messages": ["hello"]}

    def crashes(_: dict[str, object], __: str) -> tuple[object, int, int | None]:
        raise RuntimeError("connection ended after send")

    bound_call = make_call(payload, credential_revision=metadata["credentialRevision"])
    with pytest.raises(RuntimeError):
        broker.execute(call=bound_call, budget=make_budget(), provider_payload=payload, sender=crashes)
    assert broker.ledger.list_records()[0]["state"] == "possible_incurred"
    recovered_ledger = BrokerReservationLedger(ledger_path)
    assert recovered_ledger.list_records()[0]["state"] == "possible_incurred"
    recovered_broker = ModelTtsBroker(credential_store=store, ledger=recovered_ledger)
    with pytest.raises(BrokerError) as retry:
        recovered_broker.execute(call=bound_call, budget=make_budget(), provider_payload=payload, sender=crashes)
    assert retry.value.code == "RETRY_REQUIRES_RECONCILIATION"


def test_concurrent_same_call_is_sent_at_most_once(tmp_path: Path) -> None:
    store, _ = make_credentials(tmp_path)
    metadata = store.set_secret("model.primary", "provider-secret")
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    broker = ModelTtsBroker(credential_store=store, ledger=ledger)
    payload = {"messages": ["hello"]}
    bound_call = make_call(payload, credential_revision=metadata["credentialRevision"])
    sends: list[int] = []
    errors: list[str] = []

    def sender(*_: object) -> tuple[object, int, int | None]:
        sends.append(1)
        return {"ok": True}, 10, 1

    def execute() -> None:
        try:
            broker.execute(call=bound_call, budget=make_budget(), provider_payload=payload, sender=sender)
        except BrokerError as error:
            errors.append(error.code)

    threads = [threading.Thread(target=execute) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(sends) == 1
    assert errors == ["INVALID_RESERVATION_STATE"]


def test_second_ledger_does_not_recover_a_live_process_reservation(tmp_path: Path) -> None:
    path = (tmp_path / "ledger.json").resolve()
    BrokerReservationLedger(path).reserve(make_call({"messages": ["hello"]}), make_budget())
    recovered = BrokerReservationLedger(path)
    assert recovered.list_records()[0]["state"] == "reserved"


def test_reserved_dead_process_releases_without_counting_as_sent(tmp_path: Path) -> None:
    path = (tmp_path / "ledger.json").resolve()
    BrokerReservationLedger(path).reserve(make_call({"messages": ["hello"]}), make_budget())
    state = json.loads(path.read_text(encoding="utf-8"))
    state["reservations"][0]["ownerProcessToken"] = "99999999:unknown"
    from card_service.storage import AtomicJsonStore

    AtomicJsonStore._write_atomic(path, state)
    recovered = BrokerReservationLedger(path)
    assert recovered.list_records()[0]["state"] == "released_before_send"


def test_provider_usage_over_reservation_is_recorded_fail_closed(tmp_path: Path) -> None:
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    record = ledger.reserve(make_call({"messages": ["hello"]}, maximum_response_bytes=10), make_budget())
    ledger.mark_sent(record["reservationId"])
    with pytest.raises(BrokerError) as caught:
        ledger.settle(record["reservationId"], actual_response_bytes=11, actual_cost_minor_units=5)
    assert caught.value.code == "PROVIDER_USAGE_EXCEEDED_RESERVATION"
    assert ledger.list_records()[0]["state"] == "possible_incurred"


def test_negative_provider_usage_is_invalid_and_preserved_as_possible_cost(tmp_path: Path) -> None:
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    record = ledger.reserve(make_call({"messages": ["hello"]}), make_budget())
    ledger.mark_sent(record["reservationId"])
    with pytest.raises(BrokerError) as caught:
        ledger.settle(record["reservationId"], actual_response_bytes=-1, actual_cost_minor_units=1)
    assert caught.value.code == "INVALID_PROVIDER_USAGE"
    assert ledger.list_records()[0]["state"] == "possible_incurred"


def test_unknown_actual_cost_is_settled_at_the_reserved_maximum(tmp_path: Path) -> None:
    ledger = BrokerReservationLedger((tmp_path / "ledger.json").resolve())
    record = ledger.reserve(make_call({"messages": ["hello"]}, reserved_cost_minor_units=17), make_budget())
    ledger.mark_sent(record["reservationId"])
    settled = ledger.settle(record["reservationId"], actual_response_bytes=12, actual_cost_minor_units=None)
    assert settled["state"] == "settled"
    assert settled["actualCostMinorUnits"] == 17
    assert settled["actualCostWasEstimated"] is True
