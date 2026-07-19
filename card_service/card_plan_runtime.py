"""Deterministic, authenticated CardPlan publication for safe language routes.

This slice deliberately supports only routes whose cue and scoring boundary can
be reconstructed without a model or a media generator.  Unsupported routes fail
closed instead of being silently converted into a generic text card.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .candidate_selection import CandidateSelectionError, CandidateSelectionRuntime
from .project_registry import ProjectRegistry, ProjectRegistryError
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


CARD_PLAN_POLICY_VERSION = "deterministic-language-card-plan-v1"
CARD_PLAN_VALIDATION_RULE_SET_VERSION = "card-plan-validation-v1"
_SUPPORTED_ROUTES = frozenset(
    {"production", "chunk_collocation", "reading_recognition"}
)
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_PRODUCER = {
    "kind": "deterministic-service",
    "component": "card-plan-runtime",
    "version": CARD_PLAN_POLICY_VERSION,
}
_COMPONENTS = {
    "cardService": "2.0.0",
    "worker": "not-used",
    "sourceAdapterSetDigest": hashlib.sha256(
        b"card-plan-no-source-adapter-v1"
    ).hexdigest(),
    "gateRuleSetVersion": "candidate-gates-language-v1",
    "compatibilityContractVersion": CARD_PLAN_POLICY_VERSION,
}


class CardPlanRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise CardPlanRuntimeError(code, message)


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _text(value: Any, label: str, *, maximum: int = 4_000) -> str:
    if not isinstance(value, str):
        _fail("CARD_PLAN_GRAPH_CORRUPT", f"{label} is invalid")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > maximum:
        _fail("CARD_PLAN_GRAPH_CORRUPT", f"{label} is invalid")
    return normalized


def _entity_ref(artifact_ref: Mapping[str, Any], entity_id: str) -> dict[str, Any]:
    return {"artifactRef": dict(artifact_ref), "entityId": entity_id}


def _gate_states(row: Mapping[str, Any]) -> dict[str, str]:
    values = row.get("gate", {}).get("payload", {}).get("results")
    if not isinstance(values, list):
        _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate gate results are invalid")
    states: dict[str, str] = {}
    for value in values:
        if not isinstance(value, Mapping):
            _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate gate result is invalid")
        gate = value.get("gate")
        state = value.get("state")
        if not isinstance(gate, str) or state not in {"pass", "review", "fail"}:
            _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate gate result is invalid")
        if gate in states:
            _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate gate result is duplicated")
        states[gate] = state
    return states


def _validation_state(value: str) -> str:
    return {"pass": "passed", "review": "needs_review", "fail": "failed"}[value]


def _answer_leaks(cue: str, answer: str) -> bool:
    normalized_cue = _normalize(cue)
    normalized_answer = _normalize(answer)
    if not normalized_answer:
        return True
    if normalized_cue == normalized_answer:
        return True
    if len(normalized_answer) < 2:
        return False
    return normalized_answer in normalized_cue


def _plan_draft(
    row: Mapping[str, Any],
    *,
    project_revision: int,
    selection_ref: Mapping[str, Any],
    operation_digest: str,
) -> dict[str, Any]:
    candidate_ref = row.get("candidateRef")
    candidate = row.get("candidate", {}).get("payload")
    if not isinstance(candidate_ref, Mapping) or not isinstance(candidate, Mapping):
        _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate graph is invalid")
    if row.get("eligibility") not in {"recommended", "needs_review"}:
        _fail("CARD_PLAN_CANDIDATE_BLOCKED", "selected candidate is not plannable")
    objective = candidate.get("objective")
    semantic_unit = candidate.get("semanticUnit")
    evidence = candidate.get("evidenceAnchors")
    if (
        not isinstance(objective, Mapping)
        or not isinstance(semantic_unit, Mapping)
        or not isinstance(evidence, list)
        or not evidence
    ):
        _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate learning fields are invalid")
    route = objective.get("route")
    if route not in _SUPPORTED_ROUTES:
        _fail(
            "UNSUPPORTED_CARD_PLAN",
            f"route {route!r} cannot be planned without unsupported inference",
        )
    form = _text(semantic_unit.get("form"), "target form", maximum=160)
    meaning = _text(
        semantic_unit.get("meaningOrFunction"), "target meaning", maximum=500
    )
    objective_id = _text(objective.get("objectiveId"), "objectiveId", maximum=256)
    candidate_id = _text(candidate.get("candidateId"), "candidateId", maximum=256)
    scoring_boundary = objective.get("scoringBoundary")
    if (
        not isinstance(scoring_boundary, list)
        or len(scoring_boundary) != 1
        or not isinstance(scoring_boundary[0], str)
    ):
        _fail("CARD_PLAN_SCORE_BOUNDARY_INVALID", "objective is not one score point")

    if route in {"production", "chunk_collocation"}:
        cue_content = _text(objective.get("cueSpec"), "cue", maximum=1_000)
        core_answer = form
    else:
        cue_content = form
        core_answer = meaning
    scoring_point = _text(scoring_boundary[0], "scoring boundary", maximum=500)
    if _normalize(scoring_point) != _normalize(core_answer):
        _fail(
            "CARD_PLAN_SCORE_BOUNDARY_INVALID",
            "core answer does not equal the frozen scoring boundary",
        )

    evidence_refs: list[dict[str, Any]] = []
    evidence_ids: set[str] = set()
    for anchor in evidence:
        evidence_id = anchor.get("evidenceId") if isinstance(anchor, Mapping) else None
        if not isinstance(evidence_id, str) or evidence_id in evidence_ids:
            _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate evidence is invalid")
        evidence_ids.add(evidence_id)
        evidence_refs.append(_entity_ref(candidate_ref, evidence_id))
    objective_evidence = objective.get("evidenceIds")
    if (
        not isinstance(objective_evidence, list)
        or set(objective_evidence) != evidence_ids
        or len(objective_evidence) != len(evidence_ids)
    ):
        _fail("CARD_PLAN_EVIDENCE_INVALID", "objective evidence is incomplete")

    gates = _gate_states(row)
    evidence_state = gates.get("evidence", "fail")
    scoreability_state = gates.get("scoreability", "fail")
    leakage_state = "fail" if _answer_leaks(cue_content, core_answer) else "pass"
    plan_id = (
        "card_plan_"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "operationDigest": operation_digest,
                    "candidateId": candidate_id,
                    "policyVersion": CARD_PLAN_POLICY_VERSION,
                }
            )
        ).hexdigest()[:40]
    )
    expected_seconds = objective.get("granularity", {}).get("expectedAnswerSeconds")
    if (
        isinstance(expected_seconds, bool)
        or not isinstance(expected_seconds, int)
        or not 1 <= expected_seconds <= 300
    ):
        _fail("CARD_PLAN_GRAPH_CORRUPT", "expected review time is invalid")
    return {
        "cardPlanId": plan_id,
        "projectRevision": project_revision,
        "selectionRef": dict(selection_ref),
        "candidateRef": dict(candidate_ref),
        "objectiveRef": _entity_ref(candidate_ref, objective_id),
        "route": route,
        "cue": {"kind": "text", "content": cue_content, "mediaRefs": []},
        "expectedResponse": {
            "modality": "text",
            "coreAnswer": core_answer,
            "scoringPoints": [scoring_point],
            "acceptedVariants": [],
        },
        "feedback": {
            "explanation": meaning,
            "evidenceRefs": evidence_refs,
            "examples": [],
            "nonexamples": [],
        },
        "mediaPolicy": {
            "sourceAudio": False,
            "sourceVideo": False,
            "sentenceTts": False,
            "expressionTts": False,
        },
        "estimatedReviewSeconds": expected_seconds,
        "validation": {
            "answerLeakage": leakage_state,
            "scoreability": scoreability_state,
            "evidence": evidence_state,
            "templateCompatibility": "pass",
        },
        "candidateEligibility": row["eligibility"],
        "userLocks": [],
        "policyVersion": CARD_PLAN_POLICY_VERSION,
    }


def _validation_records(
    plan_ref: Mapping[str, Any],
    plan: Mapping[str, Any],
    row: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    evidence_refs = plan["feedback"]["evidenceRefs"]
    gates = _gate_states(row)
    checks = [
        (
            "evidence_coverage",
            _validation_state(plan["validation"]["evidence"]),
            evidence_refs,
        ),
        (
            "scoring_boundary",
            _validation_state(plan["validation"]["scoreability"]),
            evidence_refs,
        ),
        (
            "answer_leakage",
            "passed" if plan["validation"]["answerLeakage"] == "pass" else "failed",
            [],
        ),
        ("duplicate", "passed", []),
        (
            "conflict",
            _validation_state(gates.get("conflict", "fail")),
            evidence_refs,
        ),
        ("template_compatibility", "passed", []),
        ("media_generatability", "passed", []),
        ("user_lock_preservation", "passed", []),
    ]
    records = [
        {
            "cardPlanRef": _entity_ref(plan_ref, plan["cardPlanId"]),
            "checkId": check_id,
            "state": state,
            "producer": dict(_PRODUCER),
            "evidenceRefs": _clone(refs),
        }
        for check_id, state, refs in checks
    ]
    eligible = plan["candidateEligibility"] == "recommended" and all(
        record["state"] == "passed" for record in records
    )
    return records, eligible


class CardPlanRuntime:
    """Publish deterministic CardPlans and a validation artifact atomically by stage."""

    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        tasks: StudyTaskCoordinator,
        candidate_selection: CandidateSelectionRuntime,
    ) -> None:
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._tasks = tasks
        self._selection = candidate_selection

    def _bundle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        selection_ref: Mapping[str, Any],
        operation_digest: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        subject = {
            "kind": "project_task",
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "inputArtifacts": [
                {
                    "artifactId": selection_ref["artifactId"],
                    "artifactRevision": selection_ref["artifactRevision"],
                    "artifactDigest": selection_ref["artifactDigest"],
                }
            ],
            "sourceSnapshotDigests": [],
            "learningContractRevision": project["learningContract"]["contractRevision"],
        }
        work, work_digest = build_work_reuse_manifest(
            action_id="plan_cards",
            subject=subject,
            component_versions=_COMPONENTS,
            service_configurations=[],
            work_partition_policy_digest=operation_digest,
        )
        capability, capability_digest = build_capability_binding(
            [
                {
                    "kind": "fixed",
                    "capabilityId": "runtime.card_service",
                    "implementationVersionOrDigest": "2.0.0",
                    "compatibilityContractVersion": CARD_PLAN_POLICY_VERSION,
                }
            ]
        )
        authorization, authorization_digest = build_authorization_binding(
            audience=audience,
            service_instance_id=self._service_instance_id,
            bindings=[],
        )
        task_input, input_fingerprint = build_task_input_manifest(
            action_id="plan_cards",
            work_reuse_manifest=work,
            work_reuse_digest=work_digest,
            subject=subject,
            authorization_binding_digest=authorization_digest,
            capability_binding_digest=capability_digest,
            component_versions=_COMPONENTS,
            service_bindings=[],
            batch_policy_digest=operation_digest,
        )
        return work, task_input, capability, authorization, input_fingerprint

    def _public_result(
        self,
        *,
        audience: ArtifactAudienceBinding,
        committed: Mapping[str, Any],
    ) -> dict[str, Any]:
        found: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
        for ref in committed["artifactRefs"]:
            envelope = self._artifacts.verify_ref(ref, audience)
            schema = envelope.get("payloadSchema")
            if schema in {"study.card-plan-set", "study.card-plan-validation"}:
                if schema in found:
                    _fail("CARD_PLAN_RESULT_INVALID", "planning result is ambiguous")
                found[schema] = (ref, envelope)
        if set(found) != {"study.card-plan-set", "study.card-plan-validation"}:
            _fail("CARD_PLAN_RESULT_INVALID", "planning result is incomplete")
        set_ref, set_envelope = found["study.card-plan-set"]
        validation_ref, _validation_envelope = found["study.card-plan-validation"]
        payload = set_envelope["payload"]
        blocked = int(payload["blockedCount"])
        return {
            "schemaVersion": 1,
            "projectId": committed["projectId"],
            "projectRevision": committed["projectRevision"],
            "artifactStage": "plans_ready",
            "taskId": committed["taskId"],
            "planSetHandle": self._artifacts.issue_handle(set_ref, audience),
            "validationHandle": self._artifacts.issue_handle(validation_ref, audience),
            "totalPlans": int(payload["totalPlans"]),
            "eligiblePlans": int(payload["eligibleCount"]),
            "blockedPlans": blocked,
            "issueCodes": list(set_envelope["issueRefs"]),
            "nextAction": "generate_cards" if blocked == 0 else "review_card_plans",
        }

    def plan_cards(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        selection_handle: str,
        maximum_plans: int = 1000,
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            _fail("CARD_PLAN_REQUEST_INVALID", "idempotencyKey is invalid")
        if (
            isinstance(expected_project_revision, bool)
            or not isinstance(expected_project_revision, int)
            or expected_project_revision < 1
        ):
            _fail("CARD_PLAN_REQUEST_INVALID", "expectedProjectRevision is invalid")
        if not isinstance(selection_handle, str) or not _HANDLE_RE.fullmatch(
            selection_handle
        ):
            _fail("CARD_PLAN_REQUEST_INVALID", "selectionHandle is invalid")
        if (
            isinstance(maximum_plans, bool)
            or not isinstance(maximum_plans, int)
            or not 1 <= maximum_plans <= 1000
        ):
            _fail("CARD_PLAN_REQUEST_INVALID", "maximum plan count is invalid")
        try:
            graph = self._selection.resolve_current_selection_graph(
                audience=audience, selection_handle=selection_handle
            )
        except CandidateSelectionError as error:
            raise CardPlanRuntimeError(error.code, error.message) from error
        project = graph["project"]
        selection_ref = graph["selectionRef"]
        rows = graph["rows"]
        operation_digest = _digest(
            {
                "schema": "study.card-plan.request",
                "schemaVersion": 1,
                "projectId": project_id,
                "expectedProjectRevision": expected_project_revision,
                "selectionDigest": selection_ref["artifactDigest"],
                "policyVersion": CARD_PLAN_POLICY_VERSION,
                "validationRuleSetVersion": CARD_PLAN_VALIDATION_RULE_SET_VERSION,
            }
        )
        operation_id = "card-plan:" + idempotency_key
        try:
            prior = self._projects.get_operation_result(
                audience=audience,
                project_id=project_id,
                operation_id=operation_id,
                operation_digest=operation_digest,
            )
        except ProjectRegistryError as error:
            raise CardPlanRuntimeError(error.code, error.message) from error
        if prior is not None:
            current_stages = {
                "plans_ready",
                "cards_ready",
                "apkg_ready",
                "imported_unverified",
                "anki_data_verified",
                "anki_verified",
            }
            latest = {
                (
                    value.get("artifactId"),
                    value.get("artifactRevision"),
                    value.get("artifactDigest"),
                )
                for value in project.get("latestArtifactRefs", [])
                if isinstance(value, Mapping)
            }
            prior_refs = {
                (
                    value.get("artifactId"),
                    value.get("artifactRevision"),
                    value.get("artifactDigest"),
                )
                for value in prior.get("artifactRefs", [])
                if isinstance(value, Mapping)
            }
            if (
                project.get("workflow", {}).get("artifactStage") not in current_stages
                or len(prior_refs) != 2
                or not prior_refs.issubset(latest)
            ):
                _fail("CARD_PLAN_NOT_CURRENT", "idempotent plan result is stale")
            return self._public_result(audience=audience, committed=prior)
        if project.get("projectId") != project_id:
            _fail("CARD_PLAN_PROJECT_MISMATCH", "selection belongs to another project")
        if project["projectRevision"] != expected_project_revision:
            _fail("PROJECT_REVISION_CONFLICT", "project changed before card planning")
        if project["workflow"]["artifactStage"] != "selection_ready":
            _fail("CARD_PLAN_STAGE_CONFLICT", "card planning is not current")
        if not rows:
            _fail("CARD_PLAN_SELECTION_EMPTY", "selection contains no candidates")
        if len(rows) > maximum_plans:
            _fail(
                "CARD_PLAN_ASYNC_REQUIRED",
                "selection is too large for synchronous deterministic planning",
            )
        language_values = {
            _normalize(str(project["learningContract"].get(field, "auto")))
            for field in ("promptLanguage", "answerLanguage")
        }
        supported_languages = {"auto", "english", "en", "en-us", "en-gb"}
        if not language_values.issubset(supported_languages):
            _fail(
                "UNSUPPORTED_CARD_PLAN",
                "deterministic planning cannot translate the frozen objective",
            )

        drafts = [
            _plan_draft(
                row,
                project_revision=expected_project_revision,
                selection_ref=selection_ref,
                operation_digest=operation_digest,
            )
            for row in rows
        ]
        if len({draft["cardPlanId"] for draft in drafts}) != len(drafts):
            _fail("CARD_PLAN_DUPLICATE", "planning produced a duplicate identity")
        try:
            work, task_input, capability, authorization, input_fingerprint = (
                self._bundle(
                    audience=audience,
                    project=project,
                    selection_ref=selection_ref,
                    operation_digest=operation_digest,
                )
            )
        except TaskManifestError as error:
            raise CardPlanRuntimeError(error.code, error.message) from error
        task_id = "task_card_plan_" + operation_digest[:40]
        try:
            try:
                task = self._tasks.create_task(
                    audience=audience,
                    work_reuse_manifest=work,
                    task_input_manifest=task_input,
                    capability_binding=capability,
                    authorization_binding=authorization,
                    work_units=[
                        {
                            "workUnitId": "deterministic-card-planning",
                            "phase": "planning",
                        }
                    ],
                    cancellable=False,
                    resumability="restart_phase",
                    _task_id=task_id,
                )
            except StudyTaskError as error:
                if error.code != "TASK_ALREADY_EXISTS":
                    raise
                task = self._tasks.get_task(task_id, audience)
                if task.get("inputFingerprint") != input_fingerprint:
                    _fail("TASK_INPUT_MISMATCH", "card planning task input changed")
            if task["state"] not in {"queued", "running", "succeeded"}:
                _fail("TASK_RECOVERY_REQUIRED", "card planning task requires recovery")
            if task["state"] != "succeeded":
                if task["state"] == "queued":
                    task = self._tasks.start_task(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="start-" + operation_digest[:40],
                    )
                unit = task["workUnits"][0]
                if unit["state"] == "pending":
                    task = self._tasks.begin_work_unit(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="begin-" + operation_digest[:40],
                        work_unit_id="deterministic-card-planning",
                    )
                    unit = task["workUnits"][0]
                if unit["state"] != "completed":
                    plan_refs: list[dict[str, Any]] = []
                    all_records: list[dict[str, Any]] = []
                    eligible_refs: list[dict[str, Any]] = []
                    blocked_refs: list[dict[str, Any]] = []
                    for row, draft in zip(rows, drafts, strict=True):
                        publication = self._artifacts.publish_idempotent(
                            audience=audience,
                            project_id=project_id,
                            project_revision=expected_project_revision,
                            artifact_id=draft["cardPlanId"],
                            artifact_revision=1,
                            payload_schema="study.card-plan",
                            payload_schema_version=1,
                            payload=draft,
                            producer=_PRODUCER,
                            parents=[dict(selection_ref), dict(row["candidateRef"])],
                            input_fingerprint=input_fingerprint,
                            completeness={
                                "state": "complete",
                                "omittedLocators": [],
                                "reasonCodes": [],
                            },
                            issue_refs=[],
                        )
                        plan_refs.append(publication.artifact_ref)
                        records, eligible = _validation_records(
                            publication.artifact_ref, draft, row
                        )
                        all_records.extend(records)
                        target = eligible_refs if eligible else blocked_refs
                        target.append(
                            _entity_ref(publication.artifact_ref, draft["cardPlanId"])
                        )
                    set_id = "card_plan_set_" + operation_digest[:40]
                    set_payload = {
                        "cardPlanSetId": set_id,
                        "projectRevision": expected_project_revision,
                        "selectionRef": dict(selection_ref),
                        "cardPlanRefs": [
                            _entity_ref(ref, draft["cardPlanId"])
                            for ref, draft in zip(plan_refs, drafts, strict=True)
                        ],
                        "totalPlans": len(plan_refs),
                        "eligibleCount": len(eligible_refs),
                        "blockedCount": len(blocked_refs),
                        "policyVersion": CARD_PLAN_POLICY_VERSION,
                    }
                    set_issues = ["CARD_PLAN_REVIEW_REQUIRED"] if blocked_refs else []
                    plan_set = self._artifacts.publish_idempotent(
                        audience=audience,
                        project_id=project_id,
                        project_revision=expected_project_revision,
                        artifact_id=set_id,
                        artifact_revision=1,
                        payload_schema="study.card-plan-set",
                        payload_schema_version=1,
                        payload=set_payload,
                        producer=_PRODUCER,
                        parents=[dict(selection_ref), *plan_refs],
                        input_fingerprint=input_fingerprint,
                        completeness={
                            "state": "complete",
                            "omittedLocators": [],
                            "reasonCodes": [],
                        },
                        issue_refs=set_issues,
                    )
                    validation_id = "card_plan_validation_" + operation_digest[:40]
                    validation_payload = {
                        "validationId": validation_id,
                        "projectRevision": expected_project_revision,
                        "cardPlanSetRef": dict(plan_set.artifact_ref),
                        "cardPlanSetDigest": plan_set.artifact_ref["artifactDigest"],
                        "ruleSetVersion": CARD_PLAN_VALIDATION_RULE_SET_VERSION,
                        "inputFingerprint": input_fingerprint,
                        "records": all_records,
                        "eligibleCardPlanRefs": eligible_refs,
                        "blockedCardPlanRefs": blocked_refs,
                    }
                    validation = self._artifacts.publish_idempotent(
                        audience=audience,
                        project_id=project_id,
                        project_revision=expected_project_revision,
                        artifact_id=validation_id,
                        artifact_revision=1,
                        payload_schema="study.card-plan-validation",
                        payload_schema_version=1,
                        payload=validation_payload,
                        producer=_PRODUCER,
                        parents=[plan_set.artifact_ref, *plan_refs],
                        input_fingerprint=input_fingerprint,
                        completeness={
                            "state": "complete",
                            "omittedLocators": [],
                            "reasonCodes": [],
                        },
                        issue_refs=set_issues,
                    )
                    task = self._tasks.complete_work_unit(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="complete-" + operation_digest[:37],
                        work_unit_id="deterministic-card-planning",
                        result_handles=[plan_set.handle, validation.handle],
                    )
                if task["state"] == "running":
                    task = self._tasks.succeed_task(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="succeed-" + operation_digest[:38],
                    )
            final_task = self._tasks.get_task(task_id, audience)
            if len(final_task["resultHandles"]) != 2:
                _fail("CARD_PLAN_RESULT_INVALID", "planning task result is invalid")
            refs_and_envelopes = [
                self._artifacts.resolve_with_ref(handle, audience)
                for handle in final_task["resultHandles"]
            ]
            refs = [value[0] for value in refs_and_envelopes]
            committed = self._projects.commit_artifact_stage(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                operation_id=operation_id,
                operation_digest=operation_digest,
                task_id=task_id,
                artifact_stage="plans_ready",
                artifact_refs=refs,
                artifact_handles=final_task["resultHandles"],
            )
            return self._public_result(audience=audience, committed=committed)
        except (
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskManifestError,
        ) as error:
            raise CardPlanRuntimeError(error.code, error.message) from error


__all__ = [
    "CARD_PLAN_POLICY_VERSION",
    "CARD_PLAN_VALIDATION_RULE_SET_VERSION",
    "CardPlanRuntime",
    "CardPlanRuntimeError",
]
