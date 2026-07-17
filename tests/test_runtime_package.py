from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from card_service.runtime_manifest import canonical_bytes
from card_service.runtime_package import (
    ManagedRuntimePackage,
    RuntimePackageError,
    current_runtime_platform,
)
from card_service.runtime_trust import (
    SIGNATURE_ALGORITHM,
    SIGNATURE_DOMAIN,
    SIGNATURE_FILE_NAME,
    RuntimePackageTrustPolicy,
    RuntimeTrustError,
    encode_base64url,
    enforce_runtime_rollback_floor,
    signature_message,
)
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
TEST_NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
TEST_KEY = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"runtime-package-test-key-v1").digest())
TEST_PUBLIC_KEY = TEST_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)


def trust_policy_path(root: Path) -> Path:
    return root.parent / f"{root.name}-publisher-trust-v1.json"


def write_trust_policy(
    root: Path,
    *,
    sequence: int = 1,
    minimum_version: str = "0.1.0-dev",
    key_status: str = "active",
    revoked_versions: list[str] | None = None,
    public_key: bytes = TEST_PUBLIC_KEY,
) -> RuntimePackageTrustPolicy:
    value = {
        "schemaVersion": 1,
        "authority": "anki-study-test-publisher",
        "sequence": sequence,
        "minimumRuntimeVersion": minimum_version,
        "keys": [
            {
                "keyId": "test-release-key",
                "keyEpoch": 1,
                "publicKey": encode_base64url(public_key),
                "publicKeySha256": hashlib.sha256(public_key).hexdigest(),
                "status": key_status,
            }
        ],
        "revokedPackageVersions": revoked_versions or [],
    }
    path = trust_policy_path(root)
    path.write_bytes(canonical_bytes(value))
    return RuntimePackageTrustPolicy.load(path.resolve())


def sign_package(
    root: Path,
    *,
    private_key: Ed25519PrivateKey = TEST_KEY,
    signed_at: str = "2026-01-01T00:00:00Z",
    expires_at: str = "2030-01-01T00:00:00Z",
) -> None:
    manifest_sha256 = hashlib.sha256((root / "runtime-package-v1.json").read_bytes()).hexdigest()
    unsigned = {
        "schemaVersion": 1,
        "algorithm": SIGNATURE_ALGORITHM,
        "domain": SIGNATURE_DOMAIN,
        "authority": "anki-study-test-publisher",
        "keyId": "test-release-key",
        "keyEpoch": 1,
        "signedAt": signed_at,
        "expiresAt": expires_at,
        "manifestSha256": manifest_sha256,
    }
    value = dict(unsigned)
    value["signature"] = encode_base64url(private_key.sign(signature_message(unsigned)))
    (root / SIGNATURE_FILE_NAME).write_bytes(canonical_bytes(value))


def write_package(
    root: Path,
    *,
    canonical: bool = True,
    version: str = "0.1.0-dev",
) -> dict[str, object]:
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
    sbom_path = root / "metadata" / "SBOM.spdx.json"
    sbom_path.parent.mkdir(parents=True, exist_ok=True)
    sbom = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {
            "created": "2026-07-17T00:00:00Z",
            "creators": ["Organization: Codex Study test fixture"],
        },
        "dataLicense": "CC0-1.0",
        "documentNamespace": "urn:uuid:63ed3cc4-2a35-46f4-9cd8-125fd6d1cbef",
        "files": [
            {
                "SPDXID": f"SPDXRef-File-{index}",
                "checksums": [{"algorithm": "SHA256", "checksumValue": str(resource["sha256"])}],
                "fileName": f"./{resource['relativePath']}",
            }
            for index, resource in enumerate(
                sorted(resources, key=lambda item: str(item["relativePath"]).encode("utf-8"))
            )
        ],
        "name": f"anki-study-managed-runtime-{version}",
        "spdxVersion": "SPDX-2.3",
    }
    sbom_source = canonical_bytes(sbom)
    sbom_path.write_bytes(sbom_source)
    resources.append(
        {
            "resourceId": "metadata:sbom-spdx",
            "relativePath": "metadata/SBOM.spdx.json",
            "size": len(sbom_source),
            "sha256": hashlib.sha256(sbom_source).hexdigest(),
        }
    )
    resources.sort(key=lambda resource: str(resource["resourceId"]).encode("utf-8"))
    value: dict[str, object] = {
        "schemaVersion": 1,
        "packageId": "anki-study-managed-runtime",
        "version": version,
        "compatibility": {
            "cardServiceApiVersion": 1,
            "minimumCardServiceVersion": "0.1.0",
            "platform": current_runtime_platform(),
        },
        "sbom": {"format": "SPDX-2.3", "resourceId": "metadata:sbom-spdx"},
        "resources": resources,
    }
    manifest = root / "runtime-package-v1.json"
    manifest.write_bytes(canonical_bytes(value) if canonical else json.dumps(value, indent=2).encode())
    sign_package(root)
    write_trust_policy(root)
    return value


def load_package(root: Path, *, trust_policy: RuntimePackageTrustPolicy | None = None) -> ManagedRuntimePackage:
    return ManagedRuntimePackage(
        root,
        trust_policy=trust_policy or RuntimePackageTrustPolicy.load(trust_policy_path(root).resolve()),
        require_signature=True,
        now=TEST_NOW,
    )


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
    package = load_package(root)
    assert package.resource_path("legacy-worker:entry") == root / "worker" / "anki_worker.py"
    assert package.public_summary() == {
        "schemaVersion": 1,
        "packageId": "anki-study-managed-runtime",
        "version": "0.1.0-dev",
        "digest": f"sha256:{package.digest}",
        "resourceCount": 7,
        "pathDisclosure": False,
        "signatureVerified": True,
        "sbomVerified": True,
        "publisherAuthority": "anki-study-test-publisher",
        "trustSequence": 1,
        "signedAt": "2026-01-01T00:00:00Z",
        "expiresAt": "2030-01-01T00:00:00Z",
        "trustPolicyDigest": f"sha256:{RuntimePackageTrustPolicy.load(trust_policy_path(root).resolve()).digest}",
        "complete": False,
    }

    noncanonical_root = (tmp_path / "noncanonical").resolve()
    write_package(noncanonical_root, canonical=False)
    with pytest.raises(RuntimePackageError) as noncanonical:
        load_package(noncanonical_root)
    assert noncanonical.value.code == "RUNTIME_PACKAGE_MANIFEST_NONCANONICAL"

    unlisted_root = (tmp_path / "unlisted").resolve()
    write_package(unlisted_root)
    (unlisted_root / "shadow-config.ini").write_text("unsafe", encoding="utf-8")
    with pytest.raises(RuntimePackageError) as unlisted:
        load_package(unlisted_root)
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
    sign_package(root)
    with pytest.raises(RuntimePackageError) as caught:
        load_package(root)
    assert caught.value.code == code


def test_runtime_package_rejects_unpinned_forged_expired_and_revoked_signatures(tmp_path: Path) -> None:
    root = (tmp_path / "runtime").resolve()
    write_package(root)
    with pytest.raises(RuntimePackageError) as unpinned:
        ManagedRuntimePackage(root, require_signature=True, now=TEST_NOW)
    assert unpinned.value.code == "RUNTIME_TRUST_POLICY_REQUIRED"

    forged_key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"forged-key").digest())
    forged_public_key = forged_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    forged_policy = write_trust_policy(root, public_key=forged_public_key)
    with pytest.raises(RuntimePackageError) as forged:
        load_package(root, trust_policy=forged_policy)
    assert forged.value.code == "RUNTIME_PACKAGE_SIGNATURE_INVALID"

    revoked_policy = write_trust_policy(root, key_status="revoked")
    with pytest.raises(RuntimePackageError) as revoked:
        load_package(root, trust_policy=revoked_policy)
    assert revoked.value.code == "RUNTIME_SIGNING_KEY_REVOKED"

    active_policy = write_trust_policy(root)
    sign_package(root, expires_at="2026-07-17T11:59:59Z")
    with pytest.raises(RuntimePackageError) as expired:
        load_package(root, trust_policy=active_policy)
    assert expired.value.code == "RUNTIME_PACKAGE_SIGNATURE_EXPIRED"


def test_runtime_package_rejects_revoked_or_below_floor_version(tmp_path: Path) -> None:
    root = (tmp_path / "runtime").resolve()
    write_package(root, version="0.1.0")
    below_floor = write_trust_policy(root, minimum_version="0.2.0")
    with pytest.raises(RuntimePackageError) as old:
        load_package(root, trust_policy=below_floor)
    assert old.value.code == "RUNTIME_PACKAGE_VERSION_REVOKED"

    revoked = write_trust_policy(root, minimum_version="0.1.0", revoked_versions=["0.1.0"])
    with pytest.raises(RuntimePackageError) as blocked:
        load_package(root, trust_policy=revoked)
    assert blocked.value.code == "RUNTIME_PACKAGE_VERSION_REVOKED"


def test_runtime_package_rejects_sbom_that_does_not_match_signed_resources(tmp_path: Path) -> None:
    root = (tmp_path / "runtime").resolve()
    manifest = write_package(root)
    sbom_path = root / "metadata" / "SBOM.spdx.json"
    sbom = json.loads(sbom_path.read_bytes())
    sbom["files"][0]["checksums"][0]["checksumValue"] = "0" * 64
    sbom_source = canonical_bytes(sbom)
    sbom_path.write_bytes(sbom_source)
    sbom_entry = next(
        item for item in manifest["resources"] if item["resourceId"] == "metadata:sbom-spdx"  # type: ignore[index]
    )
    sbom_entry["size"] = len(sbom_source)  # type: ignore[index]
    sbom_entry["sha256"] = hashlib.sha256(sbom_source).hexdigest()  # type: ignore[index]
    (root / "runtime-package-v1.json").write_bytes(canonical_bytes(manifest))
    sign_package(root)
    with pytest.raises(RuntimePackageError) as mismatch:
        load_package(root)
    assert mismatch.value.code == "RUNTIME_PACKAGE_SBOM_MISMATCH"


def test_runtime_trust_floor_rejects_policy_and_package_rollback(tmp_path: Path) -> None:
    current_root = (tmp_path / "runtime-current").resolve()
    write_package(current_root, version="0.2.0")
    current_policy = write_trust_policy(current_root, sequence=2, minimum_version="0.1.0")
    current = load_package(current_root, trust_policy=current_policy)
    assert current.signature is not None
    state_root = (tmp_path / "state").resolve()
    enforce_runtime_rollback_floor(
        state_root,
        package_version=current.version,
        manifest_sha256=current.digest,
        signature=current.signature,
    )

    forked_policy = write_trust_policy(
        current_root,
        sequence=2,
        minimum_version="0.1.0",
        revoked_versions=["9.9.9"],
    )
    forked = load_package(current_root, trust_policy=forked_policy)
    assert forked.signature is not None
    with pytest.raises(RuntimeTrustError) as policy_fork:
        enforce_runtime_rollback_floor(
            state_root,
            package_version=forked.version,
            manifest_sha256=forked.digest,
            signature=forked.signature,
        )
    assert policy_fork.value.code == "RUNTIME_TRUST_POLICY_FORK"

    old_policy = write_trust_policy(current_root, sequence=1, minimum_version="0.1.0")
    old_trust = load_package(current_root, trust_policy=old_policy)
    assert old_trust.signature is not None
    with pytest.raises(RuntimeTrustError) as policy_rollback:
        enforce_runtime_rollback_floor(
            state_root,
            package_version=old_trust.version,
            manifest_sha256=old_trust.digest,
            signature=old_trust.signature,
        )
    assert policy_rollback.value.code == "RUNTIME_TRUST_POLICY_ROLLBACK"

    previous_root = (tmp_path / "runtime-previous").resolve()
    write_package(previous_root, version="0.1.0")
    previous_policy = write_trust_policy(previous_root, sequence=2, minimum_version="0.1.0")
    previous = load_package(previous_root, trust_policy=previous_policy)
    assert previous.signature is not None
    with pytest.raises(RuntimeTrustError) as package_rollback:
        enforce_runtime_rollback_floor(
            state_root,
            package_version=previous.version,
            manifest_sha256=previous.digest,
            signature=previous.signature,
        )
    assert package_rollback.value.code == "RUNTIME_PACKAGE_ROLLBACK"


def test_card_service_package_mode_rejects_path_overrides_and_detects_runtime_mutation(tmp_path: Path) -> None:
    root = (tmp_path / "runtime").resolve()
    write_package(root)
    with pytest.raises(CardServiceError) as missing_trust:
        CardService(
            state_dir=(tmp_path / "missing-trust-state").resolve(),
            runtime_package=root,
        )
    assert missing_trust.value.code == "RUNTIME_TRUST_POLICY_REQUIRED"
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
                runtime_trust_policy=trust_policy_path(root).resolve(),
            )
        assert unhardened.value.code == "WINDOWS_RUNTIME_DACL_MISMATCH"
        harden_runtime_tree(root, runtime_sandbox_sid())
    card_service = CardService(
        state_dir=(tmp_path / "state").resolve(),
        runtime_package=root,
        runtime_trust_policy=trust_policy_path(root).resolve(),
        method_policies={"runtime.check_environment": MethodPolicy("check_env", 2)},
    )
    summary = card_service.capabilities()["runtimePackage"]
    assert summary["version"] == "0.1.0-dev"
    assert summary["signatureVerified"] is True
    assert summary["sbomVerified"] is True
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

    runtime_root = (tmp_path / "runtime").resolve()
    write_package(runtime_root)
    packaged_without_trust = subprocess.run(
        [
            sys.executable,
            "-m",
            "card_service",
            "--state-dir",
            str((tmp_path / "packaged-state").resolve()),
            "--runtime-package",
            str(runtime_root),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert packaged_without_trust.returncode == 2
    assert "--runtime-package requires --runtime-trust-policy" in packaged_without_trust.stderr
