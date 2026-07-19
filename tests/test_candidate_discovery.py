from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding, ArtifactRegistry
from card_service.candidate_discovery import (
    CandidateDiscoveryEngine,
    CandidateDiscoveryError,
    CandidateDiscoveryModelIdentity,
    PROPOSAL_ROLE_VERSION,
    REVIEW_ROLE_VERSION,
)

KEY = bytes(range(32))
OWNER = hashlib.sha256(b"owner").hexdigest()
TEXT = (
    "Use in good shape when something remains in good condition. "
    "Staying in good shape takes work."
)
FORM = "in good shape"
FIRST = TEXT.index(FORM)
SECOND = TEXT.index(FORM, FIRST + 1)
NODE = "node_1"


def audience() -> ArtifactAudienceBinding:
    return ArtifactAudienceBinding(
        owner_digest=OWNER,
        host_id="codex-desktop",
        plugin_id="speakright.study",
        session_id="session-1",
    )


def completeness(count: int = 1) -> dict[str, Any]:
    return {
        "state": "complete",
        "expectedUnits": count,
        "processedUnits": count,
        "omittedLocators": [],
        "reasonCodes": [],
    }


def environment(tmp_path: Path, *, text: str = TEXT):
    artifacts = ArtifactRegistry(
        tmp_path / "artifacts",
        authentication_key=KEY,
        service_instance_id="service-1",
    )
    bound = audience()
    inspection_fingerprint = hashlib.sha256(b"inspection-input").hexdigest()
    discovery_fingerprint = hashlib.sha256(
        b"discovery-input-with-model-binding"
    ).hexdigest()
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
            "contentSha256": hashlib.sha256(text.encode()).hexdigest(),
        },
        producer={"component": "test", "version": "1"},
        parents=[],
        input_fingerprint=inspection_fingerprint,
        completeness=completeness(),
        issue_refs=[],
    )
    representation_payload = {
        "representationId": "representation_1",
        "sourceId": "source_1",
        "sourceRef": dict(source.artifact_ref),
        "kind": "plain_text",
        "plainTextBlobRef": artifacts.put_blob(text.encode(), media_type="text/plain"),
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
                    "end": len(text),
                },
                "extractionConfidence": 1.0,
                "attributes": {"textStart": 0, "textEnd": len(text)},
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
        input_fingerprint=inspection_fingerprint,
        completeness=completeness(),
        issue_refs=[],
    )
    source_inspection = artifacts.publish(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        artifact_id="inspection_source_1",
        artifact_revision=1,
        payload_schema="study.source-inspection",
        payload_schema_version=1,
        payload={
            "inspectionId": "inspection_source_1",
            "sourceId": "source_1",
            "sourceRef": dict(source.artifact_ref),
            "status": "ready",
            "supportTier": "A",
            "representationRefs": [dict(representation.artifact_ref)],
            "contentNodeCount": 1,
            "issueRefs": [],
        },
        producer={"component": "test", "version": "1"},
        parents=[representation.artifact_ref],
        input_fingerprint=inspection_fingerprint,
        completeness=completeness(),
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
            "sourceInspectionRefs": [dict(source_inspection.artifact_ref)],
            "supportTiers": {"source_1": "A"},
            "completeness": completeness(),
        },
        producer={"component": "test", "version": "1"},
        parents=[source_inspection.artifact_ref],
        input_fingerprint=inspection_fingerprint,
        completeness=completeness(),
        issue_refs=[],
    )
    contract = {
        "contractRevision": 1,
        "purpose": "Learn reusable spoken English",
        "targetBehavior": "Recall and use the expression",
        "routes": ["production", "reading_recognition"],
        "exclusions": [],
        "evidencePolicy": "automatic",
        "budget": {"maxNewCards": 20},
    }
    return artifacts, bound, discovery_fingerprint, inspection, contract


def proposal(
    *, start: int = FIRST, form: str = FORM, extra: Mapping[str, Any] | None = None
):
    value = {
        "representationId": "representation_1",
        "language": "en",
        "form": form,
        "formType": "phrase",
        "meaningOrFunction": "healthy or in a good condition",
        "route": "production",
        "spans": [{"nodeId": NODE, "start": start, "end": start + len(FORM)}],
    }
    value.update(dict(extra or {}))
    return value


class FakeModel:
    def __init__(self, proposals, *, review_mode: str = "complete") -> None:
        self.identity = CandidateDiscoveryModelIdentity(
            profile_ref="profile_model",
            configuration_fingerprint=hashlib.sha256(b"model-config").hexdigest(),
            credential_revision=3,
            implementation_version="fake-model-v1",
        )
        self.proposals = proposals
        self.review_mode = review_mode
        self.proposal_requests: list[dict[str, Any]] = []
        self.review_requests: list[dict[str, Any]] = []

    def propose(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.proposal_requests.append(dict(request))
        return {
            "schema": "study.candidate-discovery.proposals",
            "schemaVersion": 1,
            "proposals": self.proposals,
        }

    def review(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.review_requests.append(dict(request))
        reviews = []
        if self.review_mode == "complete":
            reviews = [
                {
                    "reviewKey": item["reviewKey"],
                    "semanticEvidence": "verified",
                    "conflict": "clear",
                    "learnerFit": "new",
                    "reasonCodes": ["SEMANTIC_ALIGNMENT_VERIFIED"],
                }
                for item in request["proposals"]
            ]
        elif self.review_mode == "self_grade":
            reviews = [
                {
                    "reviewKey": request["proposals"][0]["reviewKey"],
                    "eligibility": "recommended",
                }
            ]
        return {
            "schema": "study.candidate-discovery.reviews",
            "schemaVersion": 1,
            "reviews": reviews,
        }


def run(engine, bound, fingerprint, inspection, contract):
    return engine.discover(
        audience=bound,
        project_id="project_1",
        project_revision=4,
        input_fingerprint=fingerprint,
        inspection_ref=inspection.artifact_ref,
        learning_contract=contract,
        evaluated_at="2026-07-19T04:00:00.000Z",
    )


def test_two_role_discovery_publishes_auditable_graph_and_service_owned_decisions(
    tmp_path: Path,
) -> None:
    artifacts, bound, fingerprint, inspection, contract = environment(tmp_path)
    model = FakeModel([proposal(start=FIRST), proposal(start=SECOND)])
    result = run(
        CandidateDiscoveryEngine(artifacts=artifacts, model=model),
        bound,
        fingerprint,
        inspection,
        contract,
    )

    assert result["candidateCount"] == 2
    assert result["counts"]["recommended"] == 1
    assert result["counts"]["duplicate"] == 1
    assert model.proposal_requests[0]["role"] == PROPOSAL_ROLE_VERSION
    assert model.review_requests[0]["role"] == REVIEW_ROLE_VERSION
    reviewed_evidence = model.review_requests[0]["proposals"][0]["evidence"][0]
    assert reviewed_evidence["quote"] == FORM
    assert FORM in reviewed_evidence["context"]
    assert reviewed_evidence["targetEndInContext"] > reviewed_evidence["targetStartInContext"]
    assert model.review_requests[0]["learningContract"]["purpose"] == contract["purpose"]
    assert model.proposal_requests[0]["constraints"] == {
        "maximumProposals": 80,
        "maximumSpansPerProposal": 4,
        "submitEligibility": False,
        "submitScores": False,
        "submitGateResults": False,
        "submitUserLocks": False,
    }
    assert (
        model.review_requests[0]["constraints"]["duplicateDecisionOwnedByService"]
        is True
    )
    proposal_batch = artifacts.verify_ref(result["proposalBatchRef"], bound)
    review_batch = artifacts.verify_ref(result["reviewBatchRef"], bound)
    assert proposal_batch["payloadSchema"] == "study.discovery-proposal-batch"
    assert review_batch["payloadSchema"] == "study.discovery-review-batch"
    assert all(
        "eligibility" not in item and "scores" not in item
        for item in proposal_batch["payload"]["proposals"]
    )
    for published in result["candidatePublications"]:
        candidate = artifacts.verify_ref(published["candidateRef"], bound)
        gate = artifacts.verify_ref(published["gateEvaluationRef"], bound)
        assert result["proposalBatchRef"] in candidate["parents"]
        assert result["reviewBatchRef"] in gate["parents"]
        assert gate["payload"]["derivedEligibility"] == published["eligibility"]
    discovery = artifacts.verify_ref(result["discoveryRef"], bound)
    assert discovery["inputFingerprint"] == fingerprint
    assert inspection.artifact_ref in discovery["parents"]


def test_proposer_cannot_submit_scores_or_eligibility(tmp_path: Path) -> None:
    artifacts, bound, fingerprint, inspection, contract = environment(tmp_path)
    model = FakeModel([proposal(extra={"eligibility": "recommended"})])
    with pytest.raises(CandidateDiscoveryError) as captured:
        run(
            CandidateDiscoveryEngine(artifacts=artifacts, model=model),
            bound,
            fingerprint,
            inspection,
            contract,
        )
    assert captured.value.code == "DISCOVERY_MODEL_RESPONSE_INVALID"
    assert model.review_requests == []


def test_proposal_span_must_be_inside_exact_disclosed_window(tmp_path: Path) -> None:
    artifacts, bound, fingerprint, inspection, contract = environment(tmp_path)
    outside = proposal()
    outside["spans"] = [{"nodeId": NODE, "start": 0, "end": len(TEXT) + 1}]
    model = FakeModel([outside])
    with pytest.raises(CandidateDiscoveryError) as captured:
        run(
            CandidateDiscoveryEngine(artifacts=artifacts, model=model),
            bound,
            fingerprint,
            inspection,
            contract,
        )
    assert captured.value.code == "DISCOVERY_MODEL_RESPONSE_INVALID"
    assert model.review_requests == []


def test_reviewer_cannot_self_grade_a_candidate(tmp_path: Path) -> None:
    artifacts, bound, fingerprint, inspection, contract = environment(tmp_path)
    model = FakeModel([proposal()], review_mode="self_grade")
    with pytest.raises(CandidateDiscoveryError) as captured:
        run(
            CandidateDiscoveryEngine(artifacts=artifacts, model=model),
            bound,
            fingerprint,
            inspection,
            contract,
        )
    assert captured.value.code == "DISCOVERY_MODEL_RESPONSE_INVALID"


def test_missing_independent_review_degrades_to_needs_review(tmp_path: Path) -> None:
    artifacts, bound, fingerprint, inspection, contract = environment(tmp_path)
    model = FakeModel([proposal()], review_mode="missing")
    result = run(
        CandidateDiscoveryEngine(artifacts=artifacts, model=model),
        bound,
        fingerprint,
        inspection,
        contract,
    )
    assert result["counts"]["needs_review"] == 1
    assert "DISCOVERY_REVIEW_INCOMPLETE" in result["issueCodes"]
    review_batch = artifacts.verify_ref(result["reviewBatchRef"], bound)
    assert review_batch["payload"]["reviews"][0]["reviewerReturned"] is False


def test_sensitive_source_node_is_not_disclosed_to_model_or_json_artifacts(
    tmp_path: Path,
) -> None:
    canary = "sk-abcdefghijklmnopqrstuvwxyz012345"
    artifacts, bound, fingerprint, inspection, contract = environment(
        tmp_path, text=f"Private {canary} must never leave this node."
    )
    model = FakeModel([])
    result = run(
        CandidateDiscoveryEngine(artifacts=artifacts, model=model),
        bound,
        fingerprint,
        inspection,
        contract,
    )
    assert model.proposal_requests == []
    assert model.review_requests == []
    assert result["candidateCount"] == 0
    assert "DISCOVERY_SECRET_TEXT_OMITTED" in result["issueCodes"]
    persisted_json = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "artifacts").rglob("*.json")
    )
    assert canary not in persisted_json


def test_unsafe_model_proposal_is_hashed_and_suppressed_without_reviewer_disclosure(
    tmp_path: Path,
) -> None:
    artifacts, bound, fingerprint, inspection, contract = environment(tmp_path)
    canary = "sk-abcdefghijklmnopqrstuvwxyz012345"
    model = FakeModel([proposal(form=canary)])
    result = run(
        CandidateDiscoveryEngine(artifacts=artifacts, model=model),
        bound,
        fingerprint,
        inspection,
        contract,
    )
    assert model.review_requests == []
    assert result["counts"]["hard_blocked"] == 1
    assert "DISCOVERY_UNSAFE_PROPOSAL_SUPPRESSED" in result["issueCodes"]
    proposal_batch = artifacts.verify_ref(result["proposalBatchRef"], bound)
    assert proposal_batch["payload"]["proposals"] == []
    assert len(proposal_batch["payload"]["suppressedProposalDigests"]) == 1
    candidate = artifacts.verify_ref(
        result["candidatePublications"][0]["candidateRef"], bound
    )
    assert candidate["payloadSchema"] == "study.candidate-rejection"
    persisted_json = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "artifacts").rglob("*.json")
    )
    assert canary not in persisted_json


def test_discovery_fingerprint_is_distinct_from_parent_inspection_but_still_bound_end_to_end(
    tmp_path: Path,
) -> None:
    artifacts, bound, fingerprint, inspection, contract = environment(tmp_path)
    inspection_envelope = artifacts.verify_ref(inspection.artifact_ref, bound)
    assert inspection_envelope["inputFingerprint"] != fingerprint
    result = run(
        CandidateDiscoveryEngine(artifacts=artifacts, model=FakeModel([proposal()])),
        bound,
        fingerprint,
        inspection,
        contract,
    )
    candidate = artifacts.verify_ref(
        result["candidatePublications"][0]["candidateRef"], bound
    )
    gate = artifacts.verify_ref(
        result["candidatePublications"][0]["gateEvaluationRef"], bound
    )
    discovery = artifacts.verify_ref(result["discoveryRef"], bound)
    assert {
        candidate["inputFingerprint"],
        gate["inputFingerprint"],
        discovery["inputFingerprint"],
    } == {fingerprint}


def test_model_identity_type_errors_fail_as_domain_errors() -> None:
    with pytest.raises(CandidateDiscoveryError) as captured:
        CandidateDiscoveryModelIdentity(
            profile_ref=7,  # type: ignore[arg-type]
            configuration_fingerprint=hashlib.sha256(b"model-config").hexdigest(),
            credential_revision=1,
            implementation_version="fake-model-v1",
        )
    assert captured.value.code == "DISCOVERY_MODEL_IDENTITY_INVALID"


def test_inspection_summary_cannot_transplant_an_authenticated_detail(tmp_path: Path) -> None:
    artifacts, bound, fingerprint, inspection, contract = environment(tmp_path)
    inspection_envelope = artifacts.verify_ref(inspection.artifact_ref, bound)
    representation_ref = inspection_envelope["payload"]["representationRefs"][0]
    fake_detail = artifacts.publish(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        artifact_id="inspection_source_transplanted",
        artifact_revision=1,
        payload_schema="study.source-inspection",
        payload_schema_version=1,
        payload={
            "sourceId": "source_1",
            "status": "ready",
            "supportTier": "A",
            "representationRefs": [representation_ref],
        },
        producer={"component": "test", "version": "1"},
        parents=[representation_ref],
        input_fingerprint=inspection_envelope["inputFingerprint"],
        completeness=completeness(),
        issue_refs=[],
    )
    tampered_payload = dict(inspection_envelope["payload"])
    tampered_payload["sourceInspectionRefs"] = [dict(fake_detail.artifact_ref)]
    tampered = artifacts.publish(
        audience=bound,
        project_id="project_1",
        project_revision=3,
        artifact_id="inspection_transplanted",
        artifact_revision=1,
        payload_schema="study.inspection",
        payload_schema_version=1,
        payload=tampered_payload,
        producer={"component": "test", "version": "1"},
        parents=inspection_envelope["parents"],
        input_fingerprint=inspection_envelope["inputFingerprint"],
        completeness=completeness(),
        issue_refs=[],
    )
    with pytest.raises(CandidateDiscoveryError) as captured:
        run(
            CandidateDiscoveryEngine(artifacts=artifacts, model=FakeModel([proposal()])),
            bound,
            fingerprint,
            tampered,
            contract,
        )
    assert captured.value.code == "DISCOVERY_INSPECTION_INVALID"
