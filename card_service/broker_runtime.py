from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .broker import BrokerBudget, BrokerCall, BrokerError, ModelTtsBroker, canonical_digest
from .broker_ipc import BrokerIpcError
from .credentials import CredentialStoreError
from .provider_egress import ProviderEgress, ProviderEgressError, ProviderProfile, ProviderTransport


WORK_UNIT_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
INTENT_REF_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


@dataclass(frozen=True)
class AuthorizedProviderCall:
    profile: ProviderProfile
    credential_revision: int
    reserved_cost_minor_units: int | None
    transport: ProviderTransport | None = None

    def __post_init__(self) -> None:
        revision = int(self.credential_revision)
        if revision < 0:
            raise BrokerError("CREDENTIAL_BINDING_INVALID", "Credential revision is invalid")
        if self.profile.provider == "hermes":
            if revision != 0:
                raise BrokerError("CREDENTIAL_BINDING_INVALID", "Hermes uses credential revision zero")
        elif revision <= 0:
            raise BrokerError("CREDENTIAL_BINDING_INVALID", "Remote provider credential revision is required")
        if self.reserved_cost_minor_units is not None and int(self.reserved_cost_minor_units) < 0:
            raise BrokerError("INVALID_USAGE", "Reserved provider cost is invalid")


@dataclass(frozen=True)
class TaskBrokerAuthorization:
    operation_intent_ref: str
    budget: BrokerBudget
    operations: Mapping[str, AuthorizedProviderCall]

    def __post_init__(self) -> None:
        if not INTENT_REF_PATTERN.fullmatch(self.operation_intent_ref):
            raise BrokerError("OPERATION_INTENT_INVALID", "Operation intent reference is invalid")
        if not self.operations:
            raise BrokerError("BROKER_OPERATION_BLOCKED", "Task broker authorization has no operations")
        operations = dict(self.operations)
        for operation, binding in operations.items():
            expected_capability = "tts" if operation == "tts.synthesize" else "model"
            if operation not in {
                "model.openai_chat",
                "model.anthropic_messages",
                "model.gemini_content",
                "tts.synthesize",
            }:
                raise BrokerError("BROKER_OPERATION_BLOCKED", "Task broker operation is invalid")
            if binding.profile.capability != expected_capability:
                raise BrokerError("BROKER_OPERATION_BLOCKED", "Task broker profile capability mismatch")
        object.__setattr__(self, "operations", MappingProxyType(operations))


def _idempotency_key(task_id: str, work_unit_id: str, operation: str) -> str:
    value = f"study.broker-call.v1\x00{task_id}\x00{work_unit_id}\x00{operation}".encode("utf-8")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def make_task_broker_handler(
    *,
    task_id: str,
    authorization: TaskBrokerAuthorization,
    broker: ModelTtsBroker,
) -> Callable[[str, dict[str, Any]], Any]:
    if not task_id:
        raise BrokerError("TASK_BINDING_INVALID", "Task broker task binding is invalid")
    egress = {
        operation: ProviderEgress(binding.profile, transport=binding.transport)
        for operation, binding in authorization.operations.items()
    }

    def handle(operation: str, payload: dict[str, Any]) -> Any:
        try:
            binding = authorization.operations.get(operation)
            if binding is None:
                raise BrokerError("BROKER_OPERATION_BLOCKED", "Broker operation is not authorized for this task")
            if set(payload) != {"workUnitId", "request"}:
                raise BrokerError("BROKER_PAYLOAD_INVALID", "Broker payload shape is invalid")
            work_unit_id = str(payload.get("workUnitId") or "")
            request = payload.get("request")
            if not WORK_UNIT_PATTERN.fullmatch(work_unit_id) or not isinstance(request, dict):
                raise BrokerError("BROKER_PAYLOAD_INVALID", "Broker work unit or request is invalid")
            request_digest = canonical_digest(request)
            request_bytes = len(
                json.dumps(
                    request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            call = BrokerCall(
                task_id=task_id,
                work_unit_id=work_unit_id,
                capability=binding.profile.capability,
                profile_ref=binding.profile.profile_ref,
                credential_revision=int(binding.credential_revision),
                operation_intent_ref=authorization.operation_intent_ref,
                idempotency_key=_idempotency_key(task_id, work_unit_id, operation),
                request_payload_digest=request_digest,
                request_bytes=request_bytes,
                maximum_response_bytes=binding.profile.maximum_response_bytes,
                reserved_cost_minor_units=binding.reserved_cost_minor_units,
                credential_required=binding.profile.provider != "hermes",
            )
            return broker.execute(
                call=call,
                budget=authorization.budget,
                provider_payload=request,
                sender=lambda body, secret: egress[operation].execute(operation, body, secret),
            )
        except BrokerIpcError:
            raise
        except (BrokerError, ProviderEgressError) as error:
            raise BrokerIpcError(error.code, str(error)) from error
        except CredentialStoreError as error:
            raise BrokerIpcError("CREDENTIAL_UNAVAILABLE", "Provider credential is unavailable") from error

    return handle
