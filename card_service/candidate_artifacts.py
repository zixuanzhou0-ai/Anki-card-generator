"""Immutable Artifact publication for gated learning candidates."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .candidate_gates import CANDIDATE_GATE_RULE_SET_VERSION


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ELIGIBILITY = (
    "recommended",
    "candidate",
    "duplicate",
    "needs_review",
    "hard_blocked",
    "excluded",
)
_GATES = (
    "evidence",
    "goal_relevance",
    "novelty",
    "scoreability",
    "card_suitability",
    "conflict",
    "review_value",
    "security",
)
_PRODUCER = {"component": "candidate-artifact-publisher", "version": "1.0.0"}


class CandidateArtifactError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise CandidateArtifactError(
            "CANDIDATE_ARTIFACT_INVALID", f"{label} is invalid"
        )
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise CandidateArtifactError(
            "CANDIDATE_ARTIFACT_INVALID", f"{label} is invalid"
        )
    return value


def _draft(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "schemaVersion",
        "candidateId",
        "sourceId",
        "representationRef",
        "evidenceAnchors",
        "semanticUnit",
        "objective",
        "scores",
        "explanation",
        "issueRefs",
        "gateEvaluation",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required
        or value.get("schema") != "study.language-candidate-evaluation-draft"
        or value.get("schemaVersion") != 1
    ):
        raise CandidateArtifactError(
            "CANDIDATE_ARTIFACT_INVALID", "candidate evaluation draft is invalid"
        )
    result = _clone(value)
    _identifier(result["candidateId"], "candidateId")
    _identifier(result["sourceId"], "sourceId")
    if not isinstance(result["representationRef"], dict):
        raise CandidateArtifactError(
            "CANDIDATE_ARTIFACT_INVALID", "representationRef is invalid"
        )
    if not isinstance(result["evidenceAnchors"], list):
        raise CandidateArtifactError(
            "CANDIDATE_ARTIFACT_INVALID", "evidenceAnchors are invalid"
        )
    for key in ("semanticUnit", "objective", "scores", "gateEvaluation"):
        if not isinstance(result[key], dict):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID", f"{key} is invalid"
            )
    for key in ("explanation", "issueRefs"):
        if not isinstance(result[key], list) or not all(
            isinstance(item, str) for item in result[key]
        ):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID", f"{key} is invalid"
            )
    evaluation = result["gateEvaluation"]
    required_evaluation = {
        "evaluationId",
        "candidateId",
        "projectRevision",
        "inputFingerprint",
        "ruleSetVersion",
        "results",
        "derivedEligibility",
        "evaluatedAt",
        "producer",
    }
    if (
        set(evaluation) != required_evaluation
        or evaluation.get("candidateId") != result["candidateId"]
        or evaluation.get("ruleSetVersion") != CANDIDATE_GATE_RULE_SET_VERSION
        or evaluation.get("derivedEligibility") not in _ELIGIBILITY
        or not isinstance(evaluation.get("results"), list)
        or [
            item.get("gate") for item in evaluation["results"] if isinstance(item, dict)
        ]
        != list(_GATES)
    ):
        raise CandidateArtifactError(
            "CANDIDATE_ARTIFACT_INVALID", "gate evaluation draft is invalid"
        )
    _identifier(evaluation["evaluationId"], "evaluationId")
    _digest(evaluation["inputFingerprint"], "inputFingerprint")
    expected_gate_fields = {
        "gate",
        "ruleId",
        "ruleSetVersion",
        "state",
        "reasonCode",
        "producer",
        "evidenceIds",
        "evaluatedAt",
    }
    for gate in evaluation["results"]:
        if (
            not isinstance(gate, dict)
            or set(gate) != expected_gate_fields
            or gate.get("state") not in {"pass", "review", "fail"}
            or gate.get("ruleSetVersion") != CANDIDATE_GATE_RULE_SET_VERSION
            or not isinstance(gate.get("reasonCode"), str)
            or not isinstance(gate.get("evidenceIds"), list)
        ):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID", "gate result fields are invalid"
            )
    expected_issues = sorted(
        {
            gate["reasonCode"]
            for gate in evaluation["results"]
            if gate["state"] in {"review", "fail"}
        }
    )
    if sorted(set(result["issueRefs"])) != expected_issues:
        raise CandidateArtifactError(
            "CANDIDATE_ARTIFACT_INVALID", "candidate issueRefs do not match its gates"
        )
    if (
        _derived_eligibility(evaluation["results"], result["scores"])
        != evaluation["derivedEligibility"]
    ):
        raise CandidateArtifactError(
            "CANDIDATE_ARTIFACT_INVALID",
            "candidate eligibility was not derived from its gates",
        )
    return result


def _security_failed(draft: Mapping[str, Any]) -> bool:
    return any(
        value.get("gate") == "security" and value.get("state") == "fail"
        for value in draft["gateEvaluation"]["results"]
    )


def _derived_eligibility(
    results: Sequence[Mapping[str, Any]], scores: Mapping[str, Any]
) -> str:
    states = {str(value["gate"]): str(value["state"]) for value in results}
    if any(states.get(name) == "fail" for name in ("evidence", "conflict", "security")):
        return "hard_blocked"
    if states.get("goal_relevance") == "fail" or states.get("review_value") == "fail":
        return "excluded"
    if states.get("novelty") == "fail":
        return "duplicate"
    if states.get("scoreability") == "fail" or states.get("card_suitability") == "fail":
        return "hard_blocked"
    if any(value == "review" for value in states.values()):
        return "needs_review"
    transfer = scores.get("bottleneckAndTransfer")
    if isinstance(transfer, bool) or not isinstance(transfer, (int, float)):
        raise CandidateArtifactError(
            "CANDIDATE_ARTIFACT_INVALID", "candidate transfer score is invalid"
        )
    return "recommended" if float(transfer) >= 0.68 else "candidate"


def _completeness(
    state: str, count: int, reason_codes: Sequence[str] = ()
) -> dict[str, Any]:
    return {
        "state": state,
        "expectedUnits": count,
        "processedUnits": count,
        "omittedLocators": [],
        "reasonCodes": sorted(set(reason_codes)),
    }


class CandidateArtifactPublisher:
    """Publish candidate proposals and gates as an acyclic immutable graph."""

    def __init__(self, artifacts: ArtifactRegistry) -> None:
        self._artifacts = artifacts

    def _verify_evidence(
        self,
        *,
        draft: Mapping[str, Any],
        representation: Mapping[str, Any],
    ) -> None:
        payload = representation.get("payload")
        if not isinstance(payload, Mapping):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID", "representation payload is invalid"
            )
        blob_ref = payload.get("plainTextBlobRef")
        nodes = payload.get("contentNodes")
        source_ref = payload.get("sourceRef")
        if (
            not isinstance(blob_ref, Mapping)
            or not isinstance(nodes, list)
            or not isinstance(source_ref, Mapping)
            or not isinstance(blob_ref.get("sizeBytes"), int)
            or blob_ref["sizeBytes"] > 32 * 1024 * 1024
        ):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID",
                "representation evidence surface is invalid",
            )
        try:
            text = self._artifacts.read_blob(blob_ref).decode("utf-8", errors="strict")
        except (ArtifactRegistryError, UnicodeDecodeError) as error:
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID", "representation text failed verification"
            ) from error
        node_bounds: dict[str, tuple[int, int]] = {}
        for node in nodes:
            attributes = node.get("attributes") if isinstance(node, Mapping) else None
            if not isinstance(node, Mapping) or not isinstance(attributes, Mapping):
                raise CandidateArtifactError(
                    "CANDIDATE_ARTIFACT_INVALID", "representation node is invalid"
                )
            node_id = node.get("nodeId")
            start = attributes.get("textStart")
            end = attributes.get("textEnd")
            if (
                not isinstance(node_id, str)
                or not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 0
                or end <= start
                or end > len(text)
                or node_id in node_bounds
            ):
                raise CandidateArtifactError(
                    "CANDIDATE_ARTIFACT_INVALID",
                    "representation node bounds are invalid",
                )
            node_bounds[node_id] = (start, end)
        evidence_ids: list[str] = []
        for evidence in draft["evidenceAnchors"]:
            locator = evidence.get("locator") if isinstance(evidence, Mapping) else None
            evidence_id = (
                evidence.get("evidenceId") if isinstance(evidence, Mapping) else None
            )
            if (
                not isinstance(evidence, Mapping)
                or not isinstance(locator, Mapping)
                or locator.get("kind") != "text_span"
                or evidence.get("sourceRef") != dict(source_ref)
                or not isinstance(evidence_id, str)
                or evidence_id in evidence_ids
            ):
                raise CandidateArtifactError(
                    "CANDIDATE_ARTIFACT_INVALID", "candidate evidence is invalid"
                )
            node_id = locator.get("nodeId")
            start = locator.get("start")
            end = locator.get("end")
            bounds = node_bounds.get(node_id) if isinstance(node_id, str) else None
            if (
                bounds is None
                or isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(end, bool)
                or not isinstance(end, int)
                or start < bounds[0]
                or end > bounds[1]
                or end <= start
            ):
                raise CandidateArtifactError(
                    "CANDIDATE_ARTIFACT_INVALID",
                    "candidate evidence bounds are invalid",
                )
            actual = hashlib.sha256(text[start:end].encode("utf-8")).hexdigest()
            if evidence.get("quoteSha256") != actual:
                raise CandidateArtifactError(
                    "CANDIDATE_ARTIFACT_INVALID",
                    "candidate evidence quote digest is invalid",
                )
            evidence_ids.append(evidence_id)
        exact_ids = draft["semanticUnit"].get("exactEvidenceIds")
        if not isinstance(exact_ids, list) or exact_ids != evidence_ids:
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID",
                "semantic unit evidence binding is invalid",
            )
        eligibility = draft["gateEvaluation"]["derivedEligibility"]
        if (
            eligibility in {"recommended", "candidate", "needs_review"}
            and not evidence_ids
        ):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID",
                "selectable candidate has no replayable evidence",
            )

    def publish_candidate(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        project_revision: int,
        input_fingerprint: str,
        draft: Mapping[str, Any],
    ) -> dict[str, Any]:
        value = _draft(draft)
        if (
            not isinstance(project_revision, int)
            or isinstance(project_revision, bool)
            or project_revision < 1
            or value["gateEvaluation"]["projectRevision"] != project_revision
            or value["gateEvaluation"]["inputFingerprint"] != input_fingerprint
        ):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID",
                "candidate publication revision is invalid",
            )
        representation_ref = value["representationRef"]
        try:
            representation = self._artifacts.verify_ref(representation_ref, audience)
        except ArtifactRegistryError as error:
            raise CandidateArtifactError(error.code, error.message) from error
        if (
            representation_ref.get("projectId") != project_id
            or representation_ref.get("projectRevision", project_revision + 1)
            > project_revision
            or representation.get("payloadSchema") != "study.source-representation"
            or representation.get("inputFingerprint") != input_fingerprint
        ):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID",
                "candidate representation is outside the publication scope",
            )
        security_failed = _security_failed(value)
        if not security_failed:
            self._verify_evidence(draft=value, representation=representation)
        candidate_id = value["candidateId"]
        if security_failed:
            proposal_digest = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "semanticUnit": value["semanticUnit"],
                        "objective": value["objective"],
                    }
                )
            ).hexdigest()
            payload_schema = "study.candidate-rejection"
            payload = {
                "candidateId": candidate_id,
                "sourceId": value["sourceId"],
                "representationRef": representation_ref,
                "proposalSha256": proposal_digest,
                "suppressed": True,
                "reasonCodes": sorted(set(value["issueRefs"])),
            }
        else:
            payload_schema = "study.candidate-proposal"
            payload = {
                "candidateId": candidate_id,
                "sourceId": value["sourceId"],
                "representationRef": representation_ref,
                "evidenceAnchors": value["evidenceAnchors"],
                "semanticUnit": value["semanticUnit"],
                "objective": value["objective"],
                "scores": value["scores"],
                "explanation": value["explanation"],
                "issueRefs": value["issueRefs"],
            }
        candidate = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=project_revision,
            artifact_id=candidate_id,
            artifact_revision=1,
            payload_schema=payload_schema,
            payload_schema_version=1,
            payload=payload,
            producer=_PRODUCER,
            parents=[representation_ref],
            input_fingerprint=input_fingerprint,
            completeness=_completeness("complete", 1),
            issue_refs=value["issueRefs"],
        )
        evidence_refs = {
            item["evidenceId"]: {
                "artifactRef": dict(candidate.artifact_ref),
                "entityId": item["evidenceId"],
            }
            for item in ([] if security_failed else value["evidenceAnchors"])
        }
        results = []
        for raw in value["gateEvaluation"]["results"]:
            result = dict(raw)
            evidence_ids = result.pop("evidenceIds", [])
            if not isinstance(evidence_ids, list) or any(
                evidence_id not in evidence_refs for evidence_id in evidence_ids
            ):
                if security_failed:
                    evidence_ids = []
                else:
                    raise CandidateArtifactError(
                        "CANDIDATE_ARTIFACT_INVALID",
                        "gate evaluation references unknown evidence",
                    )
            result["evidenceRefs"] = [evidence_refs[value] for value in evidence_ids]
            results.append(result)
        evaluation = value["gateEvaluation"]
        gate_payload = {
            "evaluationId": evaluation["evaluationId"],
            "candidateRef": {
                "artifactRef": dict(candidate.artifact_ref),
                "entityId": candidate_id,
            },
            "projectRevision": project_revision,
            "candidateArtifactRevision": candidate.artifact_ref["artifactRevision"],
            "inputFingerprint": input_fingerprint,
            "ruleSetVersion": evaluation["ruleSetVersion"],
            "results": results,
            "derivedEligibility": evaluation["derivedEligibility"],
            "evaluatedAt": evaluation["evaluatedAt"],
            "producer": evaluation["producer"],
        }
        gate = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=project_revision,
            artifact_id=evaluation["evaluationId"],
            artifact_revision=1,
            payload_schema="study.gate-evaluation",
            payload_schema_version=1,
            payload=gate_payload,
            producer=_PRODUCER,
            parents=[candidate.artifact_ref],
            input_fingerprint=input_fingerprint,
            completeness=_completeness("complete", len(results)),
            issue_refs=value["issueRefs"],
        )
        return {
            "candidateId": candidate_id,
            "eligibility": evaluation["derivedEligibility"],
            "suppressed": security_failed,
            "candidateHandle": candidate.handle,
            "candidateRef": dict(candidate.artifact_ref),
            "gateEvaluationHandle": gate.handle,
            "gateEvaluationRef": dict(gate.artifact_ref),
        }

    def publish_discovery(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        project_revision: int,
        input_fingerprint: str,
        inspection_ref: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID", "candidate publications are invalid"
            )
        try:
            inspection = self._artifacts.verify_ref(inspection_ref, audience)
        except ArtifactRegistryError as error:
            raise CandidateArtifactError(error.code, error.message) from error
        input_fingerprint = _digest(input_fingerprint, "inputFingerprint")
        if (
            not isinstance(project_revision, int)
            or isinstance(project_revision, bool)
            or project_revision < 1
            or inspection_ref.get("projectId") != project_id
            or inspection_ref.get("projectRevision", project_revision + 1)
            > project_revision
            or inspection.get("payloadSchema") != "study.inspection"
            or inspection.get("inputFingerprint") != input_fingerprint
        ):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID", "inspectionRef is invalid"
            )
        inspection_payload = inspection.get("payload")
        inspection_representations = (
            inspection_payload.get("representationRefs")
            if isinstance(inspection_payload, Mapping)
            else None
        )
        if not isinstance(inspection_representations, list) or not all(
            isinstance(value, Mapping) for value in inspection_representations
        ):
            raise CandidateArtifactError(
                "CANDIDATE_ARTIFACT_INVALID",
                "inspection representation graph is invalid",
            )
        counts = {value: 0 for value in _ELIGIBILITY}
        candidate_refs: list[dict[str, Any]] = []
        gate_refs: list[dict[str, Any]] = []
        candidate_entities: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in candidates:
            if not isinstance(raw, Mapping):
                raise CandidateArtifactError(
                    "CANDIDATE_ARTIFACT_INVALID", "candidate publication is invalid"
                )
            candidate_id = _identifier(raw.get("candidateId"), "candidateId")
            eligibility = raw.get("eligibility")
            candidate_ref = raw.get("candidateRef")
            gate_ref = raw.get("gateEvaluationRef")
            if (
                candidate_id in seen
                or eligibility not in counts
                or not isinstance(candidate_ref, Mapping)
                or not isinstance(gate_ref, Mapping)
            ):
                raise CandidateArtifactError(
                    "CANDIDATE_ARTIFACT_INVALID",
                    "candidate publication fields are invalid",
                )
            seen.add(candidate_id)
            try:
                candidate_envelope = self._artifacts.verify_ref(candidate_ref, audience)
                gate_envelope = self._artifacts.verify_ref(gate_ref, audience)
            except ArtifactRegistryError as error:
                raise CandidateArtifactError(error.code, error.message) from error
            candidate_payload = candidate_envelope.get("payload")
            gate_payload = gate_envelope.get("payload")
            candidate_parents = candidate_envelope.get("parents")
            if (
                candidate_ref.get("projectId") != project_id
                or gate_ref.get("projectId") != project_id
                or candidate_ref.get("projectRevision") != project_revision
                or gate_ref.get("projectRevision") != project_revision
                or candidate_envelope.get("inputFingerprint") != input_fingerprint
                or gate_envelope.get("inputFingerprint") != input_fingerprint
                or candidate_envelope.get("payloadSchema")
                not in {"study.candidate-proposal", "study.candidate-rejection"}
                or gate_envelope.get("payloadSchema") != "study.gate-evaluation"
                or not isinstance(candidate_payload, Mapping)
                or not isinstance(gate_payload, Mapping)
                or candidate_payload.get("candidateId") != candidate_id
                or not isinstance(candidate_parents, list)
                or len(candidate_parents) != 1
                or candidate_parents[0] not in inspection_representations
                or candidate_parents != [candidate_payload.get("representationRef")]
                or gate_envelope.get("parents") != [dict(candidate_ref)]
                or gate_payload.get("candidateRef")
                != {"artifactRef": dict(candidate_ref), "entityId": candidate_id}
                or gate_payload.get("projectRevision") != project_revision
                or gate_payload.get("inputFingerprint") != input_fingerprint
                or gate_payload.get("ruleSetVersion") != CANDIDATE_GATE_RULE_SET_VERSION
                or gate_payload.get("derivedEligibility") != eligibility
            ):
                raise CandidateArtifactError(
                    "CANDIDATE_ARTIFACT_INVALID", "candidate Artifact graph is invalid"
                )
            counts[str(eligibility)] += 1
            candidate_refs.append(dict(candidate_ref))
            gate_refs.append(dict(gate_ref))
            candidate_entities.append(
                {"artifactRef": dict(candidate_ref), "entityId": candidate_id}
            )
        paired = sorted(
            zip(candidate_refs, gate_refs, candidate_entities, strict=True),
            key=lambda value: value[0]["artifactId"].encode("utf-8"),
        )
        candidate_refs = [value[0] for value in paired]
        gate_refs = [value[1] for value in paired]
        candidate_entities = [value[2] for value in paired]
        identity = {
            "inspectionRef": dict(inspection_ref),
            "candidateRefs": candidate_refs,
            "gateEvaluationRefs": gate_refs,
            "inputFingerprint": input_fingerprint,
            "ruleSetVersion": CANDIDATE_GATE_RULE_SET_VERSION,
        }
        discovery_id = (
            "discovery_"
            + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()[:40]
        )
        issues = []
        if counts["recommended"] == 0:
            issues.append("DISCOVERY_NO_RECOMMENDED_CANDIDATES")
        completeness = _completeness("complete", len(candidate_refs))
        payload = {
            "discoveryId": discovery_id,
            "inspectionRef": dict(inspection_ref),
            "candidateRefs": candidate_entities,
            "gateEvaluationRefs": gate_refs,
            "completeness": completeness,
            "counts": counts,
            "ruleSetVersion": CANDIDATE_GATE_RULE_SET_VERSION,
        }
        publication = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=project_revision,
            artifact_id=discovery_id,
            artifact_revision=1,
            payload_schema="study.discovery",
            payload_schema_version=1,
            payload=payload,
            producer=_PRODUCER,
            parents=[dict(inspection_ref), *candidate_refs, *gate_refs],
            input_fingerprint=input_fingerprint,
            completeness=completeness,
            issue_refs=issues,
        )
        return {
            "discoveryId": discovery_id,
            "discoveryHandle": publication.handle,
            "discoveryRef": dict(publication.artifact_ref),
            "counts": counts,
            "candidateCount": len(candidate_refs),
            "issueCodes": issues,
        }


__all__ = [
    "CandidateArtifactError",
    "CandidateArtifactPublisher",
]
