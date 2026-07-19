"""Deterministic, authenticated portfolio selection for learning candidates."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .candidate_queries import CandidateQueryError, CandidateQueryRuntime
from .project_registry import ProjectRegistry, ProjectRegistryError
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


SELECTION_POLICY_VERSION = "portfolio-coverage-v1"
REVIEW_DEBT_POLICY_VERSION = "review-debt-conservative-v1"
_OPERATIONS = frozenset({"add", "remove", "accept_recommended"})
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_MAX_CANDIDATES = 1000
_COMPONENTS = {
    "cardService": "2.0.0",
    "worker": "not-used",
    "sourceAdapterSetDigest": hashlib.sha256(
        b"candidate-selection-no-source-adapter-v1"
    ).hexdigest(),
    "gateRuleSetVersion": "candidate-gates-language-v1",
}
_PRODUCER = {
    "kind": "deterministic-service",
    "component": "candidate-selection-runtime",
    "version": SELECTION_POLICY_VERSION,
}


class CandidateSelectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise CandidateSelectionError(code, message)


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _ref_identity(value: Mapping[str, Any]) -> tuple[str, int, str]:
    artifact_id = value.get("artifactId")
    revision = value.get("artifactRevision")
    digest = value.get("artifactDigest")
    if (
        not isinstance(artifact_id, str)
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or not isinstance(digest, str)
    ):
        _fail("SELECTION_GRAPH_CORRUPT", "artifact identity is invalid")
    return artifact_id, revision, digest


def _review_cost(row: Mapping[str, Any]) -> int:
    scores = row["candidate"]["payload"].get("scores")
    value = scores.get("reviewCost") if isinstance(scores, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 30
    if not math.isfinite(float(value)):
        return 30
    return min(120, max(3, int(math.ceil(float(value)))))


def _transfer_score(row: Mapping[str, Any]) -> float:
    scores = row["candidate"]["payload"].get("scores")
    value = scores.get("bottleneckAndTransfer") if isinstance(scores, Mapping) else 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    if not math.isfinite(float(value)):
        return 0.0
    return min(1.0, max(0.0, float(value)))


def _route(row: Mapping[str, Any]) -> str:
    objective = row["candidate"]["payload"].get("objective")
    route = objective.get("route") if isinstance(objective, Mapping) else None
    if not isinstance(route, str):
        _fail("SELECTION_GRAPH_CORRUPT", "candidate route is invalid")
    return route


def _source_id(row: Mapping[str, Any]) -> str:
    value = row["candidate"]["payload"].get("sourceId")
    if not isinstance(value, str):
        _fail("SELECTION_GRAPH_CORRUPT", "candidate source is invalid")
    return value


def _candidate_form(row: Mapping[str, Any]) -> str:
    unit = row["candidate"]["payload"].get("semanticUnit")
    value = unit.get("form") if isinstance(unit, Mapping) else None
    return value.casefold().strip() if isinstance(value, str) else row["candidateId"]


def _blocked_reason(row: Mapping[str, Any]) -> str | None:
    eligibility = row["eligibility"]
    if eligibility in {"hard_blocked", "excluded", "duplicate"}:
        return "SELECTION_CANDIDATE_" + eligibility.upper()
    results = row["gate"]["payload"].get("results")
    if not isinstance(results, list):
        return "SELECTION_GATE_GRAPH_INVALID"
    for result in results:
        if (
            isinstance(result, Mapping)
            and result.get("gate") in {"evidence", "conflict", "security"}
            and result.get("state") == "fail"
        ):
            return "SELECTION_HARD_GATE_FAILED"
    return None


class CandidateSelectionRuntime:
    """Create a local SelectionArtifact without model or network participation."""

    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        tasks: StudyTaskCoordinator,
        candidate_queries: CandidateQueryRuntime,
    ) -> None:
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._tasks = tasks
        self._queries = candidate_queries

    @staticmethod
    def _budget(
        value: Mapping[str, Any] | None, learning_contract: Mapping[str, Any]
    ) -> dict[str, int]:
        if value is not None and not isinstance(value, Mapping):
            _fail("SELECTION_REQUEST_INVALID", "budget must be an object")
        raw = dict(value or {})
        if not set(raw).issubset({"maxNewCards", "targetDailyReviewMinutes"}):
            _fail("SELECTION_REQUEST_INVALID", "budget fields are invalid")
        contract_max = learning_contract.get("maxNewCards", 20)
        if (
            isinstance(contract_max, bool)
            or not isinstance(contract_max, int)
            or not 1 <= contract_max <= 10000
        ):
            _fail("SELECTION_CONTRACT_INVALID", "learning budget is invalid")
        maximum = raw.get("maxNewCards", contract_max)
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or not 1 <= maximum <= _MAX_CANDIDATES
            or maximum > contract_max
        ):
            _fail(
                "SELECTION_BUDGET_EXCEEDED",
                "maxNewCards exceeds the current Learning Contract",
            )
        result = {"maxNewCards": maximum}
        daily = raw.get(
            "targetDailyReviewMinutes",
            learning_contract.get("targetDailyReviewMinutes"),
        )
        if daily is not None:
            if (
                isinstance(daily, bool)
                or not isinstance(daily, int)
                or not 1 <= daily <= 1440
            ):
                _fail(
                    "SELECTION_REQUEST_INVALID",
                    "targetDailyReviewMinutes is invalid",
                )
            result["targetDailyReviewMinutes"] = daily
        return result

    @staticmethod
    def _validate_handles(operation: str, handles: Sequence[str] | None) -> list[str]:
        if operation not in _OPERATIONS:
            _fail("SELECTION_REQUEST_INVALID", "selection operation is invalid")
        if handles is None:
            normalized: list[str] = []
        elif isinstance(handles, Sequence) and not isinstance(handles, (str, bytes)):
            normalized = list(handles)
        else:
            _fail("SELECTION_REQUEST_INVALID", "candidateHandles must be a list")
        if (
            len(normalized) > _MAX_CANDIDATES
            or any(
                not isinstance(value, str) or not _HANDLE_RE.fullmatch(value)
                for value in normalized
            )
            or len(normalized) != len(set(normalized))
        ):
            _fail("SELECTION_REQUEST_INVALID", "candidateHandles are invalid")
        if operation in {"add", "remove"} and not normalized:
            _fail("SELECTION_REQUEST_INVALID", "this operation requires candidates")
        if operation == "accept_recommended" and normalized:
            _fail(
                "SELECTION_REQUEST_INVALID",
                "accept_recommended does not accept candidateHandles",
            )
        return normalized

    def _current_selection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        discovery_ref: Mapping[str, Any],
        member_refs: Mapping[str, tuple[str, int, str]],
    ) -> tuple[dict[str, Any] | None, set[str]]:
        stage = project.get("workflow", {}).get("artifactStage")
        if stage in {"empty", "sources_ready", "candidates_ready"}:
            return None, set()
        values = [
            value
            for value in project.get("latestArtifactRefs", [])
            if isinstance(value, Mapping)
            and value.get("payloadSchema") == "study.portfolio-selection"
        ]
        if not values:
            return None, set()
        highest = max(int(value.get("projectRevision", 0)) for value in values)
        refs = [
            dict(value) for value in values if value.get("projectRevision") == highest
        ]
        if len(refs) != 1:
            _fail("SELECTION_GRAPH_CORRUPT", "current selection is ambiguous")
        try:
            envelope = self._artifacts.verify_ref(refs[0], audience)
        except ArtifactRegistryError as error:
            raise CandidateSelectionError(error.code, error.message) from error
        payload = envelope.get("payload")
        if (
            not isinstance(payload, Mapping)
            or payload.get("discoveryRef") != dict(discovery_ref)
            or not isinstance(payload.get("candidateRefs"), list)
        ):
            _fail("SELECTION_GRAPH_CORRUPT", "current selection graph is invalid")
        selected: set[str] = set()
        for entity in payload["candidateRefs"]:
            artifact_ref = (
                entity.get("artifactRef") if isinstance(entity, Mapping) else None
            )
            candidate_id = (
                entity.get("entityId") if isinstance(entity, Mapping) else None
            )
            if (
                not isinstance(artifact_ref, Mapping)
                or not isinstance(candidate_id, str)
                or member_refs.get(candidate_id) != _ref_identity(artifact_ref)
                or candidate_id in selected
            ):
                _fail("SELECTION_GRAPH_CORRUPT", "selection contains a stale candidate")
            selected.add(candidate_id)
        return refs[0], selected

    @staticmethod
    def _automatic_portfolio(
        rows: Sequence[Mapping[str, Any]], maximum: int
    ) -> list[Mapping[str, Any]]:
        remaining = [row for row in rows if row["eligibility"] == "recommended"]
        selected: list[Mapping[str, Any]] = []
        route_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        forms: set[str] = set()
        while remaining and len(selected) < maximum:

            def rank(row: Mapping[str, Any]) -> tuple[float, bytes]:
                route = _route(row)
                source = _source_id(row)
                form = _candidate_form(row)
                utility = _transfer_score(row)
                utility += 0.20 if route_counts.get(route, 0) == 0 else 0.0
                utility += 0.10 if source_counts.get(source, 0) == 0 else 0.0
                utility -= min(0.20, 0.04 * route_counts.get(route, 0))
                utility -= min(0.12, 0.03 * source_counts.get(source, 0))
                utility -= 0.25 if form in forms else 0.0
                utility -= _review_cost(row) / 1200.0
                return -utility, row["candidateId"].encode("utf-8")

            remaining.sort(key=rank)
            chosen = remaining.pop(0)
            selected.append(chosen)
            route_counts[_route(chosen)] = route_counts.get(_route(chosen), 0) + 1
            source_counts[_source_id(chosen)] = (
                source_counts.get(_source_id(chosen), 0) + 1
            )
            forms.add(_candidate_form(chosen))
        return selected

    @staticmethod
    def _portfolio_summary(
        selected: Sequence[Mapping[str, Any]],
        all_rows: Sequence[Mapping[str, Any]],
        *,
        maximum: int,
        target_daily_minutes: int | None,
    ) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
        route_available: dict[str, int] = {}
        route_selected: dict[str, int] = {}
        for row in all_rows:
            if _blocked_reason(row) is None:
                route_available[_route(row)] = route_available.get(_route(row), 0) + 1
        for row in selected:
            route_selected[_route(row)] = route_selected.get(_route(row), 0) + 1
        coverage = [
            {
                "objectiveGroup": route,
                "selectedCount": route_selected.get(route, 0),
                "availableCount": route_available[route],
                "reasonCode": (
                    "ROUTE_REPRESENTED"
                    if route_selected.get(route, 0)
                    else "ROUTE_NOT_SELECTED"
                ),
            }
            for route in sorted(
                route_available, key=lambda value: value.encode("utf-8")
            )
        ]
        warnings: list[str] = []
        if any(row["eligibility"] == "needs_review" for row in selected):
            warnings.append("SELECTION_NEEDS_REVIEW_INCLUDED")
        recommended_count = sum(row["eligibility"] == "recommended" for row in all_rows)
        if len(selected) == maximum and recommended_count > maximum:
            warnings.append("SELECTION_BUDGET_LIMIT_REACHED")
        forms: dict[str, int] = {}
        for row in selected:
            form = _candidate_form(row)
            forms[form] = forms.get(form, 0) + 1
        if any(value > 1 for value in forms.values()):
            warnings.append("SELECTION_SEMANTIC_REDUNDANCY_REVIEW")

        seconds = sum(8 + _review_cost(row) for row in selected)
        first_minutes = round(seconds / 60.0, 2)
        day7_minutes = round(seconds * 0.35 / 60.0, 2)
        if target_daily_minutes is not None and day7_minutes > target_daily_minutes:
            warnings.append("SELECTION_REVIEW_BUDGET_RISK")
        drivers = ["CARD_COUNT", "EXPECTED_ANSWER_SECONDS"] if selected else []
        if len(route_selected) > 1:
            drivers.append("MULTI_ROUTE_PORTFOLIO")
        if "SELECTION_NEEDS_REVIEW_INCLUDED" in warnings:
            drivers.append("UNRESOLVED_REVIEW_ITEMS")
        debt = {
            "policyVersion": REVIEW_DEBT_POLICY_VERSION,
            "expectedFirstReviewMinutes": first_minutes,
            "expectedDailyMinutesAtDay7": day7_minutes,
            "confidence": "low",
            "drivers": drivers,
        }
        return coverage, sorted(set(warnings)), debt

    def _bundle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        discovery_ref: Mapping[str, Any],
        operation_digest: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        subject = {
            "kind": "project_task",
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "inputArtifacts": [
                {
                    "artifactId": discovery_ref["artifactId"],
                    "artifactRevision": discovery_ref["artifactRevision"],
                    "artifactDigest": discovery_ref["artifactDigest"],
                }
            ],
            "sourceSnapshotDigests": [],
            "learningContractRevision": project["learningContract"]["contractRevision"],
        }
        work, work_digest = build_work_reuse_manifest(
            action_id="save_selection",
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
                    "compatibilityContractVersion": SELECTION_POLICY_VERSION,
                }
            ]
        )
        authorization, authorization_digest = build_authorization_binding(
            audience=audience,
            service_instance_id=self._service_instance_id,
            bindings=[],
        )
        task_input, input_fingerprint = build_task_input_manifest(
            action_id="save_selection",
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
        selections = []
        for ref in committed["artifactRefs"]:
            envelope = self._artifacts.verify_ref(ref, audience)
            if envelope.get("payloadSchema") == "study.portfolio-selection":
                selections.append((ref, envelope))
        if len(selections) != 1:
            _fail("SELECTION_RESULT_INVALID", "selection result is missing")
        ref, envelope = selections[0]
        payload = envelope["payload"]
        return {
            "schemaVersion": 1,
            "projectId": committed["projectId"],
            "projectRevision": committed["projectRevision"],
            "artifactStage": "selection_ready",
            "taskId": committed["taskId"],
            "selectionHandle": self._artifacts.issue_handle(ref, audience),
            "selectedCount": len(payload["candidateRefs"]),
            "budget": _clone(payload["budget"]),
            "coverage": _clone(payload["coverage"]),
            "redundancyWarnings": list(payload["redundancyWarnings"]),
            "estimatedReviewDebt": _clone(payload["estimatedReviewDebt"]),
            "issueCodes": list(envelope["issueRefs"]),
            "nextAction": "plan_cards",
        }

    def set_selection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        discovery_handle: str,
        operation: str,
        candidate_handles: Sequence[str] | None = None,
        budget: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            _fail("SELECTION_REQUEST_INVALID", "idempotencyKey is invalid")
        if (
            isinstance(expected_project_revision, bool)
            or not isinstance(expected_project_revision, int)
            or expected_project_revision < 1
        ):
            _fail("SELECTION_REQUEST_INVALID", "expectedProjectRevision is invalid")
        handles = self._validate_handles(operation, candidate_handles)
        try:
            graph = self._queries.resolve_selection_graph(
                audience=audience,
                discovery_handle=discovery_handle,
                candidate_handles=handles,
            )
        except CandidateQueryError as error:
            raise CandidateSelectionError(error.code, error.message) from error
        project = graph["project"]
        discovery_ref = graph["discoveryRef"]
        rows = graph["rows"]
        requested_rows = graph["requestedRows"]
        normalized_budget = self._budget(budget, project["learningContract"])
        operation_digest = _digest(
            {
                "schema": "study.portfolio-selection.request",
                "schemaVersion": 1,
                "projectId": project_id,
                "expectedProjectRevision": expected_project_revision,
                "discoveryDigest": discovery_ref["artifactDigest"],
                "operation": operation,
                "candidateIds": sorted(row["candidateId"] for row in requested_rows),
                "budget": normalized_budget,
                "policyVersion": SELECTION_POLICY_VERSION,
            }
        )
        operation_id = "selection:" + idempotency_key
        try:
            prior = self._projects.get_operation_result(
                audience=audience,
                project_id=project_id,
                operation_id=operation_id,
                operation_digest=operation_digest,
            )
        except ProjectRegistryError as error:
            raise CandidateSelectionError(error.code, error.message) from error
        if prior is not None:
            return self._public_result(audience=audience, committed=prior)
        if project.get("projectId") != project_id:
            _fail("SELECTION_PROJECT_MISMATCH", "discovery belongs to another project")
        if project["projectRevision"] != expected_project_revision:
            _fail("PROJECT_REVISION_CONFLICT", "project changed before selection")
        if project["workflow"]["artifactStage"] not in {
            "candidates_ready",
            "selection_ready",
        }:
            _fail("SELECTION_STAGE_CONFLICT", "candidate selection is not current")

        row_by_id = {row["candidateId"]: row for row in rows}
        previous_ref, selected_ids = self._current_selection(
            audience=audience,
            project=project,
            discovery_ref=discovery_ref,
            member_refs={
                candidate_id: _ref_identity(row["candidateRef"])
                for candidate_id, row in row_by_id.items()
            },
        )
        if operation == "accept_recommended":
            selected_rows = self._automatic_portfolio(
                rows, normalized_budget["maxNewCards"]
            )
            if not selected_rows:
                _fail("SELECTION_EMPTY", "no recommended candidate is available")
            selected_ids = {row["candidateId"] for row in selected_rows}
        else:
            for row in requested_rows:
                reason = _blocked_reason(row)
                if reason is not None:
                    _fail(reason, "candidate cannot enter the selected portfolio")
            requested_ids = {row["candidateId"] for row in requested_rows}
            if operation == "add":
                selected_ids |= requested_ids
            else:
                if not requested_ids.issubset(selected_ids):
                    _fail(
                        "SELECTION_CANDIDATE_NOT_SELECTED",
                        "remove contains a candidate that is not selected",
                    )
                selected_ids -= requested_ids
            if not selected_ids:
                _fail(
                    "SELECTION_EMPTY", "selection must contain at least one candidate"
                )
            selected_rows = [row_by_id[value] for value in selected_ids]
        if len(selected_rows) > normalized_budget["maxNewCards"]:
            _fail("SELECTION_BUDGET_EXCEEDED", "selection exceeds maxNewCards")
        for row in selected_rows:
            reason = _blocked_reason(row)
            if reason is not None:
                _fail(reason, "current selection contains an ineligible candidate")
        selected_rows.sort(key=lambda row: row["candidateId"].encode("utf-8"))
        coverage, warnings, debt = self._portfolio_summary(
            selected_rows,
            rows,
            maximum=normalized_budget["maxNewCards"],
            target_daily_minutes=normalized_budget.get("targetDailyReviewMinutes"),
        )
        candidate_refs = [
            {
                "artifactRef": dict(row["candidateRef"]),
                "entityId": row["candidateId"],
            }
            for row in selected_rows
        ]
        payload = {
            "selectionId": "selection_" + operation_digest[:40],
            "projectRevision": expected_project_revision,
            "discoveryRef": dict(discovery_ref),
            "candidateRefs": candidate_refs,
            "budget": normalized_budget,
            "coverage": coverage,
            "redundancyWarnings": warnings,
            "estimatedReviewDebt": debt,
            "policyVersion": SELECTION_POLICY_VERSION,
            "operation": operation,
        }
        try:
            work, task_input, capability, authorization, input_fingerprint = (
                self._bundle(
                    audience=audience,
                    project=project,
                    discovery_ref=discovery_ref,
                    operation_digest=operation_digest,
                )
            )
        except TaskManifestError as error:
            raise CandidateSelectionError(error.code, error.message) from error
        task_id = "task_selection_" + operation_digest[:40]
        try:
            try:
                task = self._tasks.create_task(
                    audience=audience,
                    work_reuse_manifest=work,
                    task_input_manifest=task_input,
                    capability_binding=capability,
                    authorization_binding=authorization,
                    work_units=[
                        {"workUnitId": "portfolio-selection", "phase": "selection"}
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
                    _fail("TASK_INPUT_MISMATCH", "selection task input changed")
            if task["state"] not in {"queued", "running", "succeeded"}:
                _fail("TASK_RECOVERY_REQUIRED", "selection task requires recovery")
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
                        work_unit_id="portfolio-selection",
                    )
                    unit = task["workUnits"][0]
                if unit["state"] != "completed":
                    parents = [dict(discovery_ref)]
                    if previous_ref is not None:
                        parents.append(previous_ref)
                    publication = self._artifacts.publish_idempotent(
                        audience=audience,
                        project_id=project_id,
                        project_revision=expected_project_revision,
                        artifact_id=payload["selectionId"],
                        artifact_revision=1,
                        payload_schema="study.portfolio-selection",
                        payload_schema_version=1,
                        payload=payload,
                        producer=_PRODUCER,
                        parents=parents,
                        input_fingerprint=input_fingerprint,
                        completeness={
                            "state": "complete",
                            "omittedLocators": [],
                            "reasonCodes": [],
                        },
                        issue_refs=warnings,
                    )
                    task = self._tasks.complete_work_unit(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="complete-" + operation_digest[:37],
                        work_unit_id="portfolio-selection",
                        result_handles=[publication.handle],
                    )
                if task["state"] == "running":
                    task = self._tasks.succeed_task(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="succeed-" + operation_digest[:38],
                    )
            final_task = self._tasks.get_task(task_id, audience)
            if len(final_task["resultHandles"]) != 1:
                _fail("SELECTION_RESULT_INVALID", "selection task result is invalid")
            ref, _envelope = self._artifacts.resolve_with_ref(
                final_task["resultHandles"][0], audience
            )
            committed = self._projects.commit_artifact_stage(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                operation_id=operation_id,
                operation_digest=operation_digest,
                task_id=task_id,
                artifact_stage="selection_ready",
                artifact_refs=[ref],
                artifact_handles=[final_task["resultHandles"][0]],
            )
            return self._public_result(audience=audience, committed=committed)
        except (
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskManifestError,
        ) as error:
            raise CandidateSelectionError(error.code, error.message) from error


__all__ = [
    "CandidateSelectionError",
    "CandidateSelectionRuntime",
    "REVIEW_DEBT_POLICY_VERSION",
    "SELECTION_POLICY_VERSION",
]
