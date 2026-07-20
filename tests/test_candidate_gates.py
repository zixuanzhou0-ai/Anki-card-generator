from __future__ import annotations

import hashlib

import pytest

from card_service.candidate_gates import CandidateGateError, evaluate_language_candidate


TEXT = "And finally, if someone is in good shape, they're in a good state of health."
FORM = "in good shape"
START = TEXT.index(FORM)
END = START + len(FORM)
NODE_ID = "node_source_0001"


def artifact_ref(**changes):
    value = {
        "artifactId": "representation_1",
        "projectId": "project_1",
        "projectRevision": 3,
        "artifactRevision": 1,
        "payloadSchema": "study.source-representation",
        "payloadSchemaVersion": 1,
        "artifactDigest": hashlib.sha256(b"representation").hexdigest(),
        "registryAuthRef": "registry_1",
    }
    value.update(changes)
    return value


def source_ref():
    return artifact_ref(
        artifactId="source_1",
        projectRevision=2,
        payloadSchema="study.source-asset",
        artifactDigest=hashlib.sha256(b"source").hexdigest(),
    )


def representation_payload(text=TEXT):
    return {
        "representationId": "representation_1",
        "sourceId": "source_1",
        "sourceRef": source_ref(),
        "kind": "plain_text",
        "plainTextBlobRef": {
            "blobId": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "sizeBytes": len(text.encode()),
            "mediaType": "text/plain",
        },
        "contentNodes": [
            {
                "nodeId": NODE_ID,
                "sourceId": "source_1",
                "order": 0,
                "kind": "paragraph",
                "locator": {
                    "kind": "text_span",
                    "nodeId": NODE_ID,
                    "start": 0,
                    "end": len(text),
                },
                "extractionConfidence": 1.0,
                "attributes": {"textStart": 0, "textEnd": len(text)},
            }
        ],
    }


def proposal(**changes):
    value = {
        "language": "en",
        "form": FORM,
        "formType": "phrase",
        "meaningOrFunction": "身体或事物处于良好状态",
        "route": "production",
        "spans": [{"nodeId": NODE_ID, "start": START, "end": END}],
    }
    value.update(changes)
    return value


def inspection(**changes):
    value = {"sourceId": "source_1", "supportTier": "A", "status": "ready"}
    value.update(changes)
    return value


def contract(**changes):
    value = {
        "contractRevision": 1,
        "routes": ["production", "reading_recognition"],
        "exclusions": [],
    }
    value.update(changes)
    return value


def assessments(**changes):
    value = {
        "semanticEvidence": "verified",
        "duplicate": "unique",
        "conflict": "clear",
        "learnerFit": "new",
    }
    value.update(changes)
    return value


def evaluate(**changes):
    arguments = {
        "proposal": proposal(),
        "representation_ref": artifact_ref(),
        "representation_payload": representation_payload(),
        "representation_text": TEXT,
        "source_inspection": inspection(),
        "learning_contract": contract(),
        "trusted_assessments": assessments(),
        "project_revision": 3,
        "input_fingerprint": hashlib.sha256(b"input").hexdigest(),
        "evaluated_at": "2026-07-18T12:00:00.000Z",
    }
    arguments.update(changes)
    return evaluate_language_candidate(**arguments)


def gate(result, name):
    return next(value for value in result["gateEvaluation"]["results"] if value["gate"] == name)


def test_verified_phrase_derives_recommended_candidate_and_replayable_evidence() -> None:
    result = evaluate()

    assert result["gateEvaluation"]["derivedEligibility"] == "recommended"
    assert len(result["gateEvaluation"]["results"]) == 8
    assert {value["state"] for value in result["gateEvaluation"]["results"]} == {"pass"}
    evidence = result["evidenceAnchors"][0]
    assert evidence["locator"] == {
        "kind": "text_span",
        "nodeId": NODE_ID,
        "start": START,
        "end": END,
    }
    assert evidence["quoteSha256"] == hashlib.sha256(FORM.encode()).hexdigest()
    assert "quote" not in evidence
    assert result["objective"]["scoringBoundary"] == [FORM]
    assert result["objective"]["granularity"]["independentScorePoints"] == 1


def test_pdf_page_locator_is_preserved_in_candidate_evidence() -> None:
    payload = representation_payload()
    payload["kind"] = "pdf_text_layer"
    payload["contentNodes"][0]["locator"]["pageNumber"] = 7
    payload["contentNodes"][0]["attributes"]["pageNumber"] = 7

    result = evaluate(representation_payload=payload)

    assert result["evidenceAnchors"][0]["locator"]["pageNumber"] == 7


def test_model_cannot_submit_eligibility_scores_or_unknown_fields() -> None:
    with pytest.raises(CandidateGateError) as captured:
        evaluate(proposal={**proposal(), "eligibility": "recommended"})
    assert captured.value.code == "CANDIDATE_SCHEMA_INVALID"


@pytest.mark.parametrize(
    "span,reason",
    [
        ({"nodeId": "node_missing", "start": START, "end": END}, "EVIDENCE_NODE_NOT_FOUND"),
        ({"nodeId": NODE_ID, "start": START + 1, "end": END}, "EVIDENCE_FORM_MISMATCH"),
        ({"nodeId": NODE_ID, "start": 0, "end": len(TEXT) + 1}, "EVIDENCE_SPAN_OUTSIDE_NODE"),
    ],
)
def test_invalid_evidence_span_is_hard_blocked(span, reason) -> None:
    result = evaluate(proposal=proposal(spans=[span]))
    assert result["gateEvaluation"]["derivedEligibility"] == "hard_blocked"
    assert gate(result, "evidence")["state"] == "fail"
    assert gate(result, "evidence")["reasonCode"] == reason
    assert result["evidenceAnchors"] == []
    assert result["semanticUnit"]["exactEvidenceIds"] == []


def test_grammar_multi_anchor_requires_ordered_non_overlapping_exact_frame() -> None:
    text = "She is not only calm but also remarkably precise."
    first = "not only"
    second = "but also"
    first_start = text.index(first)
    second_start = text.index(second)
    payload = representation_payload(text)
    result = evaluate(
        proposal=proposal(
            form="not only … but also",
            formType="grammar",
            route="grammar_cloze",
            meaningOrFunction="连接两个并列且递进的成分",
            spans=[
                {"nodeId": NODE_ID, "start": first_start, "end": first_start + len(first)},
                {"nodeId": NODE_ID, "start": second_start, "end": second_start + len(second)},
            ],
        ),
        representation_payload=payload,
        representation_text=text,
        learning_contract=contract(routes=["grammar_cloze"]),
    )
    assert gate(result, "evidence")["state"] == "pass"
    assert result["gateEvaluation"]["derivedEligibility"] == "recommended"
    assert len(result["evidenceAnchors"]) == 2


def test_route_outside_learning_contract_is_excluded() -> None:
    result = evaluate(learning_contract=contract(routes=["reading_recognition"]))
    assert gate(result, "goal_relevance")["reasonCode"] == "GOAL_ROUTE_NOT_ALLOWED"
    assert result["gateEvaluation"]["derivedEligibility"] == "excluded"


def test_exact_project_exclusion_is_not_overridden_by_model_value() -> None:
    result = evaluate(learning_contract=contract(exclusions=[FORM]))
    assert gate(result, "goal_relevance")["reasonCode"] == "GOAL_EXPLICITLY_EXCLUDED"
    assert result["gateEvaluation"]["derivedEligibility"] == "excluded"


@pytest.mark.parametrize(
    "trusted,expected_reason",
    [
        (assessments(duplicate="duplicate"), "NOVELTY_EXACT_DUPLICATE"),
        (assessments(learnerFit="known"), "NOVELTY_LEARNER_ALREADY_KNOWS"),
    ],
)
def test_duplicate_or_known_candidate_is_not_selectable(trusted, expected_reason) -> None:
    result = evaluate(trusted_assessments=trusted)
    assert gate(result, "novelty")["reasonCode"] == expected_reason
    assert result["gateEvaluation"]["derivedEligibility"] == "duplicate"


def test_unknown_relation_or_semantic_review_never_becomes_recommended() -> None:
    result = evaluate(
        trusted_assessments=assessments(
            semanticEvidence="review", duplicate="unknown", conflict="unknown", learnerFit="unknown"
        )
    )
    assert result["gateEvaluation"]["derivedEligibility"] == "needs_review"
    assert gate(result, "evidence")["state"] == "review"
    assert gate(result, "novelty")["state"] == "review"
    assert gate(result, "conflict")["state"] == "review"


def test_tier_b_source_needs_review_and_tier_c_is_hard_blocked() -> None:
    conditional = evaluate(source_inspection=inspection(supportTier="B", status="conditional"))
    blocked = evaluate(source_inspection=inspection(supportTier="C", status="blocked"))
    assert conditional["gateEvaluation"]["derivedEligibility"] == "needs_review"
    assert gate(conditional, "evidence")["state"] == "review"
    assert blocked["gateEvaluation"]["derivedEligibility"] == "hard_blocked"
    assert gate(blocked, "evidence")["state"] == "fail"


@pytest.mark.parametrize(
    "form",
    [
        "https://example.com/private",
        "C:\\private\\lesson.txt",
        "sk-abcdefghijklmnopqrstuvwxyz012345",
    ],
)
def test_secret_url_or_path_candidate_is_security_hard_blocked(form: str) -> None:
    text = f"Use {form} here."
    start = text.index(form)
    result = evaluate(
        proposal=proposal(form=form, spans=[{"nodeId": NODE_ID, "start": start, "end": start + len(form)}]),
        representation_payload=representation_payload(text),
        representation_text=text,
    )
    assert gate(result, "security")["state"] == "fail"
    assert result["gateEvaluation"]["derivedEligibility"] == "hard_blocked"


def test_pronunciation_and_contrast_require_specialized_review() -> None:
    pronunciation = evaluate(
        proposal=proposal(formType="pronunciation", route="pronunciation"),
        learning_contract=contract(routes=["pronunciation"]),
    )
    contrast = evaluate(
        proposal=proposal(route="contrast"),
        learning_contract=contract(routes=["contrast"]),
    )
    assert gate(pronunciation, "scoreability")["state"] == "review"
    assert gate(contrast, "card_suitability")["state"] == "review"
    assert pronunciation["gateEvaluation"]["derivedEligibility"] == "needs_review"
    assert contrast["gateEvaluation"]["derivedEligibility"] == "needs_review"


def test_candidate_ids_and_results_are_deterministic_for_same_frozen_inputs() -> None:
    first = evaluate()
    second = evaluate()
    assert first == second


def test_project_scope_and_source_identity_mismatches_fail_closed() -> None:
    with pytest.raises(CandidateGateError) as wrong_project:
        evaluate(representation_ref=artifact_ref(projectId="other_project"))
    assert wrong_project.value.code == "CANDIDATE_SOURCE_INVALID"

    with pytest.raises(CandidateGateError) as wrong_source:
        evaluate(source_inspection=inspection(sourceId="other_source"))
    assert wrong_source.value.code == "CANDIDATE_SOURCE_INVALID"
