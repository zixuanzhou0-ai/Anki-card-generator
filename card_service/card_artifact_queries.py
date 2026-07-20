"""Authenticated, bounded public projections of generated CardArtifacts."""

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
from .card_artifact_runtime import CardArtifactRuntime, CardArtifactRuntimeError


_CURSOR_PREFIX = "study_card_cursor_"
_CURSOR_DOMAIN = b"study.card-artifact-query.cursor.v1\x00"
_CURSOR_RE = re.compile(r"^study_card_cursor_[A-Za-z0-9_.-]{80,1800}$")
_MAX_LIMIT = 100


class CardArtifactQueryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise CardArtifactQueryError(code, message)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as error:
        raise CardArtifactQueryError(
            "CARD_CURSOR_INVALID", "card cursor is invalid"
        ) from error
    if not hmac.compare_digest(_b64(decoded), value):
        _fail("CARD_CURSOR_INVALID", "card cursor encoding is not canonical")
    return decoded


class CardArtifactQueryRuntime:
    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        card_artifacts: CardArtifactRuntime,
        cursor_key: bytes,
    ) -> None:
        if not isinstance(cursor_key, bytes) or len(cursor_key) < 32:
            _fail("CARD_QUERY_KEY_INVALID", "card query cursor key is invalid")
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._cards = card_artifacts
        self._cursor_key = bytes(cursor_key)

    def _encode_cursor(self, *, project_digest: str, last_card_id: str) -> str:
        payload = canonical_json_bytes(
            {
                "schemaVersion": 1,
                "serviceInstanceId": self._service_instance_id,
                "projectArtifactDigest": project_digest,
                "lastCardId": last_card_id,
            }
        )
        tag = hmac.new(
            self._cursor_key, _CURSOR_DOMAIN + payload, hashlib.sha256
        ).digest()
        return _CURSOR_PREFIX + _b64(payload) + "." + _b64(tag)

    def _decode_cursor(self, value: str) -> dict[str, Any]:
        if not isinstance(value, str) or not _CURSOR_RE.fullmatch(value):
            _fail("CARD_CURSOR_INVALID", "card cursor is invalid")
        body = value[len(_CURSOR_PREFIX) :]
        try:
            payload_text, tag_text = body.split(".", 1)
        except ValueError as error:
            raise CardArtifactQueryError(
                "CARD_CURSOR_INVALID", "card cursor is invalid"
            ) from error
        payload = _decode(payload_text)
        tag = _decode(tag_text)
        expected = hmac.new(
            self._cursor_key, _CURSOR_DOMAIN + payload, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(tag, expected):
            _fail("CARD_CURSOR_INVALID", "card cursor authentication failed")
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CardArtifactQueryError(
                "CARD_CURSOR_INVALID", "card cursor payload is invalid"
            ) from error
        if (
            not isinstance(decoded, dict)
            or set(decoded)
            != {
                "schemaVersion",
                "serviceInstanceId",
                "projectArtifactDigest",
                "lastCardId",
            }
            or decoded.get("schemaVersion") != 1
            or decoded.get("serviceInstanceId") != self._service_instance_id
            or not isinstance(decoded.get("projectArtifactDigest"), str)
            or not isinstance(decoded.get("lastCardId"), str)
        ):
            _fail("CARD_CURSOR_INVALID", "card cursor fields are invalid")
        return decoded

    @staticmethod
    def _public_card(handle: str, envelope: Mapping[str, Any]) -> dict[str, Any]:
        payload = envelope.get("payload")
        if not isinstance(payload, Mapping):
            _fail("CARD_ARTIFACT_INVALID", "CardArtifact payload is invalid")
        front = payload.get("front")
        back = payload.get("back")
        scoring = payload.get("scoring")
        verification = payload.get("verification")
        generation = payload.get("generation")
        if not all(
            isinstance(value, Mapping)
            for value in (front, back, scoring, verification, generation)
        ):
            _fail("CARD_ARTIFACT_INVALID", "CardArtifact fields are invalid")
        card_id = payload.get("cardId")
        artifact_schema_version = envelope.get("payloadSchemaVersion", 1)
        if (
            not isinstance(card_id, str)
            or isinstance(artifact_schema_version, bool)
            or artifact_schema_version not in {1, 2}
            or front.get("modality") != "text"
            or not isinstance(front.get("prompt"), str)
            or not isinstance(back.get("coreAnswer"), str)
            or not isinstance(back.get("explanation"), str)
            or not isinstance(back.get("examples"), list)
            or not isinstance(back.get("nonexamples"), list)
            or not isinstance(scoring.get("points"), list)
            or not isinstance(scoring.get("acceptedVariants"), list)
            or verification.get("state") != "verified"
            or generation.get("mode") != "deterministic_projection"
            or payload.get("mediaRefs") != []
        ):
            _fail("CARD_ARTIFACT_INVALID", "CardArtifact is not safely reviewable")
        result = {
            "cardId": card_id,
            "cardHandle": handle,
            "artifactSchemaVersion": artifact_schema_version,
            "route": str(payload.get("route") or ""),
            "front": {"prompt": front["prompt"]},
            "back": {
                "coreAnswer": back["coreAnswer"],
                "explanation": back["explanation"],
                "examples": list(back["examples"]),
                "nonexamples": list(back["nonexamples"]),
            },
            "scoring": {
                "points": list(scoring["points"]),
                "acceptedVariants": list(scoring["acceptedVariants"]),
                "singleRecallTarget": bool(scoring.get("singleRecallTarget")),
            },
            "verification": {
                "state": "verified",
                "ruleSetVersion": str(verification.get("ruleSetVersion") or ""),
            },
            "mediaRoles": [],
        }
        if artifact_schema_version == 1:
            return result

        language_profile = payload.get("languageProfile")
        content_origins = payload.get("contentOrigins")
        presentation = payload.get("evidencePresentation")
        required_language_fields = {
            "promptLanguage",
            "answerLanguage",
            "targetLanguage",
            "meaningLanguage",
            "route",
        }
        required_origin_fields = {
            "frontPrompt",
            "coreAnswer",
            "explanation",
            "sourceQuote",
        }
        if (
            not isinstance(language_profile, Mapping)
            or set(language_profile) != required_language_fields
            or language_profile.get("route") != payload.get("route")
            or language_profile.get("promptLanguage") not in {"en", "zh-CN"}
            or language_profile.get("answerLanguage") != "en"
            or language_profile.get("targetLanguage") != "en"
            or language_profile.get("meaningLanguage") not in {"en", "zh-CN"}
            or not isinstance(content_origins, Mapping)
            or set(content_origins) != required_origin_fields
            or not isinstance(presentation, Mapping)
            or presentation.get("state") != "verified"
            or not isinstance(presentation.get("primaryText"), str)
            or not presentation["primaryText"].strip()
            or not isinstance(presentation.get("items"), list)
            or not 1 <= len(presentation["items"]) <= 8
        ):
            _fail("CARD_ARTIFACT_INVALID", "CardArtifact V2 fields are invalid")
        public_origins: dict[str, str] = {}
        direct_answer = payload.get("route") in {"production", "chunk_collocation"}
        expected_origin_kinds = {
            "frontPrompt": (
                "model_reviewed_interpretation" if direct_answer else "source_direct"
            ),
            "coreAnswer": (
                "source_direct" if direct_answer else "model_reviewed_interpretation"
            ),
            "explanation": "model_reviewed_interpretation",
            "sourceQuote": "source_direct",
        }
        for field, expected_kind in expected_origin_kinds.items():
            origin = content_origins.get(field)
            if not isinstance(origin, Mapping) or origin.get("kind") != expected_kind:
                _fail("CARD_ARTIFACT_INVALID", "CardArtifact origin is invalid")
            public_origins[field] = expected_kind
        public_evidence: list[dict[str, Any]] = []
        for item in presentation["items"]:
            if not isinstance(item, Mapping):
                _fail("CARD_ARTIFACT_INVALID", "CardArtifact evidence is invalid")
            quote = item.get("quote")
            context = item.get("context")
            locator = item.get("locator")
            quote_sha256 = item.get("quoteSha256")
            source_display_name = item.get("sourceDisplayName")
            source_type = item.get("sourceType")
            if (
                not isinstance(quote, str)
                or not quote
                or len(quote) > 500
                or not isinstance(context, str)
                or not context
                or len(context) > 1_200
                or quote not in context
                or not isinstance(locator, Mapping)
                or locator.get("kind") != "text_span"
                or not isinstance(source_display_name, str)
                or not source_display_name
                or len(source_display_name) > 160
                or not isinstance(source_type, str)
                or not source_type
                or len(source_type) > 64
                or not isinstance(quote_sha256, str)
                or len(quote_sha256) != 64
                or not hmac.compare_digest(
                    hashlib.sha256(quote.encode("utf-8")).hexdigest(), quote_sha256
                )
                or item.get("snapshotBacked") is not True
                or item.get("networkAccessed") is not False
            ):
                _fail("CARD_ARTIFACT_INVALID", "CardArtifact evidence is invalid")
            public_locator = {
                key: locator[key]
                for key in ("pageNumber", "startMs", "endMs")
                if isinstance(locator.get(key), int)
                and not isinstance(locator.get(key), bool)
            }
            public_evidence.append(
                {
                    "sourceDisplayName": source_display_name,
                    "sourceType": source_type,
                    "quote": quote,
                    "context": context,
                    "locator": public_locator,
                    "quoteSha256": quote_sha256,
                    "snapshotBacked": True,
                    "networkAccessed": False,
                }
            )
        if presentation["primaryText"] != public_evidence[0]["context"]:
            _fail("CARD_ARTIFACT_INVALID", "CardArtifact primary evidence is invalid")
        result["languageProfile"] = dict(language_profile)
        result["contentOrigins"] = public_origins
        result["evidencePresentation"] = {
            "state": "verified",
            "primaryText": presentation["primaryText"],
            "items": public_evidence,
        }
        return result

    def list_cards(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_artifact_handle: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_LIMIT
        ):
            _fail("CARD_QUERY_INVALID", "card query limit is invalid")
        try:
            graph = self._cards.resolve_current_project_artifact(
                audience=audience,
                project_artifact_handle=project_artifact_handle,
            )
        except CardArtifactRuntimeError as error:
            raise CardArtifactQueryError(error.code, error.message) from error
        project_ref = graph["projectRef"]
        refs = graph.get("cardRefs")
        envelopes = graph.get("cardEnvelopes")
        if (
            not isinstance(refs, list)
            or not isinstance(envelopes, list)
            or len(refs) != len(envelopes)
            or not refs
        ):
            _fail("CARD_ARTIFACT_INVALID", "ProjectArtifact card graph is invalid")
        values = sorted(
            zip(refs, envelopes, strict=True),
            key=lambda value: str(
                value[1].get("payload", {}).get("cardId") or ""
            ).encode("utf-8"),
        )
        start = 0
        if cursor is not None:
            decoded = self._decode_cursor(cursor)
            if decoded["projectArtifactDigest"] != project_ref["artifactDigest"]:
                _fail(
                    "CARD_CURSOR_STALE",
                    "card cursor belongs to another ProjectArtifact",
                )
            ids = [str(value[1]["payload"]["cardId"]) for value in values]
            try:
                start = ids.index(decoded["lastCardId"]) + 1
            except ValueError as error:
                raise CardArtifactQueryError(
                    "CARD_CURSOR_STALE", "card cursor position no longer exists"
                ) from error
        page = values[start : start + limit]
        items = []
        for ref, envelope in page:
            try:
                handle = self._artifacts.issue_handle(ref, audience)
            except ArtifactRegistryError as error:
                raise CardArtifactQueryError(error.code, error.message) from error
            items.append(self._public_card(handle, envelope))
        next_cursor = None
        if start + len(page) < len(values):
            next_cursor = self._encode_cursor(
                project_digest=project_ref["artifactDigest"],
                last_card_id=items[-1]["cardId"],
            )
        return {
            "schemaVersion": 1,
            "projectId": graph["project"]["projectId"],
            "projectRevision": graph["project"]["projectRevision"],
            "artifactStage": graph["project"]["workflow"]["artifactStage"],
            "projectArtifactHandle": project_artifact_handle,
            "totalCards": len(values),
            "returnedCards": len(items),
            "items": items,
            "nextCursor": next_cursor,
            "nextAction": "export_apkg",
        }


__all__ = ["CardArtifactQueryError", "CardArtifactQueryRuntime"]
