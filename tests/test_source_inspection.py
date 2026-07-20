from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.project_registry import ProjectRegistryError
from card_service.resource_runtime import ServiceResourceRuntime
from card_service.source_inspection import (
    SourceInspectionError,
    StructuredSourceParserError,
)
from card_service.study_runtime import StudyRuntime, StudyRuntimeError


OWNER = hashlib.sha256(b"source-inspection-owner").hexdigest()


def audience(**changes: str) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


def environment(
    tmp_path: Path,
    *,
    structured_source_parser=None,
    media_tools: bool = True,
):
    backend = InMemoryCredentialBackend()
    credentials = (tmp_path / "credentials").resolve()
    resources = ServiceResourceRuntime(
        state_dir=(tmp_path / "resources").resolve(),
        credential_store=CredentialStore(state_dir=credentials, backend=backend),
        gesture_verifier=lambda *_args: True,
        harden_callback=None,
        require_hardening=False,
    )
    runtime = StudyRuntime(
        state_dir=(tmp_path / "study").resolve(),
        credential_store=CredentialStore(state_dir=credentials, backend=backend),
        resource_runtime=resources,
        structured_source_parser=structured_source_parser,
        structured_source_parser_binding=(
            {
                "workerSha256": hashlib.sha256(b"fake-source-parser").hexdigest(),
                "pypdfVersion": "6.14.2",
                "sandboxPolicy": "windows-appcontainer-job-no-network-v1",
                **(
                    {
                        "ffmpegSha256": hashlib.sha256(b"fake-ffmpeg").hexdigest(),
                        "ffprobeSha256": hashlib.sha256(b"fake-ffprobe").hexdigest(),
                    }
                    if media_tools
                    else {}
                ),
            }
            if structured_source_parser is not None
            else None
        ),
    )
    project = runtime.create_project(
        audience=audience(),
        idempotency_key="project-1",
        learning_contract={
            "purpose": "Remember the most useful ideas",
            "targetBehavior": "Recall and apply them without seeing the source",
        },
    )
    return resources, runtime, project


def test_pdf_parser_remains_available_when_media_tools_are_absent(
    tmp_path: Path,
) -> None:
    _resources, runtime, _project = environment(
        tmp_path,
        structured_source_parser=lambda **_request: {},
        media_tools=False,
    )

    assert runtime.capabilities()["sourceAdapters"]["pdfTextLayer"] == {
        "available": True,
        "supportTier": "B",
        "blockerCode": None,
    }
    assert runtime.capabilities()["sourceAdapters"]["embeddedMediaTranscript"] == {
        "available": False,
        "supportTier": "B",
        "blockerCode": "SOURCE_PARSER_NOT_AVAILABLE",
        "requiresEmbeddedSubtitle": True,
    }


def input_ref(
    resources: ServiceResourceRuntime,
    path: Path,
    *,
    request_id: str,
) -> dict:
    kind = "directory" if path.is_dir() else "file"
    constraints = (
        {
            "actions": ["enumerate", "read"],
            "maxDepth": 8,
            "maxEntries": 64,
            "maxTotalBytes": 4 * 1024 * 1024,
        }
        if kind == "directory"
        else {"actions": ["read"], "maxBytes": max(1, path.stat().st_size)}
    )
    grant = resources.issue_local_grant(
        audience=audience(),
        grant_request_id=request_id,
        raw_path=path.resolve(),
        kind=kind,
        constraints=constraints,
        attestation_ref="gesture-" + request_id,
    )
    field = "directoryResourceRef" if kind == "directory" else "fileResourceRef"
    return {
        "schemaVersion": 1,
        "kind": kind,
        field: grant["resourceRef"],
        "displayName": grant["displayName"],
        "resourceRevisionDigest": grant["resourceRevisionDigest"],
        "constraints": grant["constraints"],
        "expiresAt": grant["expiresAt"],
    }


def register(runtime: StudyRuntime, project: dict, ref: dict) -> dict:
    return runtime.register_inputs(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=1,
        idempotency_key="register-1",
        input_refs=[ref],
    )


def inspect(
    runtime: StudyRuntime, project: dict, registration: dict, *, key="inspect-1"
):
    return runtime.start_source_inspection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=2,
        idempotency_key=key,
        source_handles=[registration["sources"][0]["sourceHandle"]],
    )


def test_text_inspection_publishes_structured_nodes_without_returning_source_text(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.md").resolve()
    source_text = "# Reliable learning\n\nRecall first, then check the answer."
    source.write_text(source_text, encoding="utf-8")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="text")
    )

    result = inspect(runtime, project, registration)

    assert result["projectRevision"] == 3
    assert result["artifactStage"] == "sources_ready"
    assert result["nextAction"] == "discover_candidates"
    assert result["completeness"] == {
        "state": "complete",
        "expectedSources": 1,
        "processedSources": 1,
        "omittedSources": 0,
        "reasonCodes": [],
    }
    assert result["sources"][0]["supportTier"] == "A"
    assert result["sources"][0]["contentNodeCount"] == 2
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert source_text not in serialized
    assert str(source) not in serialized
    assert registration["sources"][0]["sourceHandle"] not in serialized

    project_after = runtime.get_project(project["projectId"], audience())
    assert project_after["workflow"]["primaryActionId"] == "discover_candidates"
    representation_ref = next(
        value
        for value in project_after["latestArtifactRefs"]
        if value["artifactId"].startswith("representation_")
    )
    representation = runtime.artifacts.verify_ref(representation_ref, audience())
    assert representation["payloadSchema"] == "study.source-representation"
    assert (
        runtime.artifacts.read_blob(
            representation["payload"]["plainTextBlobRef"]
        ).decode("utf-8")
        == source_text
    )
    assert all("text" not in node for node in representation["payload"]["contentNodes"])


def test_subtitle_inspection_preserves_cue_timing(tmp_path: Path) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.srt").resolve()
    source.write_text(
        "1\n00:00:01,000 --> 00:00:02,250\nActions speak louder than words.\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\nUse it in context.\n",
        encoding="utf-8",
    )
    registration = register(
        runtime, project, input_ref(resources, source, request_id="subtitle")
    )

    result = inspect(runtime, project, registration)
    assert result["sources"][0]["supportTier"] == "A"
    project_after = runtime.get_project(project["projectId"], audience())
    representation_ref = next(
        value
        for value in project_after["latestArtifactRefs"]
        if value["artifactId"].startswith("representation_")
    )
    payload = runtime.artifacts.verify_ref(representation_ref, audience())["payload"]
    nodes = payload["contentNodes"]
    assert [
        (node["locator"]["startMs"], node["locator"]["endMs"]) for node in nodes
    ] == [
        (1000, 2250),
        (3000, 4000),
    ]


def test_directory_inspection_declares_unsupported_members_instead_of_hiding_them(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "course").resolve()
    source.mkdir()
    (source / "lesson.txt").write_text("A complete text lesson.", encoding="utf-8")
    (source / "slides.pdf").write_bytes(b"%PDF-1.7\nnot parsed in this milestone")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="directory")
    )

    result = inspect(runtime, project, registration)

    row = result["sources"][0]
    assert row["supportTier"] == "B"
    assert row["status"] == "conditional"
    assert row["completeness"]["expectedUnits"] == 2
    assert row["completeness"]["processedUnits"] == 1
    assert row["completeness"]["omittedCount"] == 1
    assert "SOURCE_PARSER_NOT_AVAILABLE" in row["issueCodes"]
    assert result["nextAction"] == "discover_candidates"
    serialized = json.dumps(result, ensure_ascii=False)
    assert str(source) not in serialized
    assert "slides.pdf" not in serialized


def test_unsupported_source_is_blocked_and_keeps_resolution_as_next_action(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "document.pdf").resolve()
    source.write_bytes(b"%PDF-1.7\nfixture")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="pdf")
    )

    result = inspect(runtime, project, registration)

    assert result["completeness"]["state"] == "blocked"
    assert result["completeness"]["processedSources"] == 0
    assert result["sources"][0]["supportTier"] == "C"
    assert result["sources"][0]["issueCodes"] == ["SOURCE_PARSER_NOT_AVAILABLE"]
    assert result["sources"][0]["recommendedRoutes"] == []
    assert result["nextAction"] == "resolve_issue"
    assert (
        runtime.get_project(project["projectId"], audience())["workflow"][
            "primaryActionId"
        ]
        == "resolve_issue"
    )


def test_pdf_text_layer_is_bounded_structured_and_path_free(tmp_path: Path) -> None:
    calls = []

    def parse_pdf(**request):
        materialized_root = tmp_path / "fake-parser-workspace"
        materialized_root.mkdir(exist_ok=True)
        materialized_path = materialized_root / "source.pdf"
        receipt = request["materialize"](materialized_path)
        calls.append(
            {
                key: value
                for key, value in request.items()
                if key != "materialize"
            }
        )
        assert receipt == {
            "sha256": hashlib.sha256(
                b"%PDF-1.7\nverified fixture"
            ).hexdigest(),
            "sizeBytes": len(b"%PDF-1.7\nverified fixture"),
            "path": str(materialized_path),
        }
        assert materialized_path.read_bytes() == b"%PDF-1.7\nverified fixture"
        return {
            "schema": "study.source-parser-result",
            "schemaVersion": 1,
            "kind": "pdf",
            "status": "conditional",
            "parser": {"name": "pypdf", "version": "6.14.2"},
            "pageCount": 2,
            "pages": [
                {
                    "pageNumber": 1,
                    "text": "Reliable learning\n\nRecall first, then verify.",
                    "characterAnomalyCount": 0,
                    "imageObjectCount": 0,
                    "textTruncated": False,
                },
                {
                    "pageNumber": 2,
                    "text": "Apply the idea in a new context.",
                    "characterAnomalyCount": 0,
                    "imageObjectCount": 1,
                    "textTruncated": False,
                },
            ],
            "omittedPageCount": 0,
            "omittedPages": [],
            "issueCodes": [
                "SOURCE_PDF_IMAGES_OMITTED",
                "SOURCE_PDF_LAYOUT_PARTIAL",
            ],
        }

    resources, runtime, project = environment(
        tmp_path, structured_source_parser=parse_pdf
    )
    assert runtime.capabilities()["sourceAdapters"]["pdfTextLayer"] == {
        "available": True,
        "supportTier": "B",
        "blockerCode": None,
    }
    source = (tmp_path / "lesson.pdf").resolve()
    source.write_bytes(b"%PDF-1.7\nverified fixture")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="pdf-text-layer")
    )

    result = inspect(runtime, project, registration)

    assert result["sources"][0]["status"] == "conditional"
    assert result["sources"][0]["supportTier"] == "B"
    assert result["sources"][0]["contentNodeCount"] == 3
    assert result["sources"][0]["issueCodes"] == [
        "SOURCE_PDF_IMAGES_OMITTED",
        "SOURCE_PDF_LAYOUT_PARTIAL",
    ]
    assert calls == [
        {
            "source_type": "pdf",
            "source_sha256": hashlib.sha256(
                b"%PDF-1.7\nverified fixture"
            ).hexdigest(),
            "source_size_bytes": len(b"%PDF-1.7\nverified fixture"),
            "maximum_text_bytes": 8 * 1024 * 1024,
            "maximum_execution_seconds": 60.0,
        }
    ]
    project_after = runtime.get_project(project["projectId"], audience())
    representation_ref = next(
        value
        for value in project_after["latestArtifactRefs"]
        if value["artifactId"].startswith("representation_")
    )
    representation = runtime.artifacts.verify_ref(representation_ref, audience())[
        "payload"
    ]
    assert representation["kind"] == "pdf_text_layer"
    assert representation["extractor"] == {
        "component": "source-parser-worker",
        "name": "pypdf",
        "version": "6.14.2",
    }
    assert [node["attributes"]["pageNumber"] for node in representation["contentNodes"]] == [
        1,
        1,
        2,
    ]
    assert [node["locator"]["pageNumber"] for node in representation["contentNodes"]] == [
        1,
        1,
        2,
    ]
    assert result["sources"][0]["completeness"]["omittedCount"] == 0
    public = json.dumps(result, ensure_ascii=False)
    assert str(source) not in public
    assert "Reliable learning" not in public


def test_pdf_parser_result_fails_closed_when_schema_is_not_exact(tmp_path: Path) -> None:
    def invalid_parser(**_request):
        return {
            "schema": "study.source-parser-result",
            "schemaVersion": 1,
            "kind": "pdf",
            "status": "conditional",
            "parser": {"name": "pypdf", "version": "6.14.2"},
            "pageCount": 1,
            "pages": [],
            "omittedPageCount": 0,
            "omittedPages": [],
            "issueCodes": ["SOURCE_PDF_LAYOUT_PARTIAL"],
            "unexpected": "must be rejected",
        }

    resources, runtime, project = environment(
        tmp_path, structured_source_parser=invalid_parser
    )
    source = (tmp_path / "invalid-result.pdf").resolve()
    source.write_bytes(b"%PDF-1.7\nfixture")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="pdf-invalid-result")
    )

    with pytest.raises(StudyRuntimeError) as failed:
        inspect(runtime, project, registration)
    assert failed.value.code == "SOURCE_PARSER_RESULT_INVALID"


def test_pdf_parser_execution_failure_becomes_a_completed_blocked_inspection(
    tmp_path: Path,
) -> None:
    def failed_parser(**_request):
        raise StructuredSourceParserError("SOURCE_PARSER_TIMEOUT")

    resources, runtime, project = environment(
        tmp_path, structured_source_parser=failed_parser
    )
    source = (tmp_path / "timeout.pdf").resolve()
    source.write_bytes(b"%PDF-1.7\nfixture")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="pdf-timeout")
    )

    result = inspect(runtime, project, registration)

    assert result["completeness"]["state"] == "blocked"
    assert result["sources"][0]["issueCodes"] == ["SOURCE_PARSER_TIMEOUT"]
    assert runtime.tasks.get_task(result["taskId"], audience())["state"] == "succeeded"


@pytest.mark.parametrize(
    "contradiction",
    [
        "omission_overlap",
        "blocked_with_text",
        "unavailable_with_text",
        "image_issue_missing",
        "truncation_issue_missing",
    ],
)
def test_pdf_parser_relational_contradictions_fail_closed(
    tmp_path: Path,
    contradiction: str,
) -> None:
    result = {
        "schema": "study.source-parser-result",
        "schemaVersion": 1,
        "kind": "pdf",
        "status": "conditional",
        "parser": {"name": "pypdf", "version": "6.14.2"},
        "pageCount": 1,
        "pages": [
            {
                "pageNumber": 1,
                "text": "Verified text",
                "characterAnomalyCount": 0,
                "imageObjectCount": 0,
                "textTruncated": False,
            }
        ],
        "omittedPageCount": 0,
        "omittedPages": [],
        "issueCodes": ["SOURCE_PDF_LAYOUT_PARTIAL"],
    }
    if contradiction == "omission_overlap":
        result["omittedPageCount"] = 1
        result["omittedPages"] = [1]
    elif contradiction == "blocked_with_text":
        result["status"] = "blocked"
    elif contradiction == "unavailable_with_text":
        result["status"] = "blocked"
        result["parser"] = {"name": "pypdf", "version": "unavailable"}
        result["issueCodes"] = ["SOURCE_PDF_PARSER_UNAVAILABLE"]
    elif contradiction == "image_issue_missing":
        result["pages"][0]["imageObjectCount"] = 1
    else:
        result["pages"][0]["textTruncated"] = True

    _resources, runtime, _project = environment(
        tmp_path,
        structured_source_parser=lambda **_request: result,
    )
    blob_ref = runtime.artifacts.put_blob(b"%PDF fixture", media_type="application/pdf")

    with pytest.raises(SourceInspectionError) as failed:
        runtime.source_inspection._read_pdf_source(
            source_id="source-invalid",
            blob_ref=blob_ref,
        )

    assert failed.value.code == "SOURCE_PARSER_RESULT_INVALID"


def test_video_embedded_transcript_preserves_timing_and_media_summary(
    tmp_path: Path,
) -> None:
    calls = []

    def parse_media(**request):
        materialized = tmp_path / "media-parser" / "source.media"
        materialized.parent.mkdir()
        request["materialize"](materialized)
        calls.append(
            {key: value for key, value in request.items() if key != "materialize"}
        )
        return {
            "schema": "study.source-parser-result",
            "schemaVersion": 1,
            "kind": "video",
            "status": "conditional",
            "parser": {"name": "ffmpeg-suite", "version": "sha256-bound"},
            "media": {
                "durationMs": 4000,
                "audioStreamCount": 1,
                "videoStreamCount": 1,
                "subtitleStreamCount": 1,
            },
            "transcript": {
                "format": "webvtt",
                "text": (
                    "WEBVTT\n\n"
                    "00:00:01.000 --> 00:00:02.000\nActions speak louder.\n\n"
                    "00:00:03.000 --> 00:00:04.000\nUse it in context.\n"
                ),
                "language": "eng",
                "streamIndex": 2,
            },
            "issueCodes": ["SOURCE_MEDIA_EMBEDDED_TRANSCRIPT_EXTRACTED"],
        }

    resources, runtime, project = environment(
        tmp_path,
        structured_source_parser=parse_media,
    )
    source = (tmp_path / "lesson.mp4").resolve()
    source.write_bytes(b"verified media fixture")
    registration = register(
        runtime,
        project,
        input_ref(resources, source, request_id="video-transcript"),
    )

    result = inspect(runtime, project, registration)

    assert result["sources"][0]["sourceType"] == "video"
    assert result["sources"][0]["supportTier"] == "B"
    assert result["sources"][0]["contentNodeCount"] == 2
    assert calls == [
        {
            "source_type": "video",
            "source_sha256": hashlib.sha256(b"verified media fixture").hexdigest(),
            "source_size_bytes": len(b"verified media fixture"),
            "maximum_text_bytes": 8 * 1024 * 1024,
            "maximum_execution_seconds": 180.0,
        }
    ]
    project_after = runtime.get_project(project["projectId"], audience())
    representation_ref = next(
        value
        for value in project_after["latestArtifactRefs"]
        if value["artifactId"].startswith("representation_")
    )
    payload = runtime.artifacts.verify_ref(representation_ref, audience())["payload"]
    assert payload["kind"] == "media_transcript"
    assert payload["mediaSummary"]["durationMs"] == 4000
    assert [
        (node["locator"]["startMs"], node["locator"]["endMs"])
        for node in payload["contentNodes"]
    ] == [(1000, 2000), (3000, 4000)]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "Actions speak louder" not in serialized
    assert str(source) not in serialized


def test_audio_without_embedded_transcript_completes_as_explicit_blocker(
    tmp_path: Path,
) -> None:
    def parse_media(**_request):
        return {
            "schema": "study.source-parser-result",
            "schemaVersion": 1,
            "kind": "audio",
            "status": "blocked",
            "parser": {"name": "ffmpeg-suite", "version": "sha256-bound"},
            "media": {
                "durationMs": 5000,
                "audioStreamCount": 1,
                "videoStreamCount": 0,
                "subtitleStreamCount": 0,
            },
            "transcript": None,
            "issueCodes": ["SOURCE_MEDIA_TRANSCRIPT_NOT_AVAILABLE"],
        }

    resources, runtime, project = environment(
        tmp_path,
        structured_source_parser=parse_media,
    )
    source = (tmp_path / "lesson.mp3").resolve()
    source.write_bytes(b"verified audio fixture")
    registration = register(
        runtime,
        project,
        input_ref(resources, source, request_id="audio-no-transcript"),
    )

    result = inspect(runtime, project, registration)

    assert result["completeness"]["state"] == "blocked"
    assert result["sources"][0]["issueCodes"] == [
        "SOURCE_MEDIA_TRANSCRIPT_NOT_AVAILABLE"
    ]
    assert runtime.tasks.get_task(result["taskId"], audience())["state"] == "succeeded"


@pytest.mark.parametrize(
    "contradiction",
    [
        "conditional_without_transcript",
        "conditional_without_subtitle_stream",
        "conditional_with_failure_issue",
        "blocked_with_transcript",
        "blocked_without_issue",
        "missing_transcript_with_subtitle_stream",
        "unsupported_subtitle_without_stream",
        "known_duration_marked_unknown",
        "unknown_duration_not_declared",
    ],
)
def test_media_parser_result_fails_closed_on_relational_contradictions(
    tmp_path: Path,
    contradiction: str,
) -> None:
    def contradictory_parser(**_request):
        result = {
            "schema": "study.source-parser-result",
            "schemaVersion": 1,
            "kind": "video",
            "status": "conditional",
            "parser": {"name": "ffmpeg-suite", "version": "sha256-bound"},
            "media": {
                "durationMs": 4000,
                "audioStreamCount": 1,
                "videoStreamCount": 1,
                "subtitleStreamCount": 1,
            },
            "transcript": {
                "format": "webvtt",
                "text": "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nVerify this.\n",
                "language": "eng",
                "streamIndex": 2,
            },
            "issueCodes": ["SOURCE_MEDIA_EMBEDDED_TRANSCRIPT_EXTRACTED"],
        }
        if contradiction == "conditional_without_transcript":
            result["transcript"] = None
        elif contradiction == "conditional_without_subtitle_stream":
            result["media"]["subtitleStreamCount"] = 0
        elif contradiction == "conditional_with_failure_issue":
            result["issueCodes"] = [
                "SOURCE_MEDIA_EMBEDDED_TRANSCRIPT_EXTRACTED",
                "SOURCE_MEDIA_PROBE_FAILED",
            ]
        elif contradiction == "blocked_with_transcript":
            result["status"] = "blocked"
        elif contradiction == "blocked_without_issue":
            result["status"] = "blocked"
            result["transcript"] = None
            result["issueCodes"] = []
        elif contradiction == "missing_transcript_with_subtitle_stream":
            result["status"] = "blocked"
            result["transcript"] = None
            result["issueCodes"] = ["SOURCE_MEDIA_TRANSCRIPT_NOT_AVAILABLE"]
        elif contradiction == "unsupported_subtitle_without_stream":
            result["status"] = "blocked"
            result["transcript"] = None
            result["media"]["subtitleStreamCount"] = 0
            result["issueCodes"] = ["SOURCE_MEDIA_SUBTITLE_CODEC_UNSUPPORTED"]
        elif contradiction == "known_duration_marked_unknown":
            result["issueCodes"] = [
                "SOURCE_MEDIA_DURATION_UNKNOWN",
                "SOURCE_MEDIA_EMBEDDED_TRANSCRIPT_EXTRACTED",
            ]
        elif contradiction == "unknown_duration_not_declared":
            result["media"]["durationMs"] = None
        return result

    resources, runtime, project = environment(
        tmp_path,
        structured_source_parser=contradictory_parser,
    )
    source = (tmp_path / f"{contradiction}.mp4").resolve()
    source.write_bytes(b"contradictory media fixture")
    registration = register(
        runtime,
        project,
        input_ref(resources, source, request_id=contradiction),
    )

    with pytest.raises(StudyRuntimeError) as failed:
        inspect(runtime, project, registration)
    assert failed.value.code == "SOURCE_PARSER_RESULT_INVALID"


def test_inspection_retry_is_idempotent_and_reissues_the_summary_handle(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("stable inspection", encoding="utf-8")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="retry")
    )

    first = inspect(runtime, project, registration, key="same-inspection")
    second = inspect(runtime, project, registration, key="same-inspection")

    assert second["projectRevision"] == first["projectRevision"] == 3
    assert second["taskId"] == first["taskId"]
    assert second["inspectionHandle"] != first["inspectionHandle"]
    assert runtime.artifacts.resolve(
        second["inspectionHandle"], audience()
    ) == runtime.artifacts.resolve(first["inspectionHandle"], audience())


def test_inspection_recovers_after_artifacts_publish_before_project_commit(
    tmp_path: Path, monkeypatch
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("recover the inspection", encoding="utf-8")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="recover")
    )
    original_commit = runtime.projects.commit_artifact_stage
    calls = 0

    def interrupt_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProjectRegistryError(
                "PROJECT_COMMIT_INTERRUPTED", "simulated interruption"
            )
        return original_commit(**kwargs)

    monkeypatch.setattr(runtime.projects, "commit_artifact_stage", interrupt_once)
    with pytest.raises(StudyRuntimeError) as interrupted:
        inspect(runtime, project, registration, key="recover-inspection")
    assert interrupted.value.code == "PROJECT_COMMIT_INTERRUPTED"

    recovered = inspect(runtime, project, registration, key="recover-inspection")
    assert recovered["projectRevision"] == 3
    assert recovered["completeness"]["processedSources"] == 1


def test_inspection_rejects_cross_session_and_non_source_handles(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("scoped", encoding="utf-8")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="scope")
    )

    with pytest.raises(StudyRuntimeError):
        runtime.start_source_inspection(
            audience=audience(session_id="other-session"),
            project_id=project["projectId"],
            expected_project_revision=2,
            idempotency_key="wrong-session",
            source_handles=[registration["sources"][0]["sourceHandle"]],
        )

    inspection = inspect(runtime, project, registration)
    with pytest.raises(StudyRuntimeError) as wrong_kind:
        runtime.start_source_inspection(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=3,
            idempotency_key="wrong-kind",
            source_handles=[inspection["inspectionHandle"]],
        )
    assert wrong_kind.value.code == "SOURCE_INSPECTION_INVALID"


def test_html_inspection_excludes_script_content_from_plain_text_blob(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.html").resolve()
    source.write_text(
        "<h1>Visible lesson</h1><script>steal_private_data()</script><p>Recall this.</p>",
        encoding="utf-8",
    )
    registration = register(
        runtime, project, input_ref(resources, source, request_id="html")
    )

    result = inspect(runtime, project, registration)
    assert result["sources"][0]["supportTier"] == "B"
    project_after = runtime.get_project(project["projectId"], audience())
    representation_ref = next(
        value
        for value in project_after["latestArtifactRefs"]
        if value["artifactId"].startswith("representation_")
    )
    representation = runtime.artifacts.verify_ref(representation_ref, audience())[
        "payload"
    ]
    plain = runtime.artifacts.read_blob(representation["plainTextBlobRef"]).decode(
        "utf-8"
    )
    assert "Visible lesson" in plain
    assert "Recall this" in plain
    assert "steal_private_data" not in plain


def test_get_inspection_reads_existing_artifacts_without_starting_a_new_task(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("read the existing inspection", encoding="utf-8")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="get-inspection")
    )
    created = inspect(runtime, project, registration)

    loaded = runtime.get_source_inspection(
        audience=audience(), inspection_handle=created["inspectionHandle"]
    )

    assert loaded["projectId"] == created["projectId"]
    assert loaded["projectRevision"] == created["projectRevision"]
    assert loaded["taskId"] == created["taskId"]
    assert loaded["completeness"] == created["completeness"]
    assert loaded["sources"] == created["sources"]


def test_inspection_fails_closed_when_registered_blob_is_tampered(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("tamper evidence", encoding="utf-8")
    registration = register(
        runtime, project, input_ref(resources, source, request_id="tamper")
    )
    source_envelope = runtime.artifacts.resolve(
        registration["sources"][0]["sourceHandle"], audience()
    )
    blob_ref = source_envelope["payload"]["representations"][0]["blobRef"]
    runtime.artifacts._blob_path(blob_ref["sha256"]).write_bytes(
        b"x" * blob_ref["sizeBytes"]
    )

    with pytest.raises(StudyRuntimeError) as corrupted:
        inspect(runtime, project, registration, key="tampered-inspection")
    assert corrupted.value.code == "ARTIFACT_BLOB_MISMATCH"


def test_synchronous_inspection_refuses_oversized_text_instead_of_blocking(
    tmp_path: Path,
) -> None:
    _, runtime, _ = environment(tmp_path)
    blob = runtime.artifacts.put_blob(b"0123456789", media_type="text/plain")

    result = runtime.source_inspection._read_text_source(
        source_id="source_test",
        source_type="text",
        blob_ref=blob,
        maximum_bytes=4,
    )

    assert result["status"] == "blocked"
    assert result["supportTier"] == "C"
    assert result["issueRefs"] == ["SOURCE_ASYNC_INSPECTION_REQUIRED"]
