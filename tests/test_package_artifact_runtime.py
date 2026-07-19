from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from card_service.package_artifact_runtime import (
    PackageArtifactRuntime,
    PackageExportCancelled,
)
from card_service.study_runtime import StudyRuntimeError
from tests.test_card_artifact_runtime import generated_runtime
from tests.test_candidate_discovery_runtime import audience


def _worker():
    path = Path(__file__).resolve().parents[1] / "workers" / "anki_worker.py"
    name = "anki_worker_package_artifact_runtime_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RealExportExecutor:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = 0

    def __call__(self, project, progress, cancel_event):
        self.calls += 1
        if cancel_event.is_set():
            raise PackageExportCancelled("cancelled")
        output = self.root / f"worker-{self.calls}"
        output.mkdir(parents=True)
        progress({"percent": 10})
        result = _worker().handle_export(
            {"project": dict(project), "output_dir": str(output)}
        )
        progress({"percent": 90})
        return result


class BlockingExportExecutor:
    def __init__(self) -> None:
        self.started = threading.Event()

    def __call__(self, _project, _progress, cancel_event):
        self.started.set()
        assert cancel_event.wait(5)
        raise PackageExportCancelled("cancelled")


def _with_exporter(tmp_path: Path, executor):
    runtime, project, planned, listed, generated = generated_runtime(tmp_path)
    runtime.package_artifacts = PackageArtifactRuntime(
        root=(tmp_path / "package-runtime").resolve(),
        service_instance_id=runtime.service_instance_id,
        artifacts=runtime.artifacts,
        projects=runtime.projects,
        tasks=runtime.tasks,
        resources=runtime.resources,
        card_artifacts=runtime.card_artifacts,
        export_executor=executor,
    )
    return runtime, project, planned, listed, generated


def _output_ref(runtime, root: Path, *, request_id: str = "output-1"):
    root.mkdir()
    grant = runtime.resources.issue_local_grant(
        audience=audience(),
        grant_request_id=request_id,
        raw_path=root,
        kind="output_directory",
        constraints={
            "actions": ["create", "versioned"],
            "maxFiles": 1024,
            "maxTotalBytes": 32 * 1024 * 1024 * 1024,
        },
        attestation_ref="gesture-" + request_id,
        max_uses=16,
    )
    return {
        "schemaVersion": 1,
        "displayName": grant["displayName"],
        "resourceRevisionDigest": grant["resourceRevisionDigest"],
        "constraints": grant["constraints"],
        "expiresAt": grant["expiresAt"],
        "kind": "output_directory",
        "outputResourceRef": grant["resourceRef"],
    }


def _await(runtime, task_id: str, *, timeout: float = 120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = runtime.get_study_task(audience=audience(), task_id=task_id)
        if snapshot["state"] not in {"queued", "running", "cancelling"}:
            return snapshot
        time.sleep(0.05)
    raise AssertionError("APKG export task did not finish")


def test_export_publishes_verified_package_and_versioned_output(tmp_path) -> None:
    executor = RealExportExecutor(tmp_path / "worker-exports")
    runtime, project, _planned, _listed, generated = _with_exporter(tmp_path, executor)
    output = tmp_path / "delivery"
    output_ref = _output_ref(runtime, output)
    arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": generated["projectRevision"],
        "idempotency_key": "export-package-1",
        "project_artifact_handle": generated["projectArtifactHandle"],
        "output_ref": output_ref,
    }

    started = runtime.start_apkg_export(**arguments)
    assert started["intent"] == "export_apkg"
    assert started["nextAction"] == "poll_task"
    completed = _await(runtime, started["taskId"])

    assert completed["state"] == "succeeded"
    assert completed["progress"]["overallPercent"] == 100
    assert completed["result"] == {
        **completed["result"],
        "artifactStage": "apkg_ready",
        "projectRevision": generated["projectRevision"] + 1,
        "noteCount": 1,
        "cardCount": 1,
        "mediaCount": 0,
        "deliveryState": "written",
        "nextAction": "prepare_anki_import",
    }
    delivered = output / completed["result"]["fileName"]
    assert delivered.is_file()
    assert delivered.suffix == ".apkg"
    assert len(list(output.glob("*.apkg"))) == 1
    package_ref, package = runtime.artifacts.resolve_with_ref(
        completed["result"]["packageArtifactHandle"], audience()
    )
    assert package["payloadSchema"] == "study.package-artifact"
    assert package["payload"]["apkgSha256"] == completed["result"]["apkgSha256"]
    assert package["payload"]["apkgFileRef"].startswith("apkg_file_")
    assert package["payload"]["cardCount"] == 1
    assert package["payload"]["noteCount"] == 1
    assert package["payload"]["mediaCount"] == 0
    assert package["payload"]["frontTemplateSha256"]
    assert package["payload"]["backTemplateSha256"]
    assert package["payload"]["cssSha256"]
    assert any(
        parent["payloadSchema"] == "study.apkg-file" for parent in package["parents"]
    )
    assert (
        package_ref
        in runtime.get_project(project["projectId"], audience())["latestArtifactRefs"]
    )
    encoded = json.dumps(completed, ensure_ascii=False).casefold()
    for forbidden in (
        "apkg_path",
        "media_dir",
        "artifactref",
        "registryauthref",
        "inputfingerprint",
        str(tmp_path).casefold(),
    ):
        assert forbidden not in encoded

    repeated = runtime.start_apkg_export(**arguments)
    assert repeated["state"] == "succeeded"
    assert executor.calls == 1
    assert len(list(output.glob("*.apkg"))) == 1


def test_export_rejects_forged_output_ref_before_worker_call(tmp_path) -> None:
    executor = RealExportExecutor(tmp_path / "worker-exports")
    runtime, project, _planned, _listed, generated = _with_exporter(tmp_path, executor)
    output_ref = _output_ref(runtime, tmp_path / "delivery")
    output_ref["resourceRevisionDigest"] = "0" * 64

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.start_apkg_export(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=generated["projectRevision"],
            idempotency_key="forged-output",
            project_artifact_handle=generated["projectArtifactHandle"],
            output_ref=output_ref,
        )
    assert captured.value.code == "OUTPUT_NOT_WRITABLE"
    assert executor.calls == 0


def test_export_cancellation_reaches_terminal_cancelled_state(tmp_path) -> None:
    executor = BlockingExportExecutor()
    runtime, project, _planned, _listed, generated = _with_exporter(tmp_path, executor)
    started = runtime.start_apkg_export(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=generated["projectRevision"],
        idempotency_key="cancel-export",
        project_artifact_handle=generated["projectArtifactHandle"],
        output_ref=_output_ref(runtime, tmp_path / "delivery"),
    )
    assert executor.started.wait(2)

    cancelling = runtime.cancel_study_task(
        audience=audience(), task_id=started["taskId"]
    )
    assert cancelling["state"] == "cancelling"
    cancelled = _await(runtime, started["taskId"])
    assert cancelled["state"] == "cancelled"
    assert cancelled["nextAction"] == "export_apkg"
    assert not list((tmp_path / "delivery").glob("*.apkg"))
    assert (
        runtime.get_project(project["projectId"], audience())["workflow"][
            "artifactStage"
        ]
        == "cards_ready"
    )
