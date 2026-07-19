from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from card_service.anki_import_approval import (
    AnkiImportApprovalError,
    AnkiImportApprovalLedger,
)
from card_service.artifact_registry import ArtifactAudienceBinding


PLAN_DIGEST = "a" * 64
TARGET_DIGEST = "b" * 64
APKG_DIGEST = "c" * 64


def _audience(
    session: str = "session-1", plugin: str = "plugin-1"
) -> ArtifactAudienceBinding:
    return ArtifactAudienceBinding(
        owner_digest="d" * 64,
        host_id="host-1",
        plugin_id=plugin,
        session_id=session,
    )


def _plan_ref() -> dict[str, object]:
    return {
        "artifactId": "anki_import_plan_1",
        "artifactRevision": 1,
        "artifactDigest": PLAN_DIGEST,
        "projectId": "project-1",
        "projectRevision": 4,
        "payloadSchema": "study.anki-import-plan",
        "payloadSchemaVersion": 1,
    }


def _ledger(
    tmp_path: Path,
    *,
    verifier=None,
    clock=None,
) -> AnkiImportApprovalLedger:
    return AnkiImportApprovalLedger(
        tmp_path / "import-approval",
        authentication_key=b"k" * 32,
        service_instance_id="service-1",
        gesture_attestation_verifier=verifier,
        clock=clock,
    )


def _create(ledger: AnkiImportApprovalLedger, audience=None) -> dict[str, object]:
    return ledger.create_intent(
        audience=audience or _audience(),
        project_id="project-1",
        project_revision=4,
        import_plan_ref=_plan_ref(),
        import_plan_digest=PLAN_DIGEST,
        target_digest=TARGET_DIGEST,
        apkg_sha256=APKG_DIGEST,
    )


def test_import_intent_is_deterministic_and_audience_bound(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    first = _create(ledger)
    second = _create(ledger)

    assert first == second
    assert first["approvalState"] == "pending"
    assert str(first["importIntentId"]).startswith("anki_intent_")
    with pytest.raises(AnkiImportApprovalError) as caught:
        ledger.get_intent(
            audience=_audience(session="other"),
            import_intent_id=str(first["importIntentId"]),
        )
    assert caught.value.code == "IMPORT_APPROVAL_AUDIENCE_MISMATCH"


def test_chat_value_cannot_approve_without_trusted_gesture_verifier(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    intent = _create(ledger)
    with pytest.raises(AnkiImportApprovalError) as caught:
        ledger.record_decision(
            audience=_audience(),
            import_intent_id=str(intent["importIntentId"]),
            decision="approved",
            gesture_attestation_ref="copied-chat-approval",
        )
    assert caught.value.code == "TRUSTED_GESTURE_VERIFIER_UNAVAILABLE"


def test_approved_intent_is_single_use_and_exact_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str, str, str]] = []

    def verifier(ref: str, audience: str, target: str, action: str) -> bool:
        calls.append((ref, audience, target, action))
        return ref == "trusted-ref" and action == "decide:approved"

    ledger = _ledger(tmp_path, verifier=verifier)
    intent = _create(ledger)
    intent_id = str(intent["importIntentId"])
    approved = ledger.record_decision(
        audience=_audience(),
        import_intent_id=intent_id,
        decision="approved",
        gesture_attestation_ref="trusted-ref",
    )
    assert approved["approvalState"] == "approved"
    assert calls and calls[0][2:] == (intent_id, "decide:approved")

    consumed = ledger.consume(
        audience=_audience(),
        import_intent_id=intent_id,
        execution_id="task-1",
        expected_import_plan_digest=PLAN_DIGEST,
        current_target_digest=TARGET_DIGEST,
    )
    repeated = ledger.consume(
        audience=_audience(),
        import_intent_id=intent_id,
        execution_id="task-1",
        expected_import_plan_digest=PLAN_DIGEST,
        current_target_digest=TARGET_DIGEST,
    )
    assert repeated == consumed
    assert (
        ledger.get_intent(audience=_audience(), import_intent_id=intent_id)[
            "approvalState"
        ]
        == "consumed"
    )
    with pytest.raises(AnkiImportApprovalError) as caught:
        ledger.consume(
            audience=_audience(),
            import_intent_id=intent_id,
            execution_id="task-2",
            expected_import_plan_digest=PLAN_DIGEST,
            current_target_digest=TARGET_DIGEST,
        )
    assert caught.value.code == "IMPORT_APPROVAL_CONSUMED"


def test_target_change_rejects_without_consuming_approval(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, verifier=lambda *_: True)
    intent_id = str(_create(ledger)["importIntentId"])
    ledger.record_decision(
        audience=_audience(),
        import_intent_id=intent_id,
        decision="approved",
        gesture_attestation_ref="trusted-ref",
    )
    with pytest.raises(AnkiImportApprovalError) as caught:
        ledger.consume(
            audience=_audience(),
            import_intent_id=intent_id,
            execution_id="task-1",
            expected_import_plan_digest=PLAN_DIGEST,
            current_target_digest="e" * 64,
        )
    assert caught.value.code == "ANKI_TARGET_CHANGED"
    assert (
        ledger.get_intent(audience=_audience(), import_intent_id=intent_id)[
            "approvalState"
        ]
        == "approved"
    )


def test_expired_or_tampered_intent_fails_closed(tmp_path: Path) -> None:
    now = [datetime(2026, 7, 18, tzinfo=timezone.utc)]
    ledger = _ledger(tmp_path, verifier=lambda *_: True, clock=lambda: now[0])
    intent_id = str(_create(ledger)["importIntentId"])
    now[0] += timedelta(minutes=31)
    assert (
        ledger.get_intent(audience=_audience(), import_intent_id=intent_id)[
            "approvalState"
        ]
        == "expired"
    )
    with pytest.raises(AnkiImportApprovalError) as expired:
        ledger.record_decision(
            audience=_audience(),
            import_intent_id=intent_id,
            decision="approved",
            gesture_attestation_ref="trusted-ref",
        )
    assert expired.value.code == "IMPORT_INTENT_EXPIRED"

    fresh = _ledger(tmp_path / "tamper", verifier=lambda *_: True)
    fresh_id = str(_create(fresh)["importIntentId"])
    record_path = fresh._intent_path(fresh_id)
    value = json.loads(record_path.read_text(encoding="utf-8"))
    value["intent"]["apkgSha256"] = "f" * 64
    record_path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(AnkiImportApprovalError) as tampered:
        fresh.get_intent(audience=_audience(), import_intent_id=fresh_id)
    assert tampered.value.code == "IMPORT_APPROVAL_RECORD_CORRUPT"


def test_concurrent_consumers_have_one_atomic_winner(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, verifier=lambda *_: True)
    intent_id = str(_create(ledger)["importIntentId"])
    ledger.record_decision(
        audience=_audience(),
        import_intent_id=intent_id,
        decision="approved",
        gesture_attestation_ref="trusted-ref",
    )
    barrier = threading.Barrier(3)
    outcomes: list[tuple[str, str]] = []

    def consume(execution_id: str) -> None:
        barrier.wait()
        try:
            ledger.consume(
                audience=_audience(),
                import_intent_id=intent_id,
                execution_id=execution_id,
                expected_import_plan_digest=PLAN_DIGEST,
                current_target_digest=TARGET_DIGEST,
            )
        except AnkiImportApprovalError as error:
            outcomes.append((execution_id, error.code))
        else:
            outcomes.append((execution_id, "consumed"))

    first = threading.Thread(target=consume, args=("task-a",))
    second = threading.Thread(target=consume, args=("task-b",))
    first.start()
    second.start()
    barrier.wait()
    first.join()
    second.join()

    assert sorted(code for _, code in outcomes) == [
        "IMPORT_APPROVAL_CONSUMED",
        "consumed",
    ]
