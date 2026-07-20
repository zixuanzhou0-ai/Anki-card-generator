"""Authenticated, bounded replay of text evidence from immutable artifacts."""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Mapping

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
)
from .candidate_discovery import sensitive_disclosure_reason


MAX_EVIDENCE_CONTEXT_CHARACTERS = 480
_MAX_PLAIN_TEXT_BYTES = 32 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceReplayError(RuntimeError):
    """A fail-closed replay error whose message contains no artifact metadata."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise EvidenceReplayError(code, message)


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class EvidenceReplay:
    """Replay one quoted span from an authenticated source representation.

    The caller supplies an authenticated representation reference, never a Blob
    reference.  The service verifies the representation before obtaining its
    private ``plainTextBlobRef`` and returns only the bounded evidence surface.
    """

    def __init__(self, *, artifacts: ArtifactRegistry) -> None:
        self._artifacts = artifacts

    def replay(
        self,
        *,
        audience: ArtifactAudienceBinding,
        representation_ref: Mapping[str, Any],
        locator: Mapping[str, Any],
        quote_sha256: str,
        context_characters: int = 160,
    ) -> dict[str, Any]:
        if (
            not isinstance(representation_ref, Mapping)
            or not isinstance(locator, Mapping)
            or locator.get("kind") != "text_span"
            or not isinstance(quote_sha256, str)
            or not _SHA256_RE.fullmatch(quote_sha256)
            or isinstance(context_characters, bool)
            or not isinstance(context_characters, int)
            or not 0 <= context_characters <= MAX_EVIDENCE_CONTEXT_CHARACTERS
        ):
            _fail("EVIDENCE_REPLAY_FAILED", "evidence replay request is invalid")

        try:
            representation = self._artifacts.verify_ref(representation_ref, audience)
            payload = representation.get("payload")
            if (
                representation.get("payloadSchema") != "study.source-representation"
                or representation.get("payloadSchemaVersion") != 1
                or not isinstance(payload, Mapping)
            ):
                _fail(
                    "EVIDENCE_REPLAY_FAILED",
                    "evidence source could not be replayed",
                )
            blob_ref = payload.get("plainTextBlobRef")
            nodes = payload.get("contentNodes")
            if (
                not isinstance(blob_ref, Mapping)
                or not isinstance(nodes, list)
                or _integer(blob_ref.get("sizeBytes")) is None
                or int(blob_ref["sizeBytes"]) > _MAX_PLAIN_TEXT_BYTES
                or blob_ref.get("mediaType") != "text/plain"
            ):
                _fail(
                    "EVIDENCE_REPLAY_FAILED",
                    "evidence source could not be replayed",
                )
            text = self._artifacts.read_blob(blob_ref).decode(
                "utf-8", errors="strict"
            )
        except EvidenceReplayError:
            raise
        except (ArtifactRegistryError, UnicodeDecodeError, KeyError, TypeError) as error:
            raise EvidenceReplayError(
                "EVIDENCE_REPLAY_FAILED", "evidence source could not be replayed"
            ) from error

        node_id = locator.get("nodeId")
        start = _integer(locator.get("start"))
        end = _integer(locator.get("end"))
        if not isinstance(node_id, str) or not node_id or start is None or end is None:
            _fail("EVIDENCE_REPLAY_FAILED", "evidence source bounds are invalid")

        node_matches = [
            node
            for node in nodes
            if isinstance(node, Mapping) and node.get("nodeId") == node_id
        ]
        if len(node_matches) != 1:
            _fail("EVIDENCE_REPLAY_FAILED", "evidence source bounds are invalid")
        node = node_matches[0]
        attributes = node.get("attributes")
        node_start = (
            _integer(attributes.get("textStart"))
            if isinstance(attributes, Mapping)
            else None
        )
        node_end = (
            _integer(attributes.get("textEnd"))
            if isinstance(attributes, Mapping)
            else None
        )
        if (
            node_start is None
            or node_end is None
            or node_start < 0
            or node_end <= node_start
            or node_end > len(text)
            or start < node_start
            or end > node_end
            or end <= start
        ):
            _fail("EVIDENCE_REPLAY_FAILED", "evidence source bounds are invalid")

        node_text = text[node_start:node_end]
        try:
            disclosure_reason = sensitive_disclosure_reason(node_text)
        except Exception as error:
            raise EvidenceReplayError(
                "EVIDENCE_REPLAY_FAILED", "evidence disclosure check failed"
            ) from error
        if disclosure_reason is not None:
            _fail(
                "EVIDENCE_PREVIEW_REDACTED",
                "evidence context was withheld by the disclosure policy",
            )

        quote = text[start:end]
        actual_quote_sha256 = hashlib.sha256(quote.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(actual_quote_sha256, quote_sha256):
            _fail(
                "EVIDENCE_REPLAY_FAILED",
                "evidence quote no longer matches its digest",
            )

        context_start = max(node_start, start - context_characters)
        context_end = min(node_end, end + context_characters)
        result_locator: dict[str, Any] = {
            "kind": "text_span",
            "nodeId": node_id,
            "start": start,
            "end": end,
        }
        node_locator = node.get("locator")
        if isinstance(node_locator, Mapping):
            if "pageNumber" in node_locator:
                page_number = _integer(node_locator.get("pageNumber"))
                if page_number is None or page_number < 1:
                    _fail(
                        "EVIDENCE_REPLAY_FAILED",
                        "evidence source locator is invalid",
                    )
                result_locator["pageNumber"] = page_number

            has_start_ms = "startMs" in node_locator
            has_end_ms = "endMs" in node_locator
            if has_start_ms != has_end_ms:
                _fail(
                    "EVIDENCE_REPLAY_FAILED",
                    "evidence source locator is invalid",
                )
            if has_start_ms:
                start_ms = _integer(node_locator.get("startMs"))
                end_ms = _integer(node_locator.get("endMs"))
                if (
                    start_ms is None
                    or end_ms is None
                    or start_ms < 0
                    or end_ms < start_ms
                ):
                    _fail(
                        "EVIDENCE_REPLAY_FAILED",
                        "evidence source locator is invalid",
                    )
                result_locator["startMs"] = start_ms
                result_locator["endMs"] = end_ms

        return {
            "quote": quote,
            "contextBefore": text[context_start:start],
            "contextAfter": text[end:context_end],
            "locator": result_locator,
            "quoteSha256": quote_sha256,
            "snapshotBacked": True,
            "networkAccessed": False,
        }


__all__ = [
    "EvidenceReplay",
    "EvidenceReplayError",
    "MAX_EVIDENCE_CONTEXT_CHARACTERS",
]
