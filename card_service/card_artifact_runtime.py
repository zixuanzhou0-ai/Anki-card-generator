"""Deterministic CardArtifact generation from an authenticated CardPlan graph.

The first public generation route is deliberately closed-world: every plan must
already pass all eight CardPlan gates and request no model, TTS, or media work.
The runtime therefore performs a lossless deterministic projection instead of
pretending that unsupported generation succeeded.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .card_plan_queries import CardPlanQueryError, CardPlanQueryRuntime
from .legacy_project_projection import (
    LegacyProjectProjectionError,
    LegacyProjectProjectionPublisher,
)
from .project_registry import ARTIFACT_STAGES, ProjectRegistry, ProjectRegistryError
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


CARD_GENERATION_POLICY_VERSION = "deterministic-card-artifact-v1"
CARD_RELIABILITY_RULE_SET_VERSION = "card-artifact-reliability-v1"
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_PRODUCER = {
    "kind": "deterministic-service",
    "component": "card-artifact-runtime",
    "version": CARD_GENERATION_POLICY_VERSION,
}
_COMPONENTS = {
    "cardService": "2.0.0",
    "worker": "not-used",
    "sourceAdapterSetDigest": hashlib.sha256(
        b"card-artifact-no-source-adapter-v1"
    ).hexdigest(),
    "gateRuleSetVersion": CARD_RELIABILITY_RULE_SET_VERSION,
    "compatibilityContractVersion": CARD_GENERATION_POLICY_VERSION,
}
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
_MEDIA_FIELDS = frozenset(
    {"sourceAudio", "sourceVideo", "sentenceTts", "expressionTts"}
)


class CardArtifactRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise CardArtifactRuntimeError(code, message)


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _identity(value: Mapping[str, Any]) -> tuple[str, int, str]:
    return (
        str(value.get("artifactId") or ""),
        int(value.get("artifactRevision") or 0),
        str(value.get("artifactDigest") or ""),
    )


def _text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        _fail("CARD_GENERATION_GRAPH_CORRUPT", f"{label} is invalid")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > maximum:
        _fail("CARD_GENERATION_GRAPH_CORRUPT", f"{label} is invalid")
    return normalized


def _text_list(
    value: Any, label: str, *, maximum_items: int, maximum_text: int
) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) > maximum_items
    ):
        _fail("CARD_GENERATION_GRAPH_CORRUPT", f"{label} is invalid")
    return [_text(item, label, maximum=maximum_text) for item in value]


def _artifact_entity(ref: Mapping[str, Any], entity_id: str) -> dict[str, Any]:
    return {"artifactRef": dict(ref), "entityId": entity_id}


class CardArtifactRuntime:
    """Generate immutable text cards and an export-compatible ProjectArtifact."""

    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        tasks: StudyTaskCoordinator,
        card_plan_queries: CardPlanQueryRuntime,
    ) -> None:
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._tasks = tasks
        self._plans = card_plan_queries
        self._legacy = LegacyProjectProjectionPublisher(artifacts)

    def _bundle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        plan_set_ref: Mapping[str, Any],
        validation_ref: Mapping[str, Any],
        operation_digest: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        inputs = [
            {
                "artifactId": ref["artifactId"],
                "artifactRevision": ref["artifactRevision"],
                "artifactDigest": ref["artifactDigest"],
            }
            for ref in (plan_set_ref, validation_ref)
        ]
        subject = {
            "kind": "project_task",
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "inputArtifacts": inputs,
            "sourceSnapshotDigests": [],
            "learningContractRevision": project["learningContract"]["contractRevision"],
        }
        work, work_digest = build_work_reuse_manifest(
            action_id="generate_cards",
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
                    "compatibilityContractVersion": CARD_GENERATION_POLICY_VERSION,
                }
            ]
        )
        authorization, authorization_digest = build_authorization_binding(
            audience=audience,
            service_instance_id=self._service_instance_id,
            bindings=[],
        )
        task_input, fingerprint = build_task_input_manifest(
            action_id="generate_cards",
            work_reuse_manifest=work,
            work_reuse_digest=work_digest,
            subject=subject,
            authorization_binding_digest=authorization_digest,
            capability_binding_digest=capability_digest,
            component_versions=_COMPONENTS,
            service_bindings=[],
            batch_policy_digest=operation_digest,
        )
        return work, task_input, capability, authorization, fingerprint

    def _plan_rows(
        self,
        *,
        audience: ArtifactAudienceBinding,
        graph: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        raw_refs = graph.get("planRefs")
        records = graph.get("recordsByPlan")
        eligible = graph.get("eligible")
        if (
            not isinstance(raw_refs, list)
            or not raw_refs
            or not isinstance(records, Mapping)
            or not isinstance(eligible, set)
        ):
            _fail("CARD_GENERATION_GRAPH_CORRUPT", "card plan graph is invalid")
        rows: list[dict[str, Any]] = []
        source_refs: dict[tuple[str, int, str], dict[str, Any]] = {}
        for raw in raw_refs:
            if (
                not isinstance(raw, tuple)
                or len(raw) != 3
                or not isinstance(raw[0], Mapping)
                or not isinstance(raw[1], str)
            ):
                _fail(
                    "CARD_GENERATION_GRAPH_CORRUPT", "card plan membership is invalid"
                )
            plan_ref, plan_id, membership_identity = raw
            identity = _identity(plan_ref)
            if identity != membership_identity or identity not in eligible:
                _fail(
                    "CARD_GENERATION_PLAN_BLOCKED",
                    "every current card plan must pass all generation gates",
                )
            plan_records = records.get(identity)
            if (
                not isinstance(plan_records, list)
                or len(plan_records) != len(_CHECK_IDS)
                or {
                    item.get("checkId")
                    for item in plan_records
                    if isinstance(item, Mapping)
                }
                != _CHECK_IDS
                or any(item.get("state") != "passed" for item in plan_records)
            ):
                _fail(
                    "CARD_GENERATION_PLAN_BLOCKED",
                    "card plan validation is incomplete or not fully passed",
                )
            try:
                plan = self._artifacts.verify_ref(plan_ref, audience)
            except ArtifactRegistryError as error:
                raise CardArtifactRuntimeError(error.code, error.message) from error
            payload = plan.get("payload")
            if (
                plan.get("payloadSchema") != "study.card-plan"
                or not isinstance(payload, Mapping)
                or payload.get("cardPlanId") != plan_id
            ):
                _fail("CARD_GENERATION_GRAPH_CORRUPT", "card plan payload is invalid")
            cue = payload.get("cue")
            response = payload.get("expectedResponse")
            feedback = payload.get("feedback")
            media = payload.get("mediaPolicy")
            if not all(
                isinstance(value, Mapping) for value in (cue, response, feedback, media)
            ):
                _fail("CARD_GENERATION_GRAPH_CORRUPT", "card plan fields are invalid")
            if (
                cue.get("kind") != "text"
                or cue.get("mediaRefs") != []
                or response.get("modality") != "text"
                or set(media) != _MEDIA_FIELDS
                or any(media[field] is not False for field in _MEDIA_FIELDS)
            ):
                _fail(
                    "CARD_GENERATION_UNSUPPORTED",
                    "current deterministic generation supports text-only plans",
                )
            candidate_ref = payload.get("candidateRef")
            if not isinstance(candidate_ref, Mapping):
                _fail("CARD_GENERATION_GRAPH_CORRUPT", "candidate reference is invalid")
            try:
                candidate = self._artifacts.verify_ref(candidate_ref, audience)
            except ArtifactRegistryError as error:
                raise CardArtifactRuntimeError(error.code, error.message) from error
            candidate_payload = candidate.get("payload")
            representation_ref = (
                candidate_payload.get("representationRef")
                if isinstance(candidate_payload, Mapping)
                else None
            )
            if candidate.get(
                "payloadSchema"
            ) != "study.candidate-proposal" or not isinstance(
                representation_ref, Mapping
            ):
                _fail(
                    "CARD_GENERATION_GRAPH_CORRUPT", "candidate provenance is invalid"
                )
            try:
                representation = self._artifacts.verify_ref(
                    representation_ref, audience
                )
            except ArtifactRegistryError as error:
                raise CardArtifactRuntimeError(error.code, error.message) from error
            representation_payload = representation.get("payload")
            source_ref = (
                representation_payload.get("sourceRef")
                if isinstance(representation_payload, Mapping)
                else None
            )
            if representation.get(
                "payloadSchema"
            ) != "study.source-representation" or not isinstance(source_ref, Mapping):
                _fail("CARD_GENERATION_GRAPH_CORRUPT", "source provenance is invalid")
            try:
                source = self._artifacts.verify_ref(source_ref, audience)
            except ArtifactRegistryError as error:
                raise CardArtifactRuntimeError(error.code, error.message) from error
            if source.get("payloadSchema") != "study.source-asset":
                _fail("CARD_GENERATION_GRAPH_CORRUPT", "source asset is invalid")
            source_refs[_identity(source_ref)] = dict(source_ref)
            rows.append(
                {
                    "planRef": dict(plan_ref),
                    "planId": plan_id,
                    "payload": _clone(payload),
                    "sourceRef": dict(source_ref),
                }
            )
        rows.sort(key=lambda value: value["planId"].encode("utf-8"))
        return rows, [source_refs[key] for key in sorted(source_refs)]

    def _card_payload(
        self,
        *,
        row: Mapping[str, Any],
        project_revision: int,
        operation_digest: str,
    ) -> dict[str, Any]:
        plan = row["payload"]
        cue = plan["cue"]
        response = plan["expectedResponse"]
        feedback = plan["feedback"]
        cue_text = _text(cue.get("content"), "card cue", maximum=1_000)
        answer = _text(response.get("coreAnswer"), "card answer", maximum=500)
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
            feedback.get("explanation"), "card explanation", maximum=2_000
        )
        examples = _text_list(
            feedback.get("examples"),
            "card example",
            maximum_items=10,
            maximum_text=2_000,
        )
        nonexamples = _text_list(
            feedback.get("nonexamples"),
            "card nonexample",
            maximum_items=10,
            maximum_text=2_000,
        )
        evidence_refs = feedback.get("evidenceRefs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            _fail("CARD_GENERATION_GRAPH_CORRUPT", "card evidence is missing")
        card_id = (
            "card_"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "operationDigest": operation_digest,
                        "cardPlanId": row["planId"],
                        "policyVersion": CARD_GENERATION_POLICY_VERSION,
                    }
                )
            ).hexdigest()[:40]
        )
        return {
            "cardId": card_id,
            "projectRevision": project_revision,
            "cardPlanRef": _artifact_entity(row["planRef"], row["planId"]),
            "route": plan["route"],
            "front": {"modality": "text", "prompt": cue_text},
            "back": {
                "coreAnswer": answer,
                "explanation": explanation,
                "examples": examples,
                "nonexamples": nonexamples,
            },
            "scoring": {
                "points": scoring,
                "acceptedVariants": variants,
                "singleRecallTarget": True,
            },
            "evidenceRefs": _clone(evidence_refs),
            "mediaRefs": [],
            "verification": {
                "state": "verified",
                "ruleSetVersion": CARD_RELIABILITY_RULE_SET_VERSION,
                "passedChecks": sorted(_CHECK_IDS),
            },
            "generation": {
                "mode": "deterministic_projection",
                "policyVersion": CARD_GENERATION_POLICY_VERSION,
                "modelUsed": False,
                "ttsUsed": False,
                "mediaUsed": False,
            },
        }

    @staticmethod
    def _legacy_card(card: Mapping[str, Any], plan_id: str) -> dict[str, Any]:
        front = card["front"]
        back = card["back"]
        answer = str(back["coreAnswer"])
        explanation = str(back["explanation"])
        examples = [str(value) for value in back["examples"]]
        nonexamples = [str(value) for value in back["nonexamples"]]
        source_evidence = " ".join(
            value for value in (answer, explanation, *examples) if value
        )
        return {
            "id": card["cardId"],
            "type": "knowledge",
            "enabled": True,
            "document_card_kind": "knowledge",
            "english": str(front["prompt"]),
            "answer_core": answer,
            "phrase": answer,
            "chinese": answer,
            "definition": explanation,
            "context": explanation,
            "source_evidence": source_evidence,
            "example": " / ".join(examples),
            "teacher_note": " / ".join(nonexamples),
            "learning_point_id": plan_id,
            "generation_source": "deterministic_card_plan",
            "verification_status": "verified",
            "pronunciation_meta": {},
            "quality": {"score": 100, "status": "recommended", "issues": []},
        }

    def _publish_artifacts(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        graph: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
        source_refs: Sequence[Mapping[str, Any]],
        input_fingerprint: str,
        operation_digest: str,
    ) -> str:
        project_id = project["projectId"]
        revision = project["projectRevision"]
        card_refs: list[dict[str, Any]] = []
        card_payloads: list[dict[str, Any]] = []
        for row in rows:
            payload = self._card_payload(
                row=row,
                project_revision=revision,
                operation_digest=operation_digest,
            )
            publication = self._artifacts.publish_idempotent(
                audience=audience,
                project_id=project_id,
                project_revision=revision,
                artifact_id=payload["cardId"],
                artifact_revision=1,
                payload_schema="study.card",
                payload_schema_version=1,
                payload=payload,
                producer=_PRODUCER,
                parents=[dict(row["planRef"]), dict(row["sourceRef"])],
                input_fingerprint=input_fingerprint,
                completeness={
                    "state": "complete",
                    "omittedLocators": [],
                    "reasonCodes": [],
                },
                issue_refs=[],
            )
            card_refs.append(dict(publication.artifact_ref))
            card_payloads.append(payload)

        outcomes = [
            {
                "learning_point_id": row["planId"],
                "status": "verified",
                "card_id": card["cardId"],
                "blocker_codes": [],
                "reason": "CardPlan and deterministic CardArtifact passed every current gate.",
            }
            for row, card in zip(rows, card_payloads, strict=True)
        ]
        reliability_payload = {
            "schema_version": 1,
            "verification_profile": "structural_v1",
            "decision": "pass",
            "accounting_complete": True,
            "selected_point_count": len(rows),
            "verified_count": len(rows),
            "needs_review_count": 0,
            "hard_failed_count": 0,
            "selected_point_outcomes": outcomes,
            "blocker_codes": [],
            "source_fingerprint": _digest(
                {"sourceDigests": [ref["artifactDigest"] for ref in source_refs]}
            ),
            "model_provider": "deterministic-service",
            "model_name": CARD_GENERATION_POLICY_VERSION,
            "created_at": revision,
            "cardPlanSetDigest": graph["planSetRef"]["artifactDigest"],
            "ruleSetVersion": CARD_RELIABILITY_RULE_SET_VERSION,
        }
        reliability_id = "reliability_" + operation_digest[:40]
        reliability = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=revision,
            artifact_id=reliability_id,
            artifact_revision=1,
            payload_schema="study.reliability-manifest",
            payload_schema_version=1,
            payload=reliability_payload,
            producer=_PRODUCER,
            parents=[graph["planSetRef"], graph["validationRef"], *card_refs],
            input_fingerprint=input_fingerprint,
            completeness={
                "state": "complete",
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=[],
        )
        media_payload = {
            "schemaVersion": 1,
            "state": "complete",
            "entries": [],
            "cards": [
                {"cardId": card["cardId"], "mediaRoles": []} for card in card_payloads
            ],
            "mediaCount": 0,
            "policyVersion": CARD_GENERATION_POLICY_VERSION,
        }
        media_id = "media_ledger_" + operation_digest[:40]
        media = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=revision,
            artifact_id=media_id,
            artifact_revision=1,
            payload_schema="study.media-ledger",
            payload_schema_version=1,
            payload=media_payload,
            producer=_PRODUCER,
            parents=card_refs,
            input_fingerprint=input_fingerprint,
            completeness={
                "state": "complete",
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=[],
        )

        contract = project["learningContract"]
        level = str(contract.get("learnerLevel") or "B1")
        legacy_segments = []
        for index, (row, card) in enumerate(zip(rows, card_payloads, strict=True), 1):
            legacy_segments.append(
                {
                    "id": "segment_" + card["cardId"][5:],
                    "text": card["front"]["prompt"],
                    "source_time": f"Study card {index}",
                    "learning_point_id": row["planId"],
                    "cards": [self._legacy_card(card, row["planId"])],
                }
            )
        legacy_project = {
            "schema_version": 15,
            "id": project_id,
            "title": project["title"],
            "source_mode": "document",
            "video_path": "",
            "subtitle_path": "",
            "document_path": "",
            "language": "en",
            "level": level,
            "template_id": "immersive_v11",
            "document_study_mode": "knowledge",
            "content_toggles": {"video": False, "tts": False},
            "card_types": ["knowledge"],
            "segments": legacy_segments,
            "reliability_manifest": reliability_payload,
            "warnings": [],
            "created_at": revision,
        }
        legacy_id = "legacy_projection_" + operation_digest[:40]
        legacy = self._legacy.publish(
            audience=audience,
            project_id=project_id,
            project_revision=revision,
            artifact_id=legacy_id,
            artifact_revision=1,
            legacy_project=legacy_project,
            resource_bindings=[],
            source_asset_refs=source_refs,
            media_ledger_ref=media.artifact_ref,
            reliability_manifest_ref=reliability.artifact_ref,
            input_fingerprint=input_fingerprint,
            producer=_PRODUCER,
        )
        project_artifact_id = "project_artifact_" + operation_digest[:40]
        project_payload = {
            "cardPlanRefs": [dict(row["planRef"]) for row in rows],
            "sanitizedLegacyProjectRef": dict(legacy.artifact_ref),
            "cardIds": [card["cardId"] for card in card_payloads],
            "reliabilityManifestRef": dict(reliability.artifact_ref),
            "mediaLedgerRef": dict(media.artifact_ref),
        }
        project_artifact = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=revision,
            artifact_id=project_artifact_id,
            artifact_revision=1,
            payload_schema="study.project-artifact",
            payload_schema_version=1,
            payload=project_payload,
            producer=_PRODUCER,
            parents=[
                graph["planSetRef"],
                graph["validationRef"],
                *[dict(row["planRef"]) for row in rows],
                *card_refs,
                reliability.artifact_ref,
                media.artifact_ref,
                legacy.artifact_ref,
            ],
            input_fingerprint=input_fingerprint,
            completeness={
                "state": "complete",
                "expectedUnits": len(rows),
                "processedUnits": len(rows),
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=[],
        )
        return project_artifact.handle

    def _public_result(
        self,
        *,
        audience: ArtifactAudienceBinding,
        committed: Mapping[str, Any],
    ) -> dict[str, Any]:
        matches: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        for ref in committed["artifactRefs"]:
            envelope = self._artifacts.verify_ref(ref, audience)
            if envelope.get("payloadSchema") == "study.project-artifact":
                matches.append((ref, envelope))
        if len(matches) != 1:
            _fail("CARD_GENERATION_RESULT_INVALID", "ProjectArtifact result is invalid")
        ref, envelope = matches[0]
        payload = envelope.get("payload")
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("cardIds"), list
        ):
            _fail(
                "CARD_GENERATION_RESULT_INVALID", "ProjectArtifact payload is invalid"
            )
        return {
            "schemaVersion": 1,
            "projectId": committed["projectId"],
            "projectRevision": committed["projectRevision"],
            "artifactStage": "cards_ready",
            "taskId": committed["taskId"],
            "projectArtifactHandle": self._artifacts.issue_handle(ref, audience),
            "generatedCards": len(payload["cardIds"]),
            "verifiedCards": len(payload["cardIds"]),
            "needsReviewCards": 0,
            "hardFailedCards": 0,
            "mediaCount": 0,
            "generationMode": "deterministic_projection",
            "nextAction": "export_apkg",
        }

    def resolve_current_project_artifact(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_artifact_handle: str,
    ) -> dict[str, Any]:
        if not isinstance(project_artifact_handle, str) or not _HANDLE_RE.fullmatch(
            project_artifact_handle
        ):
            _fail(
                "PROJECT_ARTIFACT_REQUEST_INVALID", "projectArtifactHandle is invalid"
            )
        try:
            ref, envelope = self._artifacts.resolve_with_ref(
                project_artifact_handle, audience
            )
            project = self._projects.get_project(ref["projectId"], audience)
        except (ArtifactRegistryError, ProjectRegistryError) as error:
            raise CardArtifactRuntimeError(error.code, error.message) from error
        if envelope.get("payloadSchema") != "study.project-artifact":
            _fail("PROJECT_ARTIFACT_INVALID", "handle is not a ProjectArtifact")
        stage = project.get("workflow", {}).get("artifactStage")
        if stage not in ARTIFACT_STAGES or ARTIFACT_STAGES.index(
            stage
        ) < ARTIFACT_STAGES.index("cards_ready"):
            _fail("PROJECT_ARTIFACT_STALE", "ProjectArtifact is no longer current")
        current = [
            item
            for item in project.get("latestArtifactRefs", [])
            if isinstance(item, Mapping)
            and item.get("payloadSchema") == "study.project-artifact"
        ]
        if len(current) != 1 or _identity(current[0]) != _identity(ref):
            _fail("PROJECT_ARTIFACT_STALE", "ProjectArtifact is not current")
        payload = envelope.get("payload")
        required = {
            "cardPlanRefs",
            "sanitizedLegacyProjectRef",
            "cardIds",
            "reliabilityManifestRef",
            "mediaLedgerRef",
        }
        if not isinstance(payload, Mapping) or set(payload) != required:
            _fail("PROJECT_ARTIFACT_INVALID", "ProjectArtifact fields are invalid")
        parents = {
            _identity(value): value
            for value in envelope.get("parents", [])
            if isinstance(value, Mapping)
        }
        for support in (
            payload["sanitizedLegacyProjectRef"],
            payload["reliabilityManifestRef"],
            payload["mediaLedgerRef"],
            *payload["cardPlanRefs"],
        ):
            if not isinstance(support, Mapping) or _identity(support) not in parents:
                _fail(
                    "PROJECT_ARTIFACT_INVALID",
                    "ProjectArtifact parent graph is incomplete",
                )
        card_refs = [
            dict(parent)
            for parent in parents.values()
            if parent.get("payloadSchema") == "study.card"
        ]
        card_envelopes = [
            self._artifacts.verify_ref(parent, audience) for parent in card_refs
        ]
        card_ids = sorted(
            str(value.get("payload", {}).get("cardId") or "")
            for value in card_envelopes
        )
        if not card_ids or card_ids != sorted(payload["cardIds"]):
            _fail(
                "PROJECT_ARTIFACT_INVALID", "ProjectArtifact card accounting is invalid"
            )
        legacy_handle = self._artifacts.issue_handle(
            payload["sanitizedLegacyProjectRef"], audience
        )
        legacy = self._legacy.resolve_internal(legacy_handle, audience)
        return {
            "projectRef": dict(ref),
            "projectArtifact": envelope,
            "project": project,
            "cardRefs": card_refs,
            "cardEnvelopes": card_envelopes,
            "legacyProjection": legacy,
        }

    def generate_cards(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        plan_set_handle: str,
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            _fail("CARD_GENERATION_REQUEST_INVALID", "idempotencyKey is invalid")
        if (
            isinstance(expected_project_revision, bool)
            or not isinstance(expected_project_revision, int)
            or expected_project_revision < 1
        ):
            _fail(
                "CARD_GENERATION_REQUEST_INVALID",
                "expectedProjectRevision is invalid",
            )
        if not isinstance(plan_set_handle, str) or not _HANDLE_RE.fullmatch(
            plan_set_handle
        ):
            _fail("CARD_GENERATION_REQUEST_INVALID", "planSetHandle is invalid")
        try:
            graph = self._plans.resolve_current_plan_graph(
                audience=audience, plan_set_handle=plan_set_handle
            )
        except CardPlanQueryError as error:
            raise CardArtifactRuntimeError(error.code, error.message) from error
        project = graph["project"]
        if project.get("projectId") != project_id:
            _fail(
                "CARD_GENERATION_PROJECT_MISMATCH",
                "plan set belongs to another project",
            )
        operation_digest = _digest(
            {
                "schema": "study.card-generation.request",
                "schemaVersion": 1,
                "projectId": project_id,
                "projectRevision": expected_project_revision,
                "planSetDigest": graph["planSetRef"]["artifactDigest"],
                "validationDigest": graph["validationRef"]["artifactDigest"],
                "policyVersion": CARD_GENERATION_POLICY_VERSION,
                "ruleSetVersion": CARD_RELIABILITY_RULE_SET_VERSION,
            }
        )
        operation_id = "card-generation:" + idempotency_key
        try:
            prior = self._projects.get_operation_result(
                audience=audience,
                project_id=project_id,
                operation_id=operation_id,
                operation_digest=operation_digest,
            )
        except ProjectRegistryError as error:
            raise CardArtifactRuntimeError(error.code, error.message) from error
        if prior is not None:
            current_refs = {
                _identity(value)
                for value in project.get("latestArtifactRefs", [])
                if isinstance(value, Mapping)
            }
            prior_refs = {
                _identity(value)
                for value in prior.get("artifactRefs", [])
                if isinstance(value, Mapping)
            }
            if (
                project.get("workflow", {}).get("artifactStage")
                not in {
                    "cards_ready",
                    "apkg_ready",
                    "imported_unverified",
                    "anki_data_verified",
                    "anki_verified",
                }
                or len(prior_refs) != 1
                or not prior_refs.issubset(current_refs)
            ):
                _fail(
                    "CARD_GENERATION_NOT_CURRENT",
                    "idempotent generation result is stale",
                )
            return self._public_result(audience=audience, committed=prior)
        if project.get("projectRevision") != expected_project_revision:
            _fail("PROJECT_REVISION_CONFLICT", "project changed before card generation")
        if project.get("workflow", {}).get("artifactStage") != "plans_ready":
            _fail("CARD_GENERATION_STAGE_CONFLICT", "card generation is not current")
        rows, source_refs = self._plan_rows(audience=audience, graph=graph)
        try:
            work, task_input, capability, authorization, input_fingerprint = (
                self._bundle(
                    audience=audience,
                    project=project,
                    plan_set_ref=graph["planSetRef"],
                    validation_ref=graph["validationRef"],
                    operation_digest=operation_digest,
                )
            )
            task_id = "task_card_generation_" + operation_digest[:40]
            try:
                task = self._tasks.create_task(
                    audience=audience,
                    work_reuse_manifest=work,
                    task_input_manifest=task_input,
                    capability_binding=capability,
                    authorization_binding=authorization,
                    work_units=[
                        {
                            "workUnitId": "deterministic-card-generation",
                            "phase": "generation",
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
                    _fail("TASK_INPUT_MISMATCH", "card generation task input changed")
            if task["state"] not in {"queued", "running", "succeeded"}:
                _fail(
                    "TASK_RECOVERY_REQUIRED", "card generation task requires recovery"
                )
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
                        work_unit_id="deterministic-card-generation",
                    )
                    unit = task["workUnits"][0]
                if unit["state"] != "completed":
                    result_handle = self._publish_artifacts(
                        audience=audience,
                        project=project,
                        graph=graph,
                        rows=rows,
                        source_refs=source_refs,
                        input_fingerprint=input_fingerprint,
                        operation_digest=operation_digest,
                    )
                    task = self._tasks.complete_work_unit(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="complete-" + operation_digest[:37],
                        work_unit_id="deterministic-card-generation",
                        result_handles=[result_handle],
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
                _fail(
                    "CARD_GENERATION_RESULT_INVALID",
                    "generation task result is invalid",
                )
            result_ref, result_envelope = self._artifacts.resolve_with_ref(
                final_task["resultHandles"][0], audience
            )
            if result_envelope.get("payloadSchema") != "study.project-artifact":
                _fail(
                    "CARD_GENERATION_RESULT_INVALID",
                    "generation result is not a ProjectArtifact",
                )
            committed = self._projects.commit_artifact_stage(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                operation_id=operation_id,
                operation_digest=operation_digest,
                task_id=task_id,
                artifact_stage="cards_ready",
                artifact_refs=[result_ref],
                artifact_handles=final_task["resultHandles"],
            )
            return self._public_result(audience=audience, committed=committed)
        except (
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskManifestError,
            LegacyProjectProjectionError,
        ) as error:
            raise CardArtifactRuntimeError(
                getattr(error, "code", "CARD_GENERATION_FAILED"),
                getattr(error, "message", str(error)),
            ) from error


__all__ = [
    "CARD_GENERATION_POLICY_VERSION",
    "CARD_RELIABILITY_RULE_SET_VERSION",
    "CardArtifactRuntime",
    "CardArtifactRuntimeError",
]
