from __future__ import annotations

import json
import io
import sys
import time
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from card_service.broker import BrokerBudget, BrokerReservationLedger, ModelTtsBroker
from card_service.broker_runtime import AuthorizedProviderCall, TaskBrokerAuthorization, make_task_broker_handler
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.provider_egress import ProviderProfile, ProviderTransportResponse
from card_service.service import CardService, MethodPolicy
from workers import anki_worker as desktop_worker


ROOT = Path(__file__).resolve().parents[1]


def _card_payload(segment_id: str) -> dict[str, object]:
    return {
        "segments": [
            {
                "id": segment_id,
                "cards": [
                    {
                        "id": "card_0001",
                        "type": "phrase",
                        "learning_point_id": "lp-common-sense",
                        "phrase": "common sense",
                        "answer_core": "common sense",
                        "normalized_answer": "common sense",
                        "exact_span": "common sense",
                        "english": "Use common sense here.",
                        "chinese": "这里要用常识判断。",
                        "definition": "ordinary practical judgment",
                        "collocations": "use common sense",
                        "context": "Use common sense here.",
                        "example": "Use common sense when deciding.",
                        "chinese_feel": "常识判断",
                        "why": "高频且可迁移",
                        "difficulty": "B1",
                        "estimated_level": "B1",
                        "teacher_note": "用于提醒对方作基本判断。",
                        "cloze": "Use ____ here.",
                        "quality": {"score": 90, "status": "recommended", "issues": []},
                    }
                ],
            }
        ]
    }


def _request() -> dict[str, object]:
    return {
        "project_id": "semantic-equivalence-project",
        "title": "Semantic equivalence proof",
        "deck_name": "字幕语言卡::Semantic Equivalence Proof",
        "language": "en",
        "level": "B1",
        "source_mode": "local",
        "skip_video_slicing": True,
        "video_path": "",
        "subtitle_path": "",
        "card_types": ["phrase"],
        "template_id": "immersive_v11",
        "api_config": {
            "provider": "openai-compatible",
            "model": "worker-model-hint",
            "tts_config": {"enabled": False, "provider": "disabled"},
        },
        "learning_points": [
            {
                "id": "lp-common-sense",
                "status": "recommended",
                "candidate_kind": "expression",
                "phrase_type": "spoken_phrase",
                "source_sentence": "Use common sense here.",
                "exact_span": "common sense",
                "answer_core": "common sense",
                "normalized_answer": "common sense",
                "reason": "高频且可迁移",
                "learning_action": "理解并会使用 common sense。",
                "value_score": 5,
                "start": 0,
                "end": 2,
            }
        ],
        "selected_learning_point_ids": ["lp-common-sense"],
        "disable_card_generation_cache_read": True,
        "disable_card_generation_cache_write": True,
    }


def _project_semantics(project: dict[str, object]) -> dict[str, object]:
    stable_keys = (
        "id",
        "title",
        "language",
        "level",
        "source_mode",
        "skip_video_slicing",
        "video_path",
        "subtitle_path",
        "template_id",
        "card_style",
        "review_density",
        "selected_learning_point_ids",
        "generated_learning_point_ids",
        "segments",
    )
    return {key: project.get(key) for key in stable_keys}


def _export_semantics(result: dict[str, object]) -> dict[str, object]:
    stable_keys = (
        "cards",
        "deck_kind",
        "note_model_contract",
        "media_manifest",
        "card_media_ledger",
        "audio_audit_items",
    )

    def without_run_identity(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: without_run_identity(child)
                for key, child in value.items()
                if key not in {"deck", "deck_name", "deck_names"}
            }
        if isinstance(value, list):
            return [without_run_identity(child) for child in value]
        return value

    return {key: without_run_identity(result.get(key)) for key in stable_keys}


def _wait_terminal(service: CardService, task_id: str, timeout: float = 60.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = service.get_task(task_id)
        assert snapshot is not None
        if snapshot["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return snapshot
        time.sleep(0.03)
    raise AssertionError("Card Service task did not reach a terminal state")


def test_desktop_worker_and_headless_service_produce_equivalent_project_and_media_ledgers(tmp_path: Path) -> None:
    request = _request()
    original_call_model_batches = desktop_worker._legacy_worker.call_model_batches
    original_phrase_review_available = desktop_worker._legacy_worker.phrase_review_available

    def direct_model(_project: dict[str, object], segments: list[dict[str, object]]) -> dict[str, object]:
        return _card_payload(str(segments[0]["id"]))

    try:
        desktop_worker._legacy_worker.phrase_review_available = lambda _payload: True
        desktop_worker._legacy_worker.call_model_batches = direct_model
        desktop_project = desktop_worker.handle_generate_cards_from_learning_points(
            json.loads(json.dumps(request, ensure_ascii=False))
        )
    finally:
        desktop_worker._legacy_worker.call_model_batches = original_call_model_batches
        desktop_worker._legacy_worker.phrase_review_available = original_phrase_review_available

    credentials = CredentialStore(
        state_dir=(tmp_path / "credentials").resolve(),
        backend=InMemoryCredentialBackend(),
    )
    metadata = credentials.set_secret("model.primary", "equivalence-secret-canary")
    ledger = BrokerReservationLedger((tmp_path / "broker-ledger.json").resolve())
    broker = ModelTtsBroker(credential_store=credentials, ledger=ledger)

    def transport(provider_request):
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_card_payload("seg_lp_0001"), ensure_ascii=False),
                    }
                }
            ]
        }
        return ProviderTransportResponse(
            200,
            provider_request.url,
            {"content-type": "application/json"},
            json.dumps(response, ensure_ascii=False).encode("utf-8"),
        )

    authorization = TaskBrokerAuthorization(
        operation_intent_ref="intent-semantic-equivalence-1",
        budget=BrokerBudget(8, 1_000_000, 1_000_000, 100),
        operations={
            "model.openai_chat": AuthorizedProviderCall(
                profile=ProviderProfile(
                    profile_ref="model.primary",
                    capability="model",
                    provider="openai",
                    base_url="https://api.openai.com/v1",
                    model="gpt-service-owned",
                    maximum_response_bytes=100_000,
                ),
                credential_revision=int(metadata["credentialRevision"]),
                reserved_cost_minor_units=3,
                transport=transport,
            )
        },
    )

    def broker_factory(task_id: str, _method: str, _task_request: dict[str, object]):
        return make_task_broker_handler(task_id=task_id, authorization=authorization, broker=broker)

    service = CardService(
        state_dir=(tmp_path / "service-state").resolve(),
        worker_path=(ROOT / "workers" / "anki_worker.py").resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.generate_cards": MethodPolicy(
                "generate_cards_from_learning_points",
                60.0,
                requires_broker=True,
            ),
            "runtime.export_apkg": MethodPolicy("export", 60.0, requires_broker=True),
        },
        broker_handler_factory=broker_factory,
        use_restricted_launcher=False,
    )
    started = service.start_task(
        "runtime.generate_cards",
        json.loads(json.dumps(request, ensure_ascii=False)),
    )
    finished = _wait_terminal(service, str(started["id"]))
    assert finished["state"] == "succeeded", finished.get("error")
    headless_project = service.read_result(str(started["id"]))
    assert _project_semantics(headless_project) == _project_semantics(desktop_project)

    desktop_output = tmp_path / "desktop-output"
    desktop_output.mkdir()
    desktop_export = desktop_worker.handle_export(
        {"project": desktop_project, "output_dir": str(desktop_output)}
    )
    headless_output = tmp_path / "headless-output"
    headless_output.mkdir()
    export_started = service.start_task(
        "runtime.export_apkg",
        {"project": headless_project, "output_dir": str(headless_output)},
    )
    export_finished = _wait_terminal(service, str(export_started["id"]))
    assert export_finished["state"] == "succeeded", export_finished.get("error")
    headless_export = service.read_result(str(export_started["id"]))
    assert _export_semantics(headless_export) == _export_semantics(desktop_export)
    assert finished["progress"]["overallPercent"] == 100
    assert export_finished["progress"]["overallPercent"] == 100
    assert {record["capability"] for record in ledger.list_records()} == {"model"}
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "equivalence-secret-canary" not in persisted

    invalid_request = _request()
    invalid_request["selected_learning_point_ids"] = []
    direct_error_stream = io.StringIO()
    original_phrase_review_available = desktop_worker._legacy_worker.phrase_review_available
    try:
        desktop_worker._legacy_worker.phrase_review_available = lambda _payload: True
        with redirect_stderr(direct_error_stream), pytest.raises(SystemExit):
            desktop_worker.handle_generate_cards_from_learning_points(
                json.loads(json.dumps(invalid_request, ensure_ascii=False))
            )
    finally:
        desktop_worker._legacy_worker.phrase_review_available = original_phrase_review_available
    direct_error_line = next(
        line
        for line in direct_error_stream.getvalue().splitlines()
        if line.startswith("__ANKI_CARD_ERROR__")
    )
    direct_error = json.loads(direct_error_line.removeprefix("__ANKI_CARD_ERROR__"))

    invalid_started = service.start_task(
        "runtime.generate_cards",
        json.loads(json.dumps(invalid_request, ensure_ascii=False)),
    )
    invalid_finished = _wait_terminal(service, str(invalid_started["id"]))
    assert invalid_finished["state"] == "failed"
    assert invalid_finished["error"] == {
        "code": direct_error["error_code"],
        "message": direct_error["message"],
        "retryable": direct_error["retryable"],
        "stage": direct_error["stage"],
    }
