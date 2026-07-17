from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from workers.acg.secret_scrub import scrub_runtime_secrets

from .credentials import CredentialStore
from .storage import AtomicJsonStore


class BrokerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BrokerBudget:
    max_remote_calls: int
    max_request_bytes: int
    max_response_bytes: int
    max_cost_minor_units: int | None

    def __post_init__(self) -> None:
        if min(
            int(self.max_remote_calls),
            int(self.max_request_bytes),
            int(self.max_response_bytes),
        ) < 0:
            raise BrokerError("INVALID_BUDGET", "Broker budget values must not be negative")
        if self.max_cost_minor_units is not None and int(self.max_cost_minor_units) < 0:
            raise BrokerError("INVALID_BUDGET", "Broker cost budget must not be negative")


@dataclass(frozen=True)
class BrokerCall:
    task_id: str
    work_unit_id: str
    capability: str
    profile_ref: str
    credential_revision: int
    operation_intent_ref: str
    idempotency_key: str
    request_payload_digest: str
    request_bytes: int
    maximum_response_bytes: int
    reserved_cost_minor_units: int | None
    credential_required: bool = True


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class BrokerReservationLedger:
    ACTIVE_COST_STATES = frozenset({"reserved", "sent", "settled", "possible_incurred"})

    def __init__(self, state_path: str | Path) -> None:
        candidate = Path(state_path).expanduser()
        if not candidate.is_absolute():
            raise BrokerError("INVALID_LEDGER_PATH", "Broker ledger path must be absolute")
        self.path = candidate.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._recover_crash_states()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"schemaVersion": 1, "reservations": [], "revokedProfiles": []}
        with self.path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict) or not isinstance(value.get("reservations"), list):
            raise BrokerError("LEDGER_CORRUPT", "Broker ledger is invalid")
        return value

    def _save(self, value: dict[str, Any]) -> None:
        AtomicJsonStore._write_atomic(self.path, value)

    def _recover_crash_states(self) -> None:
        with self._lock:
            value = self._load()
            changed = False
            now = int(time.time() * 1000)
            for record in value["reservations"]:
                if record.get("state") == "sent":
                    record.update(state="possible_incurred", updatedAt=now)
                    changed = True
                elif record.get("state") == "reserved":
                    record.update(state="released_before_send", updatedAt=now)
                    changed = True
            if changed:
                self._save(value)

    def revoke_profile(self, profile_ref: str) -> None:
        with self._lock:
            value = self._load()
            revoked = set(str(item) for item in value.get("revokedProfiles") or [])
            revoked.add(profile_ref)
            value["revokedProfiles"] = sorted(revoked)
            self._save(value)

    def reserve(self, call: BrokerCall, budget: BrokerBudget) -> dict[str, Any]:
        if call.capability not in {"model", "tts", "source"}:
            raise BrokerError("INVALID_CAPABILITY", "Broker capability must be model, tts, or source")
        if min(call.request_bytes, call.maximum_response_bytes) < 0:
            raise BrokerError("INVALID_USAGE", "Broker byte reservations must be non-negative")
        with self._lock:
            value = self._load()
            profile_revoked = call.profile_ref in set(value.get("revokedProfiles") or [])
            existing = next((record for record in value["reservations"] if record.get("idempotencyKey") == call.idempotency_key), None)
            if existing is not None:
                if existing.get("requestPayloadDigest") != call.request_payload_digest:
                    raise BrokerError("IDEMPOTENCY_CONFLICT", "Broker idempotency key was reused with another payload")
                expected_scope = {
                    "taskId": call.task_id, "workUnitId": call.work_unit_id,
                    "capability": call.capability, "profileRef": call.profile_ref,
                    "credentialRevision": call.credential_revision,
                    "operationIntentRef": call.operation_intent_ref,
                    "credentialRequired": call.credential_required,
                }
                if any(existing.get(key) != expected for key, expected in expected_scope.items()):
                    raise BrokerError("IDEMPOTENCY_SCOPE_CONFLICT", "Broker idempotency key crossed its task scope")
                if profile_revoked:
                    if existing.get("state") == "reserved":
                        existing.update(state="released_before_send", updatedAt=int(time.time() * 1000))
                        self._save(value)
                    raise BrokerError("PROFILE_REVOKED", "Broker profile is revoked")
                return dict(existing)
            if profile_revoked:
                raise BrokerError("PROFILE_REVOKED", "Broker profile is revoked")
            active = [record for record in value["reservations"] if record.get("taskId") == call.task_id and record.get("state") in self.ACTIVE_COST_STATES]
            if len(active) + 1 > budget.max_remote_calls:
                raise BrokerError("CALL_BUDGET_EXCEEDED", "Broker remote call budget exceeded")
            if sum(int(record.get("requestBytes") or 0) for record in active) + call.request_bytes > budget.max_request_bytes:
                raise BrokerError("REQUEST_BUDGET_EXCEEDED", "Broker request byte budget exceeded")
            if sum(int(record.get("maximumResponseBytes") or 0) for record in active) + call.maximum_response_bytes > budget.max_response_bytes:
                raise BrokerError("RESPONSE_BUDGET_EXCEEDED", "Broker response byte budget exceeded")
            if budget.max_cost_minor_units is not None:
                if call.reserved_cost_minor_units is None:
                    raise BrokerError("UNKNOWN_COST_BLOCKED", "Broker cannot reserve an unknown cost")
                cost = sum(int(record.get("reservedCostMinorUnits") or 0) for record in active)
                if cost + call.reserved_cost_minor_units > budget.max_cost_minor_units:
                    raise BrokerError("COST_BUDGET_EXCEEDED", "Broker cost budget exceeded")
            now = int(time.time() * 1000)
            record = {
                "schemaVersion": 1,
                "reservationId": str(uuid.uuid4()),
                "taskId": call.task_id,
                "workUnitId": call.work_unit_id,
                "capability": call.capability,
                "profileRef": call.profile_ref,
                "credentialRevision": call.credential_revision,
                "operationIntentRef": call.operation_intent_ref,
                "idempotencyKey": call.idempotency_key,
                "requestPayloadDigest": call.request_payload_digest,
                "requestBytes": call.request_bytes,
                "maximumResponseBytes": call.maximum_response_bytes,
                "reservedCostMinorUnits": call.reserved_cost_minor_units,
                "credentialRequired": call.credential_required,
                "state": "reserved",
                "createdAt": now,
                "updatedAt": now,
            }
            value["reservations"].append(record)
            self._save(value)
            return dict(record)

    def transition(self, reservation_id: str, expected: set[str], state: str, **usage: Any) -> dict[str, Any]:
        with self._lock:
            value = self._load()
            record = next((item for item in value["reservations"] if item.get("reservationId") == reservation_id), None)
            if record is None:
                raise BrokerError("RESERVATION_NOT_FOUND", "Broker reservation does not exist")
            if record.get("state") not in expected:
                raise BrokerError("INVALID_RESERVATION_STATE", "Broker reservation transition is not allowed")
            record.update(state=state, updatedAt=int(time.time() * 1000), **usage)
            self._save(value)
            return dict(record)

    def mark_sent(self, reservation_id: str) -> dict[str, Any]:
        with self._lock:
            value = self._load()
            record = next((item for item in value["reservations"] if item.get("reservationId") == reservation_id), None)
            if record is None or record.get("state") != "reserved":
                raise BrokerError("INVALID_RESERVATION_STATE", "Only a reserved broker call can be sent")
            if record.get("profileRef") in set(value.get("revokedProfiles") or []):
                raise BrokerError("PROFILE_REVOKED", "Broker profile was revoked before send")
            record.update(state="sent", updatedAt=int(time.time() * 1000))
            self._save(value)
            return dict(record)

    def release_before_send(self, reservation_id: str) -> dict[str, Any]:
        return self.transition(reservation_id, {"reserved"}, "released_before_send")

    def settle(self, reservation_id: str, *, actual_response_bytes: int, actual_cost_minor_units: int | None) -> dict[str, Any]:
        with self._lock:
            value = self._load()
            record = next((item for item in value["reservations"] if item.get("reservationId") == reservation_id), None)
            if record is None or record.get("state") != "sent":
                raise BrokerError("INVALID_RESERVATION_STATE", "Only a sent reservation can settle")
            reserved_cost = record.get("reservedCostMinorUnits")
            settled_cost = reserved_cost if actual_cost_minor_units is None else actual_cost_minor_units
            invalid = actual_response_bytes < 0 or (settled_cost is not None and int(settled_cost) < 0)
            over = invalid or actual_response_bytes > int(record.get("maximumResponseBytes") or 0)
            over = over or (reserved_cost is not None and settled_cost is not None and int(settled_cost) > int(reserved_cost))
            record.update(
                state="possible_incurred" if over else "settled",
                actualResponseBytes=max(0, int(actual_response_bytes)),
                actualCostMinorUnits=settled_cost,
                actualCostWasEstimated=actual_cost_minor_units is None and reserved_cost is not None,
                updatedAt=int(time.time() * 1000),
            )
            self._save(value)
            if invalid:
                raise BrokerError("INVALID_PROVIDER_USAGE", "Provider returned invalid usage")
            if over:
                raise BrokerError("PROVIDER_USAGE_EXCEEDED_RESERVATION", "Provider usage exceeded the reservation")
            return dict(record)

    def list_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(record) for record in self._load()["reservations"]]


class ModelTtsBroker:
    def __init__(self, *, credential_store: CredentialStore, ledger: BrokerReservationLedger) -> None:
        self.credential_store = credential_store
        self.ledger = ledger
        self._send_lock = threading.RLock()

    def execute(
        self,
        *,
        call: BrokerCall,
        budget: BrokerBudget,
        provider_payload: dict[str, Any],
        sender: Callable[[dict[str, Any], str], tuple[Any, int, int | None]],
    ) -> Any:
        if canonical_digest(provider_payload) != call.request_payload_digest:
            raise BrokerError("PAYLOAD_DIGEST_MISMATCH", "Provider payload does not match the broker call")
        reservation = self.ledger.reserve(call, budget)
        if reservation["state"] == "settled":
            raise BrokerError("ALREADY_SETTLED", "Broker call is already settled")
        if reservation["state"] != "reserved":
            raise BrokerError("RETRY_REQUIRES_RECONCILIATION", "Broker call cannot be replayed automatically")
        with self._send_lock:
            secret = ""
            try:
                if call.credential_required:
                    secret = self.credential_store.resolve_secret(
                        call.profile_ref,
                        expected_revision=call.credential_revision,
                    )
                elif call.credential_revision != 0:
                    raise BrokerError(
                        "CREDENTIAL_BINDING_INVALID",
                        "Credential-free broker calls must use revision zero",
                    )
                sent = self.ledger.mark_sent(reservation["reservationId"])
                result, response_bytes, actual_cost = sender(provider_payload, secret)
            except Exception:
                current = next(record for record in self.ledger.list_records() if record["reservationId"] == reservation["reservationId"])
                if current["state"] == "reserved":
                    self.ledger.release_before_send(reservation["reservationId"])
                elif current["state"] == "sent":
                    self.ledger.transition(reservation["reservationId"], {"sent"}, "possible_incurred")
                raise
            finally:
                secret = ""
            self.ledger.settle(sent["reservationId"], actual_response_bytes=response_bytes, actual_cost_minor_units=actual_cost)
            return scrub_runtime_secrets(result)
