"""Closed MCP adapters for authenticated candidate review and evidence preview."""

from __future__ import annotations

import re
from typing import Any

from .service import CardService
from .trusted_mcp_audience import TrustedMcpAudienceSession


LIST_CANDIDATES_TOOL_NAME = "study.list_candidates"
GET_CANDIDATE_TOOL_NAME = "study.get_candidate"
PREVIEW_EVIDENCE_TOOL_NAME = "study.preview_evidence"
CANDIDATE_TOOL_NAMES = frozenset(
    {LIST_CANDIDATES_TOOL_NAME, GET_CANDIDATE_TOOL_NAME, PREVIEW_EVIDENCE_TOOL_NAME}
)

_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_CURSOR_RE = re.compile(r"^study_cursor_[A-Za-z0-9_-]{80,1800}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_ELIGIBILITY = (
    "recommended",
    "candidate",
    "duplicate",
    "needs_review",
    "hard_blocked",
    "excluded",
)
_ROUTES = (
    "reading_recognition",
    "listening_recognition",
    "production",
    "grammar_cloze",
    "pronunciation",
    "pragmatics_register",
    "chunk_collocation",
    "contrast",
)
_SORTS = ("recommended", "source_order", "review_cost")
_SELECTION_STATES = ("selected", "unselected")


class McpCandidateToolInputError(ValueError):
    pass


def _handle_schema() -> dict[str, Any]:
    return {"type": "string", "pattern": r"^study_[A-Za-z0-9_-]{43}$"}


def _candidate_list_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "projectId": {"type": "string"},
            "discoveryHandle": _handle_schema(),
            "totalCandidates": {"type": "integer", "minimum": 0},
            "returnedCandidates": {"type": "integer", "minimum": 0},
            "items": {"type": "array", "items": {"type": "object"}},
            "nextCursor": {
                "oneOf": [
                    {"type": "string", "pattern": r"^study_cursor_[A-Za-z0-9_-]+$"},
                    {"type": "null"},
                ]
            },
        },
        "required": [
            "schemaVersion",
            "projectId",
            "discoveryHandle",
            "totalCandidates",
            "returnedCandidates",
            "items",
            "nextCursor",
        ],
        "additionalProperties": False,
    }


def _candidate_detail_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "projectId": {"type": "string"},
            "discoveryHandle": _handle_schema(),
            "candidateHandle": _handle_schema(),
            "candidateId": {"type": "string"},
            "summary": {"type": "object"},
            "objective": {"oneOf": [{"type": "object"}, {"type": "null"}]},
            "scores": {"type": "object"},
            "gates": {"type": "array", "items": {"type": "object"}},
            "evidence": {"type": "array", "items": {"type": "object"}},
            "relations": {"type": "array"},
            "supportedRoutes": {"type": "array", "items": {"type": "string"}},
            "userEditHistory": {"type": "array"},
            "issueCodes": {"type": "array", "items": {"type": "string"}},
            "suppressed": {"type": "boolean"},
        },
        "required": [
            "schemaVersion",
            "projectId",
            "discoveryHandle",
            "candidateHandle",
            "candidateId",
            "summary",
            "objective",
            "scores",
            "gates",
            "evidence",
            "relations",
            "supportedRoutes",
            "userEditHistory",
            "issueCodes",
            "suppressed",
        ],
        "additionalProperties": False,
    }


def _evidence_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "projectId": {"type": "string"},
            "discoveryHandle": _handle_schema(),
            "candidateHandle": _handle_schema(),
            "evidenceId": {"type": "string"},
            "source": {"type": "object"},
            "quote": {"type": "string"},
            "contextBefore": {"type": "string"},
            "contextAfter": {"type": "string"},
            "locator": {"type": "object"},
            "quoteSha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
            "snapshotBacked": {"type": "boolean", "const": True},
            "networkAccessed": {"type": "boolean", "const": False},
        },
        "required": [
            "schemaVersion",
            "projectId",
            "discoveryHandle",
            "candidateHandle",
            "evidenceId",
            "source",
            "quote",
            "contextBefore",
            "contextAfter",
            "locator",
            "quoteSha256",
            "snapshotBacked",
            "networkAccessed",
        ],
        "additionalProperties": False,
    }


def candidate_tool_definitions() -> list[dict[str, Any]]:
    common_annotations = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    return [
        {
            "name": LIST_CANDIDATES_TOOL_NAME,
            "title": "List authenticated learning candidates",
            "description": (
                "Read a bounded page of candidates from an existing authenticated discovery. "
                "The service derives eligibility from gates and returns no source body, local "
                "path, model prompt, credential, or internal ArtifactRef."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "discoveryHandle": _handle_schema(),
                    "filter": {
                        "type": "object",
                        "properties": {
                            "eligibility": {
                                "type": "array",
                                "items": {"type": "string", "enum": list(_ELIGIBILITY)},
                                "minItems": 1,
                                "maxItems": len(_ELIGIBILITY),
                                "uniqueItems": True,
                            },
                            "route": {
                                "type": "array",
                                "items": {"type": "string", "enum": list(_ROUTES)},
                                "minItems": 1,
                                "maxItems": len(_ROUTES),
                                "uniqueItems": True,
                            },
                            "selectionState": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": list(_SELECTION_STATES),
                                },
                                "minItems": 1,
                                "maxItems": len(_SELECTION_STATES),
                                "uniqueItems": True,
                            },
                            "sourceHandles": {
                                "type": "array",
                                "items": _handle_schema(),
                                "minItems": 1,
                                "maxItems": 64,
                                "uniqueItems": True,
                            },
                            "query": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 200,
                            },
                        },
                        "additionalProperties": False,
                    },
                    "sort": {"type": "string", "enum": list(_SORTS)},
                    "cursor": {
                        "type": "string",
                        "pattern": r"^study_cursor_[A-Za-z0-9_-]+$",
                        "maxLength": 1813,
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["discoveryHandle"],
                "additionalProperties": False,
            },
            "outputSchema": _candidate_list_output_schema(),
            "annotations": dict(common_annotations),
        },
        {
            "name": GET_CANDIDATE_TOOL_NAME,
            "title": "Read one authenticated learning candidate",
            "description": (
                "Read the objective, service-derived gates and scores, evidence metadata, "
                "routes, and risks for one candidate in the specified discovery. Evidence text "
                "is intentionally omitted; use study.preview_evidence for a bounded replay."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "discoveryHandle": _handle_schema(),
                    "candidateHandle": _handle_schema(),
                },
                "required": ["discoveryHandle", "candidateHandle"],
                "additionalProperties": False,
            },
            "outputSchema": _candidate_detail_output_schema(),
            "annotations": dict(common_annotations),
        },
        {
            "name": PREVIEW_EVIDENCE_TOOL_NAME,
            "title": "Preview bounded candidate evidence",
            "description": (
                "Replay one evidence anchor from the authenticated local source snapshot with "
                "bounded same-node context. It never reopens a remote URL and never returns a "
                "local path, BlobRef, or internal ArtifactRef."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "discoveryHandle": _handle_schema(),
                    "candidateHandle": _handle_schema(),
                    "evidenceId": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 256,
                        "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$",
                    },
                    "contextCharacters": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 480,
                    },
                },
                "required": ["discoveryHandle", "candidateHandle", "evidenceId"],
                "additionalProperties": False,
            },
            "outputSchema": _evidence_output_schema(),
            "annotations": dict(common_annotations),
        },
    ]


def _handle(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _HANDLE_RE.fullmatch(value):
        raise McpCandidateToolInputError(f"{label} is invalid")
    return value


def _list_arguments(
    arguments: Any,
) -> tuple[str, dict[str, Any] | None, str, str | None, int]:
    if (
        not isinstance(arguments, dict)
        or "discoveryHandle" not in arguments
        or not set(arguments).issubset(
            {"discoveryHandle", "filter", "sort", "cursor", "limit"}
        )
    ):
        raise McpCandidateToolInputError("candidate list fields are invalid")
    discovery_handle = _handle(arguments.get("discoveryHandle"), "discoveryHandle")
    filters = arguments.get("filter")
    if filters is not None:
        if not isinstance(filters, dict) or not set(filters).issubset(
            {"eligibility", "route", "selectionState", "sourceHandles", "query"}
        ):
            raise McpCandidateToolInputError("candidate filter fields are invalid")
        for key, allowed in (
            ("eligibility", _ELIGIBILITY),
            ("route", _ROUTES),
            ("selectionState", _SELECTION_STATES),
        ):
            value = filters.get(key)
            if value is not None and (
                not isinstance(value, list)
                or not value
                or len(value) > len(allowed)
                or any(item not in allowed for item in value)
                or len(value) != len(set(value))
            ):
                raise McpCandidateToolInputError(f"{key} filter is invalid")
        source_handles = filters.get("sourceHandles")
        if source_handles is not None and (
            not isinstance(source_handles, list)
            or not 1 <= len(source_handles) <= 64
            or any(
                not isinstance(item, str) or not _HANDLE_RE.fullmatch(item)
                for item in source_handles
            )
            or len(source_handles) != len(set(source_handles))
        ):
            raise McpCandidateToolInputError("sourceHandles filter is invalid")
        query = filters.get("query")
        if query is not None and (
            not isinstance(query, str) or not query.strip() or len(query) > 200
        ):
            raise McpCandidateToolInputError("query filter is invalid")
        filters = dict(filters)
    sort = arguments.get("sort", "recommended")
    if sort not in _SORTS:
        raise McpCandidateToolInputError("sort is invalid")
    cursor = arguments.get("cursor")
    if cursor is not None and (
        not isinstance(cursor, str) or not _CURSOR_RE.fullmatch(cursor)
    ):
        raise McpCandidateToolInputError("cursor is invalid")
    limit = arguments.get("limit", 20)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise McpCandidateToolInputError("limit is invalid")
    return discovery_handle, filters, str(sort), cursor, limit


def _candidate_arguments(arguments: Any) -> tuple[str, str]:
    if not isinstance(arguments, dict) or set(arguments) != {
        "discoveryHandle",
        "candidateHandle",
    }:
        raise McpCandidateToolInputError("candidate fields are invalid")
    return (
        _handle(arguments.get("discoveryHandle"), "discoveryHandle"),
        _handle(arguments.get("candidateHandle"), "candidateHandle"),
    )


def _evidence_arguments(arguments: Any) -> tuple[str, str, str, int]:
    if (
        not isinstance(arguments, dict)
        or not {
            "discoveryHandle",
            "candidateHandle",
            "evidenceId",
        }.issubset(arguments)
        or not set(arguments).issubset(
            {"discoveryHandle", "candidateHandle", "evidenceId", "contextCharacters"}
        )
    ):
        raise McpCandidateToolInputError("evidence preview fields are invalid")
    discovery_handle, candidate_handle = _candidate_arguments(
        {
            "discoveryHandle": arguments.get("discoveryHandle"),
            "candidateHandle": arguments.get("candidateHandle"),
        }
    )
    evidence_id = arguments.get("evidenceId")
    if not isinstance(evidence_id, str) or not _ID_RE.fullmatch(evidence_id):
        raise McpCandidateToolInputError("evidenceId is invalid")
    context = arguments.get("contextCharacters", 160)
    if (
        isinstance(context, bool)
        or not isinstance(context, int)
        or not 0 <= context <= 480
    ):
        raise McpCandidateToolInputError("contextCharacters is invalid")
    return discovery_handle, candidate_handle, evidence_id, context


def call_candidate_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    audience_session: TrustedMcpAudienceSession,
) -> dict[str, Any]:
    if tool_name == LIST_CANDIDATES_TOOL_NAME:
        discovery, filters, sort, cursor, limit = _list_arguments(arguments)
        structured = service.list_study_candidates(
            audience=audience_session.audience,
            discovery_handle=discovery,
            filters=filters,
            sort=sort,
            cursor=cursor,
            limit=limit,
        )
        text = (
            f"Loaded {structured['returnedCandidates']} of "
            f"{structured['totalCandidates']} matching candidate(s)."
        )
    elif tool_name == GET_CANDIDATE_TOOL_NAME:
        discovery, candidate = _candidate_arguments(arguments)
        structured = service.get_study_candidate(
            audience=audience_session.audience,
            discovery_handle=discovery,
            candidate_handle=candidate,
        )
        text = (
            "Loaded the candidate objective, reliability gates, and evidence metadata."
        )
    elif tool_name == PREVIEW_EVIDENCE_TOOL_NAME:
        discovery, candidate, evidence_id, context = _evidence_arguments(arguments)
        structured = service.preview_study_candidate_evidence(
            audience=audience_session.audience,
            discovery_handle=discovery,
            candidate_handle=candidate,
            evidence_id=evidence_id,
            context_characters=context,
        )
        text = "Replayed bounded evidence from the authenticated local source snapshot."
    else:
        raise McpCandidateToolInputError("Unknown candidate tool")
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }


__all__ = [
    "CANDIDATE_TOOL_NAMES",
    "GET_CANDIDATE_TOOL_NAME",
    "LIST_CANDIDATES_TOOL_NAME",
    "McpCandidateToolInputError",
    "PREVIEW_EVIDENCE_TOOL_NAME",
    "call_candidate_tool",
    "candidate_tool_definitions",
]
