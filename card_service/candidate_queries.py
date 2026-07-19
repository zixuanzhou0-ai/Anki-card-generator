"""Safe public projections over authenticated candidate discovery artifacts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from typing import Any, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .candidate_discovery import sensitive_disclosure_reason
from .project_registry import ARTIFACT_STAGES, ProjectRegistry, ProjectRegistryError


_ELIGIBILITY = frozenset(
    {
        "recommended",
        "candidate",
        "duplicate",
        "needs_review",
        "hard_blocked",
        "excluded",
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
_SORTS = frozenset({"recommended", "source_order", "review_cost"})
_SELECTION_STATES = frozenset({"selected", "unselected"})
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_CURSOR_RE = re.compile(r"^study_cursor_[A-Za-z0-9_-]{80,1800}$")
_MAX_LIMIT = 100
_MAX_QUERY = 200
_MAX_CONTEXT = 480
_CURSOR_DOMAIN = b"study.candidate-query.cursor.v1\x00"


class CandidateQueryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _fail(code: str, message: str) -> None:
    raise CandidateQueryError(code, message)


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail("CANDIDATE_QUERY_INVALID", f"{label} is invalid")
    if any(ord(character) < 0x20 and character not in "\t\r\n" for character in value):
        _fail("CANDIDATE_QUERY_INVALID", f"{label} contains control characters")
    return value


def _ref_identity(value: Mapping[str, Any]) -> tuple[str, int, str]:
    return (
        str(value.get("artifactId")),
        int(value.get("artifactRevision", 0)),
        str(value.get("artifactDigest")),
    )


class CandidateQueryRuntime:
    """Read-only candidate surface with authenticated, query-bound pagination."""

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
                "CANDIDATE_QUERY_CONFIGURATION_INVALID", "service identity is invalid"
            )
        if not isinstance(cursor_key, bytes) or len(cursor_key) < 32:
            _fail("CANDIDATE_QUERY_CONFIGURATION_INVALID", "cursor key is invalid")
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._cursor_key = bytes(cursor_key)

    def _cursor_tag(self, raw: bytes) -> bytes:
        return hmac.new(self._cursor_key, _CURSOR_DOMAIN + raw, hashlib.sha256).digest()

    def _encode_cursor(self, payload: Mapping[str, Any]) -> str:
        raw = canonical_json_bytes(dict(payload))
        encoded = base64.urlsafe_b64encode(raw + self._cursor_tag(raw)).rstrip(b"=")
        return "study_cursor_" + encoded.decode("ascii")

    def _decode_cursor(self, value: str) -> dict[str, Any]:
        if not isinstance(value, str) or not _CURSOR_RE.fullmatch(value):
            _fail("CANDIDATE_CURSOR_INVALID", "candidate cursor is invalid")
        encoded = value.removeprefix("study_cursor_")
        try:
            decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except (ValueError, TypeError) as error:
            raise CandidateQueryError(
                "CANDIDATE_CURSOR_INVALID", "candidate cursor is invalid"
            ) from error
        canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(canonical, encoded):
            _fail(
                "CANDIDATE_CURSOR_INVALID", "candidate cursor encoding is not canonical"
            )
        if len(decoded) <= 32:
            _fail("CANDIDATE_CURSOR_INVALID", "candidate cursor is invalid")
        raw, tag = decoded[:-32], decoded[-32:]
        if not hmac.compare_digest(tag, self._cursor_tag(raw)):
            _fail("CANDIDATE_CURSOR_INVALID", "candidate cursor authentication failed")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, TypeError) as error:
            raise CandidateQueryError(
                "CANDIDATE_CURSOR_INVALID", "candidate cursor is invalid"
            ) from error
        required = {
            "schemaVersion",
            "serviceInstanceId",
            "discoveryDigest",
            "queryDigest",
            "lastCandidateId",
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != required
            or payload.get("schemaVersion") != 1
            or payload.get("serviceInstanceId") != self._service_instance_id
            or not isinstance(payload.get("discoveryDigest"), str)
            or not isinstance(payload.get("queryDigest"), str)
            or not isinstance(payload.get("lastCandidateId"), str)
        ):
            _fail("CANDIDATE_CURSOR_INVALID", "candidate cursor fields are invalid")
        return payload

    def _discovery(
        self, handle: str, audience: ArtifactAudienceBinding
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        if not isinstance(handle, str) or not _HANDLE_RE.fullmatch(handle):
            _fail("CANDIDATE_QUERY_INVALID", "discoveryHandle is invalid")
        try:
            discovery_ref, discovery = self._artifacts.resolve_with_ref(
                handle, audience
            )
            project = self._projects.get_project(discovery_ref["projectId"], audience)
        except (ArtifactRegistryError, ProjectRegistryError) as error:
            raise CandidateQueryError(error.code, error.message) from error
        if discovery.get("payloadSchema") != "study.discovery":
            _fail("CANDIDATE_DISCOVERY_INVALID", "handle is not a discovery")
        stage = project.get("workflow", {}).get("artifactStage")
        if stage not in ARTIFACT_STAGES or ARTIFACT_STAGES.index(
            stage
        ) < ARTIFACT_STAGES.index("candidates_ready"):
            _fail(
                "CANDIDATE_DISCOVERY_STALE",
                "project no longer has a current candidate discovery",
            )
        current = [
            value
            for value in project.get("latestArtifactRefs", [])
            if isinstance(value, Mapping)
            and value.get("payloadSchema") == "study.discovery"
        ]
        if not current:
            _fail("CANDIDATE_DISCOVERY_STALE", "project has no current discovery")
        highest = max(int(value.get("projectRevision", 0)) for value in current)
        newest = [value for value in current if value.get("projectRevision") == highest]
        if len(newest) != 1 or _ref_identity(newest[0]) != _ref_identity(discovery_ref):
            _fail(
                "CANDIDATE_DISCOVERY_STALE",
                "discovery is not the current project discovery",
            )
        payload = discovery.get("payload")
        candidate_refs = (
            payload.get("candidateRefs") if isinstance(payload, Mapping) else None
        )
        gate_refs = (
            payload.get("gateEvaluationRefs") if isinstance(payload, Mapping) else None
        )
        if (
            not isinstance(payload, Mapping)
            or not isinstance(candidate_refs, list)
            or not isinstance(gate_refs, list)
            or len(candidate_refs) != len(gate_refs)
            or len(candidate_refs) > 1000
        ):
            _fail("CANDIDATE_DISCOVERY_CORRUPT", "discovery candidate graph is invalid")
        return discovery_ref, discovery, project

    def _members(
        self,
        discovery: Mapping[str, Any],
        audience: ArtifactAudienceBinding,
    ) -> list[dict[str, Any]]:
        payload = discovery["payload"]
        gate_by_candidate: dict[
            tuple[str, int, str], tuple[dict[str, Any], dict[str, Any]]
        ] = {}
        for raw_gate_ref in payload["gateEvaluationRefs"]:
            if not isinstance(raw_gate_ref, Mapping):
                _fail("CANDIDATE_DISCOVERY_CORRUPT", "gate reference is invalid")
            try:
                gate = self._artifacts.verify_ref(raw_gate_ref, audience)
            except ArtifactRegistryError as error:
                raise CandidateQueryError(error.code, error.message) from error
            gate_payload = gate.get("payload")
            entity = (
                gate_payload.get("candidateRef")
                if isinstance(gate_payload, Mapping)
                else None
            )
            candidate_ref = (
                entity.get("artifactRef") if isinstance(entity, Mapping) else None
            )
            if (
                gate.get("payloadSchema") != "study.gate-evaluation"
                or not isinstance(candidate_ref, Mapping)
                or not isinstance(entity.get("entityId"), str)
            ):
                _fail("CANDIDATE_DISCOVERY_CORRUPT", "gate graph is invalid")
            identity = _ref_identity(candidate_ref)
            if identity in gate_by_candidate:
                _fail(
                    "CANDIDATE_DISCOVERY_CORRUPT",
                    "candidate has duplicate gate results",
                )
            gate_by_candidate[identity] = (dict(raw_gate_ref), gate)

        rows: list[dict[str, Any]] = []
        for entity in payload["candidateRefs"]:
            candidate_ref = (
                entity.get("artifactRef") if isinstance(entity, Mapping) else None
            )
            candidate_id = (
                entity.get("entityId") if isinstance(entity, Mapping) else None
            )
            if not isinstance(candidate_ref, Mapping) or not isinstance(
                candidate_id, str
            ):
                _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate entity is invalid")
            try:
                candidate = self._artifacts.verify_ref(candidate_ref, audience)
            except ArtifactRegistryError as error:
                raise CandidateQueryError(error.code, error.message) from error
            gate_pair = gate_by_candidate.get(_ref_identity(candidate_ref))
            candidate_payload = candidate.get("payload")
            if (
                gate_pair is None
                or candidate.get("payloadSchema")
                not in {"study.candidate-proposal", "study.candidate-rejection"}
                or not isinstance(candidate_payload, Mapping)
                or candidate_payload.get("candidateId") != candidate_id
            ):
                _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate graph is invalid")
            gate_ref, gate = gate_pair
            gate_payload = gate["payload"]
            if gate_payload.get("candidateRef") != {
                "artifactRef": dict(candidate_ref),
                "entityId": candidate_id,
            }:
                _fail(
                    "CANDIDATE_DISCOVERY_CORRUPT", "candidate gate binding is invalid"
                )
            eligibility = gate_payload.get("derivedEligibility")
            if eligibility not in _ELIGIBILITY:
                _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate eligibility is invalid")
            rows.append(
                {
                    "candidateId": candidate_id,
                    "candidateRef": dict(candidate_ref),
                    "candidate": candidate,
                    "gateRef": gate_ref,
                    "gate": gate,
                    "eligibility": eligibility,
                }
            )
        if len(gate_by_candidate) != len(rows):
            _fail(
                "CANDIDATE_DISCOVERY_CORRUPT", "discovery contains orphan gate results"
            )
        return rows

    def _source_summary(
        self, row: Mapping[str, Any], audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        payload = row["candidate"]["payload"]
        representation_ref = payload.get("representationRef")
        if not isinstance(representation_ref, Mapping):
            _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate representation is invalid")
        try:
            representation = self._artifacts.verify_ref(representation_ref, audience)
        except ArtifactRegistryError as error:
            raise CandidateQueryError(error.code, error.message) from error
        representation_payload = representation.get("payload")
        source_ref = (
            representation_payload.get("sourceRef")
            if isinstance(representation_payload, Mapping)
            else None
        )
        if representation.get(
            "payloadSchema"
        ) != "study.source-representation" or not isinstance(source_ref, Mapping):
            _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate source graph is invalid")
        try:
            source = self._artifacts.verify_ref(source_ref, audience)
        except ArtifactRegistryError as error:
            raise CandidateQueryError(error.code, error.message) from error
        source_payload = source.get("payload")
        if source.get("payloadSchema") != "study.source-asset" or not isinstance(
            source_payload, Mapping
        ):
            _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate source is invalid")
        display_name = source_payload.get("displayName")
        source_type = source_payload.get("sourceType")
        source_id = source_payload.get("sourceId")
        if not all(
            isinstance(value, str) for value in (display_name, source_type, source_id)
        ):
            _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate source summary is invalid")
        return {
            "sourceId": source_id,
            "displayName": display_name,
            "sourceType": source_type,
            "sourceHandle": self._artifacts.issue_handle(source_ref, audience),
            "representationRef": dict(representation_ref),
            "representation": representation,
        }

    @staticmethod
    def _target(row: Mapping[str, Any]) -> dict[str, Any] | None:
        candidate = row["candidate"]
        if candidate.get("payloadSchema") == "study.candidate-rejection":
            return None
        unit = candidate["payload"].get("semanticUnit")
        if not isinstance(unit, Mapping):
            _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate semantic unit is invalid")
        required = ("language", "form", "formType", "meaningOrFunction")
        if not all(isinstance(unit.get(key), str) for key in required):
            _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate target is invalid")
        return {key: str(unit[key]) for key in required}

    def _selected_candidate_ids(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        discovery_ref: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
    ) -> set[str]:
        stage = project.get("workflow", {}).get("artifactStage")
        if stage not in ARTIFACT_STAGES or ARTIFACT_STAGES.index(
            stage
        ) < ARTIFACT_STAGES.index("selection_ready"):
            return set()
        selection_refs = [
            value
            for value in project.get("latestArtifactRefs", [])
            if isinstance(value, Mapping)
            and value.get("payloadSchema") == "study.portfolio-selection"
        ]
        if not selection_refs:
            _fail("CANDIDATE_SELECTION_CORRUPT", "project selection is missing")
        highest = max(int(value.get("projectRevision", 0)) for value in selection_refs)
        current = [
            dict(value)
            for value in selection_refs
            if value.get("projectRevision") == highest
        ]
        if len(current) != 1:
            _fail("CANDIDATE_SELECTION_CORRUPT", "project selection is ambiguous")
        try:
            selection = self._artifacts.verify_ref(current[0], audience)
        except ArtifactRegistryError as error:
            raise CandidateQueryError(error.code, error.message) from error
        payload = selection.get("payload")
        entities = (
            payload.get("candidateRefs") if isinstance(payload, Mapping) else None
        )
        if (
            selection.get("payloadSchema") != "study.portfolio-selection"
            or not isinstance(payload, Mapping)
            or payload.get("discoveryRef") != dict(discovery_ref)
            or not isinstance(entities, list)
        ):
            _fail("CANDIDATE_SELECTION_CORRUPT", "selection graph is invalid")
        members = {
            (_ref_identity(row["candidateRef"]), row["candidateId"]) for row in rows
        }
        selected: set[str] = set()
        for entity in entities:
            artifact_ref = (
                entity.get("artifactRef") if isinstance(entity, Mapping) else None
            )
            candidate_id = (
                entity.get("entityId") if isinstance(entity, Mapping) else None
            )
            if (
                not isinstance(artifact_ref, Mapping)
                or not isinstance(candidate_id, str)
                or (_ref_identity(artifact_ref), candidate_id) not in members
                or candidate_id in selected
            ):
                _fail(
                    "CANDIDATE_SELECTION_CORRUPT",
                    "selection contains a stale candidate",
                )
            selected.add(candidate_id)
        return selected

    def _row_projection(
        self,
        row: Mapping[str, Any],
        audience: ArtifactAudienceBinding,
        selected_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        target = self._target(row)
        source = self._source_summary(row, audience)
        gate_payload = row["gate"]["payload"]
        candidate_payload = row["candidate"]["payload"]
        objective = candidate_payload.get("objective")
        scores = candidate_payload.get("scores")
        issues = candidate_payload.get(
            "issueRefs", candidate_payload.get("reasonCodes", [])
        )
        if not isinstance(issues, list) or not all(
            isinstance(value, str) for value in issues
        ):
            _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate issues are invalid")
        review_cost = scores.get("reviewCost") if isinstance(scores, Mapping) else None
        route = objective.get("route") if isinstance(objective, Mapping) else None
        evidence = candidate_payload.get("evidenceAnchors", [])
        if not isinstance(evidence, list):
            _fail("CANDIDATE_DISCOVERY_CORRUPT", "candidate evidence is invalid")
        candidate_handle = self._artifacts.issue_handle(row["candidateRef"], audience)
        return {
            "candidateHandle": candidate_handle,
            "candidateId": row["candidateId"],
            "target": target,
            "source": {
                key: source[key]
                for key in ("sourceId", "displayName", "sourceType", "sourceHandle")
            },
            "eligibility": row["eligibility"],
            "selectionState": (
                "selected"
                if selected_ids is not None and row["candidateId"] in selected_ids
                else "unselected"
            ),
            "locked": False,
            "route": route,
            "reviewCostSeconds": review_cost,
            "evidenceCount": len(evidence),
            "recommendationReasons": list(candidate_payload.get("explanation", [])),
            "riskCodes": sorted(set(issues)),
            "suppressed": row["candidate"].get("payloadSchema")
            == "study.candidate-rejection",
            "gateSummary": {
                "pass": sum(
                    1 for item in gate_payload["results"] if item.get("state") == "pass"
                ),
                "review": sum(
                    1
                    for item in gate_payload["results"]
                    if item.get("state") == "review"
                ),
                "fail": sum(
                    1 for item in gate_payload["results"] if item.get("state") == "fail"
                ),
            },
        }

    @staticmethod
    def _normalize_filter(value: Mapping[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping) or not set(value).issubset(
            {"eligibility", "route", "selectionState", "sourceHandles", "query"}
        ):
            _fail("CANDIDATE_QUERY_INVALID", "candidate filter fields are invalid")
        result: dict[str, Any] = {}
        for key, allowed, maximum in (
            ("eligibility", _ELIGIBILITY, len(_ELIGIBILITY)),
            ("route", _LANGUAGE_ROUTES, len(_LANGUAGE_ROUTES)),
            ("selectionState", _SELECTION_STATES, len(_SELECTION_STATES)),
        ):
            raw = value.get(key)
            if raw is None:
                continue
            if (
                not isinstance(raw, Sequence)
                or isinstance(raw, (str, bytes))
                or not 1 <= len(raw) <= maximum
                or any(item not in allowed for item in raw)
                or len(raw) != len(set(raw))
            ):
                _fail("CANDIDATE_QUERY_INVALID", f"{key} filter is invalid")
            result[key] = sorted(raw)
        handles = value.get("sourceHandles")
        if handles is not None:
            if (
                not isinstance(handles, Sequence)
                or isinstance(handles, (str, bytes))
                or not 1 <= len(handles) <= 64
                or any(
                    not isinstance(item, str) or not _HANDLE_RE.fullmatch(item)
                    for item in handles
                )
                or len(handles) != len(set(handles))
            ):
                _fail("CANDIDATE_QUERY_INVALID", "sourceHandles filter is invalid")
            result["sourceHandles"] = list(handles)
        query = value.get("query")
        if query is not None:
            result["query"] = _text(query, "query", _MAX_QUERY).strip()
            if not result["query"]:
                _fail("CANDIDATE_QUERY_INVALID", "query is empty")
        return result

    def list_candidates(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        filters: Mapping[str, Any] | None = None,
        sort: str = "recommended",
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if sort not in _SORTS:
            _fail("CANDIDATE_QUERY_INVALID", "candidate sort is invalid")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_LIMIT
        ):
            _fail("CANDIDATE_QUERY_INVALID", "candidate limit is invalid")
        normalized_filter = self._normalize_filter(filters)
        discovery_ref, discovery, project = self._discovery(discovery_handle, audience)
        rows = self._members(discovery, audience)
        selected_ids = self._selected_candidate_ids(
            audience=audience,
            project=project,
            discovery_ref=discovery_ref,
            rows=rows,
        )

        source_id_filter: set[str] | None = None
        if "sourceHandles" in normalized_filter:
            source_id_filter = set()
            for handle in normalized_filter["sourceHandles"]:
                try:
                    source = self._artifacts.resolve(handle, audience)
                except ArtifactRegistryError as error:
                    raise CandidateQueryError(error.code, error.message) from error
                payload = source.get("payload")
                if source.get(
                    "payloadSchema"
                ) != "study.source-asset" or not isinstance(payload, Mapping):
                    _fail(
                        "CANDIDATE_QUERY_INVALID",
                        "sourceHandles contains a non-source handle",
                    )
                source_id = payload.get("sourceId")
                if not isinstance(source_id, str):
                    _fail(
                        "CANDIDATE_QUERY_INVALID",
                        "sourceHandles contains a malformed source",
                    )
                source_id_filter.add(source_id)

        filtered: list[dict[str, Any]] = []
        query = str(normalized_filter.get("query", "")).casefold()
        for row in rows:
            target = self._target(row)
            if (
                "eligibility" in normalized_filter
                and row["eligibility"] not in normalized_filter["eligibility"]
            ):
                continue
            selection_state = (
                "selected" if row["candidateId"] in selected_ids else "unselected"
            )
            if (
                "selectionState" in normalized_filter
                and selection_state not in normalized_filter["selectionState"]
            ):
                continue
            route = row["candidate"]["payload"].get("objective", {}).get("route")
            if "route" in normalized_filter and route not in normalized_filter["route"]:
                continue
            if (
                source_id_filter is not None
                and row["candidate"]["payload"].get("sourceId") not in source_id_filter
            ):
                continue
            if query and (
                target is None
                or query
                not in (target["form"] + "\n" + target["meaningOrFunction"]).casefold()
            ):
                continue
            filtered.append(row)

        eligibility_rank = {
            "recommended": 0,
            "candidate": 1,
            "needs_review": 2,
            "duplicate": 3,
            "excluded": 4,
            "hard_blocked": 5,
        }

        def first_start(row: Mapping[str, Any]) -> int:
            anchors = row["candidate"]["payload"].get("evidenceAnchors", [])
            if not anchors:
                return 2**31 - 1
            locator = anchors[0].get("locator", {})
            return int(locator.get("start", 2**31 - 1))

        def review_cost(row: Mapping[str, Any]) -> float:
            value = row["candidate"]["payload"].get("scores", {}).get("reviewCost")
            return (
                float(value)
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                else 1e9
            )

        if sort == "source_order":
            filtered.sort(
                key=lambda row: (
                    str(row["candidate"]["payload"].get("sourceId", "")).encode(
                        "utf-8"
                    ),
                    first_start(row),
                    row["candidateId"].encode("utf-8"),
                )
            )
        elif sort == "review_cost":
            filtered.sort(
                key=lambda row: (review_cost(row), row["candidateId"].encode("utf-8"))
            )
        else:
            filtered.sort(
                key=lambda row: (
                    eligibility_rank[row["eligibility"]],
                    -float(
                        row["candidate"]["payload"]
                        .get("scores", {})
                        .get("bottleneckAndTransfer", 0)
                    ),
                    review_cost(row),
                    row["candidateId"].encode("utf-8"),
                )
            )

        query_digest = hashlib.sha256(
            canonical_json_bytes({"filter": normalized_filter, "sort": sort})
        ).hexdigest()
        start = 0
        if cursor is not None:
            decoded = self._decode_cursor(cursor)
            if (
                decoded["discoveryDigest"] != discovery_ref["artifactDigest"]
                or decoded["queryDigest"] != query_digest
            ):
                _fail(
                    "CANDIDATE_CURSOR_MISMATCH",
                    "candidate cursor belongs to another query",
                )
            positions = [
                index
                for index, row in enumerate(filtered)
                if row["candidateId"] == decoded["lastCandidateId"]
            ]
            if len(positions) != 1:
                _fail(
                    "CANDIDATE_CURSOR_STALE",
                    "candidate cursor no longer matches this discovery",
                )
            start = positions[0] + 1
        page = filtered[start : start + limit]
        next_cursor = None
        if start + len(page) < len(filtered) and page:
            next_cursor = self._encode_cursor(
                {
                    "schemaVersion": 1,
                    "serviceInstanceId": self._service_instance_id,
                    "discoveryDigest": discovery_ref["artifactDigest"],
                    "queryDigest": query_digest,
                    "lastCandidateId": page[-1]["candidateId"],
                }
            )
        return {
            "schemaVersion": 1,
            "projectId": discovery_ref["projectId"],
            "discoveryHandle": discovery_handle,
            "totalCandidates": len(filtered),
            "returnedCandidates": len(page),
            "items": [
                self._row_projection(row, audience, selected_ids) for row in page
            ],
            "nextCursor": next_cursor,
        }

    def resolve_selection_graph(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        candidate_handles: Sequence[str] = (),
    ) -> dict[str, Any]:
        discovery_ref, discovery, project = self._discovery(discovery_handle, audience)
        rows = self._members(discovery, audience)
        by_identity = {_ref_identity(row["candidateRef"]): row for row in rows}
        requested_rows = []
        requested_identities: set[tuple[str, int, str]] = set()
        for handle in candidate_handles:
            if not isinstance(handle, str) or not _HANDLE_RE.fullmatch(handle):
                _fail("CANDIDATE_QUERY_INVALID", "candidateHandle is invalid")
            try:
                candidate_ref, candidate = self._artifacts.resolve_with_ref(
                    handle, audience
                )
            except ArtifactRegistryError as error:
                raise CandidateQueryError(error.code, error.message) from error
            identity = _ref_identity(candidate_ref)
            row = by_identity.get(identity)
            if identity in requested_identities:
                _fail(
                    "CANDIDATE_QUERY_INVALID",
                    "candidateHandles resolves the same candidate more than once",
                )
            if row is None or row["candidate"] != candidate:
                _fail(
                    "CANDIDATE_NOT_IN_DISCOVERY",
                    "candidate is not part of this discovery",
                )
            requested_identities.add(identity)
            requested_rows.append(row)
        return {
            "discoveryRef": discovery_ref,
            "discovery": discovery,
            "project": project,
            "rows": rows,
            "requestedRows": requested_rows,
        }

    def _member_from_handle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        candidate_handle: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        if not isinstance(candidate_handle, str) or not _HANDLE_RE.fullmatch(
            candidate_handle
        ):
            _fail("CANDIDATE_QUERY_INVALID", "candidateHandle is invalid")
        discovery_ref, discovery, project = self._discovery(discovery_handle, audience)
        try:
            candidate_ref, candidate = self._artifacts.resolve_with_ref(
                candidate_handle, audience
            )
        except ArtifactRegistryError as error:
            raise CandidateQueryError(error.code, error.message) from error
        rows = self._members(discovery, audience)
        matched = [
            row
            for row in rows
            if _ref_identity(row["candidateRef"]) == _ref_identity(candidate_ref)
        ]
        if len(matched) != 1 or matched[0]["candidate"] != candidate:
            _fail(
                "CANDIDATE_NOT_IN_DISCOVERY", "candidate is not part of this discovery"
            )
        return matched[0], discovery, discovery_ref, project

    def get_candidate(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        candidate_handle: str,
    ) -> dict[str, Any]:
        row, discovery, discovery_ref, project = self._member_from_handle(
            audience=audience,
            discovery_handle=discovery_handle,
            candidate_handle=candidate_handle,
        )
        selected_ids = self._selected_candidate_ids(
            audience=audience,
            project=project,
            discovery_ref=discovery_ref,
            rows=self._members(discovery, audience),
        )
        summary = self._row_projection(row, audience, selected_ids)
        candidate_payload = row["candidate"]["payload"]
        gate_payload = row["gate"]["payload"]
        evidence = candidate_payload.get("evidenceAnchors", [])
        evidence_summaries = []
        for anchor in evidence:
            locator = anchor.get("locator") if isinstance(anchor, Mapping) else None
            if not isinstance(locator, Mapping):
                _fail(
                    "CANDIDATE_DISCOVERY_CORRUPT",
                    "candidate evidence locator is invalid",
                )
            evidence_summaries.append(
                {
                    "evidenceId": anchor["evidenceId"],
                    "locator": {
                        "kind": locator.get("kind"),
                        "nodeId": locator.get("nodeId"),
                        "start": locator.get("start"),
                        "end": locator.get("end"),
                    },
                    "quoteSha256": anchor["quoteSha256"],
                    "provenanceClass": anchor["provenanceClass"],
                    "semanticRelation": anchor["semanticRelation"],
                    "independentlyVerified": bool(
                        anchor.get("assessment", {}).get("independentlyVerified")
                    ),
                }
            )
        gates = []
        for gate in gate_payload["results"]:
            gates.append(
                {
                    "gate": gate.get("gate"),
                    "state": gate.get("state"),
                    "reasonCode": gate.get("reasonCode"),
                    "ruleSetVersion": gate.get("ruleSetVersion"),
                    "evidenceIds": [
                        value.get("entityId")
                        for value in gate.get("evidenceRefs", [])
                        if isinstance(value, Mapping)
                    ],
                }
            )
        objective = candidate_payload.get("objective")
        supported_routes = []
        if isinstance(objective, Mapping):
            route = objective.get("route")
            alternatives = objective.get("routeDecision", {}).get("alternatives", [])
            supported_routes = [route, *alternatives]
            supported_routes = [
                value for value in supported_routes if value in _LANGUAGE_ROUTES
            ]
        return {
            "schemaVersion": 1,
            "projectId": row["candidateRef"]["projectId"],
            "discoveryHandle": discovery_handle,
            "candidateHandle": candidate_handle,
            "candidateId": row["candidateId"],
            "summary": summary,
            "objective": _clone(objective) if isinstance(objective, Mapping) else None,
            "scores": _clone(candidate_payload.get("scores", {})),
            "gates": gates,
            "evidence": evidence_summaries,
            "relations": _clone(
                candidate_payload.get("semanticUnit", {}).get("relations", [])
            ),
            "supportedRoutes": supported_routes,
            "userEditHistory": [],
            "issueCodes": sorted(
                set(
                    candidate_payload.get(
                        "issueRefs", candidate_payload.get("reasonCodes", [])
                    )
                )
            ),
            "suppressed": row["candidate"].get("payloadSchema")
            == "study.candidate-rejection",
        }

    def preview_evidence(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        candidate_handle: str,
        evidence_id: str,
        context_characters: int = 160,
    ) -> dict[str, Any]:
        evidence_id = _text(evidence_id, "evidenceId", 256)
        if (
            isinstance(context_characters, bool)
            or not isinstance(context_characters, int)
            or not 0 <= context_characters <= _MAX_CONTEXT
        ):
            _fail("CANDIDATE_QUERY_INVALID", "contextCharacters is invalid")
        row, _discovery, _discovery_ref, _project = self._member_from_handle(
            audience=audience,
            discovery_handle=discovery_handle,
            candidate_handle=candidate_handle,
        )
        candidate_payload = row["candidate"]["payload"]
        anchors = candidate_payload.get("evidenceAnchors", [])
        matches = [
            value
            for value in anchors
            if isinstance(value, Mapping) and value.get("evidenceId") == evidence_id
        ]
        if len(matches) != 1:
            _fail("EVIDENCE_NOT_FOUND", "evidence does not exist on this candidate")
        anchor = matches[0]
        locator = anchor.get("locator")
        representation_ref = candidate_payload.get("representationRef")
        if not isinstance(locator, Mapping) or not isinstance(
            representation_ref, Mapping
        ):
            _fail("EVIDENCE_REPLAY_FAILED", "evidence locator is invalid")
        try:
            representation = self._artifacts.verify_ref(representation_ref, audience)
            representation_payload = representation["payload"]
            text = self._artifacts.read_blob(
                representation_payload["plainTextBlobRef"]
            ).decode("utf-8", errors="strict")
        except (
            ArtifactRegistryError,
            UnicodeDecodeError,
            KeyError,
            TypeError,
        ) as error:
            raise CandidateQueryError(
                "EVIDENCE_REPLAY_FAILED", "evidence source could not be replayed"
            ) from error
        nodes = representation_payload.get("contentNodes")
        node_id = locator.get("nodeId")
        start = locator.get("start")
        end = locator.get("end")
        node_matches = (
            [
                value
                for value in nodes
                if isinstance(nodes, list)
                and isinstance(value, Mapping)
                and value.get("nodeId") == node_id
            ]
            if isinstance(nodes, list)
            else []
        )
        if (
            len(node_matches) != 1
            or isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
        ):
            _fail("EVIDENCE_REPLAY_FAILED", "evidence source bounds are invalid")
        attributes = node_matches[0].get("attributes")
        node_start = (
            attributes.get("textStart") if isinstance(attributes, Mapping) else None
        )
        node_end = (
            attributes.get("textEnd") if isinstance(attributes, Mapping) else None
        )
        if (
            not isinstance(node_start, int)
            or not isinstance(node_end, int)
            or start < node_start
            or end > node_end
            or end <= start
            or node_end > len(text)
        ):
            _fail("EVIDENCE_REPLAY_FAILED", "evidence source bounds are invalid")
        sensitive_reason = sensitive_disclosure_reason(text[node_start:node_end])
        if sensitive_reason is not None:
            _fail(
                "EVIDENCE_PREVIEW_REDACTED",
                "evidence context was withheld by the disclosure policy",
            )
        quote = text[start:end]
        if hashlib.sha256(quote.encode("utf-8")).hexdigest() != anchor.get(
            "quoteSha256"
        ):
            _fail(
                "EVIDENCE_REPLAY_FAILED", "evidence quote no longer matches its digest"
            )
        context_start = max(node_start, start - context_characters)
        context_end = min(node_end, end + context_characters)
        node_locator = node_matches[0].get("locator", {})
        source = self._source_summary(row, audience)
        result_locator = {
            "kind": "text_span",
            "nodeId": node_id,
            "start": start,
            "end": end,
        }
        if isinstance(node_locator, Mapping):
            if isinstance(node_locator.get("startMs"), int):
                result_locator["startMs"] = node_locator["startMs"]
            if isinstance(node_locator.get("endMs"), int):
                result_locator["endMs"] = node_locator["endMs"]
        return {
            "schemaVersion": 1,
            "projectId": row["candidateRef"]["projectId"],
            "discoveryHandle": discovery_handle,
            "candidateHandle": candidate_handle,
            "evidenceId": evidence_id,
            "source": {
                key: source[key]
                for key in ("sourceId", "displayName", "sourceType", "sourceHandle")
            },
            "quote": quote,
            "contextBefore": text[context_start:start],
            "contextAfter": text[end:context_end],
            "locator": result_locator,
            "quoteSha256": anchor["quoteSha256"],
            "snapshotBacked": True,
            "networkAccessed": False,
        }


__all__ = ["CandidateQueryError", "CandidateQueryRuntime"]
