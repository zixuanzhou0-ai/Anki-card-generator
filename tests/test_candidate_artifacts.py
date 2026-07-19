from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding, ArtifactRegistry
from card_service.candidate_artifacts import (
    CandidateArtifactError,
    CandidateArtifactPublisher,
)
from card_service.candidate_gates import evaluate_language_candidate


KEY = bytes(range(32))
OWNER = hashlib.sha256(b"owner").hexdigest()
TEXT = "Use in good shape when something remains in a good condition."
FORM = "in good shape"
START = TEXT.index(FORM)
END = START + len(FORM)
NODE = "node_1"


def audience(**changes):
    values = {
        "owner_digest": OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


def environment(tmp_path: Path):
    artifacts = ArtifactRegistry(
        tmp_path / "artifacts",
        authentication_key=KEY,
        service_instance_id="service-1",
    )
    bound = audience()
    fingerprint = hashlib.sha256(b"input").hexdigest()
    source = artifacts.publish(
        audience=bound,
        project_id="project_1",
        project_revision=2,
        artifact_id="source_1",
        artifact_revision=1,
        payload_schema="study.source-asset",
        payload_schema_version=1,
        payload={
            "sourceId": "source_1",
            "contentSha256": hashlib.sha256(TEXT.encode()).hexdigest(),
        },
        producer={"component": "test", "version": "1"},
        parents=[],
        input_fingerprint=fingerprint,
        completeness={
            "state": "complete",
            "processedUnits": 1,
            "omittedLocators": [],
            "reasonCodes": [],
        },
        issue_refs=[],
    )
    representation_payload = {
        "representationId": "representation_1",
        "sourceId": "source_1",
        "sourceRef": dict(source.artifact_ref),
        "kind": "plain_text",
        "plainTextBlobRef": artifacts.put_blob(TEXT.encode(), media_type="text/plain"),
        "contentNodes": [
            {
                "nodeId": NODE,
                "sourceId": "source_1",
                "order": 0,
                "kind": "paragraph",
                "locator": {
                    "kind": "text_span",
                    "nodeId": NODE,
                    "start": 0,
                    "end": len(TEXT),
                },
                "extractionConfidence": 1.0,
                "attributes": {"textStart": 0, "textEnd": len(TEXT)},
            }
        ],
    }
    representation = artifacts.publish(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        artifact_id="representation_1",
        artifact_revision=1,
        payload_schema="study.source-representation",
        payload_schema_version=1,
        payload=representation_payload,
        producer={"component": "test", "version": "1"},
        parents=[source.artifact_ref],
        input_fingerprint=fingerprint,
        completeness={
            "state": "complete",
            "processedUnits": 1,
            "omittedLocators": [],
            "reasonCodes": [],
        },
        issue_refs=[],
    )
    inspection = artifacts.publish(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        artifact_id="inspection_1",
        artifact_revision=1,
        payload_schema="study.inspection",
        payload_schema_version=1,
        payload={
            "inspectionId": "inspection_1",
            "sourceRefs": [dict(source.artifact_ref)],
            "representationRefs": [dict(representation.artifact_ref)],
            "completeness": {
                "state": "complete",
                "processedUnits": 1,
                "omittedLocators": [],
                "reasonCodes": [],
            },
        },
        producer={"component": "test", "version": "1"},
        parents=[representation.artifact_ref],
        input_fingerprint=fingerprint,
        completeness={
            "state": "complete",
            "processedUnits": 1,
            "omittedLocators": [],
            "reasonCodes": [],
        },
        issue_refs=[],
    )
    return (
        artifacts,
        CandidateArtifactPublisher(artifacts),
        bound,
        fingerprint,
        representation,
        representation_payload,
        inspection,
    )


def draft(
    representation, payload, fingerprint, *, trusted_changes=None, **proposal_changes
):
    proposal = {
        "language": "en",
        "form": FORM,
        "formType": "phrase",
        "meaningOrFunction": "状态良好",
        "route": "production",
        "spans": [{"nodeId": NODE, "start": START, "end": END}],
    }
    proposal.update(proposal_changes)
    trusted = {
        "semanticEvidence": "verified",
        "duplicate": "unique",
        "conflict": "clear",
        "learnerFit": "new",
    }
    trusted.update(trusted_changes or {})
    return evaluate_language_candidate(
        proposal=proposal,
        representation_ref=representation.artifact_ref,
        representation_payload=payload,
        representation_text=(
            TEXT if proposal["form"] == FORM else f"Use {proposal['form']} here."
        ),
        source_inspection={
            "sourceId": "source_1",
            "supportTier": "A",
            "status": "ready",
        },
        learning_contract={
            "contractRevision": 1,
            "routes": ["production"],
            "exclusions": [],
        },
        trusted_assessments=trusted,
        project_revision=3,
        input_fingerprint=fingerprint,
        evaluated_at="2026-07-18T12:00:00.000Z",
    )


def test_candidate_and_gate_publish_as_acyclic_authenticated_graph(
    tmp_path: Path,
) -> None:
    artifacts, publisher, bound, fingerprint, representation, payload, _ = environment(
        tmp_path
    )
    result = publisher.publish_candidate(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        input_fingerprint=fingerprint,
        draft=draft(representation, payload, fingerprint),
    )

    assert result["eligibility"] == "recommended"
    assert result["suppressed"] is False
    candidate = artifacts.verify_ref(result["candidateRef"], bound)
    gate = artifacts.verify_ref(result["gateEvaluationRef"], bound)
    assert candidate["payloadSchema"] == "study.candidate-proposal"
    assert "gateEvaluationRef" not in candidate["payload"]
    assert gate["parents"] == [result["candidateRef"]]
    assert gate["payload"]["candidateRef"] == {
        "artifactRef": result["candidateRef"],
        "entityId": result["candidateId"],
    }
    evidence_ref = gate["payload"]["results"][0]["evidenceRefs"][0]
    assert evidence_ref["artifactRef"] == result["candidateRef"]


def test_exact_retry_reissues_handles_without_republishing_artifacts(
    tmp_path: Path,
) -> None:
    _, publisher, bound, fingerprint, representation, payload, _ = environment(tmp_path)
    arguments = {
        "audience": bound,
        "project_id": "project_1",
        "project_revision": 3,
        "input_fingerprint": fingerprint,
        "draft": draft(representation, payload, fingerprint),
    }
    first = publisher.publish_candidate(**arguments)
    second = publisher.publish_candidate(**arguments)
    assert first["candidateRef"] == second["candidateRef"]
    assert first["gateEvaluationRef"] == second["gateEvaluationRef"]
    assert first["candidateHandle"] != second["candidateHandle"]


@pytest.mark.parametrize(
    "unsafe",
    [
        "C:\\private\\lesson.txt",
        "https://example.com/private",
        "sk-abcdefghijklmnopqrstuvwxyz012345",
    ],
)
def test_security_failed_proposal_is_redacted_before_artifact_persistence(
    tmp_path: Path, unsafe: str
) -> None:
    artifacts, publisher, bound, fingerprint, representation, payload, _ = environment(
        tmp_path
    )
    unsafe_text = f"Use {unsafe} here."
    unsafe_payload = dict(payload)
    unsafe_payload["contentNodes"] = [
        {
            **payload["contentNodes"][0],
            "locator": {
                **payload["contentNodes"][0]["locator"],
                "end": len(unsafe_text),
            },
            "attributes": {"textStart": 0, "textEnd": len(unsafe_text)},
        }
    ]
    value = evaluate_language_candidate(
        proposal={
            "language": "en",
            "form": unsafe,
            "formType": "phrase",
            "meaningOrFunction": "sensitive material",
            "route": "production",
            "spans": [{"nodeId": NODE, "start": 4, "end": 4 + len(unsafe)}],
        },
        representation_ref=representation.artifact_ref,
        representation_payload=unsafe_payload,
        representation_text=unsafe_text,
        source_inspection={
            "sourceId": "source_1",
            "supportTier": "A",
            "status": "ready",
        },
        learning_contract={
            "contractRevision": 1,
            "routes": ["production"],
            "exclusions": [],
        },
        trusted_assessments={
            "semanticEvidence": "verified",
            "duplicate": "unique",
            "conflict": "clear",
            "learnerFit": "new",
        },
        project_revision=3,
        input_fingerprint=fingerprint,
        evaluated_at="2026-07-18T12:00:00.000Z",
    )
    published = publisher.publish_candidate(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        input_fingerprint=fingerprint,
        draft=value,
    )
    candidate = artifacts.verify_ref(published["candidateRef"], bound)
    gate = artifacts.verify_ref(published["gateEvaluationRef"], bound)
    assert published["suppressed"] is True
    assert candidate["payloadSchema"] == "study.candidate-rejection"
    assert "semanticUnit" not in candidate["payload"]
    assert "objective" not in candidate["payload"]
    assert unsafe not in str(candidate)
    assert unsafe not in str(gate)
    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "artifacts").rglob("*.json")
    )
    assert unsafe not in persisted


def test_discovery_summary_joins_candidate_and_gate_refs_without_cycles(
    tmp_path: Path,
) -> None:
    artifacts, publisher, bound, fingerprint, representation, payload, inspection = (
        environment(tmp_path)
    )
    candidate = publisher.publish_candidate(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        input_fingerprint=fingerprint,
        draft=draft(representation, payload, fingerprint),
    )
    discovery = publisher.publish_discovery(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        input_fingerprint=fingerprint,
        inspection_ref=inspection.artifact_ref,
        candidates=[candidate],
    )
    envelope = artifacts.verify_ref(discovery["discoveryRef"], bound)
    assert discovery["counts"]["recommended"] == 1
    assert envelope["payloadSchema"] == "study.discovery"
    assert envelope["payload"]["candidateRefs"] == [
        {"artifactRef": candidate["candidateRef"], "entityId": candidate["candidateId"]}
    ]
    assert envelope["payload"]["gateEvaluationRefs"] == [candidate["gateEvaluationRef"]]
    assert envelope["parents"] == [
        inspection.artifact_ref,
        candidate["candidateRef"],
        candidate["gateEvaluationRef"],
    ]


def test_discovery_without_recommended_candidates_declares_issue(
    tmp_path: Path,
) -> None:
    artifacts, publisher, bound, fingerprint, representation, payload, inspection = (
        environment(tmp_path)
    )
    value = draft(
        representation,
        payload,
        fingerprint,
        trusted_changes={"duplicate": "unknown"},
    )
    candidate = publisher.publish_candidate(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        input_fingerprint=fingerprint,
        draft=value,
    )
    discovery = publisher.publish_discovery(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        input_fingerprint=fingerprint,
        inspection_ref=inspection.artifact_ref,
        candidates=[candidate],
    )
    assert discovery["issueCodes"] == ["DISCOVERY_NO_RECOMMENDED_CANDIDATES"]
    envelope = artifacts.verify_ref(discovery["discoveryRef"], bound)
    assert envelope["completeness"]["state"] == "complete"
    assert envelope["completeness"]["reasonCodes"] == []
    assert envelope["issueRefs"] == discovery["issueCodes"]


def test_cross_project_or_tampered_graph_is_rejected(tmp_path: Path) -> None:
    _, publisher, bound, fingerprint, representation, payload, inspection = environment(
        tmp_path
    )
    with pytest.raises(CandidateArtifactError):
        publisher.publish_candidate(
            audience=bound,
            project_id="other_project",
            project_revision=3,
            input_fingerprint=fingerprint,
            draft=draft(representation, payload, fingerprint),
        )
    candidate = publisher.publish_candidate(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        input_fingerprint=fingerprint,
        draft=draft(representation, payload, fingerprint),
    )
    tampered = {**candidate, "eligibility": "excluded"}
    with pytest.raises(CandidateArtifactError):
        publisher.publish_discovery(
            audience=bound,
            project_id="project_1",
            project_revision=3,
            input_fingerprint=fingerprint,
            inspection_ref=inspection.artifact_ref,
            candidates=[tampered],
        )


def test_publisher_rejects_tampered_eligibility_or_quote_digest(tmp_path: Path) -> None:
    _, publisher, bound, fingerprint, representation, payload, _ = environment(tmp_path)
    changed_eligibility = draft(representation, payload, fingerprint)
    changed_eligibility["gateEvaluation"]["derivedEligibility"] = "excluded"
    with pytest.raises(CandidateArtifactError):
        publisher.publish_candidate(
            audience=bound,
            project_id="project_1",
            project_revision=3,
            input_fingerprint=fingerprint,
            draft=changed_eligibility,
        )

    changed_quote = draft(representation, payload, fingerprint)
    changed_quote["evidenceAnchors"][0]["quoteSha256"] = hashlib.sha256(
        b"other"
    ).hexdigest()
    with pytest.raises(CandidateArtifactError):
        publisher.publish_candidate(
            audience=bound,
            project_id="project_1",
            project_revision=3,
            input_fingerprint=fingerprint,
            draft=changed_quote,
        )


def test_publisher_replays_evidence_against_authenticated_representation_not_draft_input(
    tmp_path: Path,
) -> None:
    _, publisher, bound, fingerprint, representation, payload, _ = environment(tmp_path)
    forged_text = "Use a forged form here."
    forged = evaluate_language_candidate(
        proposal={
            "language": "en",
            "form": "a forged form",
            "formType": "phrase",
            "meaningOrFunction": "伪造",
            "route": "production",
            "spans": [{"nodeId": NODE, "start": 4, "end": 17}],
        },
        representation_ref=representation.artifact_ref,
        representation_payload={
            **payload,
            "contentNodes": [
                {
                    **payload["contentNodes"][0],
                    "locator": {
                        **payload["contentNodes"][0]["locator"],
                        "end": len(forged_text),
                    },
                    "attributes": {"textStart": 0, "textEnd": len(forged_text)},
                }
            ],
        },
        representation_text=forged_text,
        source_inspection={
            "sourceId": "source_1",
            "supportTier": "A",
            "status": "ready",
        },
        learning_contract={
            "contractRevision": 1,
            "routes": ["production"],
            "exclusions": [],
        },
        trusted_assessments={
            "semanticEvidence": "verified",
            "duplicate": "unique",
            "conflict": "clear",
            "learnerFit": "new",
        },
        project_revision=3,
        input_fingerprint=fingerprint,
        evaluated_at="2026-07-18T12:00:00.000Z",
    )
    with pytest.raises(CandidateArtifactError):
        publisher.publish_candidate(
            audience=bound,
            project_id="project_1",
            project_revision=3,
            input_fingerprint=fingerprint,
            draft=forged,
        )


def test_stale_fingerprint_or_wrong_candidate_entity_is_rejected(
    tmp_path: Path,
) -> None:
    _, publisher, bound, fingerprint, representation, payload, inspection = environment(
        tmp_path
    )
    stale_fingerprint = hashlib.sha256(b"stale-input").hexdigest()
    with pytest.raises(CandidateArtifactError):
        publisher.publish_candidate(
            audience=bound,
            project_id="project_1",
            project_revision=3,
            input_fingerprint=stale_fingerprint,
            draft=draft(representation, payload, stale_fingerprint),
        )

    candidate = publisher.publish_candidate(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        input_fingerprint=fingerprint,
        draft=draft(representation, payload, fingerprint),
    )
    with pytest.raises(CandidateArtifactError):
        publisher.publish_discovery(
            audience=bound,
            project_id="project_1",
            project_revision=3,
            input_fingerprint=stale_fingerprint,
            inspection_ref=inspection.artifact_ref,
            candidates=[candidate],
        )
    with pytest.raises(CandidateArtifactError):
        publisher.publish_discovery(
            audience=bound,
            project_id="project_1",
            project_revision=3,
            input_fingerprint=fingerprint,
            inspection_ref=inspection.artifact_ref,
            candidates=[{**candidate, "candidateId": "candidate_wrong"}],
        )
