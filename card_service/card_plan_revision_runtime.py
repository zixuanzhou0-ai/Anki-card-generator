"""Authenticated CardPlan edits and deterministic validation replay.

Agent edits are deliberately narrower than the internal CardPlan schema.  They
cannot change provenance, evidence references, user locks, artifact identity,
or service policy fields.  Every accepted edit republishes the exact plan-set
graph and all eight validation checks before the project revision advances.
"""

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
from .candidate_selection import CandidateSelectionError, CandidateSelectionRuntime
from .card_plan_queries import CardPlanQueryError, CardPlanQueryRuntime
from .card_plan_runtime import (
    CARD_PLAN_POLICY_VERSION,
    CARD_PLAN_VALIDATION_RULE_SET_VERSION,
)
from .project_registry import ProjectRegistry, ProjectRegistryError
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


CARD_PLAN_EDIT_POLICY_VERSION = "card-plan-agent-edit-v1"
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_SUPPORTED_ROUTES = frozenset(
    {"production", "chunk_collocation", "reading_recognition"}
)
_MEDIA_FIELDS = frozenset(
    {"sourceAudio", "sourceVideo", "sentenceTts", "expressionTts"}
)
_LOCK_FIELDS = frozenset(
    {"card.cue", "card.expectedResponse", "card.feedback", "card.mediaPolicy"}
)
_HOST_CATEGORIES = frozenset(
    {"codex_trusted_ui", "native_consent_ui", "desktop_compat"}
)
_CHECK_IDS = (
    "evidence_coverage",
    "scoring_boundary",
    "answer_leakage",
    "duplicate",
    "conflict",
    "template_compatibility",
    "media_generatability",
    "user_lock_preservation",
)
_PRODUCER = {
    "kind": "deterministic-service",
    "component": "card-plan-revision-runtime",
    "version": CARD_PLAN_EDIT_POLICY_VERSION,
}
_COMPONENTS = {
    "cardService": "2.0.0",
    "worker": "not-used",
    "sourceAdapterSetDigest": hashlib.sha256(
        b"card-plan-revision-no-source-adapter-v1"
    ).hexdigest(),
    "gateRuleSetVersion": "candidate-gates-language-v1",
    "compatibilityContractVersion": CARD_PLAN_EDIT_POLICY_VERSION,
}


class CardPlanRevisionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise CardPlanRevisionError(code, message)


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _identity(value: Mapping[str, Any]) -> tuple[str, int, str]:
    try:
        return (
            str(value["artifactId"]),
            int(value["artifactRevision"]),
            str(value["artifactDigest"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CardPlanRevisionError(
            "CARD_PLAN_GRAPH_CORRUPT", "artifact reference is invalid"
        ) from error


def _entity_ref(artifact_ref: Mapping[str, Any], entity_id: str) -> dict[str, Any]:
    return {"artifactRef": dict(artifact_ref), "entityId": entity_id}


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        _fail("CARD_PLAN_EDIT_INVALID", f"{label} must be text")
    result = value.strip()
    if not result or len(result) > maximum:
        _fail("CARD_PLAN_EDIT_INVALID", f"{label} length is invalid")
    if any(ord(character) < 0x20 and character not in "\t\r\n" for character in result):
        _fail("CARD_PLAN_EDIT_INVALID", f"{label} contains control characters")
    return result


def _text_list(
    value: Any,
    label: str,
    *,
    maximum_items: int,
    maximum_text: int,
) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        _fail("CARD_PLAN_EDIT_INVALID", f"{label} is invalid")
    result = [_text(item, label, maximum=maximum_text) for item in value]
    normalized = [_normalize(item) for item in result]
    if len(normalized) != len(set(normalized)):
        _fail("CARD_PLAN_EDIT_INVALID", f"{label} contains duplicates")
    return result


def _state_from_gate(value: str) -> str:
    return {"pass": "passed", "review": "needs_review", "fail": "failed"}.get(
        value, "failed"
    )


def _gate_states(row: Mapping[str, Any]) -> dict[str, str]:
    values = row.get("gate", {}).get("payload", {}).get("results")
    if not isinstance(values, list):
        _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate gate results are invalid")
    result: dict[str, str] = {}
    for value in values:
        gate = value.get("gate") if isinstance(value, Mapping) else None
        state = value.get("state") if isinstance(value, Mapping) else None
        if (
            not isinstance(gate, str)
            or state not in {"pass", "review", "fail"}
            or gate in result
        ):
            _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate gate result is invalid")
        result[gate] = state
    return result


def _answer_leaks(cue: str, answer: str) -> bool:
    normalized_cue = _normalize(cue)
    normalized_answer = _normalize(answer)
    return bool(
        not normalized_answer
        or normalized_cue == normalized_answer
        or (len(normalized_answer) >= 2 and normalized_answer in normalized_cue)
    )


def _strict_entity_identities(
    values: Any, label: str
) -> list[tuple[str, int, str, str]]:
    if not isinstance(values, list) or not values:
        _fail("CARD_PLAN_GRAPH_CORRUPT", f"{label} is invalid")
    result: list[tuple[str, int, str, str]] = []
    for value in values:
        artifact_ref = value.get("artifactRef") if isinstance(value, Mapping) else None
        entity_id = value.get("entityId") if isinstance(value, Mapping) else None
        if not isinstance(artifact_ref, Mapping) or not isinstance(entity_id, str):
            _fail("CARD_PLAN_GRAPH_CORRUPT", f"{label} is invalid")
        result.append((*_identity(artifact_ref), entity_id))
    if len(result) != len(set(result)):
        _fail("CARD_PLAN_GRAPH_CORRUPT", f"{label} contains duplicates")
    return result


def _validate_locks(value: Any) -> set[str]:
    if not isinstance(value, list) or len(value) > len(_LOCK_FIELDS):
        _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan locks are invalid")
    fields: set[str] = set()
    for lock in value:
        if (
            not isinstance(lock, Mapping)
            or not {"field", "lockedAtRevision", "provenance"}.issubset(lock)
            or not set(lock).issubset(
                {"field", "lockedAtRevision", "provenance", "reason"}
            )
        ):
            _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan lock is invalid")
        field = lock.get("field")
        revision = lock.get("lockedAtRevision")
        provenance = lock.get("provenance")
        if (
            field not in _LOCK_FIELDS
            or field in fields
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or not isinstance(provenance, Mapping)
            or set(provenance)
            != {"actor", "attestationDigest", "hostCategory", "recordedAt"}
            or provenance.get("actor") != "user"
            or not isinstance(provenance.get("attestationDigest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", provenance["attestationDigest"])
            or provenance.get("hostCategory") not in _HOST_CATEGORIES
            or not isinstance(provenance.get("recordedAt"), str)
            or not provenance["recordedAt"]
            or len(provenance["recordedAt"]) > 64
        ):
            _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan lock is invalid")
        if "reason" in lock:
            _text(lock["reason"], "lock reason", maximum=500)
        fields.add(str(field))
    return fields


def _changed_fields(operation: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    kind = operation.get("kind")
    if kind == "edit_card_cue" and set(operation) == {"kind", "cue"}:
        cue = operation["cue"]
        if not isinstance(cue, Mapping) or set(cue) != {"kind", "content"}:
            _fail("CARD_PLAN_EDIT_INVALID", "cue fields are invalid")
        if cue.get("kind") != "text":
            _fail("CARD_PLAN_EDIT_INVALID", "only text cues are currently supported")
        return (
            {
                "cue": {
                    "kind": "text",
                    "content": _text(cue.get("content"), "cue", maximum=1000),
                    "mediaRefs": [],
                }
            },
            ["card.cue"],
        )
    if kind == "edit_card_answer" and set(operation) == {
        "kind",
        "expectedResponse",
    }:
        response = operation["expectedResponse"]
        required = {"modality", "coreAnswer", "scoringPoints", "acceptedVariants"}
        if not isinstance(response, Mapping) or set(response) != required:
            _fail("CARD_PLAN_EDIT_INVALID", "expectedResponse fields are invalid")
        if response.get("modality") != "text":
            _fail("CARD_PLAN_EDIT_INVALID", "only text answers are currently supported")
        scoring = _text_list(
            response.get("scoringPoints"),
            "scoring point",
            maximum_items=8,
            maximum_text=500,
        )
        if not scoring:
            _fail("CARD_PLAN_EDIT_INVALID", "at least one scoring point is required")
        return (
            {
                "expectedResponse": {
                    "modality": "text",
                    "coreAnswer": _text(
                        response.get("coreAnswer"), "core answer", maximum=500
                    ),
                    "scoringPoints": scoring,
                    "acceptedVariants": _text_list(
                        response.get("acceptedVariants"),
                        "accepted variant",
                        maximum_items=20,
                        maximum_text=500,
                    ),
                }
            },
            ["card.expectedResponse"],
        )
    if kind == "edit_card_feedback" and set(operation) == {"kind", "feedback"}:
        feedback = operation["feedback"]
        if not isinstance(feedback, Mapping) or set(feedback) != {
            "explanation",
            "examples",
            "nonexamples",
        }:
            _fail("CARD_PLAN_EDIT_INVALID", "feedback fields are invalid")
        return (
            {
                "feedback": {
                    "explanation": _text(
                        feedback.get("explanation"), "explanation", maximum=2000
                    ),
                    "examples": _text_list(
                        feedback.get("examples"),
                        "example",
                        maximum_items=10,
                        maximum_text=2000,
                    ),
                    "nonexamples": _text_list(
                        feedback.get("nonexamples"),
                        "nonexample",
                        maximum_items=10,
                        maximum_text=2000,
                    ),
                }
            },
            ["card.feedback"],
        )
    if kind == "edit_media_policy" and set(operation) == {"kind", "mediaPolicy"}:
        media = operation["mediaPolicy"]
        if (
            not isinstance(media, Mapping)
            or set(media) != _MEDIA_FIELDS
            or any(not isinstance(media[field], bool) for field in _MEDIA_FIELDS)
        ):
            _fail("CARD_PLAN_EDIT_INVALID", "mediaPolicy fields are invalid")
        return ({"mediaPolicy": dict(media)}, ["card.mediaPolicy"])
    _fail("CARD_PLAN_EDIT_INVALID", "operation is not an agent-writable CardPlan edit")


class CardPlanRevisionRuntime:
    """Republish edited or revalidated CardPlan graphs under revision CAS."""

    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        tasks: StudyTaskCoordinator,
        candidate_selection: CandidateSelectionRuntime,
        card_plan_queries: CardPlanQueryRuntime,
    ) -> None:
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._tasks = tasks
        self._selection = candidate_selection
        self._queries = card_plan_queries

    def _bundle(
        self,
        *,
        action_id: str,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        input_refs: Sequence[Mapping[str, Any]],
        operation_digest: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        subject = {
            "kind": "project_task",
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "inputArtifacts": [
                {
                    "artifactId": ref["artifactId"],
                    "artifactRevision": ref["artifactRevision"],
                    "artifactDigest": ref["artifactDigest"],
                }
                for ref in input_refs
            ],
            "sourceSnapshotDigests": [],
            "learningContractRevision": project["learningContract"]["contractRevision"],
        }
        work, work_digest = build_work_reuse_manifest(
            action_id=action_id,
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
                    "compatibilityContractVersion": CARD_PLAN_EDIT_POLICY_VERSION,
                }
            ]
        )
        authorization, authorization_digest = build_authorization_binding(
            audience=audience,
            service_instance_id=self._service_instance_id,
            bindings=[],
        )
        task_input, input_fingerprint = build_task_input_manifest(
            action_id=action_id,
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

    def _start_task(
        self,
        *,
        audience: ArtifactAudienceBinding,
        action_id: str,
        operation_digest: str,
        bundle: tuple[
            dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str
        ],
    ) -> tuple[dict[str, Any], str, str]:
        work, task_input, capability, authorization, input_fingerprint = bundle
        task_id = "task_card_plan_revision_" + operation_digest[:36]
        work_unit_id = action_id.replace("_", "-")
        try:
            try:
                task = self._tasks.create_task(
                    audience=audience,
                    work_reuse_manifest=work,
                    task_input_manifest=task_input,
                    capability_binding=capability,
                    authorization_binding=authorization,
                    work_units=[{"workUnitId": work_unit_id, "phase": "planning"}],
                    cancellable=False,
                    resumability="restart_phase",
                    _task_id=task_id,
                )
            except StudyTaskError as error:
                if error.code != "TASK_ALREADY_EXISTS":
                    raise
                task = self._tasks.get_task(task_id, audience)
                if task.get("inputFingerprint") != input_fingerprint:
                    _fail("TASK_INPUT_MISMATCH", "card plan revision input changed")
            if task["state"] == "queued":
                task = self._tasks.start_task(
                    task_id,
                    audience,
                    expected_revision=task["taskRevision"],
                    operation_id="start-" + operation_digest[:40],
                )
            if task["state"] == "running":
                unit = task["workUnits"][0]
                if unit["state"] == "pending":
                    task = self._tasks.begin_work_unit(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="begin-" + operation_digest[:40],
                        work_unit_id=work_unit_id,
                    )
            if task["state"] == "succeeded":
                return task, input_fingerprint, work_unit_id
            if task["state"] != "running" or task["workUnits"][0]["state"] not in {
                "active",
                "completed",
            }:
                _fail("TASK_RECOVERY_REQUIRED", "card plan revision requires recovery")
            return task, input_fingerprint, work_unit_id
        except StudyTaskError as error:
            raise CardPlanRevisionError(error.code, error.message) from error

    def _handle_identities(
        self,
        handles: Sequence[str],
        audience: ArtifactAudienceBinding,
    ) -> list[tuple[str, int, str]]:
        identities: list[tuple[str, int, str]] = []
        try:
            for handle in handles:
                ref, _envelope = self._artifacts.resolve_with_ref(handle, audience)
                identities.append(_identity(ref))
        except ArtifactRegistryError as error:
            raise CardPlanRevisionError(error.code, error.message) from error
        return identities

    def _finish_task(
        self,
        *,
        audience: ArtifactAudienceBinding,
        task: Mapping[str, Any],
        operation_digest: str,
        work_unit_id: str,
        result_handles: Sequence[str],
    ) -> dict[str, Any]:
        try:
            if task["state"] == "succeeded":
                if self._handle_identities(
                    task.get("resultHandles", []), audience
                ) != self._handle_identities(result_handles, audience):
                    _fail("CARD_PLAN_RESULT_INVALID", "recovered task result changed")
                return dict(task)
            if task["workUnits"][0]["state"] == "completed":
                if self._handle_identities(
                    task["workUnits"][0].get("resultHandles", []), audience
                ) != self._handle_identities(result_handles, audience):
                    _fail(
                        "CARD_PLAN_RESULT_INVALID",
                        "recovered work-unit result changed",
                    )
                updated = dict(task)
            else:
                updated = self._tasks.complete_work_unit(
                    task["taskId"],
                    audience,
                    expected_revision=task["taskRevision"],
                    operation_id="complete-" + operation_digest[:37],
                    work_unit_id=work_unit_id,
                    result_handles=result_handles,
                )
            return self._tasks.succeed_task(
                updated["taskId"],
                audience,
                expected_revision=updated["taskRevision"],
                operation_id="succeed-" + operation_digest[:38],
            )
        except StudyTaskError as error:
            raise CardPlanRevisionError(error.code, error.message) from error

    def _current_graph(
        self,
        *,
        audience: ArtifactAudienceBinding,
        plan_set_handle: str,
    ) -> dict[str, Any]:
        try:
            raw = self._queries.resolve_current_plan_graph(
                audience=audience, plan_set_handle=plan_set_handle
            )
            selection_ref = raw["planSet"]["payload"]["selectionRef"]
            selection = self._selection.resolve_current_selection_graph(
                audience=audience,
                selection_handle=self._artifacts.issue_handle(selection_ref, audience),
            )
        except (
            CardPlanQueryError,
            CandidateSelectionError,
            ArtifactRegistryError,
        ) as error:
            raise CardPlanRevisionError(error.code, error.message) from error
        rows_by_candidate = {
            _identity(row["candidateRef"]): row for row in selection["rows"]
        }
        plans: list[dict[str, Any]] = []
        for plan_ref, plan_id, _identity_value in raw["planRefs"]:
            try:
                envelope = self._artifacts.verify_ref(plan_ref, audience)
            except ArtifactRegistryError as error:
                raise CardPlanRevisionError(error.code, error.message) from error
            payload = envelope.get("payload")
            candidate_ref = (
                payload.get("candidateRef") if isinstance(payload, Mapping) else None
            )
            payload_selection_ref = (
                payload.get("selectionRef") if isinstance(payload, Mapping) else None
            )
            if (
                envelope.get("payloadSchema") != "study.card-plan"
                or not isinstance(payload, Mapping)
                or payload.get("cardPlanId") != plan_id
                or not isinstance(candidate_ref, Mapping)
                or not isinstance(payload_selection_ref, Mapping)
                or _identity(payload_selection_ref) != _identity(selection_ref)
                or _identity(candidate_ref) not in rows_by_candidate
            ):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan membership is invalid")
            plans.append(
                {
                    "ref": dict(plan_ref),
                    "id": plan_id,
                    "payload": _clone(payload),
                    "row": rows_by_candidate[_identity(candidate_ref)],
                }
            )
        return {**raw, "selection": selection, "plans": plans}

    def _validate_plans(
        self, plans: Sequence[Mapping[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        duplicate_counts: dict[tuple[str, str], int] = {}
        for item in plans:
            payload = item["payload"]
            cue = payload.get("cue")
            response = payload.get("expectedResponse")
            if not isinstance(cue, Mapping) or not isinstance(response, Mapping):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan response is invalid")
            key = (
                _normalize(str(cue.get("content", ""))),
                _normalize(str(response.get("coreAnswer", ""))),
            )
            duplicate_counts[key] = duplicate_counts.get(key, 0) + 1

        all_records: list[dict[str, Any]] = []
        eligible: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for item in plans:
            plan_ref = item["ref"]
            plan = item["payload"]
            row = item["row"]
            candidate = row.get("candidate", {}).get("payload")
            if not isinstance(candidate, Mapping):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate payload is invalid")
            objective = candidate.get("objective")
            semantic = candidate.get("semanticUnit")
            evidence = candidate.get("evidenceAnchors")
            if (
                not isinstance(objective, Mapping)
                or not isinstance(semantic, Mapping)
                or not isinstance(evidence, list)
            ):
                _fail(
                    "CARD_PLAN_GRAPH_CORRUPT", "candidate learning fields are invalid"
                )
            cue = plan.get("cue")
            response = plan.get("expectedResponse")
            feedback = plan.get("feedback")
            media = plan.get("mediaPolicy")
            locks = plan.get("userLocks")
            if not all(
                isinstance(value, Mapping) for value in (cue, response, feedback, media)
            ):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan fields are invalid")
            _validate_locks(locks)
            cue_content = _text(cue.get("content"), "cue", maximum=1000)
            core_answer = _text(response.get("coreAnswer"), "core answer", maximum=500)
            scoring = _text_list(
                response.get("scoringPoints"),
                "scoring point",
                maximum_items=8,
                maximum_text=500,
            )
            variants = _text_list(
                response.get("acceptedVariants"),
                "accepted variant",
                maximum_items=20,
                maximum_text=500,
            )
            explanation = _text(
                feedback.get("explanation"), "explanation", maximum=2000
            )
            examples = _text_list(
                feedback.get("examples"),
                "example",
                maximum_items=10,
                maximum_text=2000,
            )
            nonexamples = _text_list(
                feedback.get("nonexamples"),
                "nonexample",
                maximum_items=10,
                maximum_text=2000,
            )
            evidence_refs = feedback.get("evidenceRefs")
            candidate_ref = plan.get("candidateRef")
            objective_ref = plan.get("objectiveRef")
            if not isinstance(candidate_ref, Mapping) or not isinstance(
                objective_ref, Mapping
            ):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan candidate is invalid")
            objective_artifact_ref = objective_ref.get("artifactRef")
            if (
                not isinstance(objective_artifact_ref, Mapping)
                or _identity(objective_artifact_ref) != _identity(candidate_ref)
                or objective_ref.get("entityId") != objective.get("objectiveId")
            ):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan objective is invalid")
            expected_evidence_identities = []
            for anchor in evidence:
                evidence_id = (
                    anchor.get("evidenceId") if isinstance(anchor, Mapping) else None
                )
                if not isinstance(evidence_id, str):
                    _fail("CARD_PLAN_GRAPH_CORRUPT", "candidate evidence is invalid")
                expected_evidence_identities.append(
                    (*_identity(candidate_ref), evidence_id)
                )
            actual_evidence_identities = _strict_entity_identities(
                evidence_refs, "card plan evidence"
            )
            gates = _gate_states(row)

            evidence_state = _state_from_gate(gates.get("evidence", "fail"))
            if actual_evidence_identities != expected_evidence_identities:
                evidence_state = "failed"
            meaning = str(semantic.get("meaningOrFunction", ""))
            if (
                _normalize(explanation) != _normalize(meaning)
                or examples
                or nonexamples
            ) and evidence_state == "passed":
                evidence_state = "needs_review"

            boundary = objective.get("scoringBoundary")
            score_state = _state_from_gate(gates.get("scoreability", "fail"))
            boundary_ok = (
                isinstance(boundary, list)
                and len(boundary) == 1
                and len(scoring) == 1
                and _normalize(str(boundary[0])) == _normalize(core_answer)
                and _normalize(scoring[0]) == _normalize(core_answer)
            )
            if not boundary_ok:
                score_state = "failed"
            elif any(
                _normalize(value) != _normalize(core_answer) for value in variants
            ):
                score_state = "needs_review"

            key = (_normalize(cue_content), _normalize(core_answer))
            template_state = (
                "passed"
                if plan.get("route") in _SUPPORTED_ROUTES
                and plan.get("route") == objective.get("route")
                and cue.get("kind") == "text"
                and cue.get("mediaRefs") == []
                and response.get("modality") == "text"
                else "failed"
            )
            media_state = (
                "passed"
                if set(media) == _MEDIA_FIELDS
                and all(media[field] is False for field in _MEDIA_FIELDS)
                else "failed"
            )
            checks = {
                "evidence_coverage": evidence_state,
                "scoring_boundary": score_state,
                "answer_leakage": (
                    "failed" if _answer_leaks(cue_content, core_answer) else "passed"
                ),
                "duplicate": "failed" if duplicate_counts[key] > 1 else "passed",
                "conflict": _state_from_gate(gates.get("conflict", "fail")),
                "template_compatibility": template_state,
                "media_generatability": media_state,
                "user_lock_preservation": "passed",
            }
            plan["validation"] = {
                "answerLeakage": (
                    "pass" if checks["answer_leakage"] == "passed" else "fail"
                ),
                "scoreability": {
                    "passed": "pass",
                    "needs_review": "review",
                    "failed": "fail",
                }[score_state],
                "evidence": {
                    "passed": "pass",
                    "needs_review": "review",
                    "failed": "fail",
                }[evidence_state],
                "templateCompatibility": (
                    "pass" if template_state == "passed" else "fail"
                ),
            }
            target_ref = _entity_ref(plan_ref, plan["cardPlanId"])
            for check_id in _CHECK_IDS:
                refs = (
                    evidence_refs
                    if check_id in {"evidence_coverage", "scoring_boundary", "conflict"}
                    else []
                )
                all_records.append(
                    {
                        "cardPlanRef": target_ref,
                        "checkId": check_id,
                        "state": checks[check_id],
                        "producer": dict(_PRODUCER),
                        "evidenceRefs": _clone(refs),
                    }
                )
            is_eligible = row.get("eligibility") == "recommended" and all(
                state == "passed" for state in checks.values()
            )
            (eligible if is_eligible else blocked).append(target_ref)
        return all_records, eligible, blocked

    def _publish_graph(
        self,
        *,
        audience: ArtifactAudienceBinding,
        graph: Mapping[str, Any],
        plans: list[dict[str, Any]],
        input_fingerprint: str,
        project_revision: int,
        edited_index: int | None,
    ) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
        if edited_index is not None:
            self._validate_plans(plans)
            item = plans[edited_index]
            previous_ref = item["ref"]
            publication = self._artifacts.publish_idempotent(
                audience=audience,
                project_id=graph["project"]["projectId"],
                project_revision=project_revision,
                artifact_id=previous_ref["artifactId"],
                artifact_revision=previous_ref["artifactRevision"] + 1,
                payload_schema="study.card-plan",
                payload_schema_version=1,
                payload=item["payload"],
                producer=_PRODUCER,
                parents=[
                    previous_ref,
                    item["payload"]["selectionRef"],
                    item["payload"]["candidateRef"],
                ],
                input_fingerprint=input_fingerprint,
                completeness={
                    "state": "complete",
                    "omittedLocators": [],
                    "reasonCodes": [],
                },
                issue_refs=[],
            )
            item["ref"] = publication.artifact_ref

        records, eligible, blocked = self._validate_plans(plans)
        plan_entities = [_entity_ref(item["ref"], item["id"]) for item in plans]
        old_set_ref = graph["planSetRef"]
        set_payload = _clone(graph["planSet"]["payload"])
        set_payload.update(
            {
                "projectRevision": project_revision,
                "cardPlanRefs": plan_entities,
                "totalPlans": len(plans),
                "eligibleCount": len(eligible),
                "blockedCount": len(blocked),
                "policyVersion": CARD_PLAN_POLICY_VERSION,
            }
        )
        issues = ["CARD_PLAN_REVIEW_REQUIRED"] if blocked else []
        plan_set = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=graph["project"]["projectId"],
            project_revision=project_revision,
            artifact_id=old_set_ref["artifactId"],
            artifact_revision=old_set_ref["artifactRevision"] + 1,
            payload_schema="study.card-plan-set",
            payload_schema_version=1,
            payload=set_payload,
            producer=_PRODUCER,
            parents=[
                old_set_ref,
                graph["selection"]["selectionRef"],
                *[item["ref"] for item in plans],
            ],
            input_fingerprint=input_fingerprint,
            completeness={
                "state": "complete",
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=issues,
        )
        old_validation_ref = graph["validationRef"]
        validation_payload = {
            "validationId": graph["validation"]["payload"]["validationId"],
            "projectRevision": project_revision,
            "cardPlanSetRef": dict(plan_set.artifact_ref),
            "cardPlanSetDigest": plan_set.artifact_ref["artifactDigest"],
            "ruleSetVersion": CARD_PLAN_VALIDATION_RULE_SET_VERSION,
            "inputFingerprint": input_fingerprint,
            "records": records,
            "eligibleCardPlanRefs": eligible,
            "blockedCardPlanRefs": blocked,
        }
        validation = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=graph["project"]["projectId"],
            project_revision=project_revision,
            artifact_id=old_validation_ref["artifactId"],
            artifact_revision=old_validation_ref["artifactRevision"] + 1,
            payload_schema="study.card-plan-validation",
            payload_schema_version=1,
            payload=validation_payload,
            producer=_PRODUCER,
            parents=[
                old_validation_ref,
                plan_set.artifact_ref,
                *[item["ref"] for item in plans],
            ],
            input_fingerprint=input_fingerprint,
            completeness={
                "state": "complete",
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=issues,
        )
        refs = [plan_set.artifact_ref, validation.artifact_ref]
        handles = [plan_set.handle, validation.handle]
        if edited_index is not None:
            refs.insert(0, plans[edited_index]["ref"])
            handles.insert(
                0, self._artifacts.issue_handle(plans[edited_index]["ref"], audience)
            )
        summary = {
            "totalPlans": len(plans),
            "eligiblePlans": len(eligible),
            "blockedPlans": len(blocked),
            "issueCodes": issues,
        }
        return refs, handles, summary

    def _prior_result(
        self,
        *,
        audience: ArtifactAudienceBinding,
        committed: Mapping[str, Any],
        edited: bool,
    ) -> dict[str, Any]:
        schemas: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for ref in committed["artifactRefs"]:
            try:
                envelope = self._artifacts.verify_ref(ref, audience)
            except ArtifactRegistryError as error:
                raise CardPlanRevisionError(error.code, error.message) from error
            schemas[envelope["payloadSchema"]] = (dict(ref), envelope)
        required = {"study.card-plan-set", "study.card-plan-validation"}
        if edited:
            required.add("study.card-plan")
        if set(schemas) != required or len(committed["artifactRefs"]) != len(required):
            _fail("CARD_PLAN_RESULT_INVALID", "card plan revision result is incomplete")
        try:
            project = self._projects.get_project(committed["projectId"], audience)
        except ProjectRegistryError as error:
            raise CardPlanRevisionError(error.code, error.message) from error
        latest = {
            _identity(value)
            for value in project.get("latestArtifactRefs", [])
            if isinstance(value, Mapping)
        }
        committed_identities = {
            _identity(value)
            for value in committed["artifactRefs"]
            if isinstance(value, Mapping)
        }
        if (
            project.get("workflow", {}).get("artifactStage") != "plans_ready"
            or len(committed_identities) != len(required)
            or not committed_identities.issubset(latest)
        ):
            _fail("CARD_PLAN_NOT_CURRENT", "card plan revision result is stale")
        set_ref, set_envelope = schemas["study.card-plan-set"]
        validation_ref, _ = schemas["study.card-plan-validation"]
        payload = set_envelope["payload"]
        result = {
            "schemaVersion": 1,
            "projectId": committed["projectId"],
            "projectRevision": committed["projectRevision"],
            "artifactStage": "plans_ready",
            "taskId": committed["taskId"],
            "planSetHandle": self._artifacts.issue_handle(set_ref, audience),
            "validationHandle": self._artifacts.issue_handle(validation_ref, audience),
            "totalPlans": payload["totalPlans"],
            "eligiblePlans": payload["eligibleCount"],
            "blockedPlans": payload["blockedCount"],
            "issueCodes": list(set_envelope["issueRefs"]),
            "nextAction": (
                "generate_cards"
                if payload["blockedCount"] == 0
                else "review_card_plans"
            ),
        }
        if edited:
            plan_ref, plan_envelope = schemas["study.card-plan"]
            result["cardPlanHandle"] = self._artifacts.issue_handle(plan_ref, audience)
            result["cardPlanId"] = plan_envelope["payload"]["cardPlanId"]
        return result

    def _execute(
        self,
        *,
        action_id: str,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        plan_set_handle: str,
        card_plan_handle: str | None,
        operation: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            _fail("CARD_PLAN_EDIT_INVALID", "idempotencyKey is invalid")
        if (
            isinstance(expected_project_revision, bool)
            or not isinstance(expected_project_revision, int)
            or expected_project_revision < 1
        ):
            _fail("CARD_PLAN_EDIT_INVALID", "expectedProjectRevision is invalid")
        for value, label in ((plan_set_handle, "planSetHandle"),):
            if not isinstance(value, str) or not _HANDLE_RE.fullmatch(value):
                _fail("CARD_PLAN_EDIT_INVALID", f"{label} is invalid")
        if card_plan_handle is not None and (
            not isinstance(card_plan_handle, str)
            or not _HANDLE_RE.fullmatch(card_plan_handle)
        ):
            _fail("CARD_PLAN_EDIT_INVALID", "cardPlanHandle is invalid")
        try:
            preliminary_set_ref, preliminary_set = self._artifacts.resolve_with_ref(
                plan_set_handle, audience
            )
            project = self._projects.get_project(
                preliminary_set_ref["projectId"], audience
            )
            preliminary_plan_ref = None
            if card_plan_handle is not None:
                preliminary_plan_ref, preliminary_plan = (
                    self._artifacts.resolve_with_ref(card_plan_handle, audience)
                )
                if preliminary_plan.get("payloadSchema") != "study.card-plan":
                    _fail("CARD_PLAN_EDIT_INVALID", "cardPlanHandle is not a card plan")
        except (ArtifactRegistryError, ProjectRegistryError) as error:
            raise CardPlanRevisionError(error.code, error.message) from error
        if preliminary_set.get("payloadSchema") != "study.card-plan-set":
            _fail("CARD_PLAN_EDIT_INVALID", "planSetHandle is not a card plan set")
        normalized_change = None
        changed_fields: list[str] = []
        if operation is not None:
            normalized_change, changed_fields = _changed_fields(operation)
        operation_digest = _digest(
            {
                "schema": f"study.{action_id}.request",
                "schemaVersion": 1,
                "projectId": project_id,
                "expectedProjectRevision": expected_project_revision,
                "planSetDigest": preliminary_set_ref["artifactDigest"],
                "cardPlanDigest": (
                    None
                    if preliminary_plan_ref is None
                    else preliminary_plan_ref["artifactDigest"]
                ),
                "operation": operation,
                "policyVersion": CARD_PLAN_EDIT_POLICY_VERSION,
                "validationRuleSetVersion": CARD_PLAN_VALIDATION_RULE_SET_VERSION,
            }
        )
        operation_id = (
            "card-plan-edit:" if operation is not None else "card-plan-validate:"
        ) + idempotency_key
        try:
            prior = self._projects.get_operation_result(
                audience=audience,
                project_id=project_id,
                operation_id=operation_id,
                operation_digest=operation_digest,
            )
        except ProjectRegistryError as error:
            raise CardPlanRevisionError(error.code, error.message) from error
        if prior is not None:
            return self._prior_result(
                audience=audience, committed=prior, edited=operation is not None
            )
        if project.get("projectId") != project_id:
            _fail("CARD_PLAN_PROJECT_MISMATCH", "plan set belongs to another project")
        if project.get("projectRevision") != expected_project_revision:
            _fail(
                "PROJECT_REVISION_CONFLICT", "project changed before card plan revision"
            )
        if project.get("workflow", {}).get("artifactStage") != "plans_ready":
            _fail("CARD_PLAN_STAGE_CONFLICT", "card plan revision is not current")
        graph = self._current_graph(audience=audience, plan_set_handle=plan_set_handle)
        plans = graph["plans"]
        edited_index = None
        if operation is not None:
            assert preliminary_plan_ref is not None and normalized_change is not None
            matches = [
                index
                for index, item in enumerate(plans)
                if _identity(item["ref"]) == _identity(preliminary_plan_ref)
            ]
            if len(matches) != 1:
                _fail("CARD_PLAN_NOT_CURRENT", "card plan is not a current set member")
            edited_index = matches[0]
            plan = plans[edited_index]["payload"]
            locked = _validate_locks(plan.get("userLocks"))
            if locked.intersection(changed_fields):
                _fail(
                    "CARD_PLAN_FIELD_LOCKED", "agent edit cannot overwrite a user lock"
                )
            for field, value in normalized_change.items():
                if field == "feedback":
                    value["evidenceRefs"] = _clone(plan["feedback"]["evidenceRefs"])
                plan[field] = value
            history = plan.get("editHistory", [])
            if not isinstance(history, list) or len(history) >= 100:
                _fail(
                    "CARD_PLAN_EDIT_HISTORY_INVALID",
                    "card plan edit history is invalid",
                )
            plan["editHistory"] = [
                *history,
                {
                    "actor": "agent",
                    "taskId": "task_card_plan_revision_" + operation_digest[:36],
                    "operation": operation["kind"],
                    "changedFields": changed_fields,
                    "baseArtifactDigest": preliminary_plan_ref["artifactDigest"],
                },
            ]
            plan["projectRevision"] = expected_project_revision

        input_refs = [preliminary_set_ref]
        if preliminary_plan_ref is not None:
            input_refs.append(preliminary_plan_ref)
        try:
            bundle = self._bundle(
                action_id=action_id,
                audience=audience,
                project=project,
                input_refs=input_refs,
                operation_digest=operation_digest,
            )
            task, input_fingerprint, work_unit_id = self._start_task(
                audience=audience,
                action_id=action_id,
                operation_digest=operation_digest,
                bundle=bundle,
            )
            refs, handles, _summary = self._publish_graph(
                audience=audience,
                graph=graph,
                plans=plans,
                input_fingerprint=input_fingerprint,
                project_revision=expected_project_revision,
                edited_index=edited_index,
            )
            final_task = self._finish_task(
                audience=audience,
                task=task,
                operation_digest=operation_digest,
                work_unit_id=work_unit_id,
                result_handles=handles,
            )
            committed = self._projects.commit_artifact_stage(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                operation_id=operation_id,
                operation_digest=operation_digest,
                task_id=final_task["taskId"],
                artifact_stage="plans_ready",
                artifact_refs=refs,
                artifact_handles=handles,
            )
            return self._prior_result(
                audience=audience, committed=committed, edited=operation is not None
            )
        except (
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskManifestError,
        ) as error:
            raise CardPlanRevisionError(error.code, error.message) from error

    def edit_card_plan(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        plan_set_handle: str,
        card_plan_handle: str,
        operation: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._execute(
            action_id="edit_card_plan",
            audience=audience,
            project_id=project_id,
            expected_project_revision=expected_project_revision,
            idempotency_key=idempotency_key,
            plan_set_handle=plan_set_handle,
            card_plan_handle=card_plan_handle,
            operation=operation,
        )

    def validate_card_plans(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        plan_set_handle: str,
    ) -> dict[str, Any]:
        return self._execute(
            action_id="validate_card_plans",
            audience=audience,
            project_id=project_id,
            expected_project_revision=expected_project_revision,
            idempotency_key=idempotency_key,
            plan_set_handle=plan_set_handle,
            card_plan_handle=None,
            operation=None,
        )


__all__ = [
    "CARD_PLAN_EDIT_POLICY_VERSION",
    "CardPlanRevisionError",
    "CardPlanRevisionRuntime",
]
