from __future__ import annotations

import threading
from types import SimpleNamespace

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.service import CardService


INTENT_ID = "anki_intent_" + "a" * 48


def _audience() -> ArtifactAudienceBinding:
    return ArtifactAudienceBinding(
        owner_digest="b" * 64,
        host_id="host-1",
        plugin_id="plugin-1",
        session_id="session-1",
    )


class _StudyRuntime:
    def __init__(self) -> None:
        self.state = "pending"
        self.recorded: list[dict[str, object]] = []

    def get_anki_import_approval(self, **_kwargs):
        return {
            "schemaVersion": 1,
            "importIntentId": INTENT_ID,
            "approvalState": self.state,
            "expiresAt": "2026-07-18T12:30:00.000Z",
        }

    def get_anki_import_confirmation_context(self, **_kwargs):
        return {
            "schemaVersion": 1,
            "importIntentId": INTENT_ID,
            "audienceDigest": "c" * 64,
            "importPlanDigest": "d" * 64,
            "summary": "导入 3 张卡；仅检测重复；写入边界不明时停止。",
        }

    def record_anki_import_decision(self, **kwargs):
        self.recorded.append(kwargs)
        self.state = str(kwargs["decision"])
        return self.get_anki_import_approval()


class _TrustedSurfaces:
    def __init__(self) -> None:
        self.created = 0
        self.completed: list[str] = []

    def create_anki_import_consent_session(self, **_kwargs):
        self.created += 1
        return {"sessionRef": "trusted-session-1", "state": "created"}

    def launch(self, session_ref: str):
        return {"sessionRef": session_ref, "state": "open"}

    def get_session(self, session_ref: str):
        return {
            "schemaVersion": 1,
            "sessionRef": session_ref,
            "state": "approved",
            "userGestureRecorded": True,
        }

    def import_consent_decision(self, session_ref: str):
        return SimpleNamespace(
            session_ref=session_ref,
            import_intent_id=INTENT_ID,
            decision="approved",
            attestation_ref="private-attestation-ref",
        )

    def complete_import_consent(self, session_ref: str) -> None:
        self.completed.append(session_ref)


def _service() -> tuple[CardService, _StudyRuntime, _TrustedSurfaces]:
    service = object.__new__(CardService)
    study = _StudyRuntime()
    surfaces = _TrustedSurfaces()
    service._study_runtime = study
    service._study_runtime_lock = threading.RLock()
    service.trusted_surfaces = surfaces
    service._anki_import_confirmation_requests = {}
    service._completed_anki_import_confirmations = {}
    service._anki_import_confirmation_lock = threading.RLock()
    return service, study, surfaces


def test_service_opens_once_then_records_only_internal_trusted_decision() -> None:
    service, study, surfaces = _service()
    first = service.request_study_anki_import_confirmation(
        audience=_audience(), import_intent_id=INTENT_ID
    )
    assert first["approvalState"] == "pending"
    assert surfaces.created == 1

    second = service.request_study_anki_import_confirmation(
        audience=_audience(), import_intent_id=INTENT_ID
    )
    assert second["approvalState"] == "approved"
    assert surfaces.created == 1
    assert surfaces.completed == ["trusted-session-1"]
    assert study.recorded == [
        {
            "audience": _audience(),
            "import_intent_id": INTENT_ID,
            "decision": "approved",
            "gesture_attestation_ref": "private-attestation-ref",
        }
    ]
    assert "attestation" not in str(second).lower()


def test_terminal_approval_does_not_reopen_trusted_window() -> None:
    service, study, surfaces = _service()
    study.state = "approved"
    result = service.request_study_anki_import_confirmation(
        audience=_audience(), import_intent_id=INTENT_ID
    )
    assert result["approvalState"] == "approved"
    assert surfaces.created == 0
