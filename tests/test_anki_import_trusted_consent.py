from __future__ import annotations

import sys
import time
from pathlib import Path

from card_service.trusted_surfaces import TrustedSurfaceManager


ROOT = Path(__file__).resolve().parents[1]
FAKE_SURFACE = ROOT / "tests" / "fixtures" / "card_service" / "fake_surface.py"


def _wait(manager: TrustedSurfaceManager, session_ref: str) -> dict[str, object]:
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        result = manager.get_session(session_ref)
        if result["state"] not in {"created", "open"}:
            return result
        time.sleep(0.02)
    raise AssertionError("trusted Anki confirmation did not finish")


def test_import_confirmation_produces_only_internal_exact_attestation(
    tmp_path: Path,
) -> None:
    manager = TrustedSurfaceManager(
        state_dir=(tmp_path / "surfaces").resolve(),
        python_path=Path(sys.executable).resolve(),
        surface_path=FAKE_SURFACE.resolve(),
    )
    intent_id = "anki_intent_" + "a" * 48
    audience_digest = "b" * 64
    plan_digest = "c" * 64
    session = manager.create_anki_import_consent_session(
        import_intent_id=intent_id,
        audience_digest=audience_digest,
        import_plan_digest=plan_digest,
        summary="将 3 张卡片写入当前 Anki；APKG cccc…；重复项仅检测并报告。",
    )
    manager.launch(str(session["sessionRef"]))
    public = _wait(manager, str(session["sessionRef"]))

    assert public == {
        "schemaVersion": 1,
        "sessionRef": session["sessionRef"],
        "state": "approved",
        "userGestureRecorded": True,
    }
    assert "attestation" not in str(public).lower()
    decision = manager.import_consent_decision(str(session["sessionRef"]))
    assert decision is not None
    assert decision.import_intent_id == intent_id
    assert decision.decision == "approved"
    assert manager.verify_import_consent_gesture(
        decision.attestation_ref,
        audience_digest,
        intent_id,
        "decide:approved",
    )
    assert not manager.verify_import_consent_gesture(
        decision.attestation_ref,
        "d" * 64,
        intent_id,
        "decide:approved",
    )
    assert not manager.verify_import_consent_gesture(
        decision.attestation_ref,
        audience_digest,
        intent_id,
        "decide:declined",
    )
    manager.complete_import_consent(str(session["sessionRef"]))
    assert manager.import_consent_decision(str(session["sessionRef"])) is None
    assert not manager.verify_import_consent_gesture(
        decision.attestation_ref,
        audience_digest,
        intent_id,
        "decide:approved",
    )
