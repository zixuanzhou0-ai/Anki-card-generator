from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from card_service.runtime_manifest import canonical_bytes
from card_service.runtime_package import ManagedRuntimePackage, RuntimePackageError
from card_service.service import CardService, CardServiceError, MethodPolicy
from card_service.windows_sandbox_acl import harden_runtime_tree, runtime_sandbox_sid


RESOURCE_FILES = {
    "managed-python:executable": "python/python.exe",
    "card-service:worker-bootstrap": "service/worker_bootstrap.py",
    "card-service:broker-client": "worker/acg/broker_client.py",
    "card-service:windows-restricted-launcher": "service/windows_restricted_launcher.py",
    "card-service:windows-sandbox-acl": "service/windows_sandbox_acl.py",
    "legacy-worker:entry": "worker/anki_worker.py",
}


def write_package(root: Path, *, canonical: bool = True) -> dict[str, object]:
    resources: list[dict[str, object]] = []
    for index, (resource_id, relative_path) in enumerate(RESOURCE_FILES.items()):
        path = root.joinpath(*relative_path.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        source = f"resource-{index}".encode()
        path.write_bytes(source)
        resources.append(
            {
                "resourceId": resource_id,
                "relativePath": relative_path,
                "size": len(source),
                "sha256": hashlib.sha256(source).hexdigest(),
            }
        )
    resources.sort(key=lambda resource: str(resource["resourceId"]).encode("utf-8"))
    value: dict[str, object] = {
        "schemaVersion": 1,
        "packageId": "anki-study-managed-runtime",
        "version": "0.1.0-dev",
        "resources": resources,
    }
    manifest = root / "runtime-package-v1.json"
    manifest.write_bytes(canonical_bytes(value) if canonical else json.dumps(value, indent=2).encode())
    return value


def wait_terminal(card_service: CardService, task_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        snapshot = card_service.get_task(task_id)
        assert snapshot is not None
        if snapshot["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("task did not finish")


def test_runtime_package_requires_canonical_root_contained_hashed_resources(tmp_path: Path) -> None:
    root = (tmp_path / "runtime").resolve()
    write_package(root)
    package = ManagedRuntimePackage(root)
    assert package.resource_path("legacy-worker:entry") == root / "worker" / "anki_worker.py"
    assert package.public_summary() == {
        "schemaVersion": 1,
        "packageId": "anki-study-managed-runtime",
        "version": "0.1.0-dev",
        "digest": f"sha256:{package.digest}",
        "resourceCount": 6,
        "pathDisclosure": False,
        "signatureVerified": False,
        "complete": False,
    }

    noncanonical_root = (tmp_path / "noncanonical").resolve()
    write_package(noncanonical_root, canonical=False)
    with pytest.raises(RuntimePackageError) as noncanonical:
        ManagedRuntimePackage(noncanonical_root)
    assert noncanonical.value.code == "RUNTIME_PACKAGE_MANIFEST_NONCANONICAL"

    unlisted_root = (tmp_path / "unlisted").resolve()
    write_package(unlisted_root)
    (unlisted_root / "shadow-config.ini").write_text("unsafe", encoding="utf-8")
    with pytest.raises(RuntimePackageError) as unlisted:
        ManagedRuntimePackage(unlisted_root)
    assert unlisted.value.code == "RUNTIME_PACKAGE_UNLISTED_RESOURCE"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda value: value["resources"].pop(), "RUNTIME_PACKAGE_RESOURCE_MISSING"),
        (
            lambda value: value["resources"].insert(1, dict(value["resources"][0])),
            "RUNTIME_PACKAGE_RESOURCE_INVALID",
        ),
        (
            lambda value: value["resources"][0].update({"relativePath": "../python.exe"}),
            "RUNTIME_PACKAGE_PATH_INVALID",
        ),
        (
            lambda value: value["resources"][1].update(
                {"relativePath": str(value["resources"][0]["relativePath"]).upper()}
            ),
            "RUNTIME_PACKAGE_PATH_COLLISION",
        ),
    ],
)
def test_runtime_package_rejects_missing_duplicate_escape_and_case_collision(
    tmp_path: Path,
    mutate: object,
    code: str,
) -> None:
    root = (tmp_path / code).resolve()
    value = write_package(root)
    mutate(value)  # type: ignore[operator]
    (root / "runtime-package-v1.json").write_bytes(canonical_bytes(value))
    with pytest.raises(RuntimePackageError) as caught:
        ManagedRuntimePackage(root)
    assert caught.value.code == code


def test_card_service_package_mode_rejects_path_overrides_and_detects_runtime_mutation(tmp_path: Path) -> None:
    root = (tmp_path / "runtime").resolve()
    write_package(root)
    with pytest.raises(CardServiceError) as conflict:
        CardService(
            state_dir=(tmp_path / "conflict-state").resolve(),
            runtime_package=root,
            python_path=Path(sys.executable).resolve(),
        )
    assert conflict.value.code == "RUNTIME_PACKAGE_CONFLICT"

    if os.name == "nt":
        with pytest.raises(CardServiceError) as unhardened:
            CardService(
                state_dir=(tmp_path / "unhardened-state").resolve(),
                runtime_package=root,
            )
        assert unhardened.value.code == "WINDOWS_RUNTIME_DACL_MISMATCH"
        harden_runtime_tree(root, runtime_sandbox_sid())
    card_service = CardService(
        state_dir=(tmp_path / "state").resolve(),
        runtime_package=root,
        method_policies={"runtime.check_environment": MethodPolicy("check_env", 2)},
    )
    summary = card_service.capabilities()["runtimePackage"]
    assert summary["version"] == "0.1.0-dev"
    assert summary["signatureVerified"] is False
    assert summary["complete"] is False
    assert card_service.capabilities()["processIsolation"]["runtimePackageDacl"] is (os.name == "nt")
    assert card_service.capabilities()["processIsolation"]["taskWorkspaceDacl"] is (os.name == "nt")
    assert card_service.capabilities()["processIsolation"]["appContainerOrRestrictedSidDacl"] is (os.name == "nt")
    assert card_service.capabilities()["processIsolation"]["forcedOutboundBroker"] is (os.name == "nt")

    card_service.worker_path.write_text("mutated", encoding="utf-8")
    started = card_service.start_task("runtime.check_environment", {})
    finished = wait_terminal(card_service, started["id"])
    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "RUNTIME_PACKAGE_RESOURCE_CHANGED"


def test_stdio_requires_explicit_packaged_or_development_runtime_mode(tmp_path: Path) -> None:
    process = subprocess.run(
        [sys.executable, "-m", "card_service", "--state-dir", str((tmp_path / "state").resolve())],
        cwd=str(Path(__file__).resolve().parents[1]),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert process.returncode == 2
    assert "--runtime-package" in process.stderr
    assert "--development-unpackaged-runtime" in process.stderr
