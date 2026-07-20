from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from card_service.plugin_bundle import LAUNCHER_PATH
from card_service.plugin_install_bundle import (
    INSTALL_SIGNATURE_DOMAIN,
    INSTALL_SIGNATURE_NAME,
    MCP_CONFIG_PATH,
    PluginInstallBundle,
    PluginInstallError,
    _build_plugin_install_candidate,
    _finalize_plugin_install_package,
    build_plugin_install_candidate,
    build_plugin_install_signing_request,
    build_result_json,
    finalize_result_json,
    finalize_plugin_install_package,
    plugin_install_signature_message,
    verify_plugin_install_signature,
    write_plugin_install_signing_request,
)
from card_service.plugin_release_trust import PluginReleaseTrustPolicy
from card_service.runtime_manifest import canonical_bytes, file_sha256
from card_service.runtime_trust import encode_base64url
from card_service.windows_authenticode import AuthenticodePolicy, VerifiedAuthenticode
from tests.test_plugin_bundle import PLUGIN_ROOT, launcher, signed_runtime
from tests.test_plugin_release_trust import (
    TEST_KEY,
    write_policy as write_publisher_policy,
)
from tests.test_windows_authenticode import (
    certificate,
    write_policy as write_authenticode_policy,
)


ROOT = Path(__file__).resolve().parents[1]
TEST_NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


def stable_plugin(root: Path) -> Path:
    plugin = (root / "stable-plugin").resolve()
    if not plugin.exists():
        shutil.copytree(PLUGIN_ROOT, plugin)
        manifest_path = plugin / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "0.1.0"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return plugin


def fake_authenticode(path: Path, policy: AuthenticodePolicy) -> VerifiedAuthenticode:
    signer = next(
        value for value in policy.signers.values() if value.status == "active"
    )
    return VerifiedAuthenticode(
        file_sha256=file_sha256(path),
        certificate_sha256=signer.certificate_sha256,
        subject=signer.subject,
        verified_at="2026-07-18T12:00:00Z",
        timestamp_present=True,
        policy_sequence=policy.sequence,
        policy_digest=policy.digest,
    )


def install_inputs(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    runtime, runtime_trust = signed_runtime(root)
    publisher_path, publisher = write_publisher_policy(root)
    der, subject = certificate()
    authenticode_path = write_authenticode_policy(root, der, subject)
    return runtime, runtime_trust, publisher_path, publisher, authenticode_path


def build(root: Path, name: str = "candidate"):
    runtime, runtime_trust, publisher_path, publisher, authenticode_path = (
        install_inputs(root)
    )
    result = _build_plugin_install_candidate(
        (root / name).resolve(),
        version="0.1.0",
        created_at="2026-07-18T00:00:00Z",
        plugin_root=stable_plugin(root),
        launcher=launcher(root),
        runtime_root=runtime,
        runtime_trust_policy=runtime_trust,
        plugin_publisher_trust_policy=publisher_path,
        launcher_authenticode_policy=authenticode_path,
        authenticode_verifier=fake_authenticode,
    )
    candidate = PluginInstallBundle(
        result.root,
        publisher_policy=publisher,
        require_signature=False,
    )
    return result, candidate, publisher_path, publisher, authenticode_path


def signing_request(
    candidate: PluginInstallBundle, publisher: PluginReleaseTrustPolicy
):
    return build_plugin_install_signing_request(
        candidate.root,
        trust_policy=publisher,
        key_id="release-2026",
        key_epoch=1,
        signed_at="2026-07-18T00:00:00Z",
        expires_at="2027-07-18T00:00:00Z",
    )


def write_signature(
    root: Path, request: dict[str, object], *, domain: str = INSTALL_SIGNATURE_DOMAIN
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    unsigned = dict(request["unsignedEnvelope"])
    unsigned["domain"] = domain
    value = dict(unsigned)
    value["signature"] = encode_base64url(
        TEST_KEY.sign(plugin_install_signature_message(unsigned))
    )
    path = (root / INSTALL_SIGNATURE_NAME).resolve()
    path.write_bytes(canonical_bytes(value))
    return path


def test_install_candidate_is_deterministic_mcp_wired_and_never_installable(
    tmp_path: Path,
) -> None:
    runtime, runtime_trust, publisher_path, publisher, authenticode_path = (
        install_inputs(tmp_path)
    )
    executable = launcher(tmp_path)
    first = _build_plugin_install_candidate(
        (tmp_path / "candidate-a").resolve(),
        version="0.1.0",
        created_at="2026-07-18T00:00:00Z",
        plugin_root=stable_plugin(tmp_path),
        launcher=executable,
        runtime_root=runtime,
        runtime_trust_policy=runtime_trust,
        plugin_publisher_trust_policy=publisher_path,
        launcher_authenticode_policy=authenticode_path,
        authenticode_verifier=fake_authenticode,
    )
    second = _build_plugin_install_candidate(
        (tmp_path / "candidate-b").resolve(),
        version="0.1.0",
        created_at="2026-07-18T00:00:00Z",
        plugin_root=stable_plugin(tmp_path),
        launcher=executable,
        runtime_root=runtime,
        runtime_trust_policy=runtime_trust,
        plugin_publisher_trust_policy=publisher_path,
        launcher_authenticode_policy=authenticode_path,
        authenticode_verifier=fake_authenticode,
    )

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
    candidate = PluginInstallBundle(
        first.root, publisher_policy=publisher, require_signature=False
    )
    assert candidate.signature is None
    assert not (first.root / INSTALL_SIGNATURE_NAME).exists()
    assert json.loads((first.root / MCP_CONFIG_PATH).read_bytes()) == {
        "mcpServers": {
            "anki-study-agent": {
                "command": "./server/launcher/anki-study-agent.exe",
                "args": ["--stdio"],
                "cwd": ".",
                "tool_timeout_sec": 900,
            }
        }
    }
    plugin = json.loads((first.root / ".codex-plugin" / "plugin.json").read_bytes())
    assert plugin["mcpServers"] == "./.mcp.json"
    summary = json.loads(build_result_json(first))
    assert summary["mcpDeclared"] is True
    assert summary["authenticodeVerified"] is True
    assert summary["outerSignatureVerified"] is False
    assert summary["nativeVerificationPassed"] is False
    assert summary["installable"] is False


def test_public_only_signing_request_uses_install_domain_and_verifies(
    tmp_path: Path,
) -> None:
    _, candidate, _, publisher, _ = build(tmp_path)
    first = signing_request(candidate, publisher)
    second = signing_request(candidate, publisher)
    assert first == second
    assert first["domain"] == INSTALL_SIGNATURE_DOMAIN
    assert first["privateKeyRead"] is False
    assert first["networkUsed"] is False
    output = (tmp_path / "install-signing-request.json").resolve()
    digest = write_plugin_install_signing_request(output, first)
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()

    signature = write_signature(tmp_path / "detached", first)
    verified = verify_plugin_install_signature(
        signature,
        manifest_sha256=candidate.digest,
        package_id="anki-study-agent-plugin",
        plugin_version="0.1.0",
        trust_policy=publisher,
        now=TEST_NOW,
    )
    assert verified.manifest_sha256 == candidate.digest
    assert verified.trust_policy_digest == publisher.digest


def test_finalizer_requires_all_gates_and_publishes_atomically(tmp_path: Path) -> None:
    _, candidate, publisher_path, publisher, authenticode_path = build(tmp_path)
    request = signing_request(candidate, publisher)
    signature = write_signature(tmp_path / "detached", request)
    calls: list[Path] = []

    def native(root: Path) -> None:
        calls.append(root)
        PluginInstallBundle(
            root, publisher_policy=publisher, require_signature=True, now=TEST_NOW
        )

    output = (tmp_path / "final").resolve()
    result = _finalize_plugin_install_package(
        output,
        candidate_root=candidate.root,
        signature_path=signature,
        plugin_publisher_trust_policy=publisher_path,
        launcher_authenticode_policy=authenticode_path,
        now=TEST_NOW,
        authenticode_verifier=fake_authenticode,
        native_install_verifier=native,
    )

    assert output.is_dir()
    assert len(calls) == 2
    assert calls[0] != output
    assert calls[1] == output
    assert result.native_verification is True
    assert result.signature.manifest_sha256 == candidate.digest
    summary = json.loads(finalize_result_json(result))
    assert summary["outerSignatureVerified"] is True
    assert summary["publisherKeyManaged"] is True
    assert summary["nativeVerificationPassed"] is True
    assert summary["installable"] is True


def test_tamper_cross_domain_and_native_failure_are_fail_closed(tmp_path: Path) -> None:
    _, candidate, publisher_path, publisher, authenticode_path = build(tmp_path)
    request = signing_request(candidate, publisher)
    wrong_domain = write_signature(
        tmp_path / "wrong", request, domain="study.plugin-release-manifest.v1"
    )
    with pytest.raises(PluginInstallError) as domain:
        verify_plugin_install_signature(
            wrong_domain,
            manifest_sha256=candidate.digest,
            package_id="anki-study-agent-plugin",
            plugin_version="0.1.0",
            trust_policy=publisher,
            now=TEST_NOW,
        )
    assert domain.value.code == "PLUGIN_INSTALL_SIGNATURE_INVALID"

    signature = write_signature(tmp_path / "detached", request)
    output = (tmp_path / "rejected").resolve()

    def reject(_root: Path) -> None:
        raise PluginInstallError(
            "PLUGIN_INSTALL_NATIVE_VERIFICATION_FAILED", "rejected"
        )

    with pytest.raises(PluginInstallError) as native:
        _finalize_plugin_install_package(
            output,
            candidate_root=candidate.root,
            signature_path=signature,
            plugin_publisher_trust_policy=publisher_path,
            launcher_authenticode_policy=authenticode_path,
            now=TEST_NOW,
            authenticode_verifier=fake_authenticode,
            native_install_verifier=reject,
        )
    assert native.value.code == "PLUGIN_INSTALL_NATIVE_VERIFICATION_FAILED"
    assert not output.exists()
    assert not (candidate.root / INSTALL_SIGNATURE_NAME).exists()

    (candidate.root / LAUNCHER_PATH).write_bytes(b"tampered")
    with pytest.raises(PluginInstallError) as changed:
        PluginInstallBundle(
            candidate.root, publisher_policy=publisher, require_signature=False
        )
    assert changed.value.code == "PLUGIN_INSTALL_RESOURCE_CHANGED"


@pytest.mark.skipif(
    sys.platform != "win32", reason="Authenticode CLI gate is Windows-only"
)
def test_real_candidate_cli_rejects_unsigned_launcher(tmp_path: Path) -> None:
    runtime, runtime_trust, publisher_path, _, authenticode_path = install_inputs(
        tmp_path
    )
    output = (tmp_path / "must-not-exist").resolve()
    process = subprocess.run(
        [
            sys.executable,
            "scripts/build_plugin_install_candidate.py",
            "--output",
            str(output),
            "--version",
            "0.1.0",
            "--created-at",
            "2026-07-18T00:00:00Z",
            "--plugin-root",
            str(stable_plugin(tmp_path)),
            "--launcher",
            str(launcher(tmp_path)),
            "--runtime-root",
            str(runtime),
            "--runtime-trust-policy",
            str(runtime_trust),
            "--plugin-publisher-trust-policy",
            str(publisher_path),
            "--launcher-authenticode-policy",
            str(authenticode_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode != 0
    assert "PLUGIN_INSTALL_AUTHENTICODE_INVALID" in process.stderr
    assert not output.exists()


def test_public_install_apis_do_not_expose_test_verifier_or_clock_injection() -> None:
    build_parameters = inspect.signature(build_plugin_install_candidate).parameters
    finalize_parameters = inspect.signature(finalize_plugin_install_package).parameters

    assert "authenticode_verifier" not in build_parameters
    assert "authenticode_verifier" not in finalize_parameters
    assert "native_install_verifier" not in finalize_parameters
    assert "now" not in finalize_parameters
