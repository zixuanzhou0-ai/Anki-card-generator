"""Read-only public projections over authenticated CardPlan artifacts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from typing import Any, Mapping

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .project_registry import ARTIFACT_STAGES, ProjectRegistry, ProjectRegistryError


_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_CURSOR_RE = re.compile(r"^study_plan_cursor_[A-Za-z0-9_-]{80,1800}$")
_CURSOR_DOMAIN = b"study.card-plan-query.cursor.v1\x00"
_MAX_LIMIT = 100
_MAX_PLANS = 1000
_SUPPORTED_ROUTES = frozenset(
    {"production", "chunk_collocation", "reading_recognition"}
)
_MEDIA_FIELDS = frozenset(
    {"sourceAudio", "sourceVideo", "sentenceTts", "expressionTts"}
)
_CHECK_IDS = frozenset(
    {
        "evidence_coverage",
        "scoring_boundary",
        "answer_leakage",
        "duplicate",
        "conflict",
        "template_compatibility",
        "media_generatability",
        "user_lock_preservation",
    }
)


class CardPlanQueryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise CardPlanQueryError(code, message)


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _public_text(value: Any, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail("CARD_PLAN_GRAPH_CORRUPT", f"{label} is invalid")
    if any(ord(character) < 0x20 and character not in "\t\r\n" for character in value):
        _fail("CARD_PLAN_GRAPH_CORRUPT", f"{label} contains control characters")
    return value


def _public_string_list(
    value: Any, *, label: str, maximum_items: int, maximum_text: int
) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        _fail("CARD_PLAN_GRAPH_CORRUPT", f"{label} is invalid")
    return [_public_text(item, label=label, maximum=maximum_text) for item in value]


def _ref_identity(value: Mapping[str, Any]) -> tuple[str, int, str]:
    return (
        str(value.get("artifactId")),
        int(value.get("artifactRevision", 0)),
        str(value.get("artifactDigest")),
    )


def _entity(
    value: Any, *, label: str
) -> tuple[dict[str, Any], str, tuple[str, int, str]]:
    artifact_ref = value.get("artifactRef") if isinstance(value, Mapping) else None
    entity_id = value.get("entityId") if isinstance(value, Mapping) else None
    if not isinstance(artifact_ref, Mapping) or not isinstance(entity_id, str):
        _fail("CARD_PLAN_GRAPH_CORRUPT", f"{label} is invalid")
    ref = dict(artifact_ref)
    return ref, entity_id, _ref_identity(ref)


class CardPlanQueryRuntime:
    """Authenticate CardPlan graphs and expose only learner-facing projections."""

    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        cursor_key: bytes,
    ) -> None:
        if not isinstance(service_instance_id, str) or not service_instance_id:
            _fail(
                "CARD_PLAN_QUERY_CONFIGURATION_INVALID", "service identity is invalid"
            )
        if not isinstance(cursor_key, bytes) or len(cursor_key) < 32:
            _fail("CARD_PLAN_QUERY_CONFIGURATION_INVALID", "cursor key is invalid")
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._cursor_key = bytes(cursor_key)

    def _cursor_tag(self, raw: bytes) -> bytes:
        return hmac.new(self._cursor_key, _CURSOR_DOMAIN + raw, hashlib.sha256).digest()

    def _encode_cursor(self, *, plan_set_digest: str, last_plan_id: str) -> str:
        raw = canonical_json_bytes(
            {
                "schemaVersion": 1,
                "serviceInstanceId": self._service_instance_id,
                "planSetDigest": plan_set_digest,
                "lastPlanId": last_plan_id,
            }
        )
        encoded = base64.urlsafe_b64encode(raw + self._cursor_tag(raw)).rstrip(b"=")
        return "study_plan_cursor_" + encoded.decode("ascii")

    def _decode_cursor(self, value: str) -> dict[str, Any]:
        if not isinstance(value, str) or not _CURSOR_RE.fullmatch(value):
            _fail("CARD_PLAN_CURSOR_INVALID", "card plan cursor is invalid")
        encoded = value.removeprefix("study_plan_cursor_")
        try:
            decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except (TypeError, ValueError) as error:
            raise CardPlanQueryError(
                "CARD_PLAN_CURSOR_INVALID", "card plan cursor is invalid"
            ) from error
        if len(decoded) <= 32:
            _fail("CARD_PLAN_CURSOR_INVALID", "card plan cursor is invalid")
        raw, tag = decoded[:-32], decoded[-32:]
        if not hmac.compare_digest(tag, self._cursor_tag(raw)):
            _fail("CARD_PLAN_CURSOR_INVALID", "card plan cursor authentication failed")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError) as error:
            raise CardPlanQueryError(
                "CARD_PLAN_CURSOR_INVALID", "card plan cursor is invalid"
            ) from error
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "schemaVersion",
                "serviceInstanceId",
                "planSetDigest",
                "lastPlanId",
            }
            or payload.get("schemaVersion") != 1
            or payload.get("serviceInstanceId") != self._service_instance_id
            or not isinstance(payload.get("planSetDigest"), str)
            or not isinstance(payload.get("lastPlanId"), str)
        ):
            _fail("CARD_PLAN_CURSOR_INVALID", "card plan cursor fields are invalid")
        return payload

    def _current_graph(
        self,
        *,
        audience: ArtifactAudienceBinding,
        plan_set_handle: str,
    ) -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        list[tuple[dict[str, Any], str, tuple[str, int, str]]],
        dict[tuple[str, int, str], list[dict[str, Any]]],
        set[tuple[str, int, str]],
    ]:
        if not isinstance(plan_set_handle, str) or not _HANDLE_RE.fullmatch(
            plan_set_handle
        ):
            _fail("CARD_PLAN_QUERY_INVALID", "planSetHandle is invalid")
        try:
            plan_set_ref, plan_set = self._artifacts.resolve_with_ref(
                plan_set_handle, audience
            )
            project = self._projects.get_project(plan_set_ref["projectId"], audience)
        except (ArtifactRegistryError, ProjectRegistryError) as error:
            raise CardPlanQueryError(error.code, error.message) from error
        if plan_set.get("payloadSchema") != "study.card-plan-set":
            _fail("CARD_PLAN_SET_INVALID", "handle is not a card plan set")
        stage = project.get("workflow", {}).get("artifactStage")
        if stage not in ARTIFACT_STAGES or ARTIFACT_STAGES.index(
            stage
        ) < ARTIFACT_STAGES.index("plans_ready"):
            _fail("CARD_PLAN_SET_STALE", "card plans are no longer current")
        current_sets = [
            value
            for value in project.get("latestArtifactRefs", [])
            if isinstance(value, Mapping)
            and value.get("payloadSchema") == "study.card-plan-set"
        ]
        if not current_sets:
            _fail("CARD_PLAN_SET_STALE", "project has no current card plan set")
        highest = max(int(value.get("projectRevision", 0)) for value in current_sets)
        newest = [
            value for value in current_sets if value.get("projectRevision") == highest
        ]
        if len(newest) != 1 or _ref_identity(newest[0]) != _ref_identity(plan_set_ref):
            _fail("CARD_PLAN_SET_STALE", "card plan set is not current")

        validation_refs = [
            value
            for value in project.get("latestArtifactRefs", [])
            if isinstance(value, Mapping)
            and value.get("payloadSchema") == "study.card-plan-validation"
            and value.get("projectRevision") == highest
        ]
        if len(validation_refs) != 1:
            _fail("CARD_PLAN_GRAPH_CORRUPT", "current plan validation is missing")
        try:
            validation = self._artifacts.verify_ref(validation_refs[0], audience)
        except ArtifactRegistryError as error:
            raise CardPlanQueryError(error.code, error.message) from error
        validation_payload = validation.get("payload")
        set_payload = plan_set.get("payload")
        if (
            validation.get("payloadSchema") != "study.card-plan-validation"
            or not isinstance(validation_payload, Mapping)
            or not isinstance(set_payload, Mapping)
            or _ref_identity(validation_payload.get("cardPlanSetRef", {}))
            != _ref_identity(plan_set_ref)
            or validation_payload.get("cardPlanSetDigest")
            != plan_set_ref["artifactDigest"]
        ):
            _fail("CARD_PLAN_GRAPH_CORRUPT", "plan validation graph is invalid")

        raw_plan_refs = set_payload.get("cardPlanRefs")
        if (
            not isinstance(raw_plan_refs, list)
            or not raw_plan_refs
            or len(raw_plan_refs) > _MAX_PLANS
        ):
            _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan membership is invalid")
        plan_refs = [
            _entity(value, label="card plan membership") for value in raw_plan_refs
        ]
        identities = [value[2] for value in plan_refs]
        plan_ids = [value[1] for value in plan_refs]
        if len(set(identities)) != len(identities) or len(set(plan_ids)) != len(
            plan_ids
        ):
            _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan membership is duplicated")

        eligible_values = validation_payload.get("eligibleCardPlanRefs")
        blocked_values = validation_payload.get("blockedCardPlanRefs")
        records = validation_payload.get("records")
        if not all(
            isinstance(value, list)
            for value in (eligible_values, blocked_values, records)
        ):
            _fail("CARD_PLAN_GRAPH_CORRUPT", "plan validation records are invalid")
        eligible = {
            _entity(value, label="eligible card plan")[2] for value in eligible_values
        }
        blocked = {
            _entity(value, label="blocked card plan")[2] for value in blocked_values
        }
        if eligible & blocked or eligible | blocked != set(identities):
            _fail("CARD_PLAN_GRAPH_CORRUPT", "plan validation coverage is invalid")
        if (
            set_payload.get("totalPlans") != len(identities)
            or set_payload.get("eligibleCount") != len(eligible)
            or set_payload.get("blockedCount") != len(blocked)
        ):
            _fail("CARD_PLAN_GRAPH_CORRUPT", "plan set counts are invalid")

        records_by_plan: dict[tuple[str, int, str], list[dict[str, Any]]] = {
            identity: [] for identity in identities
        }
        for value in records:
            if not isinstance(value, Mapping):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "plan validation record is invalid")
            identity = _entity(value.get("cardPlanRef"), label="validation target")[2]
            check_id = value.get("checkId")
            state = value.get("state")
            if (
                identity not in records_by_plan
                or check_id not in _CHECK_IDS
                or state not in {"passed", "needs_review", "failed"}
            ):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "plan validation record is invalid")
            records_by_plan[identity].append(
                {"checkId": str(check_id), "state": str(state)}
            )
        for plan_records in records_by_plan.values():
            if (
                len(plan_records) != len(_CHECK_IDS)
                or {value["checkId"] for value in plan_records} != _CHECK_IDS
            ):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "plan validation is incomplete")
            plan_records.sort(key=lambda value: value["checkId"])
        return (
            plan_set_ref,
            plan_set,
            validation,
            project,
            plan_refs,
            records_by_plan,
            eligible,
        )

    def list_card_plans(
        self,
        *,
        audience: ArtifactAudienceBinding,
        plan_set_handle: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_LIMIT
        ):
            _fail("CARD_PLAN_QUERY_INVALID", "limit is invalid")
        (
            plan_set_ref,
            plan_set,
            _validation,
            project,
            plan_refs,
            records_by_plan,
            eligible,
        ) = self._current_graph(audience=audience, plan_set_handle=plan_set_handle)
        start = 0
        if cursor is not None:
            decoded = self._decode_cursor(cursor)
            if decoded["planSetDigest"] != plan_set_ref["artifactDigest"]:
                _fail("CARD_PLAN_CURSOR_INVALID", "cursor belongs to another plan set")
            matches = [
                index
                for index, (_ref, plan_id, _identity) in enumerate(plan_refs)
                if plan_id == decoded["lastPlanId"]
            ]
            if len(matches) != 1:
                _fail("CARD_PLAN_CURSOR_INVALID", "cursor position is invalid")
            start = matches[0] + 1
        page = plan_refs[start : start + limit]
        items: list[dict[str, Any]] = []
        for plan_ref, plan_id, identity in page:
            try:
                envelope = self._artifacts.verify_ref(plan_ref, audience)
            except ArtifactRegistryError as error:
                raise CardPlanQueryError(error.code, error.message) from error
            payload = envelope.get("payload")
            if (
                envelope.get("payloadSchema") != "study.card-plan"
                or not isinstance(payload, Mapping)
                or payload.get("cardPlanId") != plan_id
            ):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan artifact is invalid")
            cue = payload.get("cue")
            response = payload.get("expectedResponse")
            feedback = payload.get("feedback")
            media = payload.get("mediaPolicy")
            if not all(
                isinstance(value, Mapping) for value in (cue, response, feedback, media)
            ):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan projection is invalid")
            route = payload.get("route")
            cue_kind = cue.get("kind")
            cue_content = _public_text(
                cue.get("content"), label="card plan cue", maximum=1000
            )
            modality = response.get("modality")
            core_answer = _public_text(
                response.get("coreAnswer"), label="card plan answer", maximum=500
            )
            scoring_points = _public_string_list(
                response.get("scoringPoints"),
                label="card plan scoring point",
                maximum_items=8,
                maximum_text=500,
            )
            accepted_variants = _public_string_list(
                response.get("acceptedVariants"),
                label="card plan accepted variant",
                maximum_items=20,
                maximum_text=500,
            )
            explanation = _public_text(
                feedback.get("explanation"),
                label="card plan explanation",
                maximum=2000,
            )
            evidence_refs = feedback.get("evidenceRefs")
            examples = _public_string_list(
                feedback.get("examples"),
                label="card plan example",
                maximum_items=10,
                maximum_text=2000,
            )
            nonexamples = _public_string_list(
                feedback.get("nonexamples"),
                label="card plan nonexample",
                maximum_items=10,
                maximum_text=2000,
            )
            estimated_seconds = payload.get("estimatedReviewSeconds")
            locks = payload.get("userLocks")
            if (
                route not in _SUPPORTED_ROUTES
                or cue_kind != "text"
                or modality != "text"
                or not scoring_points
                or not isinstance(evidence_refs, list)
                or not evidence_refs
                or set(media) != _MEDIA_FIELDS
                or any(not isinstance(media[field], bool) for field in _MEDIA_FIELDS)
                or isinstance(estimated_seconds, bool)
                or not isinstance(estimated_seconds, int)
                or not 1 <= estimated_seconds <= 300
                or not isinstance(locks, list)
                or len(locks) > 32
            ):
                _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan projection is invalid")
            for evidence_ref in evidence_refs:
                _entity(evidence_ref, label="card plan evidence")
            locked_fields: list[str] = []
            for lock in locks:
                field = lock.get("field") if isinstance(lock, Mapping) else None
                if not isinstance(field, str) or not field or len(field) > 100:
                    _fail("CARD_PLAN_GRAPH_CORRUPT", "card plan lock is invalid")
                locked_fields.append(field)
            checks = records_by_plan[identity]
            items.append(
                {
                    "cardPlanHandle": self._artifacts.issue_handle(plan_ref, audience),
                    "cardPlanId": plan_id,
                    "route": route,
                    "cue": {
                        "kind": cue_kind,
                        "content": cue_content,
                    },
                    "expectedResponse": {
                        "modality": modality,
                        "coreAnswer": core_answer,
                        "scoringPoints": scoring_points,
                        "acceptedVariants": accepted_variants,
                    },
                    "feedback": {
                        "explanation": explanation,
                        "evidenceCount": len(evidence_refs),
                        "examples": examples,
                        "nonexamples": nonexamples,
                    },
                    "mediaPolicy": _clone(dict(media)),
                    "estimatedReviewSeconds": estimated_seconds,
                    "validationState": (
                        "eligible" if identity in eligible else "blocked"
                    ),
                    "checks": _clone(checks),
                    "userLockedFields": locked_fields,
                }
            )
        end = start + len(page)
        next_cursor = None
        if end < len(plan_refs) and page:
            next_cursor = self._encode_cursor(
                plan_set_digest=plan_set_ref["artifactDigest"],
                last_plan_id=page[-1][1],
            )
        set_payload = plan_set["payload"]
        blocked_count = len(plan_refs) - len(eligible)
        return {
            "schemaVersion": 1,
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "artifactStage": project["workflow"]["artifactStage"],
            "planSetHandle": self._artifacts.issue_handle(plan_set_ref, audience),
            "totalPlans": len(plan_refs),
            "returnedPlans": len(items),
            "eligiblePlans": len(eligible),
            "blockedPlans": blocked_count,
            "items": items,
            "nextCursor": next_cursor,
            "nextAction": (
                "generate_cards" if blocked_count == 0 else "review_card_plans"
            ),
        }


__all__ = ["CardPlanQueryError", "CardPlanQueryRuntime"]
