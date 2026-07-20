"""Deterministic learning-candidate gates for model-assisted discovery.

The model may propose a language form and its intended meaning. It cannot choose
eligibility, scores, evidence validity, or gate outcomes. This module consumes a
closed proposal plus trusted source/reviewer state and derives an auditable draft
that a later Artifact publisher can persist without circular self references.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Any, Mapping, Sequence

from .artifact_registry import canonical_json_bytes
from .language_profiles import (
    EN,
    candidate_language_profile,
    contains_han,
    is_latin_script_text,
    normalize_answer_leakage_text,
    normalize_language,
)


CANDIDATE_GATE_RULE_SET_VERSION = "candidate-gates-language-v1"
_PRODUCER = {"component": "candidate-gate-engine", "version": "1.0.0"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_URL_RE = re.compile(r"(?i)\b(?:https?|file)://")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:^|\s)(?:[a-z]:[\\/]|\\\\)")
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}\b", re.IGNORECASE),
)
_FORM_TYPES = frozenset({"word", "phrase", "grammar", "pronunciation", "pragmatic"})
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
_SEMANTIC_REVIEW_STATES = frozenset({"verified", "review", "failed"})
_DUPLICATE_STATES = frozenset({"unique", "duplicate", "unknown"})
_CONFLICT_STATES = frozenset({"clear", "conflict", "unknown"})
_LEARNER_FIT_STATES = frozenset({"new", "partial", "known", "unknown"})
_MAX_SPANS = 4
_MAX_FORM_CHARACTERS = 160
_MAX_MEANING_CHARACTERS = 500


class CandidateGateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _clone(value: Any) -> Any:
    import json

    return json.loads(json.dumps(value, ensure_ascii=False))


def _text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", f"{label} must be text")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > maximum:
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", f"{label} length is invalid"
        )
    if any(ord(character) < 32 and character not in "\t\n" for character in normalized):
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", f"{label} contains a control character"
        )
    return normalized


def _normalized_match(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    value = value.replace("…", "...")
    value = re.sub(r"\s*\.\.\.\s*", " ... ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", "evaluatedAt must be a UTC RFC 3339 timestamp"
        )
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", "evaluatedAt is invalid"
        ) from error
    return value


def _artifact_ref(value: Any, label: str) -> dict[str, Any]:
    required = {
        "artifactId",
        "projectId",
        "projectRevision",
        "artifactRevision",
        "payloadSchema",
        "payloadSchemaVersion",
        "artifactDigest",
        "registryAuthRef",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", f"{label} is invalid")
    result = dict(value)
    for key in ("artifactId", "projectId", "payloadSchema", "registryAuthRef"):
        if not isinstance(result[key], str) or not _ID_RE.fullmatch(result[key]):
            raise CandidateGateError(
                "CANDIDATE_SCHEMA_INVALID", f"{label}.{key} is invalid"
            )
    for key in ("projectRevision", "artifactRevision", "payloadSchemaVersion"):
        if (
            isinstance(result[key], bool)
            or not isinstance(result[key], int)
            or result[key] < 1
        ):
            raise CandidateGateError(
                "CANDIDATE_SCHEMA_INVALID", f"{label}.{key} is invalid"
            )
    if not isinstance(result["artifactDigest"], str) or not _DIGEST_RE.fullmatch(
        result["artifactDigest"]
    ):
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", f"{label}.artifactDigest is invalid"
        )
    return result


def _closed_proposal(value: Any) -> dict[str, Any]:
    required = {
        "language",
        "form",
        "formType",
        "meaningOrFunction",
        "route",
        "spans",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", "Language candidate proposal fields are invalid"
        )
    language = _text(value["language"], "language", maximum=32)
    language = normalize_language(language) or language
    form = _text(value["form"], "form", maximum=_MAX_FORM_CHARACTERS)
    meaning = _text(
        value["meaningOrFunction"],
        "meaningOrFunction",
        maximum=_MAX_MEANING_CHARACTERS,
    )
    form_type = value["formType"]
    route = value["route"]
    if form_type not in _FORM_TYPES:
        raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", "formType is invalid")
    if route not in _LANGUAGE_ROUTES:
        raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", "route is invalid")
    spans = value["spans"]
    if (
        not isinstance(spans, Sequence)
        or isinstance(spans, (str, bytes))
        or not 1 <= len(spans) <= _MAX_SPANS
    ):
        raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", "spans are invalid")
    normalized_spans: list[dict[str, Any]] = []
    for raw in spans:
        if not isinstance(raw, Mapping) or set(raw) != {"nodeId", "start", "end"}:
            raise CandidateGateError(
                "CANDIDATE_SCHEMA_INVALID", "candidate span fields are invalid"
            )
        node_id = raw["nodeId"]
        start = raw["start"]
        end = raw["end"]
        if not isinstance(node_id, str) or not _ID_RE.fullmatch(node_id):
            raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", "span nodeId is invalid")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or end <= start
        ):
            raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", "span range is invalid")
        normalized_spans.append({"nodeId": node_id, "start": start, "end": end})
    if normalized_spans != sorted(
        normalized_spans, key=lambda item: (item["start"], item["end"], item["nodeId"])
    ):
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", "spans must use canonical source order"
        )
    for previous, current in zip(normalized_spans, normalized_spans[1:]):
        if current["start"] < previous["end"]:
            raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", "spans overlap")
    return {
        "language": language,
        "form": form,
        "formType": form_type,
        "meaningOrFunction": meaning,
        "route": route,
        "spans": normalized_spans,
    }


def _trusted_assessments(value: Any) -> dict[str, str]:
    expected = {"semanticEvidence", "duplicate", "conflict", "learnerFit"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", "trusted assessment fields are invalid"
        )
    result = {key: str(value[key]) for key in expected}
    if result["semanticEvidence"] not in _SEMANTIC_REVIEW_STATES:
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", "semanticEvidence is invalid"
        )
    if result["duplicate"] not in _DUPLICATE_STATES:
        raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", "duplicate is invalid")
    if result["conflict"] not in _CONFLICT_STATES:
        raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", "conflict is invalid")
    if result["learnerFit"] not in _LEARNER_FIT_STATES:
        raise CandidateGateError("CANDIDATE_SCHEMA_INVALID", "learnerFit is invalid")
    return result


def _nodes(payload: Mapping[str, Any]) -> dict[str, tuple[int, int, Mapping[str, Any]]]:
    raw_nodes = payload.get("contentNodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise CandidateGateError(
            "CANDIDATE_SOURCE_INVALID", "Source representation has no content nodes"
        )
    nodes: dict[str, tuple[int, int, Mapping[str, Any]]] = {}
    for raw in raw_nodes:
        attributes = raw.get("attributes") if isinstance(raw, Mapping) else None
        if not isinstance(raw, Mapping) or not isinstance(attributes, Mapping):
            raise CandidateGateError(
                "CANDIDATE_SOURCE_INVALID", "Source content node is invalid"
            )
        node_id = raw.get("nodeId")
        start = attributes.get("textStart")
        end = attributes.get("textEnd")
        if (
            not isinstance(node_id, str)
            or not _ID_RE.fullmatch(node_id)
            or isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or node_id in nodes
        ):
            raise CandidateGateError(
                "CANDIDATE_SOURCE_INVALID", "Source content node bounds are invalid"
            )
        nodes[node_id] = (start, end, raw)
    return nodes


def _span_replay(
    proposal: Mapping[str, Any],
    *,
    representation_text: str,
    representation_payload: Mapping[str, Any],
) -> tuple[list[str], str | None]:
    if not isinstance(representation_text, str):
        raise CandidateGateError(
            "CANDIDATE_SOURCE_INVALID", "Source representation text is invalid"
        )
    nodes = _nodes(representation_payload)
    values: list[str] = []
    for span in proposal["spans"]:
        node = nodes.get(span["nodeId"])
        if node is None:
            return [], "EVIDENCE_NODE_NOT_FOUND"
        node_start, node_end, _ = node
        if span["start"] < node_start or span["end"] > node_end:
            return [], "EVIDENCE_SPAN_OUTSIDE_NODE"
        if span["end"] > len(representation_text):
            return [], "EVIDENCE_SPAN_OUTSIDE_TEXT"
        value = representation_text[span["start"] : span["end"]]
        if not value:
            return [], "EVIDENCE_SPAN_EMPTY"
        values.append(value)
    if proposal["formType"] == "grammar" and len(values) > 1:
        actual = " ... ".join(value.strip() for value in values)
    else:
        if len(values) != 1:
            return [], "EVIDENCE_FORM_REQUIRES_ONE_SPAN"
        actual = values[0]
    if _normalized_match(actual) != _normalized_match(str(proposal["form"])):
        return values, "EVIDENCE_FORM_MISMATCH"
    return values, None


def _unsafe_text_reason(values: Sequence[str]) -> str | None:
    for value in values:
        if _URL_RE.search(value):
            return "SECURITY_URL_IN_CANDIDATE"
        if _WINDOWS_PATH_RE.search(value) or value.startswith("/"):
            return "SECURITY_PATH_IN_CANDIDATE"
        if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
            return "SECURITY_SECRET_PATTERN"
    return None


def _gate(
    gate: str,
    state: str,
    reason_code: str,
    *,
    evaluated_at: str,
    evidence_ids: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "gate": gate,
        "ruleId": f"{CANDIDATE_GATE_RULE_SET_VERSION}:{gate}",
        "ruleSetVersion": CANDIDATE_GATE_RULE_SET_VERSION,
        "state": state,
        "reasonCode": reason_code,
        "producer": dict(_PRODUCER),
        "evidenceIds": list(evidence_ids),
        "evaluatedAt": evaluated_at,
    }


def _objective_fields(
    proposal: Mapping[str, Any], *, learning_contract: Mapping[str, Any]
) -> tuple[str, str, str, list[str]]:
    route = str(proposal["route"])
    form = str(proposal["form"])
    meaning = str(proposal["meaningOrFunction"])
    if route in {"production", "chunk_collocation", "grammar_cloze"}:
        profile = candidate_language_profile(learning_contract)
        cue = (
            f"表达这个意思：{meaning}"
            if profile.is_zh_cn_to_en
            else f"Intended function: {meaning}"
        )
        return (
            "Produce the target language form from its intended function and context.",
            cue,
            form,
            [form],
        )
    if route == "pronunciation":
        return (
            "Pronounce the target form accurately.",
            form,
            form,
            [form],
        )
    if route == "contrast":
        return (
            "Discriminate the target form from a confusable alternative.",
            form,
            meaning,
            [meaning],
        )
    return (
        "Recall the contextual meaning or function of the target language form.",
        form,
        meaning,
        [meaning],
    )


def _scores(
    proposal: Mapping[str, Any],
    *,
    source_tier: str,
    assessments: Mapping[str, str],
) -> dict[str, float | int]:
    token_count = max(1, len(re.findall(r"\w+", str(proposal["form"]), flags=re.UNICODE)))
    transfer = 0.86 if 2 <= token_count <= 6 else (0.68 if token_count == 1 else 0.58)
    type_frequency = {
        "word": 0.62,
        "phrase": 0.82,
        "grammar": 0.76,
        "pronunciation": 0.58,
        "pragmatic": 0.74,
    }[str(proposal["formType"])]
    evidence = {"A": 1.0, "B": 0.72, "C": 0.0}[source_tier]
    learner_fit = {"new": 0.88, "partial": 0.7, "unknown": 0.5, "known": 0.12}[
        assessments["learnerFit"]
    ]
    answer_seconds = min(30, max(3, 2 + token_count * 2))
    scoreability = 0.92 if len(str(proposal["form"])) <= 80 else 0.68
    return {
        "goalRelevance": 1.0,
        "futureFrequencyOrStakes": type_frequency,
        "bottleneckAndTransfer": transfer,
        "forgettingOrConfusionRisk": 0.65,
        "evidenceConfidence": evidence,
        "noveltyAndLearnerFit": learner_fit,
        "scoreability": scoreability,
        "reviewCost": answer_seconds,
    }


def _derive_eligibility(gates: Sequence[Mapping[str, Any]], scores: Mapping[str, Any]) -> str:
    states = {str(value["gate"]): str(value["state"]) for value in gates}
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
    if float(scores["bottleneckAndTransfer"]) >= 0.68:
        return "recommended"
    return "candidate"


def evaluate_language_candidate(
    *,
    proposal: Mapping[str, Any],
    representation_ref: Mapping[str, Any],
    representation_payload: Mapping[str, Any],
    representation_text: str,
    source_inspection: Mapping[str, Any],
    learning_contract: Mapping[str, Any],
    trusted_assessments: Mapping[str, Any],
    project_revision: int,
    input_fingerprint: str,
    evaluated_at: str,
) -> dict[str, Any]:
    """Validate and score one proposed language objective without trusting the model."""

    normalized = _closed_proposal(proposal)
    assessments = _trusted_assessments(trusted_assessments)
    ref = _artifact_ref(representation_ref, "representationRef")
    evaluated_at = _timestamp(evaluated_at)
    if (
        isinstance(project_revision, bool)
        or not isinstance(project_revision, int)
        or project_revision < 1
        or ref["projectRevision"] > project_revision
    ):
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", "projectRevision is invalid"
        )
    if not isinstance(input_fingerprint, str) or not _DIGEST_RE.fullmatch(input_fingerprint):
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", "inputFingerprint is invalid"
        )
    source_id = representation_payload.get("sourceId")
    source_ref = representation_payload.get("sourceRef")
    if (
        ref["payloadSchema"] != "study.source-representation"
        or not isinstance(source_id, str)
        or not _ID_RE.fullmatch(source_id)
        or not isinstance(source_ref, Mapping)
    ):
        raise CandidateGateError(
            "CANDIDATE_SOURCE_INVALID", "representation payload is invalid"
        )
    source_ref = _artifact_ref(source_ref, "sourceRef")
    if source_ref["projectId"] != ref["projectId"]:
        raise CandidateGateError(
            "CANDIDATE_SOURCE_INVALID", "representation source scope is invalid"
        )
    tier = source_inspection.get("supportTier")
    status = source_inspection.get("status")
    if tier not in {"A", "B", "C"} or status not in {"ready", "conditional", "blocked"}:
        raise CandidateGateError(
            "CANDIDATE_SOURCE_INVALID", "source inspection state is invalid"
        )
    if source_inspection.get("sourceId") != source_id:
        raise CandidateGateError(
            "CANDIDATE_SOURCE_INVALID", "source inspection does not match representation"
        )
    contract_routes = learning_contract.get("routes")
    exclusions = learning_contract.get("exclusions")
    contract_revision = learning_contract.get("contractRevision")
    if (
        not isinstance(contract_routes, list)
        or not all(isinstance(value, str) for value in contract_routes)
        or not isinstance(exclusions, list)
        or not all(isinstance(value, str) for value in exclusions)
        or isinstance(contract_revision, bool)
        or not isinstance(contract_revision, int)
        or contract_revision < 1
    ):
        raise CandidateGateError(
            "CANDIDATE_SCHEMA_INVALID", "learningContract is invalid"
        )

    span_values, replay_issue = _span_replay(
        normalized,
        representation_text=representation_text,
        representation_payload=representation_payload,
    )
    identity = {
        "projectId": ref["projectId"],
        "projectRevision": project_revision,
        "contractRevision": contract_revision,
        "representationRef": ref,
        "proposal": normalized,
        "inputFingerprint": input_fingerprint,
        "ruleSetVersion": CANDIDATE_GATE_RULE_SET_VERSION,
    }
    identity_digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    candidate_id = "candidate_" + identity_digest[:40]
    unit_id = "unit_" + identity_digest[:40]
    objective_id = "objective_" + identity_digest[:40]
    evaluation_id = "evaluation_" + identity_digest[:40]
    evidence: list[dict[str, Any]] = []
    verified_spans = [] if replay_issue is not None else list(zip(normalized["spans"], span_values))
    for index, (span, quote) in enumerate(verified_spans):
        evidence_id = "evidence_" + hashlib.sha256(
            f"{identity_digest}:{index}:{span['start']}:{span['end']}".encode("ascii")
        ).hexdigest()[:40]
        node = next(
            value
            for value in representation_payload["contentNodes"]
            if value.get("nodeId") == span["nodeId"]
        )
        node_locator = node.get("locator", {})
        locator = {
            "kind": "text_span",
            "nodeId": span["nodeId"],
            "start": span["start"],
            "end": span["end"],
        }
        if isinstance(node_locator, Mapping):
            for key in ("pageNumber", "startMs", "endMs"):
                if isinstance(node_locator.get(key), int) and not isinstance(
                    node_locator.get(key), bool
                ):
                    locator[key] = node_locator[key]
        evidence.append(
            {
                "evidenceId": evidence_id,
                "sourceRef": source_ref,
                "locator": locator,
                "quoteSha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                "provenanceClass": "source_direct",
                "semanticRelation": "supports",
                "assessment": {
                    "producer": dict(_PRODUCER),
                    "method": "deterministic_replay",
                    "confidence": 1.0,
                    "independentlyVerified": True,
                },
                "attribution": {},
            }
        )
    evidence_ids = [value["evidenceId"] for value in evidence]

    if replay_issue is not None:
        evidence_state, evidence_reason = "fail", replay_issue
    elif tier == "C" or status == "blocked" or assessments["semanticEvidence"] == "failed":
        evidence_state, evidence_reason = "fail", "EVIDENCE_SOURCE_OR_SEMANTICS_BLOCKED"
    elif tier == "B" or status == "conditional" or assessments["semanticEvidence"] == "review":
        evidence_state, evidence_reason = "review", "EVIDENCE_REVIEW_REQUIRED"
    else:
        evidence_state, evidence_reason = "pass", "EVIDENCE_REPLAYED_AND_REVIEWED"

    excluded_values = {_normalized_match(value) for value in exclusions if value.strip()}
    matches_exclusion = bool(
        {_normalized_match(normalized["form"]), _normalized_match(normalized["meaningOrFunction"])}
        & excluded_values
    )
    if normalized["route"] not in contract_routes:
        relevance_state, relevance_reason = "fail", "GOAL_ROUTE_NOT_ALLOWED"
    elif matches_exclusion:
        relevance_state, relevance_reason = "fail", "GOAL_EXPLICITLY_EXCLUDED"
    else:
        relevance_state, relevance_reason = "pass", "GOAL_ROUTE_ALLOWED"

    if assessments["duplicate"] == "duplicate":
        novelty_state, novelty_reason = "fail", "NOVELTY_EXACT_DUPLICATE"
    elif assessments["duplicate"] == "unknown":
        novelty_state, novelty_reason = "review", "NOVELTY_RELATION_REVIEW_REQUIRED"
    elif assessments["learnerFit"] == "known":
        novelty_state, novelty_reason = "fail", "NOVELTY_LEARNER_ALREADY_KNOWS"
    elif assessments["learnerFit"] == "unknown":
        novelty_state, novelty_reason = "review", "NOVELTY_LEARNER_FIT_UNKNOWN"
    else:
        novelty_state, novelty_reason = "pass", "NOVELTY_LEARNER_FIT_SUPPORTED"

    language_profile = candidate_language_profile(learning_contract)
    recall_action, cue_spec, response_spec, scoring_boundary = _objective_fields(
        normalized, learning_contract=learning_contract
    )
    if not response_spec or len(response_spec) > 500 or len(scoring_boundary) != 1:
        score_state, score_reason = "fail", "SCOREABILITY_BOUNDARY_INVALID"
    elif language_profile.is_zh_cn_to_en and (
        normalize_answer_leakage_text(normalized["form"])
        in normalize_answer_leakage_text(normalized["meaningOrFunction"])
    ):
        score_state, score_reason = "fail", "SCOREABILITY_CUE_REVEALS_TARGET"
    elif language_profile.is_zh_cn_to_en and not contains_han(
        normalized["meaningOrFunction"]
    ):
        score_state, score_reason = "fail", "SCOREABILITY_PROMPT_LANGUAGE_REQUIRED"
    elif language_profile.mode == "legacy-en" and not is_latin_script_text(
        normalized["meaningOrFunction"]
    ):
        score_state, score_reason = "fail", "SCOREABILITY_PROMPT_LANGUAGE_REQUIRED"
    elif normalized["route"] == "pronunciation":
        score_state, score_reason = "review", "SCOREABILITY_PRONUNCIATION_RUBRIC_REQUIRED"
    else:
        score_state, score_reason = "pass", "SCOREABILITY_SINGLE_BOUNDARY"

    if language_profile.mode == "unsupported":
        suitability_state, suitability_reason = (
            "fail",
            "CARD_LANGUAGE_PAIR_UNSUPPORTED",
        )
    elif language_profile.is_zh_cn_to_en and not language_profile.supports_route(
        normalized["route"]
    ):
        suitability_state, suitability_reason = (
            "fail",
            "CARD_LANGUAGE_ROUTE_UNSUPPORTED",
        )
    elif language_profile.mode in {"zh-CN-to-en", "legacy-en"} and normalize_language(
        normalized["language"]
    ) != EN:
        suitability_state, suitability_reason = (
            "fail",
            "CARD_ANSWER_LANGUAGE_MISMATCH",
        )
    elif language_profile.mode in {"zh-CN-to-en", "legacy-en"} and (
        not is_latin_script_text(normalized["form"])
    ):
        suitability_state, suitability_reason = (
            "fail",
            "CARD_TARGET_LANGUAGE_MISMATCH",
        )
    elif normalized["route"] == "contrast":
        suitability_state, suitability_reason = "review", "CARD_CONTRAST_PAIR_REQUIRED"
    elif normalized["formType"] == "grammar" and len(normalized["spans"]) == 1:
        suitability_state, suitability_reason = "review", "CARD_GRAMMAR_FRAME_REVIEW_REQUIRED"
    else:
        suitability_state, suitability_reason = "pass", "CARD_ROUTE_SUPPORTED"

    if assessments["conflict"] == "conflict":
        conflict_state, conflict_reason = "fail", "CONFLICT_UNRESOLVED"
    elif assessments["conflict"] == "unknown":
        conflict_state, conflict_reason = "review", "CONFLICT_RELATION_REVIEW_REQUIRED"
    else:
        conflict_state, conflict_reason = "pass", "CONFLICT_NONE_FOUND"

    token_count = max(1, len(re.findall(r"\w+", normalized["form"], flags=re.UNICODE)))
    if len(normalized["form"]) > 120 or token_count > 12:
        value_state, value_reason = "fail", "REVIEW_VALUE_COST_EXCEEDS_TARGET"
    elif len(normalized["form"]) < 2:
        value_state, value_reason = "review", "REVIEW_VALUE_TARGET_TOO_SMALL"
    else:
        value_state, value_reason = "pass", "REVIEW_VALUE_BOUNDED"

    unsafe_reason = _unsafe_text_reason(
        [normalized["form"], normalized["meaningOrFunction"]]
    )
    security_state = "fail" if unsafe_reason else "pass"
    security_reason = unsafe_reason or "SECURITY_UNTRUSTED_TEXT_CONFINED"
    gates = [
        _gate("evidence", evidence_state, evidence_reason, evaluated_at=evaluated_at, evidence_ids=evidence_ids),
        _gate("goal_relevance", relevance_state, relevance_reason, evaluated_at=evaluated_at),
        _gate("novelty", novelty_state, novelty_reason, evaluated_at=evaluated_at),
        _gate("scoreability", score_state, score_reason, evaluated_at=evaluated_at),
        _gate("card_suitability", suitability_state, suitability_reason, evaluated_at=evaluated_at),
        _gate("conflict", conflict_state, conflict_reason, evaluated_at=evaluated_at, evidence_ids=evidence_ids),
        _gate("review_value", value_state, value_reason, evaluated_at=evaluated_at),
        _gate("security", security_state, security_reason, evaluated_at=evaluated_at),
    ]
    scores = _scores(normalized, source_tier=str(tier), assessments=assessments)
    eligibility = _derive_eligibility(gates, scores)
    issue_refs = sorted(
        {
            value["reasonCode"]
            for value in gates
            if value["state"] in {"review", "fail"}
        }
    )
    explanation = [
        value["reasonCode"]
        for value in gates
        if value["gate"] in {"goal_relevance", "evidence", "review_value"}
    ]
    exact_evidence_ids = [value["evidenceId"] for value in evidence]
    objective = {
        "objectiveId": objective_id,
        "unitIds": [unit_id],
        "route": normalized["route"],
        "recallAction": recall_action,
        "cueSpec": cue_spec,
        "responseSpec": response_spec,
        "scoringBoundary": scoring_boundary,
        "evidenceIds": exact_evidence_ids,
        "prerequisiteObjectiveIds": [],
        "granularity": {
            "atomicity": "pass" if score_state == "pass" else score_state,
            "contextSufficiency": (
                "pass" if assessments["semanticEvidence"] == "verified" else "review"
            ),
            "expectedAnswerSeconds": int(scores["reviewCost"]),
            "independentScorePoints": 1,
        },
        "learnerFit": {
            "status": assessments["learnerFit"],
            "estimatedDifficulty": min(5, max(1, 1 + token_count // 2)),
            "reasonCodes": [f"LEARNER_FIT_{assessments['learnerFit'].upper()}"],
        },
        "routeDecision": {
            "reasonCodes": ["ROUTE_PROPOSED_AND_CONTRACT_ALLOWED"],
            "alternatives": [value for value in contract_routes if value != normalized["route"]],
        },
        "provenance": dict(_PRODUCER),
        "userLocks": [],
    }
    return {
        "schema": "study.language-candidate-evaluation-draft",
        "schemaVersion": 1,
        "candidateId": candidate_id,
        "sourceId": source_id,
        "representationRef": ref,
        "evidenceAnchors": evidence,
        "semanticUnit": {
            "kind": "language_form",
            "unitId": unit_id,
            "language": normalized["language"],
            "form": normalized["form"],
            "normalizedForm": _normalized_match(normalized["form"]),
            "formType": normalized["formType"],
            "meaningOrFunction": normalized["meaningOrFunction"],
            "exactEvidenceIds": exact_evidence_ids,
            "relations": [],
        },
        "objective": objective,
        "scores": scores,
        "explanation": explanation,
        "issueRefs": issue_refs,
        "gateEvaluation": {
            "evaluationId": evaluation_id,
            "candidateId": candidate_id,
            "projectRevision": project_revision,
            "inputFingerprint": input_fingerprint,
            "ruleSetVersion": CANDIDATE_GATE_RULE_SET_VERSION,
            "results": gates,
            "derivedEligibility": eligibility,
            "evaluatedAt": evaluated_at,
            "producer": dict(_PRODUCER),
        },
    }


__all__ = [
    "CANDIDATE_GATE_RULE_SET_VERSION",
    "CandidateGateError",
    "evaluate_language_candidate",
]
