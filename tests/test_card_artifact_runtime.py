from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

from card_service.card_artifact_queries import CardArtifactQueryRuntime
from card_service.card_artifact_runtime import CardArtifactRuntimeError
from card_service.card_plan_runtime import (
    CardPlanRuntimeError,
    _answer_leaks,
    _language_profile,
)
from card_service.language_profiles import normalize_answer_leakage_text
from card_service.project_registry import ProjectRegistryError
from card_service.study_runtime import StudyRuntimeError
from card_service.task_coordinator import StudyTaskError
from tests.test_card_plan_revision_runtime import planned_runtime
from tests.test_candidate_discovery_runtime import audience
from tests.test_candidate_discovery_runtime import (
    FakeDiscoveryModel,
    _selection_for_card_planning,
    discover,
    environment,
)


def generated_runtime(tmp_path):
    runtime, project, planned, listed = planned_runtime(tmp_path)
    generated = runtime.generate_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="generate-cards-1",
        plan_set_handle=planned["planSetHandle"],
    )
    return runtime, project, planned, listed, generated


@pytest.mark.parametrize(
    "cue",
    [
        "Please recall in-good shape.",
        "Please recall in\u200bgood shape.",
        "Please recall IN / GOOD / SHAPE.",
    ],
)
def test_card_plan_answer_leakage_collapses_display_only_separators(cue) -> None:
    assert _answer_leaks(cue, "in good shape") is True


@pytest.mark.parametrize(
    ("learning_contract", "form", "meaning"),
    [
        (
            {"promptLanguage": "zh-CN", "answerLanguage": "en"},
            "状态良好",
            "身体或事物处于良好状态",
        ),
        (
            {"promptLanguage": "en", "answerLanguage": "en"},
            "in good shape",
            "身体或事物处于良好状态",
        ),
    ],
)
def test_card_plan_language_profile_replays_form_and_meaning_scripts(
    learning_contract, form, meaning
) -> None:
    with pytest.raises(CardPlanRuntimeError) as captured:
        _language_profile(
            learning_contract=learning_contract,
            route="production",
            candidate_language="en",
            form=form,
            meaning=meaning,
        )
    assert captured.value.code == "UNSUPPORTED_CARD_PLAN"


def test_generation_publishes_verified_cards_and_export_compatible_projection(
    tmp_path,
) -> None:
    runtime, project, planned, _listed, result = generated_runtime(tmp_path)

    assert result == {
        "schemaVersion": 1,
        "projectId": project["projectId"],
        "projectRevision": planned["projectRevision"] + 1,
        "artifactStage": "cards_ready",
        "taskId": result["taskId"],
        "projectArtifactHandle": result["projectArtifactHandle"],
        "generatedCards": 1,
        "verifiedCards": 1,
        "needsReviewCards": 0,
        "hardFailedCards": 0,
        "mediaCount": 0,
        "generationMode": "deterministic_projection",
        "nextAction": "export_apkg",
    }
    resolved = runtime.card_artifacts.resolve_current_project_artifact(
        audience=audience(),
        project_artifact_handle=result["projectArtifactHandle"],
    )
    assert len(resolved["cardEnvelopes"]) == 1
    card = resolved["cardEnvelopes"][0]["payload"]
    assert (
        card["front"]["prompt"] == "Intended function: healthy or in a good condition"
    )
    assert card["back"]["coreAnswer"] == "in good shape"
    assert card["scoring"]["points"] == ["in good shape"]
    assert card["verification"]["state"] == "verified"
    assert card["mediaRefs"] == []
    assert card["generation"] == {
        "mode": "deterministic_projection",
        "policyVersion": "deterministic-card-artifact-v2",
        "modelUsed": False,
        "ttsUsed": False,
        "mediaUsed": False,
    }
    assert card["languageProfile"] == {
        "answerLanguage": "en",
        "meaningLanguage": "en",
        "promptLanguage": "en",
        "route": "production",
        "targetLanguage": "en",
    }
    assert card["evidencePresentation"]["state"] == "verified"
    assert card["evidencePresentation"]["items"][0]["quote"] == "in good shape"
    assert card["evidencePresentation"]["primaryText"] in (
        "Use in good shape when something remains in good condition.",
        "Use in good shape when something remains in good condition. Staying in good shape takes work.",
    )
    assert card["contentOrigins"]["coreAnswer"]["kind"] == "source_direct"
    assert (
        card["contentOrigins"]["frontPrompt"]["kind"]
        == "model_reviewed_interpretation"
    )
    legacy = resolved["legacyProjection"]["projection"]["project"]
    assert legacy["source_mode"] == "local"
    assert legacy["skip_video_slicing"] is True
    assert legacy["video_path"] == ""
    assert legacy["subtitle_path"] == ""
    assert legacy["reliability_manifest"]["decision"] == "pass"
    legacy_card = legacy["segments"][0]["cards"][0]
    assert legacy_card["type"] == "phrase"
    assert legacy_card["answer_core"] == "in good shape"
    assert legacy_card["english"] == card["evidencePresentation"]["primaryText"]
    assert legacy_card["source_evidence"] == card["evidencePresentation"]["primaryText"]
    assert legacy_card["retrieval_prompt"] == card["front"]["prompt"]
    assert legacy["segments"][0]["source_time"].startswith("lesson.txt · 字符 ")
    assert legacy_card["verification_status"] == "verified"
    assert legacy_card["quality"]["status"] == "recommended"
    worker = _load_worker()
    assert worker.card_front_fields(legacy_card)["front_prompt"] == card["front"]["prompt"]
    assert worker.anki_template_version("immersive_v11", "subtitle_language") == "V15"


def test_bilingual_generation_preserves_chinese_cue_and_source_backed_v15_fields(
    tmp_path,
) -> None:
    class ChineseMeaningModel(FakeDiscoveryModel):
        def propose(self, request):
            result = dict(super().propose(request))
            for proposal in result["proposals"]:
                proposal["meaningOrFunction"] = "身体或事物处于良好状态"
            return result

    runtime, project, inspected, _source = environment(
        tmp_path,
        ChineseMeaningModel(),
        routes=["production", "chunk_collocation"],
        prompt_language="zh-CN",
        answer_language="en",
    )
    discovered = discover(runtime, project, inspected)
    candidates = runtime.list_candidates(
        audience=audience(), discovery_handle=discovered["discoveryHandle"]
    )
    selected = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        idempotency_key="select-bilingual-card",
        discovery_handle=discovered["discoveryHandle"],
        operation="add",
        candidate_handles=[candidates["items"][0]["candidateHandle"]],
        budget={"maxNewCards": 1},
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-bilingual-card",
        selection_handle=selected["selectionHandle"],
    )
    plans = runtime.list_card_plans(
        audience=audience(), plan_set_handle=planned["planSetHandle"]
    )
    assert plans["items"][0]["cue"]["content"] == "表达这个意思：身体或事物处于良好状态"
    assert plans["items"][0]["expectedResponse"]["coreAnswer"] == "in good shape"

    generated = runtime.generate_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="generate-bilingual-card",
        plan_set_handle=planned["planSetHandle"],
    )
    resolved = runtime.card_artifacts.resolve_current_project_artifact(
        audience=audience(),
        project_artifact_handle=generated["projectArtifactHandle"],
    )
    envelope = resolved["cardEnvelopes"][0]
    assert envelope["payloadSchemaVersion"] == 2
    card = envelope["payload"]
    assert card["front"]["prompt"] == "表达这个意思：身体或事物处于良好状态"
    assert card["back"]["coreAnswer"] == "in good shape"
    assert card["back"]["explanation"] == "身体或事物处于良好状态"
    assert card["languageProfile"]["promptLanguage"] == "zh-CN"
    assert card["languageProfile"]["answerLanguage"] == "en"
    assert card["evidencePresentation"]["items"][0]["quote"] == "in good shape"

    legacy = resolved["legacyProjection"]["projection"]["project"]
    legacy_card = legacy["segments"][0]["cards"][0]
    worker = _load_worker()
    front = worker.card_front_fields(legacy_card)
    assert front["front_prompt"] == "表达这个意思：身体或事物处于良好状态"
    assert front["answer"] == "in good shape"
    assert legacy_card["chinese"] == "身体或事物处于良好状态"
    assert legacy_card["english"] == card["evidencePresentation"]["primaryText"]
    assert legacy_card["source_evidence"] == card["evidencePresentation"]["primaryText"]
    assert "身体或事物" not in legacy_card["source_evidence"]

    output_dir = tmp_path / "bilingual-export"
    output_dir.mkdir()
    exported = worker.handle_export(
        {"project": legacy, "output_dir": str(output_dir)}
    )
    assert exported["deck_kind"] == "subtitle_language"
    assert exported["template_version"] == "V15"
    frozen_contract = worker._legacy_worker.resolve_export_note_model_contract(
        exported["template_family"],
        exported["template_schema"],
        exported["template_name"],
    )
    assert exported["note_model_id"] == frozen_contract.note_model_id
    assert exported["note_model_contract_digest"] == frozen_contract.contract_digest
    inspected_contract = (
        worker._legacy_worker.anki_model_contracts_module.inspect_apkg_note_model_contract(
            Path(exported["apkg_path"])
        )
    )
    assert inspected_contract == {
        "contracts": [frozen_contract.public_dict()],
        "issues": [],
    }
    with zipfile.ZipFile(exported["apkg_path"]) as archive:
        collection_name = next(
            name
            for name in ("collection.anki2", "collection.anki21")
            if name in archive.namelist()
        )
        database = tmp_path / collection_name
        database.write_bytes(archive.read(collection_name))
    connection = sqlite3.connect(database)
    try:
        field_text = connection.execute("select flds from notes").fetchone()[0]
    finally:
        connection.close()
    field_names = [
        item["name"] for item in worker._legacy_worker.note_model_field_specs(True)
    ]
    note = dict(zip(field_names, field_text.split("\x1f"), strict=True))
    assert note["FrontPrompt"] == "表达这个意思：身体或事物处于良好状态"
    assert note["Answer"] == "in good shape"
    assert note["Chinese"] == "身体或事物处于良好状态"
    assert note["English"] == card["evidencePresentation"]["primaryText"]
    assert note["Context"] == card["evidencePresentation"]["primaryText"]
    mark_open = '<mark class="target-expression">'
    expected_english_display = (
        note["English"][: legacy_card["exact_span_start"]]
        + mark_open
        + "in good shape</mark>"
        + note["English"][legacy_card["exact_span_end"] :]
    )
    assert note["EnglishDisplay"] == expected_english_display
    assert note["EnglishDisplay"].count(mark_open) == 1
    assert note["EnglishDisplay"].count("</mark>") == 1
    assert (
        note["EnglishDisplay"].replace(mark_open, "").replace("</mark>", "")
        == note["English"]
    )
    locator = card["evidencePresentation"]["items"][0]["locator"]
    assert note["SourceTime"] == (
        f"lesson.txt · 字符 {locator['start']}–{locator['end']}"
    )
    assert normalize_answer_leakage_text(note["Answer"]) not in (
        normalize_answer_leakage_text(note["FrontPrompt"])
    )


def test_card_artifact_rejects_direct_answer_without_authenticated_quote(
    tmp_path,
) -> None:
    runtime, _project, _planned, _listed, result = generated_runtime(tmp_path)
    resolved = runtime.card_artifacts.resolve_current_project_artifact(
        audience=audience(),
        project_artifact_handle=result["projectArtifactHandle"],
    )
    card = resolved["cardEnvelopes"][0]["payload"]
    row = {
        "planId": card["cardPlanRef"]["entityId"],
        "planRef": card["cardPlanRef"]["artifactRef"],
        "payload": {
            "route": "production",
            "languageProfile": card["languageProfile"],
            "cue": {"content": card["front"]["prompt"]},
            "expectedResponse": {
                "coreAnswer": "in great shape",
                "scoringPoints": ["in great shape"],
                "acceptedVariants": [],
            },
            "feedback": {
                "explanation": card["back"]["explanation"],
                "examples": [],
                "nonexamples": [],
                "evidenceRefs": card["evidenceRefs"],
            },
        },
        "evidencePresentation": card["evidencePresentation"],
    }

    with pytest.raises(CardArtifactRuntimeError) as captured:
        runtime.card_artifacts._card_payload(
            row=row,
            project_revision=card["projectRevision"],
            operation_digest="f" * 64,
        )
    assert captured.value.code == "CARD_GENERATION_GRAPH_CORRUPT"
    assert "authenticated source-direct evidence quote" in captured.value.message


@pytest.mark.parametrize(
    ("core_answer", "explanation", "expected_message"),
    [
        ("in good shape 状态", "healthy or in a good condition", "target form"),
        ("in good shape", "身体或事物处于良好状态", "card meaning"),
    ],
)
def test_card_artifact_replays_language_profile_scripts(
    tmp_path, core_answer, explanation, expected_message
) -> None:
    runtime, _project, _planned, _listed, result = generated_runtime(tmp_path)
    resolved = runtime.card_artifacts.resolve_current_project_artifact(
        audience=audience(),
        project_artifact_handle=result["projectArtifactHandle"],
    )
    card = resolved["cardEnvelopes"][0]["payload"]
    row = {
        "planId": card["cardPlanRef"]["entityId"],
        "planRef": card["cardPlanRef"]["artifactRef"],
        "payload": {
            "route": "production",
            "languageProfile": card["languageProfile"],
            "cue": {"content": card["front"]["prompt"]},
            "expectedResponse": {
                "coreAnswer": core_answer,
                "scoringPoints": [core_answer],
                "acceptedVariants": [],
            },
            "feedback": {
                "explanation": explanation,
                "examples": [],
                "nonexamples": [],
                "evidenceRefs": card["evidenceRefs"],
            },
        },
        "evidencePresentation": card["evidencePresentation"],
    }

    with pytest.raises(CardArtifactRuntimeError) as captured:
        runtime.card_artifacts._card_payload(
            row=row,
            project_revision=card["projectRevision"],
            operation_digest="e" * 64,
        )
    assert captured.value.code == "CARD_GENERATION_GRAPH_CORRUPT"
    assert expected_message in captured.value.message


def test_legacy_english_reading_route_remains_generatable(tmp_path) -> None:
    class ReadingModel(FakeDiscoveryModel):
        def propose(self, request):
            result = dict(super().propose(request))
            for proposal in result["proposals"]:
                proposal["route"] = "reading_recognition"
            return result

    runtime, project, inspected, _source = environment(
        tmp_path,
        ReadingModel(),
        routes=["reading_recognition"],
        prompt_language="English",
        answer_language="English",
    )
    discovered = discover(runtime, project, inspected)
    candidates = runtime.list_candidates(
        audience=audience(), discovery_handle=discovered["discoveryHandle"]
    )
    selected = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        idempotency_key="select-reading-card",
        discovery_handle=discovered["discoveryHandle"],
        operation="add",
        candidate_handles=[candidates["items"][0]["candidateHandle"]],
        budget={"maxNewCards": 1},
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-reading-card",
        selection_handle=selected["selectionHandle"],
    )
    generated = runtime.generate_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="generate-reading-card",
        plan_set_handle=planned["planSetHandle"],
    )
    resolved = runtime.card_artifacts.resolve_current_project_artifact(
        audience=audience(),
        project_artifact_handle=generated["projectArtifactHandle"],
    )
    card = resolved["cardEnvelopes"][0]["payload"]

    assert card["route"] == "reading_recognition"
    assert card["front"]["prompt"] == "in good shape"
    assert card["back"]["coreAnswer"] == "healthy or in a good condition"
    assert card["contentOrigins"]["frontPrompt"]["kind"] == "source_direct"
    assert (
        card["contentOrigins"]["coreAnswer"]["kind"]
        == "model_reviewed_interpretation"
    )
    legacy = resolved["legacyProjection"]["projection"]["project"]
    legacy_card = legacy["segments"][0]["cards"][0]
    assert legacy_card["answer_core"] == "healthy or in a good condition"
    assert legacy_card["phrase"] == "in good shape"
    assert legacy_card["exact_span"] == "in good shape"
    assert (
        legacy_card["english"][
            legacy_card["exact_span_start"] : legacy_card["exact_span_end"]
        ]
        == "in good shape"
    )
    public_cards = runtime.list_generated_cards(
        audience=audience(),
        project_artifact_handle=generated["projectArtifactHandle"],
    )
    assert public_cards["returnedCards"] == 1
    public_card = public_cards["items"][0]
    assert public_card["contentOrigins"] == {
        "frontPrompt": "source_direct",
        "coreAnswer": "model_reviewed_interpretation",
        "explanation": "model_reviewed_interpretation",
        "sourceQuote": "source_direct",
    }
    assert public_card["front"]["prompt"] == "in good shape"
    assert public_card["back"]["coreAnswer"] == "healthy or in a good condition"


def test_generation_is_idempotent_without_duplicate_card_artifacts(tmp_path) -> None:
    runtime, project, planned, _listed = planned_runtime(tmp_path)
    arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": planned["projectRevision"],
        "idempotency_key": "generate-idempotent",
        "plan_set_handle": planned["planSetHandle"],
    }
    first = runtime.generate_cards(**arguments)
    repeated = runtime.generate_cards(**arguments)

    first_ref, _ = runtime.artifacts.resolve_with_ref(
        first["projectArtifactHandle"], audience()
    )
    repeated_ref, _ = runtime.artifacts.resolve_with_ref(
        repeated["projectArtifactHandle"], audience()
    )
    assert repeated_ref == first_ref
    assert {
        key: value for key, value in repeated.items() if key != "projectArtifactHandle"
    } == {key: value for key, value in first.items() if key != "projectArtifactHandle"}
    current = runtime.get_project(project["projectId"], audience())
    project_artifacts = [
        value
        for value in current["latestArtifactRefs"]
        if value["payloadSchema"] == "study.project-artifact"
    ]
    assert len(project_artifacts) == 1


def test_generation_fails_closed_when_one_plan_needs_review(tmp_path) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    edited = runtime.edit_card_plan(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="feedback-review-before-generate",
        plan_set_handle=planned["planSetHandle"],
        card_plan_handle=listed["items"][0]["cardPlanHandle"],
        operation={
            "kind": "edit_card_feedback",
            "feedback": {
                "explanation": "Unsupported new explanation.",
                "examples": ["A new example."],
                "nonexamples": [],
            },
        },
    )

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.generate_cards(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=edited["projectRevision"],
            idempotency_key="blocked-generation",
            plan_set_handle=edited["planSetHandle"],
        )
    assert captured.value.code == "CARD_GENERATION_PLAN_BLOCKED"
    current = runtime.get_project(project["projectId"], audience())
    assert current["workflow"]["artifactStage"] == "plans_ready"
    assert not any(
        value["payloadSchema"] == "study.project-artifact"
        for value in current["latestArtifactRefs"]
    )


def test_generation_rejects_model_media_and_path_injection_fields(tmp_path) -> None:
    runtime, project, planned, _listed = planned_runtime(tmp_path)
    with pytest.raises(TypeError):
        runtime.generate_cards(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=planned["projectRevision"],
            idempotency_key="reject-injection",
            plan_set_handle=planned["planSetHandle"],
            model_profile_ref="model.private",  # type: ignore[call-arg]
        )


def test_project_artifact_is_bound_to_audience_and_current_revision(tmp_path) -> None:
    runtime, _project, _planned, _listed, result = generated_runtime(tmp_path)
    with pytest.raises(CardArtifactRuntimeError):
        runtime.card_artifacts.resolve_current_project_artifact(
            audience=audience(session_id="session-other"),
            project_artifact_handle=result["projectArtifactHandle"],
        )


def test_persisted_generation_graph_contains_no_raw_path_or_credentials(
    tmp_path,
) -> None:
    runtime, _project, _planned, _listed, result = generated_runtime(tmp_path)
    resolved = runtime.card_artifacts.resolve_current_project_artifact(
        audience=audience(),
        project_artifact_handle=result["projectArtifactHandle"],
    )
    encoded = json.dumps(resolved["projectArtifact"], ensure_ascii=False).casefold()
    for forbidden in (
        "apikey",
        "access_token",
        "authorization",
        "e:\\",
        "c:\\users",
        "lesson.txt",
    ):
        assert forbidden not in encoded


def _load_worker():
    path = Path(__file__).resolve().parents[1] / "workers" / "anki_worker.py"
    spec = importlib.util.spec_from_file_location(
        "anki_worker_card_artifact_projection_tests", path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_legacy_projection_exports_through_the_real_apkg_worker(tmp_path) -> None:
    runtime, _project, _planned, _listed, result = generated_runtime(tmp_path)
    resolved = runtime.card_artifacts.resolve_current_project_artifact(
        audience=audience(),
        project_artifact_handle=result["projectArtifactHandle"],
    )
    legacy_project = resolved["legacyProjection"]["projection"]["project"]
    output_dir = tmp_path / "export"
    output_dir.mkdir()

    exported = _load_worker().handle_export(
        {"project": legacy_project, "output_dir": str(output_dir)}
    )

    apkg_path = Path(exported["apkg_path"])
    assert apkg_path.is_file()
    assert apkg_path.resolve().is_relative_to(output_dir.resolve())
    assert exported["cards"] == 1
    assert exported["deck_kind"] == "subtitle_language"
    assert exported["template_version"] == "V15"


def test_public_card_query_keeps_legacy_v1_artifacts_readable() -> None:
    result = CardArtifactQueryRuntime._public_card(
        "study_" + "A" * 43,
        {
            "payloadSchemaVersion": 1,
            "payload": {
                "cardId": "card_legacy_v1",
                "route": "production",
                "front": {"modality": "text", "prompt": "Intended function: healthy"},
                "back": {
                    "coreAnswer": "in good shape",
                    "explanation": "healthy",
                    "examples": [],
                    "nonexamples": [],
                },
                "scoring": {
                    "points": ["in good shape"],
                    "acceptedVariants": [],
                    "singleRecallTarget": True,
                },
                "evidenceRefs": [{"legacy": True}],
                "mediaRefs": [],
                "verification": {"state": "verified", "ruleSetVersion": "v1"},
                "generation": {"mode": "deterministic_projection"},
            },
        },
    )

    assert result["artifactSchemaVersion"] == 1
    assert result["back"]["coreAnswer"] == "in good shape"
    assert "languageProfile" not in result


def test_generation_recovers_after_work_unit_completion_before_task_success(
    tmp_path,
) -> None:
    runtime, project, planned, _listed = planned_runtime(tmp_path)
    original = runtime.tasks.succeed_task
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise StudyTaskError(
                "SIMULATED_INTERRUPTION", "simulated generation interruption"
            )
        return original(*args, **kwargs)

    runtime.tasks.succeed_task = fail_once
    arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": planned["projectRevision"],
        "idempotency_key": "recover-completed-generation",
        "plan_set_handle": planned["planSetHandle"],
    }
    with pytest.raises(StudyRuntimeError) as interrupted:
        runtime.generate_cards(**arguments)
    assert interrupted.value.code == "SIMULATED_INTERRUPTION"

    runtime.tasks.succeed_task = original
    recovered = runtime.generate_cards(**arguments)
    assert recovered["artifactStage"] == "cards_ready"
    task = runtime.tasks.get_task(recovered["taskId"], audience())
    assert task["state"] == "succeeded"


def test_generation_recovers_after_task_success_before_project_commit(tmp_path) -> None:
    runtime, project, planned, _listed = planned_runtime(tmp_path)
    original = runtime.projects.commit_artifact_stage
    failed = False

    def fail_once(**kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise ProjectRegistryError(
                "SIMULATED_COMMIT_INTERRUPTION",
                "simulated generation commit interruption",
            )
        return original(**kwargs)

    runtime.projects.commit_artifact_stage = fail_once
    arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": planned["projectRevision"],
        "idempotency_key": "recover-succeeded-generation",
        "plan_set_handle": planned["planSetHandle"],
    }
    with pytest.raises(StudyRuntimeError) as interrupted:
        runtime.generate_cards(**arguments)
    assert interrupted.value.code == "SIMULATED_COMMIT_INTERRUPTION"

    runtime.projects.commit_artifact_stage = original
    recovered = runtime.generate_cards(**arguments)
    assert recovered["artifactStage"] == "cards_ready"
    assert recovered["projectRevision"] == planned["projectRevision"] + 1


def test_generated_cards_are_reviewable_through_authenticated_pagination(
    tmp_path,
) -> None:
    runtime, project, _discovered, selected, _source = _selection_for_card_planning(
        tmp_path,
        FakeDiscoveryModel(proposal_count=2),
        candidate_count=2,
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-two-reviewable-cards",
        selection_handle=selected["selectionHandle"],
    )
    generated = runtime.generate_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="generate-two-reviewable-cards",
        plan_set_handle=planned["planSetHandle"],
    )

    first = runtime.list_generated_cards(
        audience=audience(),
        project_artifact_handle=generated["projectArtifactHandle"],
        limit=1,
    )
    second = runtime.list_generated_cards(
        audience=audience(),
        project_artifact_handle=generated["projectArtifactHandle"],
        cursor=first["nextCursor"],
        limit=1,
    )

    assert first["totalCards"] == 2
    assert first["returnedCards"] == 1
    assert second["returnedCards"] == 1
    assert second["nextCursor"] is None
    assert first["items"][0]["cardId"] != second["items"][0]["cardId"]
    for item in [*first["items"], *second["items"]]:
        assert item["verification"]["state"] == "verified"
        assert item["mediaRoles"] == []
        assert item["front"]["prompt"]
        assert item["back"]["coreAnswer"] == "in good shape"
        encoded = json.dumps(item, ensure_ascii=False).casefold()
        for forbidden in (
            "artifactref",
            "registryauthref",
            "evidenceref",
            "inputfingerprint",
            "e:\\",
        ):
            assert forbidden not in encoded
        assert item["evidencePresentation"]["items"][0]["sourceDisplayName"] == "lesson.txt"
        public_locator = item["evidencePresentation"]["items"][0]["locator"]
        assert "nodeId" not in public_locator
        assert "start" not in public_locator
        assert "end" not in public_locator

    cursor = first["nextCursor"]
    replacement = "A" if cursor[-1] != "A" else "B"
    with pytest.raises(StudyRuntimeError) as tampered:
        runtime.list_generated_cards(
            audience=audience(),
            project_artifact_handle=generated["projectArtifactHandle"],
            cursor=cursor[:-1] + replacement,
            limit=1,
        )
    assert tampered.value.code == "CARD_CURSOR_INVALID"
