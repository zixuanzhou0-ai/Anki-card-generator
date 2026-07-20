from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding, ArtifactRegistry
from card_service.evidence_replay import EvidenceReplay, EvidenceReplayError


_OWNER = hashlib.sha256(b"evidence-replay-owner").hexdigest()
_KEY = hashlib.sha256(b"evidence-replay-registry-key").digest()


def _audience(**changes: str) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": _OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


def _representation(
    root: Path,
    text: str,
    *,
    node_start: int = 4,
    node_end: int | None = None,
    payload_schema_version: int = 1,
    node_locator: dict[str, object] | None = None,
) -> tuple[EvidenceReplay, dict[str, object]]:
    artifacts = ArtifactRegistry(
        root,
        authentication_key=_KEY,
        service_instance_id="evidence-replay-service",
    )
    blob_ref = artifacts.put_blob(text.encode("utf-8"), media_type="text/plain")
    end = len(text) - 4 if node_end is None else node_end
    publication = artifacts.publish(
        audience=_audience(),
        project_id="project-1",
        project_revision=1,
        artifact_id="representation-1",
        artifact_revision=1,
        payload_schema="study.source-representation",
        payload_schema_version=payload_schema_version,
        payload={
            "representationId": "representation-1",
            "plainTextBlobRef": blob_ref,
            "contentNodes": [
                {
                    "nodeId": "node-1",
                    "locator": (
                        dict(node_locator)
                        if node_locator is not None
                        else {
                            "pageNumber": 3,
                            "startMs": 1200,
                            "endMs": 4800,
                            "sourceUrl": "https://private.invalid/source",
                        }
                    ),
                    "attributes": {"textStart": node_start, "textEnd": end},
                }
            ],
        },
        producer={"component": "test-suite", "version": "1.0.0"},
        parents=[],
        input_fingerprint=hashlib.sha256(b"source-input").hexdigest(),
        completeness={
            "state": "complete",
            "omittedLocators": [],
            "reasonCodes": [],
        },
        issue_refs=[],
    )
    return EvidenceReplay(artifacts=artifacts), dict(publication.artifact_ref)


def _locator(text: str, quote: str) -> dict[str, object]:
    start = text.index(quote)
    return {
        "kind": "text_span",
        "nodeId": "node-1",
        "start": start,
        "end": start + len(quote),
    }


def test_replay_authenticates_representation_and_returns_only_bounded_surface(
    tmp_path: Path,
) -> None:
    text = "OUT|before target phrase after|OUT"
    quote = "target phrase"
    replay, representation_ref = _representation(tmp_path / "artifacts", text)

    result = replay.replay(
        audience=_audience(),
        representation_ref=representation_ref,
        locator=_locator(text, quote),
        quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        context_characters=7,
    )

    assert result == {
        "quote": quote,
        "contextBefore": "before ",
        "contextAfter": " after",
        "locator": {
            "kind": "text_span",
            "nodeId": "node-1",
            "start": text.index(quote),
            "end": text.index(quote) + len(quote),
            "pageNumber": 3,
            "startMs": 1200,
            "endMs": 4800,
        },
        "quoteSha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        "snapshotBacked": True,
        "networkAccessed": False,
    }
    serialized = json.dumps(result, sort_keys=True)
    for forbidden in (
        "plainTextBlobRef",
        "registryAuthRef",
        "artifactRef",
        "authorization",
        "http://",
        "https://",
        str(tmp_path),
    ):
        assert forbidden not in serialized


def test_replay_uses_unicode_code_point_offsets_before_the_target(
    tmp_path: Path,
) -> None:
    prefix = "OUT|🙂e\u0301 prefix "
    quote = "target phrase"
    text = prefix + quote + " after|OUT"
    replay, representation_ref = _representation(tmp_path / "unicode", text)
    locator = _locator(text, quote)

    result = replay.replay(
        audience=_audience(),
        representation_ref=representation_ref,
        locator=locator,
        quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        context_characters=64,
    )

    assert locator["start"] == len(prefix)
    assert result["quote"] == quote
    assert result["contextBefore"] == prefix[4:]
    assert result["locator"]["start"] == len(prefix)


def test_replay_rejects_unknown_representation_schema_version(tmp_path: Path) -> None:
    text = "OUT|before target phrase after|OUT"
    quote = "target phrase"
    replay, representation_ref = _representation(
        tmp_path / "future-version", text, payload_schema_version=2
    )

    with pytest.raises(EvidenceReplayError) as captured:
        replay.replay(
            audience=_audience(),
            representation_ref=representation_ref,
            locator=_locator(text, quote),
            quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        )

    assert captured.value.code == "EVIDENCE_REPLAY_FAILED"


def test_replay_rejects_cross_audience_and_hides_private_reference_details(
    tmp_path: Path,
) -> None:
    text = "OUT|before target phrase after|OUT"
    quote = "target phrase"
    replay, representation_ref = _representation(tmp_path / "private", text)

    with pytest.raises(EvidenceReplayError) as captured:
        replay.replay(
            audience=_audience(owner_digest=hashlib.sha256(b"other").hexdigest()),
            representation_ref=representation_ref,
            locator=_locator(text, quote),
            quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        )

    assert captured.value.code == "EVIDENCE_REPLAY_FAILED"
    rendered = f"{captured.value.code}: {captured.value.message}"
    assert str(tmp_path) not in rendered
    assert representation_ref["registryAuthRef"] not in rendered


def test_replay_verifies_the_authenticated_blob_before_releasing_text(
    tmp_path: Path,
) -> None:
    text = "OUT|before target phrase after|OUT"
    quote = "target phrase"
    replay, representation_ref = _representation(tmp_path / "private", text)
    artifacts = replay._artifacts  # The corruption is below the public replay API.
    envelope = artifacts.verify_ref(representation_ref, _audience())
    blob_ref = envelope["payload"]["plainTextBlobRef"]
    artifacts._blob_path(blob_ref["sha256"]).write_bytes(b"tampered")

    with pytest.raises(EvidenceReplayError) as captured:
        replay.replay(
            audience=_audience(),
            representation_ref=representation_ref,
            locator=_locator(text, quote),
            quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        )

    assert captured.value.code == "EVIDENCE_REPLAY_FAILED"
    rendered = f"{captured.value.code}: {captured.value.message}"
    assert str(tmp_path) not in rendered
    assert blob_ref["blobId"] not in rendered


@pytest.mark.parametrize(
    ("locator_change", "quote_digest"),
    [
        ({"start": True}, None),
        ({"end": 10_000}, None),
        ({"nodeId": "missing"}, None),
        ({}, hashlib.sha256(b"different quote").hexdigest()),
    ],
)
def test_replay_revalidates_node_offsets_and_quote_digest(
    tmp_path: Path,
    locator_change: dict[str, object],
    quote_digest: str | None,
) -> None:
    text = "OUT|before target phrase after|OUT"
    quote = "target phrase"
    replay, representation_ref = _representation(tmp_path / "artifacts", text)
    locator = {**_locator(text, quote), **locator_change}

    with pytest.raises(EvidenceReplayError) as captured:
        replay.replay(
            audience=_audience(),
            representation_ref=representation_ref,
            locator=locator,
            quote_sha256=quote_digest
            or hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        )

    assert captured.value.code == "EVIDENCE_REPLAY_FAILED"


def test_replay_checks_the_entire_node_before_releasing_a_safe_quote(
    tmp_path: Path,
) -> None:
    secret = "Bearer " + "A" * 24
    text = f"OUT|safe target then hidden {secret}|OUT"
    quote = "safe target"
    replay, representation_ref = _representation(tmp_path / "artifacts", text)

    with pytest.raises(EvidenceReplayError) as captured:
        replay.replay(
            audience=_audience(),
            representation_ref=representation_ref,
            locator=_locator(text, quote),
            quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            context_characters=0,
        )

    assert captured.value.code == "EVIDENCE_PREVIEW_REDACTED"
    assert secret not in captured.value.message


@pytest.mark.parametrize(
    "node_locator",
    [
        {"pageNumber": 0, "startMs": 1200, "endMs": 4800},
        {"pageNumber": -1, "startMs": 1200, "endMs": 4800},
        {"pageNumber": 3, "startMs": -1, "endMs": 4800},
        {"pageNumber": 3, "startMs": 4801, "endMs": 4800},
        {"pageNumber": 3, "startMs": 1200, "endMs": -1},
        {"pageNumber": 3, "startMs": 1200},
        {"pageNumber": 3, "endMs": 4800},
    ],
)
def test_replay_rejects_invalid_page_and_time_locators(
    tmp_path: Path, node_locator: dict[str, object]
) -> None:
    text = "OUT|before target phrase after|OUT"
    quote = "target phrase"
    replay, representation_ref = _representation(
        tmp_path
        / ("locator-" + hashlib.sha256(repr(node_locator).encode()).hexdigest()),
        text,
        node_locator=node_locator,
    )

    with pytest.raises(EvidenceReplayError) as captured:
        replay.replay(
            audience=_audience(),
            representation_ref=representation_ref,
            locator=_locator(text, quote),
            quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        )

    assert captured.value.code == "EVIDENCE_REPLAY_FAILED"


@pytest.mark.parametrize("context_characters", [-1, 481, True])
def test_replay_enforces_its_own_context_limit(
    tmp_path: Path, context_characters: object
) -> None:
    text = "OUT|before target phrase after|OUT"
    quote = "target phrase"
    replay, representation_ref = _representation(tmp_path / "artifacts", text)

    with pytest.raises(EvidenceReplayError) as captured:
        replay.replay(
            audience=_audience(),
            representation_ref=representation_ref,
            locator=_locator(text, quote),
            quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            context_characters=context_characters,  # type: ignore[arg-type]
        )

    assert captured.value.code == "EVIDENCE_REPLAY_FAILED"
