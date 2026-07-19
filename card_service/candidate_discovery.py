"""Controlled two-role candidate discovery over authenticated source representations."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import parse_qsl, urlsplit

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .candidate_artifacts import CandidateArtifactError, CandidateArtifactPublisher
from .candidate_gates import CandidateGateError, evaluate_language_candidate

DISCOVERY_POLICY_VERSION = "candidate-discovery-language-v1"
PROPOSAL_ROLE_VERSION = "high-recall-language-proposer-v1"
REVIEW_ROLE_VERSION = "independent-learning-reviewer-v1"
_MAX_REPRESENTATIONS = 64
_MAX_PROPOSALS = 256
_MAX_DISCLOSURE_CHARACTERS = 256_000
_MAX_NODE_CHARACTERS = 4_096
_MAX_MODEL_RESPONSE_BYTES = 2 * 1024 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_URL_RE = re.compile(r"(?i)https?://[^\s<>\"']+")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:^|\s)(?:[a-z]:[\\/]|\\\\)")
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}\b", re.IGNORECASE),
)
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "auth",
        "authorization",
        "credential",
        "key",
        "signature",
        "sig",
        "token",
        "x-amz-credential",
        "x-amz-signature",
        "x-goog-credential",
        "x-goog-signature",
    }
)
_LANGUAGE_ROUTES = frozenset(
    {
        "reading_recognition",
        "listening_recognition",
        "production",
        "grammar_cloze",
        "pronunciation",
        "pragmatics_register",
        "chunk_collocation",
        "contrast",
    }
)
_FORM_TYPES = frozenset({"word", "phrase", "grammar", "pronunciation", "pragmatic"})


class CandidateDiscoveryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CandidateDiscoveryModelIdentity:
    profile_ref: str
    configuration_fingerprint: str
    credential_revision: int
    implementation_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.profile_ref, str) or not _ID_RE.fullmatch(self.profile_ref):
            raise CandidateDiscoveryError(
                "DISCOVERY_MODEL_IDENTITY_INVALID", "model profileRef is invalid"
            )
        if not isinstance(self.configuration_fingerprint, str) or not _DIGEST_RE.fullmatch(self.configuration_fingerprint):
            raise CandidateDiscoveryError(
                "DISCOVERY_MODEL_IDENTITY_INVALID",
                "model configuration fingerprint is invalid",
            )
        if (
            isinstance(self.credential_revision, bool)
            or not isinstance(self.credential_revision, int)
            or self.credential_revision < 0
        ):
            raise CandidateDiscoveryError(
                "DISCOVERY_MODEL_IDENTITY_INVALID",
                "model credential revision is invalid",
            )
        if not isinstance(self.implementation_version, str) or not _ID_RE.fullmatch(self.implementation_version):
            raise CandidateDiscoveryError(
                "DISCOVERY_MODEL_IDENTITY_INVALID",
                "model implementation version is invalid",
            )

    def public(self) -> dict[str, Any]:
        return {
            "profileRef": self.profile_ref,
            "configurationFingerprint": self.configuration_fingerprint,
            "credentialRevision": self.credential_revision,
            "implementationVersion": self.implementation_version,
        }


class CandidateDiscoveryModel(Protocol):
    @property
    def identity(self) -> CandidateDiscoveryModelIdentity: ...
    def propose(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def review(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class CandidateDiscoveryModelProvider(Protocol):
    @property
    def identity(self) -> CandidateDiscoveryModelIdentity: ...
    def bind(self, task_id: str) -> CandidateDiscoveryModel: ...


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CandidateDiscoveryError(
            "DISCOVERY_INPUT_INVALID", "evaluatedAt must be a UTC timestamp"
        )
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise CandidateDiscoveryError(
            "DISCOVERY_INPUT_INVALID", "evaluatedAt is invalid"
        ) from error
    return value


def _bounded_model_value(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CandidateDiscoveryError(
            "DISCOVERY_MODEL_RESPONSE_INVALID", f"{label} response is not an object"
        )
    try:
        result = _clone(value)
        size = len(canonical_json_bytes(result))
    except (ArtifactRegistryError, TypeError, ValueError) as error:
        raise CandidateDiscoveryError(
            "DISCOVERY_MODEL_RESPONSE_INVALID", f"{label} response is invalid"
        ) from error
    if size > _MAX_MODEL_RESPONSE_BYTES:
        raise CandidateDiscoveryError(
            "DISCOVERY_MODEL_RESPONSE_INVALID", f"{label} response is too large"
        )
    return result


def _text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise CandidateDiscoveryError(
            "DISCOVERY_MODEL_RESPONSE_INVALID", f"{label} must be text"
        )
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > maximum:
        raise CandidateDiscoveryError(
            "DISCOVERY_MODEL_RESPONSE_INVALID", f"{label} length is invalid"
        )
    if any(ord(character) < 32 and character not in "\t\n" for character in normalized):
        raise CandidateDiscoveryError(
            "DISCOVERY_MODEL_RESPONSE_INVALID", f"{label} has a control character"
        )
    return normalized


def _sensitive_reason(value: str) -> str | None:
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        return "DISCOVERY_SECRET_TEXT_OMITTED"
    if _WINDOWS_PATH_RE.search(value):
        return "DISCOVERY_LOCAL_PATH_OMITTED"
    for match in _URL_RE.finditer(value):
        try:
            parsed = urlsplit(match.group(0).rstrip(".,;:!?)"))
            query = parse_qsl(parsed.query, keep_blank_values=True)
        except ValueError:
            return "DISCOVERY_SENSITIVE_URL_OMITTED"
        for key, child in query:
            if key.casefold() in _SENSITIVE_QUERY_KEYS or len(child) >= 48:
                return "DISCOVERY_SENSITIVE_URL_OMITTED"
    return None


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class CandidateDiscoveryEngine:
    """Run proposer and reviewer roles, then let deterministic gates decide."""

    def __init__(
        self, *, artifacts: ArtifactRegistry, model: CandidateDiscoveryModel
    ) -> None:
        if not isinstance(model.identity, CandidateDiscoveryModelIdentity):
            raise CandidateDiscoveryError(
                "DISCOVERY_MODEL_IDENTITY_INVALID", "model identity is invalid"
            )
        self._artifacts = artifacts
        self._model = model
        self._publisher = CandidateArtifactPublisher(artifacts)

    @staticmethod
    def _completeness(count: int) -> dict[str, Any]:
        return {
            "state": "complete",
            "expectedUnits": count,
            "processedUnits": count,
            "omittedLocators": [],
            "reasonCodes": [],
        }

    def _resolve_inspection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        project_revision: int,
        inspection_ref: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            envelope = self._artifacts.verify_ref(inspection_ref, audience)
        except ArtifactRegistryError as error:
            raise CandidateDiscoveryError(error.code, error.message) from error
        if (
            inspection_ref.get("projectId") != project_id
            or inspection_ref.get("projectRevision", project_revision + 1)
            > project_revision
            or envelope.get("payloadSchema") != "study.inspection"
            or envelope.get("payloadSchemaVersion") != 1
            or not isinstance(envelope.get("payload"), Mapping)
        ):
            raise CandidateDiscoveryError(
                "DISCOVERY_INSPECTION_INVALID",
                "inspectionRef is outside the project scope",
            )
        return envelope

    def _source_states(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        inspection_payload: Mapping[str, Any],
        inspection_parents: Sequence[Mapping[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        refs = inspection_payload.get("sourceInspectionRefs")
        if not isinstance(refs, list) or len(refs) > _MAX_REPRESENTATIONS:
            raise CandidateDiscoveryError(
                "DISCOVERY_INSPECTION_INVALID", "source inspection refs are invalid"
            )
        states: dict[str, dict[str, str]] = {}
        for ref in refs:
            if not isinstance(ref, Mapping):
                raise CandidateDiscoveryError(
                    "DISCOVERY_INSPECTION_INVALID", "source inspection ref is invalid"
                )
            try:
                envelope = self._artifacts.verify_ref(ref, audience)
            except ArtifactRegistryError as error:
                raise CandidateDiscoveryError(error.code, error.message) from error
            payload = envelope.get("payload")
            representation_refs = (
                payload.get("representationRefs")
                if isinstance(payload, Mapping)
                else None
            )
            if (
                ref.get("projectId") != project_id
                or dict(ref) not in inspection_parents
                or envelope.get("payloadSchema") != "study.source-inspection"
                or not isinstance(payload, Mapping)
                or not isinstance(payload.get("sourceId"), str)
                or payload.get("supportTier") not in {"A", "B", "C"}
                or payload.get("status") not in {"ready", "conditional", "blocked"}
                or not isinstance(representation_refs, list)
                or not all(
                    isinstance(value, Mapping)
                    and dict(value) in envelope.get("parents", [])
                    for value in representation_refs
                )
                or payload["sourceId"] in states
            ):
                raise CandidateDiscoveryError(
                    "DISCOVERY_INSPECTION_INVALID", "source inspection graph is invalid"
                )
            states[payload["sourceId"]] = {
                "sourceId": payload["sourceId"],
                "supportTier": payload["supportTier"],
                "status": payload["status"],
                "representationRefs": [dict(value) for value in representation_refs],
            }
        return states

    def _contexts(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        inspection_payload: Mapping[str, Any],
        inspection_parents: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        refs = inspection_payload.get("representationRefs")
        if (
            not isinstance(refs, list)
            or not 1 <= len(refs) <= _MAX_REPRESENTATIONS
            or not all(isinstance(value, Mapping) for value in refs)
        ):
            raise CandidateDiscoveryError(
                "DISCOVERY_INSPECTION_INVALID", "representation refs are invalid"
            )
        states = self._source_states(
            audience=audience,
            project_id=project_id,
            inspection_payload=inspection_payload,
            inspection_parents=inspection_parents,
        )
        expected_representations = [
            value
            for state in states.values()
            for value in state["representationRefs"]
        ]
        if (
            len(expected_representations) != len(refs)
            or sorted(canonical_json_bytes(value) for value in expected_representations)
            != sorted(canonical_json_bytes(value) for value in refs)
        ):
            raise CandidateDiscoveryError(
                "DISCOVERY_INSPECTION_INVALID",
                "inspection representation summary does not match its details",
            )
        contexts: list[dict[str, Any]] = []
        issues: list[str] = []
        disclosed = 0
        for ref in sorted(refs, key=lambda value: value["artifactId"].encode("utf-8")):
            try:
                envelope = self._artifacts.verify_ref(ref, audience)
            except ArtifactRegistryError as error:
                raise CandidateDiscoveryError(error.code, error.message) from error
            payload = envelope.get("payload")
            if (
                ref.get("projectId") != project_id
                or envelope.get("payloadSchema") != "study.source-representation"
                or not isinstance(payload, Mapping)
                or not isinstance(payload.get("representationId"), str)
                or not isinstance(payload.get("sourceId"), str)
                or not isinstance(payload.get("plainTextBlobRef"), Mapping)
                or not isinstance(payload.get("contentNodes"), list)
            ):
                raise CandidateDiscoveryError(
                    "DISCOVERY_INSPECTION_INVALID", "representation graph is invalid"
                )
            state = states.get(payload["sourceId"])
            if state is None or dict(ref) not in state["representationRefs"]:
                raise CandidateDiscoveryError(
                    "DISCOVERY_INSPECTION_INVALID", "representation has no source state"
                )
            try:
                text = self._artifacts.read_blob(payload["plainTextBlobRef"]).decode(
                    "utf-8", errors="strict"
                )
            except (ArtifactRegistryError, UnicodeDecodeError) as error:
                raise CandidateDiscoveryError(
                    "DISCOVERY_SOURCE_UNREADABLE",
                    "representation text failed verification",
                ) from error
            windows: list[dict[str, Any]] = []
            if state["supportTier"] != "C" and state["status"] != "blocked":
                for node in payload["contentNodes"]:
                    attributes = (
                        node.get("attributes") if isinstance(node, Mapping) else None
                    )
                    start = (
                        attributes.get("textStart")
                        if isinstance(attributes, Mapping)
                        else None
                    )
                    end = (
                        attributes.get("textEnd")
                        if isinstance(attributes, Mapping)
                        else None
                    )
                    node_id = node.get("nodeId") if isinstance(node, Mapping) else None
                    if (
                        not isinstance(node_id, str)
                        or not isinstance(start, int)
                        or isinstance(start, bool)
                        or not isinstance(end, int)
                        or isinstance(end, bool)
                        or start < 0
                        or end <= start
                        or end > len(text)
                        or end - start > _MAX_NODE_CHARACTERS
                    ):
                        raise CandidateDiscoveryError(
                            "DISCOVERY_INSPECTION_INVALID",
                            "content node bounds are invalid",
                        )
                    excerpt = text[start:end]
                    reason = _sensitive_reason(excerpt)
                    if reason is not None:
                        issues.append(reason)
                        continue
                    if disclosed + len(excerpt) > _MAX_DISCLOSURE_CHARACTERS:
                        issues.append("DISCOVERY_DISCLOSURE_LIMIT_REACHED")
                        break
                    windows.append(
                        {"nodeId": node_id, "start": start, "end": end, "text": excerpt}
                    )
                    disclosed += len(excerpt)
            contexts.append(
                {
                    "representationRef": dict(ref),
                    "representationPayload": _clone(payload),
                    "representationText": text,
                    "representationId": payload["representationId"],
                    "sourceId": payload["sourceId"],
                    "sourceInspection": state,
                    "windows": windows,
                }
            )
        return contexts, sorted(set(issues))

    @staticmethod
    def _proposal_request(
        *,
        contexts: Sequence[Mapping[str, Any]],
        learning_contract: Mapping[str, Any],
        maximum_proposals: int,
    ) -> dict[str, Any]:
        allowed_contract_fields = {
            "purpose",
            "targetBehavior",
            "learnerLevel",
            "routes",
            "promptLanguage",
            "answerLanguage",
            "exclusions",
            "evidencePolicy",
        }
        contract = {
            key: _clone(value)
            for key, value in learning_contract.items()
            if key in allowed_contract_fields
        }
        return {
            "schema": "study.candidate-discovery.proposal-request",
            "schemaVersion": 1,
            "role": PROPOSAL_ROLE_VERSION,
            "learningContract": contract,
            "sources": [
                {
                    "representationId": value["representationId"],
                    "sourceId": value["sourceId"],
                    "supportTier": value["sourceInspection"]["supportTier"],
                    "windows": _clone(value["windows"]),
                }
                for value in contexts
                if value["windows"]
            ],
            "constraints": {
                "maximumProposals": maximum_proposals,
                "maximumSpansPerProposal": 4,
                "submitEligibility": False,
                "submitScores": False,
                "submitGateResults": False,
                "submitUserLocks": False,
            },
        }

    @staticmethod
    def _proposal_in_windows(
        spans: Sequence[Mapping[str, Any]], windows: Sequence[Mapping[str, Any]]
    ) -> bool:
        return all(
            any(
                span["nodeId"] == window["nodeId"]
                and span["start"] >= window["start"]
                and span["end"] <= window["end"]
                for window in windows
            )
            for span in spans
        )

    def _proposals(
        self,
        response: Any,
        *,
        contexts: Sequence[Mapping[str, Any]],
        maximum_proposals: int,
    ) -> tuple[list[dict[str, Any]], int]:
        value = _bounded_model_value(response, label="proposal")
        if set(value) != {"schema", "schemaVersion", "proposals"} or (
            value.get("schema") != "study.candidate-discovery.proposals"
            or value.get("schemaVersion") != 1
            or not isinstance(value.get("proposals"), list)
            or len(value["proposals"]) > maximum_proposals
        ):
            raise CandidateDiscoveryError(
                "DISCOVERY_MODEL_RESPONSE_INVALID",
                "proposal response fields are invalid",
            )
        by_representation = {item["representationId"]: item for item in contexts}
        proposals: list[dict[str, Any]] = []
        collapsed = 0
        seen: set[bytes] = set()
        expected = {
            "representationId",
            "language",
            "form",
            "formType",
            "meaningOrFunction",
            "route",
            "spans",
        }
        for raw in value["proposals"]:
            if not isinstance(raw, Mapping) or set(raw) != expected:
                raise CandidateDiscoveryError(
                    "DISCOVERY_MODEL_RESPONSE_INVALID", "proposal fields are invalid"
                )
            representation_id = raw.get("representationId")
            context = by_representation.get(representation_id)
            spans = raw.get("spans")
            if (
                context is None
                or not isinstance(spans, list)
                or not 1 <= len(spans) <= 4
            ):
                raise CandidateDiscoveryError(
                    "DISCOVERY_MODEL_RESPONSE_INVALID", "proposal source is invalid"
                )
            normalized_spans = []
            for span in spans:
                if (
                    not isinstance(span, Mapping)
                    or set(span) != {"nodeId", "start", "end"}
                    or not isinstance(span.get("nodeId"), str)
                    or isinstance(span.get("start"), bool)
                    or not isinstance(span.get("start"), int)
                    or isinstance(span.get("end"), bool)
                    or not isinstance(span.get("end"), int)
                    or span["start"] < 0
                    or span["end"] <= span["start"]
                ):
                    raise CandidateDiscoveryError(
                        "DISCOVERY_MODEL_RESPONSE_INVALID", "proposal span is invalid"
                    )
                normalized_spans.append(dict(span))
            normalized_spans.sort(
                key=lambda item: (item["start"], item["end"], item["nodeId"])
            )
            if not self._proposal_in_windows(normalized_spans, context["windows"]):
                raise CandidateDiscoveryError(
                    "DISCOVERY_MODEL_RESPONSE_INVALID",
                    "proposal span is outside the disclosed source windows",
                )
            proposal = {
                "representationId": representation_id,
                "language": _text(raw["language"], "language", maximum=32),
                "form": _text(raw["form"], "form", maximum=160),
                "formType": raw["formType"],
                "meaningOrFunction": _text(
                    raw["meaningOrFunction"], "meaningOrFunction", maximum=500
                ),
                "route": raw["route"],
                "spans": normalized_spans,
            }
            if (
                proposal["formType"] not in _FORM_TYPES
                or proposal["route"] not in _LANGUAGE_ROUTES
            ):
                raise CandidateDiscoveryError(
                    "DISCOVERY_MODEL_RESPONSE_INVALID", "proposal taxonomy is invalid"
                )
            encoded = canonical_json_bytes(proposal)
            if encoded in seen:
                collapsed += 1
                continue
            seen.add(encoded)
            proposal["reviewKey"] = "review_" + hashlib.sha256(encoded).hexdigest()[:40]
            proposals.append(proposal)
        proposals.sort(key=canonical_json_bytes)
        return proposals, collapsed

    @staticmethod
    def _review_request(
        proposals: Sequence[Mapping[str, Any]],
        contexts: Sequence[Mapping[str, Any]],
        learning_contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        by_representation = {value["representationId"]: value for value in contexts}
        review_items = []
        for value in proposals:
            if _sensitive_reason(value["form"] + "\n" + value["meaningOrFunction"]):
                continue
            source = by_representation[value["representationId"]]
            evidence = []
            for span in value["spans"]:
                window = next(
                    item
                    for item in source["windows"]
                    if item["nodeId"] == span["nodeId"]
                    and item["start"] <= span["start"]
                    and item["end"] >= span["end"]
                )
                context_start = max(window["start"], span["start"] - 240)
                context_end = min(window["end"], span["end"] + 240)
                context_text = source["representationText"][context_start:context_end]
                evidence.append(
                    {
                        "nodeId": span["nodeId"],
                        "quote": source["representationText"][span["start"]:span["end"]],
                        "context": context_text,
                        "targetStartInContext": span["start"] - context_start,
                        "targetEndInContext": span["end"] - context_start,
                    }
                )
            review_items.append(
                {
                    "reviewKey": value["reviewKey"],
                    "language": value["language"],
                    "form": value["form"],
                    "formType": value["formType"],
                    "meaningOrFunction": value["meaningOrFunction"],
                    "route": value["route"],
                    "evidence": evidence,
                }
            )
        contract_fields = {
            "purpose", "targetBehavior", "learnerLevel", "routes",
            "promptLanguage", "answerLanguage", "exclusions", "evidencePolicy",
        }
        return {
            "schema": "study.candidate-discovery.review-request",
            "schemaVersion": 1,
            "role": REVIEW_ROLE_VERSION,
            "learningContract": {
                key: _clone(value)
                for key, value in learning_contract.items()
                if key in contract_fields
            },
            "proposals": review_items,
            "constraints": {
                "submitEligibility": False,
                "submitScores": False,
                "submitGateResults": False,
                "duplicateDecisionOwnedByService": True,
            },
        }

    @staticmethod
    def _reviews(
        response: Any, *, expected_keys: set[str]
    ) -> tuple[dict[str, dict[str, Any]], bool]:
        value = _bounded_model_value(response, label="review")
        if set(value) != {"schema", "schemaVersion", "reviews"} or (
            value.get("schema") != "study.candidate-discovery.reviews"
            or value.get("schemaVersion") != 1
            or not isinstance(value.get("reviews"), list)
            or len(value["reviews"]) > len(expected_keys)
        ):
            raise CandidateDiscoveryError(
                "DISCOVERY_MODEL_RESPONSE_INVALID", "review response fields are invalid"
            )
        reviews: dict[str, dict[str, Any]] = {}
        expected = {
            "reviewKey",
            "semanticEvidence",
            "conflict",
            "learnerFit",
            "reasonCodes",
        }
        for raw in value["reviews"]:
            if not isinstance(raw, Mapping) or set(raw) != expected:
                raise CandidateDiscoveryError(
                    "DISCOVERY_MODEL_RESPONSE_INVALID", "review fields are invalid"
                )
            key = raw.get("reviewKey")
            reasons = raw.get("reasonCodes")
            if (
                key not in expected_keys
                or key in reviews
                or raw.get("semanticEvidence") not in {"verified", "review", "failed"}
                or raw.get("conflict") not in {"clear", "conflict", "unknown"}
                or raw.get("learnerFit") not in {"new", "partial", "known", "unknown"}
                or not isinstance(reasons, list)
                or len(reasons) > 8
                or any(
                    not isinstance(reason, str) or not _REASON_RE.fullmatch(reason)
                    for reason in reasons
                )
            ):
                raise CandidateDiscoveryError(
                    "DISCOVERY_MODEL_RESPONSE_INVALID", "review value is invalid"
                )
            reviews[key] = {
                "reviewKey": key,
                "semanticEvidence": raw["semanticEvidence"],
                "conflict": raw["conflict"],
                "learnerFit": raw["learnerFit"],
                "reasonCodes": sorted(set(reasons)),
                "reviewerReturned": True,
            }
        incomplete = set(reviews) != expected_keys
        for key in sorted(expected_keys - set(reviews)):
            reviews[key] = {
                "reviewKey": key,
                "semanticEvidence": "review",
                "conflict": "unknown",
                "learnerFit": "unknown",
                "reasonCodes": ["INDEPENDENT_REVIEW_MISSING"],
                "reviewerReturned": False,
            }
        return reviews, incomplete

    def _publish_batch(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        project_revision: int,
        input_fingerprint: str,
        artifact_id: str,
        payload_schema: str,
        payload: Mapping[str, Any],
        parents: Sequence[Mapping[str, Any]],
        issue_refs: Sequence[str],
    ):
        count = len(payload.get("proposals", payload.get("reviews", [])))
        return self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=project_revision,
            artifact_id=artifact_id,
            artifact_revision=1,
            payload_schema=payload_schema,
            payload_schema_version=1,
            payload=payload,
            producer={"component": "candidate-discovery-engine", "version": "1.0.0"},
            parents=parents,
            input_fingerprint=input_fingerprint,
            completeness=self._completeness(count),
            issue_refs=sorted(set(issue_refs)),
        )

    def discover(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        project_revision: int,
        input_fingerprint: str,
        inspection_ref: Mapping[str, Any],
        learning_contract: Mapping[str, Any],
        evaluated_at: str,
        maximum_proposals: int | None = None,
    ) -> dict[str, Any]:
        if (
            not isinstance(project_revision, int)
            or isinstance(project_revision, bool)
            or project_revision < 1
            or not isinstance(input_fingerprint, str)
            or not _DIGEST_RE.fullmatch(input_fingerprint)
            or not isinstance(learning_contract, Mapping)
        ):
            raise CandidateDiscoveryError(
                "DISCOVERY_INPUT_INVALID", "discovery inputs are invalid"
            )
        evaluated_at = _timestamp(evaluated_at)
        routes = learning_contract.get("routes")
        if not isinstance(routes, list) or not (set(routes) & _LANGUAGE_ROUTES):
            raise CandidateDiscoveryError(
                "DISCOVERY_LANGUAGE_ROUTE_REQUIRED",
                "learning contract has no language-learning route",
            )
        inspection = self._resolve_inspection(
            audience=audience,
            project_id=project_id,
            project_revision=project_revision,
            inspection_ref=inspection_ref,
        )
        contexts, issues = self._contexts(
            audience=audience,
            project_id=project_id,
            inspection_payload=inspection["payload"],
            inspection_parents=inspection["parents"],
        )
        if maximum_proposals is None:
            budget = learning_contract.get("budget")
            nested_maximum = (
                budget.get("maxNewCards") if isinstance(budget, Mapping) else None
            )
            max_new_cards = learning_contract.get("maxNewCards", nested_maximum)
            if isinstance(max_new_cards, bool) or not isinstance(max_new_cards, int):
                max_new_cards = 20
            maximum_proposals = min(_MAX_PROPOSALS, max(8, max_new_cards * 4))
        elif (
            isinstance(maximum_proposals, bool)
            or not isinstance(maximum_proposals, int)
            or not 1 <= maximum_proposals <= _MAX_PROPOSALS
        ):
            raise CandidateDiscoveryError(
                "DISCOVERY_INPUT_INVALID", "maximum proposal budget is invalid"
            )
        proposal_request = self._proposal_request(
            contexts=contexts,
            learning_contract=learning_contract,
            maximum_proposals=maximum_proposals,
        )
        if proposal_request["sources"]:
            try:
                proposal_response = self._model.propose(_clone(proposal_request))
            except CandidateDiscoveryError:
                raise
            except Exception as error:
                raise CandidateDiscoveryError(
                    "DISCOVERY_PROPOSER_FAILED", "candidate proposer failed safely"
                ) from error
        else:
            proposal_response = {
                "schema": "study.candidate-discovery.proposals",
                "schemaVersion": 1,
                "proposals": [],
            }
        proposals, collapsed = self._proposals(
            proposal_response, contexts=contexts, maximum_proposals=maximum_proposals
        )
        if collapsed:
            issues.append("DISCOVERY_EXACT_PROPOSALS_COLLAPSED")
        safe_proposals = []
        suppressed_digests = []
        for proposal in proposals:
            if _sensitive_reason(
                proposal["form"] + "\n" + proposal["meaningOrFunction"]
            ):
                suppressed_digests.append(_digest(proposal))
                issues.append("DISCOVERY_UNSAFE_PROPOSAL_SUPPRESSED")
            else:
                safe_proposals.append(_clone(proposal))
        proposal_batch_id = (
            "proposal_batch_"
            + _digest(
                {
                    "inspectionRef": dict(inspection_ref),
                    "inputFingerprint": input_fingerprint,
                    "proposals": safe_proposals,
                    "suppressedProposalDigests": suppressed_digests,
                }
            )[:40]
        )
        proposal_payload = {
            "batchId": proposal_batch_id,
            "inspectionRef": dict(inspection_ref),
            "role": PROPOSAL_ROLE_VERSION,
            "modelIdentity": self._model.identity.public(),
            "proposals": safe_proposals,
            "suppressedProposalDigests": suppressed_digests,
            "issueRefs": sorted(set(issues)),
        }
        proposal_batch = self._publish_batch(
            audience=audience,
            project_id=project_id,
            project_revision=project_revision,
            input_fingerprint=input_fingerprint,
            artifact_id=proposal_batch_id,
            payload_schema="study.discovery-proposal-batch",
            payload=proposal_payload,
            parents=[dict(inspection_ref)],
            issue_refs=issues,
        )
        review_request = self._review_request(
            safe_proposals, contexts, learning_contract
        )
        if review_request["proposals"]:
            try:
                review_response = self._model.review(_clone(review_request))
            except CandidateDiscoveryError:
                raise
            except Exception as error:
                raise CandidateDiscoveryError(
                    "DISCOVERY_REVIEWER_FAILED", "candidate reviewer failed safely"
                ) from error
        else:
            review_response = {
                "schema": "study.candidate-discovery.reviews",
                "schemaVersion": 1,
                "reviews": [],
            }
        expected_review_keys = {value["reviewKey"] for value in safe_proposals}
        reviews, incomplete = self._reviews(
            review_response, expected_keys=expected_review_keys
        )
        review_issues = ["DISCOVERY_REVIEW_INCOMPLETE"] if incomplete else []
        review_batch_id = (
            "review_batch_"
            + _digest(
                {
                    "proposalBatchRef": proposal_batch.artifact_ref,
                    "inputFingerprint": input_fingerprint,
                    "reviews": [reviews[key] for key in sorted(reviews)],
                }
            )[:40]
        )
        review_payload = {
            "batchId": review_batch_id,
            "proposalBatchRef": dict(proposal_batch.artifact_ref),
            "role": REVIEW_ROLE_VERSION,
            "modelIdentity": self._model.identity.public(),
            "reviews": [reviews[key] for key in sorted(reviews)],
            "issueRefs": review_issues,
        }
        review_batch = self._publish_batch(
            audience=audience,
            project_id=project_id,
            project_revision=project_revision,
            input_fingerprint=input_fingerprint,
            artifact_id=review_batch_id,
            payload_schema="study.discovery-review-batch",
            payload=review_payload,
            parents=[proposal_batch.artifact_ref],
            issue_refs=review_issues,
        )
        by_representation = {value["representationId"]: value for value in contexts}
        semantic_seen: set[tuple[str, str, str, str]] = set()
        publications = []
        for proposal in proposals:
            unsafe = _sensitive_reason(
                proposal["form"] + "\n" + proposal["meaningOrFunction"]
            )
            review = reviews.get(proposal["reviewKey"])
            if unsafe is not None:
                trusted = {
                    "semanticEvidence": "failed",
                    "duplicate": "unknown",
                    "conflict": "unknown",
                    "learnerFit": "unknown",
                }
            else:
                assert review is not None
                semantic_key = (
                    _normalized(proposal["language"]),
                    _normalized(proposal["form"]),
                    _normalized(proposal["meaningOrFunction"]),
                    proposal["route"],
                )
                duplicate = "duplicate" if semantic_key in semantic_seen else "unique"
                semantic_seen.add(semantic_key)
                trusted = {
                    "semanticEvidence": review["semanticEvidence"],
                    "duplicate": duplicate,
                    "conflict": review["conflict"],
                    "learnerFit": review["learnerFit"],
                }
            context = by_representation[proposal["representationId"]]
            closed_proposal = {
                key: _clone(proposal[key])
                for key in (
                    "language",
                    "form",
                    "formType",
                    "meaningOrFunction",
                    "route",
                    "spans",
                )
            }
            try:
                draft = evaluate_language_candidate(
                    proposal=closed_proposal,
                    representation_ref=context["representationRef"],
                    representation_payload=context["representationPayload"],
                    representation_text=context["representationText"],
                    source_inspection=context["sourceInspection"],
                    learning_contract=learning_contract,
                    trusted_assessments=trusted,
                    project_revision=project_revision,
                    input_fingerprint=input_fingerprint,
                    evaluated_at=evaluated_at,
                )
                publication = self._publisher.publish_candidate(
                    audience=audience,
                    project_id=project_id,
                    project_revision=project_revision,
                    input_fingerprint=input_fingerprint,
                    draft=draft,
                    candidate_parent_refs=[proposal_batch.artifact_ref],
                    gate_parent_refs=[review_batch.artifact_ref],
                )
            except (CandidateGateError, CandidateArtifactError) as error:
                raise CandidateDiscoveryError(
                    getattr(error, "code", "DISCOVERY_GATE_FAILED"),
                    getattr(error, "message", "candidate gate failed safely"),
                ) from error
            publications.append(publication)
        try:
            discovery = self._publisher.publish_discovery(
                audience=audience,
                project_id=project_id,
                project_revision=project_revision,
                input_fingerprint=input_fingerprint,
                inspection_ref=inspection_ref,
                candidates=publications,
                issue_refs=[*issues, *review_issues],
            )
        except CandidateArtifactError as error:
            raise CandidateDiscoveryError(error.code, error.message) from error
        return {
            "schemaVersion": 1,
            "projectId": project_id,
            "projectRevision": project_revision,
            "inputFingerprint": input_fingerprint,
            "proposalBatchHandle": proposal_batch.handle,
            "proposalBatchRef": dict(proposal_batch.artifact_ref),
            "reviewBatchHandle": review_batch.handle,
            "reviewBatchRef": dict(review_batch.artifact_ref),
            "candidatePublications": publications,
            **discovery,
            "issueCodes": sorted(
                set(issues + review_issues + list(discovery["issueCodes"]))
            ),
        }


__all__ = [
    "CandidateDiscoveryEngine",
    "CandidateDiscoveryError",
    "CandidateDiscoveryModel",
    "CandidateDiscoveryModelIdentity",
    "CandidateDiscoveryModelProvider",
    "DISCOVERY_POLICY_VERSION",
    "PROPOSAL_ROLE_VERSION",
    "REVIEW_ROLE_VERSION",
]
