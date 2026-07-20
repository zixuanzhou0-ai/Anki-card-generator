from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from card_service.plugin_release_trust import (
    SIGNATURE_FILE_NAME,
    PluginReleaseTrustError,
    PluginReleaseTrustPolicy,
    build_plugin_release_signing_request,
    enforce_plugin_release_rollback_floor,
    plugin_release_signature_message,
    verify_plugin_release_signature,
    write_plugin_release_signing_request,
)
from card_service.runtime_manifest import canonical_bytes
from card_service.runtime_trust import encode_base64url
from tests.test_plugin_bundle import PLUGIN_VERSION, build


ROOT = Path(__file__).resolve().parents[1]
TEST_NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
TEST_KEY = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"plugin-release-test-key-v1").digest()
)
TEST_PUBLIC_KEY = TEST_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)


def write_policy(
    root: Path,
    *,
    key: Ed25519PrivateKey = TEST_KEY,
    sequence: int = 1,
    minimum_version: str = "0.1.0",
    key_status: str = "active",
    revoked_versions: list[str] | None = None,
    revoked_manifests: list[str] | None = None,
) -> tuple[Path, PluginReleaseTrustPolicy]:
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    value = {
        "schemaVersion": 1,
        "authority": "anki-study-agent.release",
        "sequence": sequence,
        "minimumPluginVersion": minimum_version,
        "maximumSignatureLifetimeSeconds": 31_536_000,
        "keys": [
            {
                "keyId": "release-2026",
                "keyEpoch": 1,
                "publicKey": encode_base64url(public_key),
                "publicKeySha256": hashlib.sha256(public_key).hexdigest(),
                "status": key_status,
            }
        ],
        "revokedPluginVersions": revoked_versions or [],
        "revokedManifestSha256": revoked_manifests or [],
    }
    path = (root / f"publisher-trust-{sequence}.json").resolve()
    path.write_bytes(canonical_bytes(value))
    return path, PluginReleaseTrustPolicy.load(path)


def request_for(
    bundle_root: Path, policy: PluginReleaseTrustPolicy
) -> dict[str, object]:
    return build_plugin_release_signing_request(
        (bundle_root / "release-package-v1.json").resolve(),
        trust_policy=policy,
        key_id="release-2026",
        key_epoch=1,
        signed_at="2026-07-18T00:00:00Z",
        expires_at="2027-07-18T00:00:00Z",
    )


def write_signature(
    root: Path,
    request: dict[str, object],
    *,
    key: Ed25519PrivateKey = TEST_KEY,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    unsigned = dict(request["unsignedEnvelope"])
    signature = dict(unsigned)
    signature["signature"] = encode_base64url(
        key.sign(plugin_release_signature_message(unsigned))
    )
    path = (root / SIGNATURE_FILE_NAME).resolve()
    path.write_bytes(canonical_bytes(signature))
    return path


def verify(root: Path, policy: PluginReleaseTrustPolicy, signature: Path):
    request = request_for(root, policy)
    unsigned = request["unsignedEnvelope"]
    return verify_plugin_release_signature(
        signature,
        manifest_sha256=unsigned["manifestSha256"],
        package_id=unsigned["packageId"],
        plugin_version=unsigned["pluginVersion"],
        trust_policy=policy,
        now=TEST_NOW,
    )


def test_public_only_signing_request_is_deterministic_and_signature_verifies(
    tmp_path: Path,
) -> None:
    bundle = build(tmp_path / "bundle")
    _, policy = write_policy(tmp_path)
    first = request_for(bundle.root, policy)
    second = request_for(bundle.root, policy)

    assert first == second
    assert first["privateKeyRead"] is False
    assert first["networkUsed"] is False
    assert (
        first["signingMessageSha256"]
        == hashlib.sha256(
            plugin_release_signature_message(first["unsignedEnvelope"])
        ).hexdigest()
    )
    output = (tmp_path / "request.json").resolve()
    digest = write_plugin_release_signing_request(output, first)
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert json.loads(output.read_bytes()) == first

    signature = write_signature(tmp_path, first)
    verified = verify(bundle.root, policy, signature)
    assert verified.authority == "anki-study-agent.release"
    assert verified.package_id == "anki-study-agent-plugin"
    assert verified.plugin_version == PLUGIN_VERSION
    assert verified.manifest_sha256 == first["unsignedEnvelope"]["manifestSha256"]


def test_signing_request_never_overwrites_and_rejects_invalid_windows(
    tmp_path: Path,
) -> None:
    bundle = build(tmp_path / "bundle")
    _, policy = write_policy(tmp_path)
    request = request_for(bundle.root, policy)
    output = (tmp_path / "request.json").resolve()
    output.write_text("keep", encoding="utf-8")

    with pytest.raises(PluginReleaseTrustError) as existing:
        write_plugin_release_signing_request(output, request)
    assert existing.value.code == "PLUGIN_RELEASE_SIGNING_REQUEST_EXISTS"
    assert output.read_text(encoding="utf-8") == "keep"

    with pytest.raises(PluginReleaseTrustError) as lifetime:
        build_plugin_release_signing_request(
            (bundle.root / "release-package-v1.json").resolve(),
            trust_policy=policy,
            key_id="release-2026",
            key_epoch=1,
            signed_at="2026-07-18T00:00:00Z",
            expires_at="2027-07-19T00:00:01Z",
        )
    assert lifetime.value.code == "PLUGIN_RELEASE_SIGNATURE_WINDOW_INVALID"

    with pytest.raises(PluginReleaseTrustError) as alternate_stream:
        write_plugin_release_signing_request(
            (tmp_path / "request.json:payload").resolve(),
            request,
        )
    assert alternate_stream.value.code == "PLUGIN_RELEASE_SIGNING_REQUEST_PATH_INVALID"


def test_signature_rejects_forgery_revocation_expiry_and_manifest_change(
    tmp_path: Path,
) -> None:
    bundle = build(tmp_path / "bundle")
    _, policy = write_policy(tmp_path)
    request = request_for(bundle.root, policy)
    signature = write_signature(tmp_path, request)

    forged_key = Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"forged-plugin-release-key").digest()
    )
    _, forged_policy = write_policy(tmp_path, key=forged_key, sequence=2)
    with pytest.raises(PluginReleaseTrustError) as forged:
        verify(bundle.root, forged_policy, signature)
    assert forged.value.code == "PLUGIN_RELEASE_SIGNATURE_INVALID"

    _, revoked_policy = write_policy(tmp_path, key_status="revoked", sequence=3)
    with pytest.raises(PluginReleaseTrustError) as revoked:
        verify(bundle.root, revoked_policy, signature)
    assert revoked.value.code == "PLUGIN_RELEASE_SIGNING_KEY_REVOKED"

    unsigned = dict(request["unsignedEnvelope"])
    unsigned["expiresAt"] = "2026-07-18T11:59:59Z"
    expired_request = dict(request)
    expired_request["unsignedEnvelope"] = unsigned
    expired = write_signature(tmp_path / "expired", expired_request)
    with pytest.raises(PluginReleaseTrustError) as outside_window:
        verify_plugin_release_signature(
            expired,
            manifest_sha256=unsigned["manifestSha256"],
            package_id=unsigned["packageId"],
            plugin_version=unsigned["pluginVersion"],
            trust_policy=policy,
            now=TEST_NOW,
        )
    assert outside_window.value.code == "PLUGIN_RELEASE_SIGNATURE_EXPIRED"

    with pytest.raises(PluginReleaseTrustError) as changed:
        verify_plugin_release_signature(
            signature,
            manifest_sha256="f" * 64,
            package_id="anki-study-agent-plugin",
            plugin_version="0.1.0",
            trust_policy=policy,
            now=TEST_NOW,
        )
    assert changed.value.code == "PLUGIN_RELEASE_SIGNATURE_INVALID"


def test_policy_rejects_noncanonical_and_revoked_release(tmp_path: Path) -> None:
    bundle = build(tmp_path / "bundle")
    manifest_digest = hashlib.sha256(
        (bundle.root / "release-package-v1.json").read_bytes()
    ).hexdigest()
    path, _ = write_policy(tmp_path, revoked_manifests=[manifest_digest])
    policy = PluginReleaseTrustPolicy.load(path)
    with pytest.raises(PluginReleaseTrustError) as revoked:
        request_for(bundle.root, policy)
    assert revoked.value.code == "PLUGIN_RELEASE_VERSION_REVOKED"

    value = json.loads(path.read_bytes())
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    with pytest.raises(PluginReleaseTrustError) as noncanonical:
        PluginReleaseTrustPolicy.load(path)
    assert noncanonical.value.code == "PLUGIN_RELEASE_TRUST_POLICY_NONCANONICAL"


def test_plugin_release_floor_blocks_policy_fork_rollback_and_version_reuse(
    tmp_path: Path,
) -> None:
    bundle = build(tmp_path / "current")
    _, policy = write_policy(tmp_path, sequence=2)
    request = request_for(bundle.root, policy)
    signature_path = write_signature(tmp_path, request)
    current = verify(bundle.root, policy, signature_path)
    state_root = (tmp_path / "state").resolve()
    enforce_plugin_release_rollback_floor(
        state_root,
        plugin_version=current.plugin_version,
        manifest_sha256=current.manifest_sha256,
        signature=current,
    )

    fork_path, fork_policy = write_policy(
        tmp_path, sequence=2, revoked_versions=["9.9.9"]
    )
    assert fork_path.is_file()
    fork_request = request_for(bundle.root, fork_policy)
    fork_signature = write_signature(tmp_path / "fork", fork_request)
    fork = verify(bundle.root, fork_policy, fork_signature)
    with pytest.raises(PluginReleaseTrustError) as policy_fork:
        enforce_plugin_release_rollback_floor(
            state_root,
            plugin_version=fork.plugin_version,
            manifest_sha256=fork.manifest_sha256,
            signature=fork,
        )
    assert policy_fork.value.code == "PLUGIN_RELEASE_TRUST_POLICY_FORK"

    older_path, older_policy = write_policy(tmp_path, sequence=1)
    assert older_path.is_file()
    older_request = request_for(bundle.root, older_policy)
    older_signature = write_signature(tmp_path / "older", older_request)
    older = verify(bundle.root, older_policy, older_signature)
    with pytest.raises(PluginReleaseTrustError) as rollback:
        enforce_plugin_release_rollback_floor(
            state_root,
            plugin_version=older.plugin_version,
            manifest_sha256=older.manifest_sha256,
            signature=older,
        )
    assert rollback.value.code == "PLUGIN_RELEASE_TRUST_POLICY_ROLLBACK"

    with pytest.raises(PluginReleaseTrustError) as reused:
        enforce_plugin_release_rollback_floor(
            state_root,
            plugin_version=current.plugin_version,
            manifest_sha256="e" * 64,
            signature=current,
        )
    assert reused.value.code == "PLUGIN_RELEASE_VERSION_REUSED"


def test_cli_writes_request_without_signing_or_installing(tmp_path: Path) -> None:
    bundle = build(tmp_path / "bundle")
    policy_path, _ = write_policy(tmp_path)
    output = (tmp_path / "request.json").resolve()
    process = subprocess.run(
        [
            sys.executable,
            "scripts/create_plugin_release_signing_request.py",
            "--candidate",
            str(bundle.root),
            "--trust-policy",
            str(policy_path),
            "--key-id",
            "release-2026",
            "--key-epoch",
            "1",
            "--signed-at",
            "2026-07-18T00:00:00Z",
            "--expires-at",
            "2027-07-18T00:00:00Z",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["privateKeyRead"] is False
    assert result["networkUsed"] is False
    assert result["signatureCreated"] is False
    assert result["installable"] is False
    assert output.is_file()

    inside = bundle.root / "release-signing-request-v1.json"
    blocked = subprocess.run(
        [
            sys.executable,
            "scripts/create_plugin_release_signing_request.py",
            "--candidate",
            str(bundle.root),
            "--trust-policy",
            str(policy_path),
            "--key-id",
            "release-2026",
            "--key-epoch",
            "1",
            "--signed-at",
            "2026-07-18T00:00:00Z",
            "--expires-at",
            "2027-07-18T00:00:00Z",
            "--output",
            str(inside),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert blocked.returncode != 0
    assert "PLUGIN_RELEASE_SIGNING_REQUEST_PATH_INVALID" in blocked.stderr
    assert not inside.exists()


def test_verify_cli_uses_external_policy_and_keeps_candidate_passive(
    tmp_path: Path,
) -> None:
    bundle = build(tmp_path / "bundle")
    policy_path, policy = write_policy(tmp_path)
    request = request_for(bundle.root, policy)
    signature = write_signature(tmp_path, request)
    process = subprocess.run(
        [
            sys.executable,
            "scripts/verify_plugin_release_signature.py",
            "--candidate",
            str(bundle.root),
            "--trust-policy",
            str(policy_path),
            "--signature",
            str(signature),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["signatureVerified"] is True
    assert result["payloadVerified"] is True
    assert result["privateKeyRead"] is False
    assert result["networkUsed"] is False
    assert result["installable"] is False


def test_ephemeral_probe_signature_persists_no_private_key(tmp_path: Path) -> None:
    bundle = build(tmp_path / "bundle")
    output = (tmp_path / "probe").resolve()
    process = subprocess.run(
        [
            sys.executable,
            "scripts/create_ephemeral_plugin_probe_signature.py",
            "--candidate",
            str(bundle.root),
            "--output",
            str(output),
            "--lifetime-seconds",
            "600",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["signatureVerified"] is True
    assert result["privateKeyPersisted"] is False
    assert result["networkUsed"] is False
    assert result["probeOnly"] is True
    assert result["installable"] is False
    files = sorted(path.name for path in output.iterdir())
    assert files == [
        "plugin-publisher-trust-v1.json",
        "release-package-v1.sig.json",
        "release-signing-request-v1.json",
    ]
    corpus = b"\n".join(path.read_bytes() for path in output.iterdir())
    assert b"PRIVATE KEY" not in corpus
