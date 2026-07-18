from __future__ import annotations

import hashlib
import json
import io
import os
import shutil
import subprocess
import sys
import time
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

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


def _tts_media_semantics(result: dict[str, object]) -> list[dict[str, object]]:
    manifest = result.get("media_manifest")
    assert isinstance(manifest, dict)
    entries = [
        value
        for value in manifest.values()
        if isinstance(value, dict)
        and str(value.get("role") or "") in {"sentence_tts", "phrase_tts"}
    ]
    return sorted(
        json.loads(json.dumps(entries, ensure_ascii=False)),
        key=lambda value: (str(value.get("role") or ""), str(value.get("tts_text") or "")),
    )


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


@pytest.mark.skipif(sys.platform != "win32", reason="restricted Worker equivalence is Windows-only")
def test_restricted_headless_export_matches_desktop_brokered_tts_semantics(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg is not None and ffprobe is not None
    managed_tools = tmp_path / "managed-tools"
    managed_tools.mkdir()
    shutil.copy2(ffmpeg, managed_tools / "ffmpeg.exe")
    shutil.copy2(ffprobe, managed_tools / "ffprobe.exe")
    audio_path = tmp_path / "deterministic-silence.mp3"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono:d=0.4",
            "-acodec",
            "libmp3lame",
            "-q:a",
            "5",
            str(audio_path),
        ],
        check=True,
        timeout=30,
    )
    audio = audio_path.read_bytes()
    assert audio.startswith(b"ID3")

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

    tts_config = {
        "enabled": True,
        "provider": "xai",
        "base_url": "https://api.x.ai/v1",
        "model": "tts-service-owned",
        "voice": "eve",
        "language": "auto",
        "sample_rate": 24000,
        "bit_rate": 128000,
        "output_volume": 1.0,
    }
    desktop_project["api_config"]["tts_config"] = {
        **tts_config,
        "api_key": "desktop-test-only-canary",
    }
    desktop_project["disable_tts_cache_read"] = True
    desktop_project["disable_tts_cache_write"] = True
    desktop_output = tmp_path / "desktop-tts-output"
    desktop_output.mkdir()
    with (
        patch.object(desktop_worker._legacy_worker, "call_tts_audio", return_value=audio),
        patch.object(desktop_worker._legacy_worker, "store_cached_file"),
    ):
        desktop_export = desktop_worker.handle_export(
            {"project": desktop_project, "output_dir": str(desktop_output)}
        )

    headless_project = json.loads(json.dumps(desktop_project, ensure_ascii=False))
    headless_project["api_config"]["tts_config"].pop("api_key", None)
    credentials = CredentialStore(
        state_dir=(tmp_path / "tts-credentials").resolve(),
        backend=InMemoryCredentialBackend(),
    )
    metadata = credentials.set_secret("tts.primary", "tts-equivalence-secret-canary")
    ledger = BrokerReservationLedger((tmp_path / "tts-broker-ledger.json").resolve())
    broker = ModelTtsBroker(credential_store=credentials, ledger=ledger)
    observed_requests = []

    def transport(provider_request):
        observed_requests.append(provider_request)
        assert provider_request.headers["Authorization"] == "Bearer tts-equivalence-secret-canary"
        return ProviderTransportResponse(
            200,
            provider_request.url,
            {"content-type": "audio/mpeg"},
            audio,
        )

    authorization = TaskBrokerAuthorization(
        operation_intent_ref="intent-semantic-equivalence-tts-1",
        budget=BrokerBudget(8, 1_000_000, 1_000_000, 100),
        operations={
            "tts.synthesize": AuthorizedProviderCall(
                profile=ProviderProfile(
                    profile_ref="tts.primary",
                    capability="tts",
                    provider="xai",
                    base_url="https://api.x.ai/v1",
                    model="tts-service-owned",
                    voice="eve",
                    maximum_response_bytes=100_000,
                ),
                credential_revision=int(metadata["credentialRevision"]),
                reserved_cost_minor_units=3,
                transport=transport,
            )
        },
    )
    requested_output = tmp_path / "caller-headless-output"
    requested_output.mkdir()

    def broker_factory(task_id: str, method: str, task_request: dict[str, object]):
        assert method == "runtime.export_apkg"
        serialized = json.dumps(task_request, ensure_ascii=False)
        assert "api_key" not in serialized.casefold()
        output_dir = Path(str(task_request["output_dir"])).resolve()
        expected_output_dir = (
            tmp_path / "tts-service-state" / "sandboxes" / task_id / "exports"
        ).resolve()
        assert output_dir == expected_output_dir
        assert output_dir != requested_output.resolve()
        return make_task_broker_handler(task_id=task_id, authorization=authorization, broker=broker)

    service = CardService(
        state_dir=(tmp_path / "tts-service-state").resolve(),
        worker_path=(ROOT / "workers" / "anki_worker.py").resolve(),
        python_path=Path(sys.executable).resolve(),
        managed_tool_directories=[managed_tools.resolve()],
        method_policies={
            "runtime.export_apkg": MethodPolicy("export", 120.0, requires_broker=True),
        },
        broker_handler_factory=broker_factory,
        use_restricted_launcher=True,
    )
    started = service.start_task(
        "runtime.export_apkg",
        {"project": headless_project, "output_dir": str(requested_output)},
    )
    finished = _wait_terminal(service, str(started["id"]), timeout=120.0)
    assert finished["state"] == "succeeded", finished.get("error")
    assert finished["isolation"]["restrictedPrimaryToken"] is True
    assert finished["isolation"]["jobInheritedBeforeResume"] is True
    headless_export = service.read_result(str(started["id"]))

    assert _tts_media_semantics(headless_export) == _tts_media_semantics(desktop_export)
    for contract_field in (
        "template_family",
        "template_schema",
        "note_model_id",
        "model_name",
        "compatibility_contract_version",
        "note_model_contract_digest",
        "note_content_fingerprint",
    ):
        assert headless_export[contract_field] == desktop_export[contract_field]
    assert headless_export["media_summary"]["sentence_tts_files"] == 1
    assert headless_export["media_summary"]["phrase_tts_files"] == 1
    assert len(observed_requests) == 2
    assert {record["capability"] for record in ledger.list_records()} == {"tts"}
    assert {record["state"] for record in ledger.list_records()} == {"settled"}
    assert not any(requested_output.iterdir())
    assert Path(headless_export["apkg_path"]).resolve().is_relative_to(
        (tmp_path / "tts-service-state" / "sandboxes" / str(started["id"]) / "exports").resolve()
    )
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "tts-equivalence-secret-canary" not in persisted


@pytest.mark.skipif(sys.platform != "win32", reason="packaged runtime verification is Windows-only")
def test_signed_packaged_runtime_matches_desktop_brokered_tts_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_text = os.environ.get("ANKI_TEST_MANAGED_RUNTIME", "").strip()
    trust_text = os.environ.get("ANKI_TEST_MANAGED_RUNTIME_TRUST", "").strip()
    if not runtime_text or not trust_text:
        pytest.skip("set ANKI_TEST_MANAGED_RUNTIME and ANKI_TEST_MANAGED_RUNTIME_TRUST")

    runtime_root = Path(runtime_text).resolve()
    trust_policy = Path(trust_text).resolve()
    assert runtime_root.is_dir()
    assert trust_policy.is_file()
    manifest_path = runtime_root / "runtime-package-v1.json"
    before_files = tuple(
        sorted(
            path.relative_to(runtime_root).as_posix()
            for path in runtime_root.rglob("*")
            if path.is_file()
        )
    )
    before_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert not any(path.casefold().endswith((".pyc", ".pyo")) for path in before_files)
    base_service = CardService
    instances: list[CardService] = []

    class PackagedCardService(base_service):
        def __init__(
            self,
            *,
            state_dir: str | Path,
            method_policies: dict[str, MethodPolicy],
            broker_handler_factory,
            use_restricted_launcher: bool,
            **_ignored,
        ) -> None:
            packaged_policies = {
                method: (
                    MethodPolicy(
                        policy.worker_command,
                        max(360.0, policy.timeout_seconds),
                        requires_broker=policy.requires_broker,
                    )
                    if method == "runtime.export_apkg"
                    else policy
                )
                for method, policy in method_policies.items()
            }
            super().__init__(
                state_dir=state_dir,
                runtime_package=runtime_root,
                runtime_trust_policy=trust_policy,
                method_policies=packaged_policies,
                broker_handler_factory=broker_handler_factory,
                use_restricted_launcher=use_restricted_launcher,
            )
            instances.append(self)

    monkeypatch.setattr(sys.modules[__name__], "CardService", PackagedCardService)
    source_wait_terminal = _wait_terminal

    def wait_for_packaged_runtime(
        service: CardService,
        task_id: str,
        timeout: float = 60.0,
    ) -> dict[str, object]:
        return source_wait_terminal(service, task_id, timeout=max(timeout, 360.0))

    monkeypatch.setattr(sys.modules[__name__], "_wait_terminal", wait_for_packaged_runtime)
    test_restricted_headless_export_matches_desktop_brokered_tts_semantics(tmp_path)

    assert len(instances) == 1
    capabilities = instances[0].capabilities()
    assert capabilities["runtimePackage"]["signatureVerified"] is True
    assert capabilities["runtimePackage"]["sbomVerified"] is True
    assert capabilities["processIsolation"]["runtimePackageDacl"] is True
    assert capabilities["processIsolation"]["taskWorkspaceDacl"] is True
    after_files = tuple(
        sorted(
            path.relative_to(runtime_root).as_posix()
            for path in runtime_root.rglob("*")
            if path.is_file()
        )
    )
    assert after_files == before_files
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == before_manifest_sha256
    assert not any(path.casefold().endswith((".pyc", ".pyo")) for path in after_files)
