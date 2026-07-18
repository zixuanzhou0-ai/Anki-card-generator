from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from card_service.artifact_registry import (
    ArtifactAudienceBinding,
    canonical_json_bytes,
)
from card_service.authorization_ledger import (
    AuthorizationLedger,
    AuthorizationLedgerError,
)
from card_service.task_manifests import build_authorization_binding


KEY = bytes(range(32))
OWNER = hashlib.sha256(b"owner").hexdigest()
DIGESTS = [hashlib.sha256(f"digest-{index}".encode()).hexdigest() for index in range(16)]


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 18, 4, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **changes: int) -> None:
        self.value += timedelta(**changes)


def audience(**changes: str) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


def ledger(
    tmp_path: Path,
    clock: Clock,
    *,
    key: bytes = KEY,
    service_instance_id: str = "service-1",
    verify_gestures: bool = True,
) -> AuthorizationLedger:
    return AuthorizationLedger(
        tmp_path / "authorization",
        authentication_key=key,
        service_instance_id=service_instance_id,
        clock=clock,
        gesture_attestation_verifier=(
            (lambda _gesture, _audience, _target, _action: True)
            if verify_gestures
            else None
        ),
    )


def binding(
    *,
    capability: str = "model",
    profile_ref: str = "profile-model",
    configuration_fingerprint: str = DIGESTS[0],
    credential_revision: int = 1,
    egress_manifest_digest: str = DIGESTS[1],
) -> dict:
    return {
        "capability": capability,
        "profileRef": profile_ref,
        "configurationFingerprint": configuration_fingerprint,
        "credentialRevision": credential_revision,
        "egressManifestDigest": egress_manifest_digest,
    }


def disclosure(service_bindings: list[dict]) -> dict:
    entries = []
    for index, service_binding in enumerate(service_bindings):
        entries.append(
            {
                "disclosureEntryId": f"disclosure-{index}",
                "target": {
                    "capability": service_binding["capability"],
                    "profileRef": service_binding["profileRef"],
                    "providerOriginDigest": DIGESTS[2 + index],
                    "modelOrVoiceRef": f"model-or-voice-{index}",
                },
                "dataCategory": (
                    "tts_text"
                    if service_binding["capability"] == "tts"
                    else "source_excerpt"
                ),
                "sourceSlices": [
                    {
                        "sourceArtifactDigest": DIGESTS[6],
                        "sourceRevisionDigest": DIGESTS[7],
                        "locatorSetDigest": DIGESTS[8],
                        "maxBytes": 1_000,
                    }
                ],
                "maxRequestBytes": 2_000,
                "maxInputTokens": 500,
                "maxOutputTokens": 500,
                "maxTtsCharacters": 1_000,
                "maxTtsAudioSeconds": 120,
            }
        )
    return {
        "schema": "study.disclosure.manifest",
        "schemaVersion": 1,
        "entries": entries,
        "globalCaps": {
            "maxTotalRequestBytes": 10_000,
            "maxInputTokens": 2_000,
            "maxOutputTokens": 2_000,
            "maxTtsCharacters": 5_000,
            "maxTtsAudioSeconds": 600,
        },
    }


def budget(*, max_remote_calls: int = 3) -> dict:
    return {
        "priceKnown": True,
        "currency": "USD",
        "maxMinorUnits": 250,
        "pricingSnapshotRef": "pricing-2026-07-18",
        "pricingSnapshotVersion": "v1",
        "maxRemoteCalls": max_remote_calls,
        "maxCards": 20,
        "maxMediaItems": 40,
    }


def digest(value: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def request(
    clock: Clock,
    service_bindings: list[dict],
    disclosure_manifest: dict,
    cost_budget: dict,
    *,
    expires_in_minutes: int = 60,
) -> dict:
    return {
        "schema": "study.operation.request",
        "schemaVersion": 1,
        "actionId": "generate_cards",
        "subject": {
            "kind": "project_task",
            "projectId": "project-1",
            "projectRevision": 4,
            "learningContractRevision": 2,
            "inputArtifactDigests": [DIGESTS[4]],
            "sourceRevisionDigests": [DIGESTS[5]],
        },
        "serviceBindings": service_bindings,
        "disclosureManifestDigest": digest(disclosure_manifest),
        "costBudgetDigest": digest(cost_budget),
        "batchPolicyDigest": DIGESTS[9],
        "expiresAt": (
            clock.value + timedelta(minutes=expires_in_minutes)
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }


def create_intent(
    store: AuthorizationLedger,
    clock: Clock,
    *,
    bound: ArtifactAudienceBinding | None = None,
    service_bindings: list[dict] | None = None,
    cost_budget: dict | None = None,
    key: str = "intent-create-1",
) -> tuple[dict, list[dict], dict, dict]:
    current_bindings = service_bindings or [binding()]
    current_disclosure = disclosure(current_bindings)
    current_budget = cost_budget or budget()
    operation_request = request(
        clock, current_bindings, current_disclosure, current_budget
    )
    created = store.create_operation_intent(
        audience=bound or audience(),
        idempotency_key=key,
        operation_request_manifest=operation_request,
        disclosure_manifest=current_disclosure,
        cost_budget=current_budget,
    )
    return created, current_bindings, current_disclosure, current_budget


def approve_and_consume(
    store: AuthorizationLedger,
    clock: Clock,
    *,
    max_remote_calls: int = 3,
) -> tuple[dict, dict, list[dict]]:
    created, bindings, _, _ = create_intent(
        store, clock, cost_budget=budget(max_remote_calls=max_remote_calls)
    )
    store.record_operation_decision(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        decision="approved",
        gesture_attestation_digest=DIGESTS[10],
    )
    consumed = store.consume_operation_approval(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        task_id="task-1",
        consumption_id="approval-consumption-1",
        expected_intent_digest=created["intentDigest"],
        expected_operation_request_digest=created[
            "operationRequestManifestDigest"
        ],
        current_service_bindings=bindings,
    )
    return created, consumed, bindings


def test_create_get_and_idempotent_retry(tmp_path: Path) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    first, bindings, manifest, cost = create_intent(store, clock)
    repeated = store.create_operation_intent(
        audience=audience(),
        idempotency_key="intent-create-1",
        operation_request_manifest=request(clock, bindings, manifest, cost),
        disclosure_manifest=manifest,
        cost_budget=cost,
    )
    assert repeated == first
    assert first["state"] == "pending"
    assert store.get_operation_intent(first["operationIntentId"], audience()) == first
    encoded = json.dumps(first)
    assert "userGesture" not in encoded
    assert "authorizationId" not in encoded


def test_create_idempotency_rejects_changed_input(tmp_path: Path) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    create_intent(store, clock)
    with pytest.raises(AuthorizationLedgerError) as captured:
        create_intent(
            store,
            clock,
            cost_budget=budget(max_remote_calls=4),
            key="intent-create-1",
        )
    assert captured.value.code == "AUTHORIZATION_IDEMPOTENCY_CONFLICT"


def test_audience_binds_session_and_service_instance(tmp_path: Path) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    created, _, _, _ = create_intent(store, clock)
    with pytest.raises(AuthorizationLedgerError) as session_error:
        store.get_operation_intent(
            created["operationIntentId"], audience(session_id="session-2")
        )
    assert session_error.value.code == "AUTHORIZATION_AUDIENCE_MISMATCH"
    with pytest.raises(AuthorizationLedgerError) as service_error:
        ledger(
            tmp_path, clock, service_instance_id="service-2"
        ).get_operation_intent(created["operationIntentId"], audience())
    assert service_error.value.code == "AUTHORIZATION_AUDIENCE_MISMATCH"


def test_trusted_decision_is_terminal_and_gesture_bound(tmp_path: Path) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    created, _, _, _ = create_intent(store, clock)
    approved = store.record_operation_decision(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        decision="approved",
        gesture_attestation_digest=DIGESTS[10],
    )
    assert approved["state"] == "approved"
    assert (
        store.record_operation_decision(
            operation_intent_id=created["operationIntentId"],
            audience=audience(),
            decision="approved",
            gesture_attestation_digest=DIGESTS[10],
        )
        == approved
    )
    with pytest.raises(AuthorizationLedgerError) as captured:
        store.record_operation_decision(
            operation_intent_id=created["operationIntentId"],
            audience=audience(),
            decision="declined",
            gesture_attestation_digest=DIGESTS[11],
        )
    assert captured.value.code == "OPERATION_APPROVAL_TERMINAL"


def test_decision_fails_closed_without_trusted_gesture_verifier(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock, verify_gestures=False)
    created, _, _, _ = create_intent(store, clock)
    with pytest.raises(AuthorizationLedgerError) as captured:
        store.record_operation_decision(
            operation_intent_id=created["operationIntentId"],
            audience=audience(),
            decision="approved",
            gesture_attestation_digest=DIGESTS[10],
        )
    assert captured.value.code == "TRUSTED_GESTURE_VERIFIER_UNAVAILABLE"
    assert store.get_operation_intent(
        created["operationIntentId"], audience()
    )["state"] == "pending"


def test_trusted_gesture_verifier_is_bound_to_audience_target_and_action(
    tmp_path: Path,
) -> None:
    clock = Clock()
    calls: list[tuple[str, str, str, str]] = []

    def verify(gesture: str, bound: str, target: str, action: str) -> bool:
        calls.append((gesture, bound, target, action))
        return True

    store = AuthorizationLedger(
        tmp_path / "authorization",
        authentication_key=KEY,
        service_instance_id="service-1",
        clock=clock,
        gesture_attestation_verifier=verify,
    )
    created, _, _, _ = create_intent(store, clock)
    store.record_operation_decision(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        decision="approved",
        gesture_attestation_digest=DIGESTS[10],
    )
    assert len(calls) == 1
    assert calls[0][0] == DIGESTS[10]
    assert len(calls[0][1]) == 64
    assert calls[0][2:] == (
        created["operationIntentId"],
        "decide:approved",
    )


def test_expired_intent_cannot_be_approved(tmp_path: Path) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    created, _, _, _ = create_intent(store, clock)
    clock.advance(hours=2)
    assert store.get_operation_intent(
        created["operationIntentId"], audience()
    )["state"] == "expired"
    with pytest.raises(AuthorizationLedgerError) as captured:
        store.record_operation_decision(
            operation_intent_id=created["operationIntentId"],
            audience=audience(),
            decision="approved",
            gesture_attestation_digest=DIGESTS[10],
        )
    assert captured.value.code == "OPERATION_INTENT_EXPIRED"


def consume_use(
    store: AuthorizationLedger,
    created: dict,
    consumed: dict,
    service_bindings: list[dict],
    *,
    capability: str = "model",
    use_id: str = "use-1",
) -> dict:
    action = "call_model" if capability == "model" else "call_tts"
    authorization_binding, authorization_grant = authorization_parts(
        consumed, action
    )
    service_binding = next(
        item for item in service_bindings if item["capability"] == capability
    )
    return store.consume_authorization(
        operation_intent_id=created["operationIntentId"],
        authorization_id=authorization_grant["authorizationId"],
        audience=audience(),
        task_id="task-1",
        action=action,
        use_id=use_id,
        expected_authorization_record_digest=authorization_binding[
            "authorizationRecordDigest"
        ],
        expected_exact_scope_digest=authorization_binding["exactScopeDigest"],
        expected_revocation_epoch=authorization_binding["expectedRevocationEpoch"],
        current_service_binding=service_binding,
    )


def authorization_parts(consumed: dict, action: str) -> tuple[dict, dict]:
    authorization_binding = next(
        item
        for item in consumed["authorizationBindings"]
        if item["action"] == action
    )
    authorization_grant = next(
        item
        for item in consumed["internalAuthorizationGrants"]
        if item["action"] == action
    )
    return authorization_binding, authorization_grant


def test_approval_must_exist_and_consumption_is_exactly_idempotent(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    created, bindings, _, _ = create_intent(store, clock)
    arguments = {
        "operation_intent_id": created["operationIntentId"],
        "audience": audience(),
        "task_id": "task-1",
        "consumption_id": "approval-consumption-1",
        "expected_intent_digest": created["intentDigest"],
        "expected_operation_request_digest": created[
            "operationRequestManifestDigest"
        ],
        "current_service_bindings": bindings,
    }
    with pytest.raises(AuthorizationLedgerError) as required:
        store.consume_operation_approval(**arguments)
    assert required.value.code == "OPERATION_APPROVAL_REQUIRED"
    store.record_operation_decision(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        decision="approved",
        gesture_attestation_digest=DIGESTS[10],
    )
    first = store.consume_operation_approval(**arguments)
    assert store.consume_operation_approval(**arguments) == first
    assert store.get_operation_intent(
        created["operationIntentId"], audience()
    )["state"] == "consumed"
    with pytest.raises(AuthorizationLedgerError) as consumed:
        store.consume_operation_approval(
            **{
                **arguments,
                "task_id": "task-2",
                "consumption_id": "approval-consumption-2",
            }
        )
    assert consumed.value.code == "OPERATION_APPROVAL_CONSUMED"


def test_consumed_bindings_feed_task_manifest_without_internal_ids(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    _, consumed, _ = approve_and_consume(store, clock)
    manifest, manifest_digest = build_authorization_binding(
        audience=audience(),
        service_instance_id="service-1",
        bindings=consumed["authorizationBindings"],
    )
    assert len(manifest_digest) == 64
    assert manifest["bindings"] == consumed["authorizationBindings"]
    assert "authorizationId" not in json.dumps(manifest)
    assert consumed["internalAuthorizationGrants"][0]["authorizationId"].startswith(
        "authorization_"
    )


def test_credential_or_configuration_change_invalidates_approved_intent(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    created, bindings, _, _ = create_intent(store, clock)
    store.record_operation_decision(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        decision="approved",
        gesture_attestation_digest=DIGESTS[10],
    )
    stale = [{**bindings[0], "credentialRevision": 2}]
    with pytest.raises(AuthorizationLedgerError) as captured:
        store.consume_operation_approval(
            operation_intent_id=created["operationIntentId"],
            audience=audience(),
            task_id="task-1",
            consumption_id="approval-consumption-1",
            expected_intent_digest=created["intentDigest"],
            expected_operation_request_digest=created[
                "operationRequestManifestDigest"
            ],
            current_service_bindings=stale,
        )
    assert captured.value.code == "AUTHORIZATION_SERVICE_BINDING_STALE"


def test_authorization_use_is_idempotent_and_profile_bound(tmp_path: Path) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    created, consumed, bindings = approve_and_consume(store, clock)
    first = consume_use(store, created, consumed, bindings)
    assert first["consumedUses"] == 1
    assert consume_use(store, created, consumed, bindings) == first
    second = consume_use(
        store, created, consumed, bindings, use_id="use-2"
    )
    assert second["consumedUses"] == 2
    authorization, grant = authorization_parts(consumed, "call_model")
    with pytest.raises(AuthorizationLedgerError) as stale:
        store.consume_authorization(
            operation_intent_id=created["operationIntentId"],
            authorization_id=grant["authorizationId"],
            audience=audience(),
            task_id="task-1",
            action="call_model",
            use_id="use-3",
            expected_authorization_record_digest=authorization[
                "authorizationRecordDigest"
            ],
            expected_exact_scope_digest=authorization["exactScopeDigest"],
            expected_revocation_epoch=0,
            current_service_binding={**bindings[0], "credentialRevision": 2},
        )
    assert stale.value.code == "AUTHORIZATION_SERVICE_BINDING_STALE"


def test_shared_operation_budget_cannot_be_multiplied_by_two_authorizations(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    bindings = [
        binding(),
        binding(
            capability="tts",
            profile_ref="profile-tts",
            configuration_fingerprint=DIGESTS[12],
            egress_manifest_digest=DIGESTS[13],
        ),
    ]
    created, _, _, _ = create_intent(
        store,
        clock,
        service_bindings=bindings,
        cost_budget=budget(max_remote_calls=1),
    )
    store.record_operation_decision(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        decision="approved",
        gesture_attestation_digest=DIGESTS[10],
    )
    consumed = store.consume_operation_approval(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        task_id="task-1",
        consumption_id="approval-consumption-1",
        expected_intent_digest=created["intentDigest"],
        expected_operation_request_digest=created[
            "operationRequestManifestDigest"
        ],
        current_service_bindings=bindings,
    )
    consume_use(store, created, consumed, bindings, capability="model")
    with pytest.raises(AuthorizationLedgerError) as exhausted:
        consume_use(
            store,
            created,
            consumed,
            bindings,
            capability="tts",
            use_id="tts-use-1",
        )
    assert exhausted.value.code == "OPERATION_BUDGET_CONSUMED"


def test_authorization_revocation_epoch_invalidates_old_binding(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    created, consumed, bindings = approve_and_consume(store, clock)
    authorization, grant = authorization_parts(consumed, "call_model")
    revoked = store.revoke_authorization(
        operation_intent_id=created["operationIntentId"],
        authorization_id=grant["authorizationId"],
        audience=audience(),
        expected_revocation_epoch=0,
        revocation_attestation_digest=DIGESTS[11],
    )
    assert revoked["state"] == "revoked"
    assert revoked["currentRevocationEpoch"] == 1
    assert (
        store.revoke_authorization(
            operation_intent_id=created["operationIntentId"],
            authorization_id=grant["authorizationId"],
            audience=audience(),
            expected_revocation_epoch=0,
            revocation_attestation_digest=DIGESTS[11],
        )
        == revoked
    )
    with pytest.raises(AuthorizationLedgerError) as captured:
        consume_use(store, created, consumed, bindings)
    assert captured.value.code == "AUTHORIZATION_REVOKED"


def test_approved_operation_can_be_revoked_before_task_creation(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    created, bindings, _, _ = create_intent(store, clock)
    store.record_operation_decision(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        decision="approved",
        gesture_attestation_digest=DIGESTS[10],
    )
    revoked = store.revoke_operation_approval(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        revocation_attestation_digest=DIGESTS[11],
    )
    assert revoked["state"] == "revoked"
    with pytest.raises(AuthorizationLedgerError) as captured:
        store.consume_operation_approval(
            operation_intent_id=created["operationIntentId"],
            audience=audience(),
            task_id="task-1",
            consumption_id="approval-consumption-1",
            expected_intent_digest=created["intentDigest"],
            expected_operation_request_digest=created[
                "operationRequestManifestDigest"
            ],
            current_service_bindings=bindings,
        )
    assert captured.value.code == "OPERATION_APPROVAL_REQUIRED"


def test_concurrent_approval_consumption_has_one_winner(tmp_path: Path) -> None:
    clock = Clock()
    first_store = ledger(tmp_path, clock)
    second_store = ledger(tmp_path, clock)
    created, bindings, _, _ = create_intent(first_store, clock)
    first_store.record_operation_decision(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        decision="approved",
        gesture_attestation_digest=DIGESTS[10],
    )
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def consume(store: AuthorizationLedger, number: int) -> None:
        barrier.wait()
        try:
            store.consume_operation_approval(
                operation_intent_id=created["operationIntentId"],
                audience=audience(),
                task_id=f"task-{number}",
                consumption_id=f"consumption-{number}",
                expected_intent_digest=created["intentDigest"],
                expected_operation_request_digest=created[
                    "operationRequestManifestDigest"
                ],
                current_service_bindings=bindings,
            )
            outcomes.append("ok")
        except AuthorizationLedgerError as error:
            outcomes.append(error.code)

    threads = [
        threading.Thread(target=consume, args=(first_store, 1)),
        threading.Thread(target=consume, args=(second_store, 2)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["OPERATION_APPROVAL_CONSUMED", "ok"]


def test_concurrent_authorization_budget_consumption_has_one_winner(
    tmp_path: Path,
) -> None:
    clock = Clock()
    first_store = ledger(tmp_path, clock)
    second_store = ledger(tmp_path, clock)
    created, consumed, bindings = approve_and_consume(
        first_store, clock, max_remote_calls=1
    )
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def consume(store: AuthorizationLedger, number: int) -> None:
        barrier.wait()
        try:
            consume_use(
                store,
                created,
                consumed,
                bindings,
                use_id=f"use-{number}",
            )
            outcomes.append("ok")
        except AuthorizationLedgerError as error:
            outcomes.append(error.code)

    threads = [
        threading.Thread(target=consume, args=(first_store, 1)),
        threading.Thread(target=consume, args=(second_store, 2)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert outcomes.count("ok") == 1
    assert len(outcomes) == 2
    assert next(item for item in outcomes if item != "ok") in {
        "AUTHORIZATION_NOT_ACTIVE",
        "OPERATION_BUDGET_CONSUMED",
    }


def test_use_id_same_but_changed_expected_binding_is_not_a_false_replay(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    created, consumed, bindings = approve_and_consume(store, clock)
    consume_use(store, created, consumed, bindings)
    authorization, grant = authorization_parts(consumed, "call_model")
    with pytest.raises(AuthorizationLedgerError) as captured:
        store.consume_authorization(
            operation_intent_id=created["operationIntentId"],
            authorization_id=grant["authorizationId"],
            audience=audience(),
            task_id="task-1",
            action="call_model",
            use_id="use-1",
            expected_authorization_record_digest=DIGESTS[15],
            expected_exact_scope_digest=authorization["exactScopeDigest"],
            expected_revocation_epoch=0,
            current_service_binding=bindings[0],
        )
    assert captured.value.code == "AUTHORIZATION_BINDING_MISMATCH"


def test_manifest_digest_scope_and_cost_policy_fail_closed(tmp_path: Path) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    bindings = [binding()]
    manifest = disclosure(bindings)
    cost = budget()
    operation_request = request(clock, bindings, manifest, cost)
    cases: list[tuple[dict, dict, dict, str]] = []
    cases.append(
        (
            {**operation_request, "disclosureManifestDigest": DIGESTS[15]},
            manifest,
            cost,
            "AUTHORIZATION_MANIFEST_MISMATCH",
        )
    )
    no_entries = {**manifest, "entries": []}
    cases.append(
        (
            {
                **operation_request,
                "disclosureManifestDigest": digest(no_entries),
            },
            no_entries,
            cost,
            "AUTHORIZATION_SCHEMA_INVALID",
        )
    )
    unknown_cost = {
        "priceKnown": False,
        "currency": None,
        "maxMinorUnits": None,
        "pricingSnapshotRef": None,
        "pricingSnapshotVersion": None,
        "unknownPricePolicy": "block",
        "maxRemoteCalls": 3,
        "maxCards": 20,
        "maxMediaItems": 40,
    }
    cases.append(
        (
            {**operation_request, "costBudgetDigest": digest(unknown_cost)},
            manifest,
            unknown_cost,
            "AUTHORIZATION_COST_BLOCKED",
        )
    )
    for number, (candidate_request, candidate_manifest, candidate_cost, code) in enumerate(cases):
        with pytest.raises(AuthorizationLedgerError) as captured:
            store.create_operation_intent(
                audience=audience(),
                idempotency_key=f"invalid-{number}",
                operation_request_manifest=candidate_request,
                disclosure_manifest=candidate_manifest,
                cost_budget=candidate_cost,
            )
        assert captured.value.code == code


def test_profile_validation_subject_must_match_exact_profile_revision(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    current_binding = binding()
    manifest = disclosure([current_binding])
    current_budget = budget(max_remote_calls=1)
    operation_request = request(
        clock, [current_binding], manifest, current_budget
    )
    operation_request["actionId"] = "validate_profile"
    operation_request["subject"] = {
        "kind": "profile_validation",
        "profileRef": current_binding["profileRef"],
        "configurationFingerprint": current_binding[
            "configurationFingerprint"
        ],
        "credentialRevision": current_binding["credentialRevision"],
    }
    created = store.create_operation_intent(
        audience=audience(),
        idempotency_key="profile-validation",
        operation_request_manifest=operation_request,
        disclosure_manifest=manifest,
        cost_budget=current_budget,
    )
    assert created["actionId"] == "validate_profile"
    mismatched = json.loads(json.dumps(operation_request))
    mismatched["subject"]["credentialRevision"] = 2
    with pytest.raises(AuthorizationLedgerError) as captured:
        store.create_operation_intent(
            audience=audience(),
            idempotency_key="profile-mismatch",
            operation_request_manifest=mismatched,
            disclosure_manifest=manifest,
            cost_budget=current_budget,
        )
    assert captured.value.code == "AUTHORIZATION_SUBJECT_MISMATCH"


def test_non_remote_workflow_action_cannot_request_service_authorization(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    current_binding = binding()
    manifest = disclosure([current_binding])
    current_budget = budget()
    operation_request = request(
        clock, [current_binding], manifest, current_budget
    )
    operation_request["actionId"] = "export_apkg"
    with pytest.raises(AuthorizationLedgerError) as captured:
        store.create_operation_intent(
            audience=audience(),
            idempotency_key="bad-action",
            operation_request_manifest=operation_request,
            disclosure_manifest=manifest,
            cost_budget=current_budget,
        )
    assert captured.value.code == "AUTHORIZATION_SCHEMA_INVALID"


def test_secret_path_and_excessive_lifetime_are_rejected(tmp_path: Path) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    secret_binding = binding(profile_ref="sk-" + "A" * 32)
    secret_disclosure = disclosure([secret_binding])
    current_budget = budget()
    with pytest.raises(AuthorizationLedgerError) as secret:
        store.create_operation_intent(
            audience=audience(),
            idempotency_key="secret",
            operation_request_manifest=request(
                clock, [secret_binding], secret_disclosure, current_budget
            ),
            disclosure_manifest=secret_disclosure,
            cost_budget=current_budget,
        )
    assert secret.value.code == "AUTHORIZATION_SECRET_FORBIDDEN"

    current_binding = binding()
    path_disclosure = disclosure([current_binding])
    path_disclosure["entries"][0]["target"]["modelOrVoiceRef"] = (
        r"C:\Users\Someone\secret.txt"
    )
    with pytest.raises(AuthorizationLedgerError):
        store.create_operation_intent(
            audience=audience(),
            idempotency_key="path",
            operation_request_manifest=request(
                clock, [current_binding], path_disclosure, current_budget
            ),
            disclosure_manifest=path_disclosure,
            cost_budget=current_budget,
        )

    manifest = disclosure([current_binding])
    too_long = request(
        clock,
        [current_binding],
        manifest,
        current_budget,
        expires_in_minutes=24 * 60 + 1,
    )
    with pytest.raises(AuthorizationLedgerError) as expiry:
        store.create_operation_intent(
            audience=audience(),
            idempotency_key="too-long",
            operation_request_manifest=too_long,
            disclosure_manifest=manifest,
            cost_budget=current_budget,
        )
    assert expiry.value.code == "AUTHORIZATION_EXPIRY_INVALID"


def test_authenticated_outer_and_inner_records_fail_closed_on_tamper(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    created, consumed, bindings = approve_and_consume(store, clock)
    with pytest.raises(AuthorizationLedgerError) as wrong_key:
        ledger(tmp_path, clock, key=b"x" * 32).get_operation_intent(
            created["operationIntentId"], audience()
        )
    assert wrong_key.value.code == "AUTHORIZATION_RECORD_CORRUPT"

    path = store._intent_path(created["operationIntentId"])
    original_raw = path.read_bytes()
    value = json.loads(original_raw.decode("utf-8"))
    value["globalUsage"]["maxRemoteCalls"] = 99
    path.write_bytes(canonical_json_bytes(value))
    with pytest.raises(AuthorizationLedgerError) as outer:
        store.get_operation_intent(created["operationIntentId"], audience())
    assert outer.value.code == "AUTHORIZATION_RECORD_CORRUPT"

    original_value = store._decode(original_raw)
    original_value["authorizations"][0]["record"]["maxUses"] = 99
    original_value.pop("authKeyId", None)
    original_value.pop("authTag", None)
    forged_outer = store._authenticate(original_value)
    path.write_bytes(canonical_json_bytes(forged_outer))
    authorization, grant = authorization_parts(consumed, "call_model")
    with pytest.raises(AuthorizationLedgerError) as inner:
        store.consume_authorization(
            operation_intent_id=created["operationIntentId"],
            authorization_id=grant["authorizationId"],
            audience=audience(),
            task_id="task-1",
            action="call_model",
            use_id="use-forged",
            expected_authorization_record_digest=authorization[
                "authorizationRecordDigest"
            ],
            expected_exact_scope_digest=authorization["exactScopeDigest"],
            expected_revocation_epoch=0,
            current_service_binding=bindings[0],
        )
    assert inner.value.code == "AUTHORIZATION_RECORD_CORRUPT"


def test_raw_idempotency_consumption_and_use_ids_are_not_persisted(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = ledger(tmp_path, clock)
    raw_intent_key = "raw-intent-key-canary"
    created, bindings, _, _ = create_intent(
        store, clock, key=raw_intent_key
    )
    store.record_operation_decision(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        decision="approved",
        gesture_attestation_digest=DIGESTS[10],
    )
    raw_consumption_id = "raw-consumption-id-canary"
    consumed = store.consume_operation_approval(
        operation_intent_id=created["operationIntentId"],
        audience=audience(),
        task_id="task-1",
        consumption_id=raw_consumption_id,
        expected_intent_digest=created["intentDigest"],
        expected_operation_request_digest=created[
            "operationRequestManifestDigest"
        ],
        current_service_bindings=bindings,
    )
    raw_use_id = "raw-use-id-canary"
    consume_use(
        store, created, consumed, bindings, use_id=raw_use_id
    )
    raw = store._intent_path(created["operationIntentId"]).read_bytes()
    for value in (raw_intent_key, raw_consumption_id, raw_use_id):
        assert value.encode("utf-8") not in raw
