from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from card_service.plugin_bundle import (
    LAUNCHER_PATH,
    RELEASE_MANIFEST_NAME,
    PluginBundleError,
    PluginReleaseBundle,
    build_plugin_release_candidate,
)
from card_service.runtime_manifest import canonical_bytes
from card_service.windows_sandbox_acl import (
    FILE_GENERIC_READ_EXECUTE,
    apply_exact_dacl,
    current_user_sid,
)
from tests.test_runtime_package import trust_policy_path, write_package


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = (ROOT / "plugins" / "anki-study-agent").resolve()
PLUGIN_VERSION = json.loads(
    (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
)["version"]


def signed_runtime(root: Path) -> tuple[Path, Path]:
    runtime = (root / "runtime").resolve()
    write_package(runtime)
    return runtime, trust_policy_path(runtime).resolve()


def launcher(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    value = (root / "anki-study-agent.exe").resolve()
    value.write_bytes(b"pinned-native-launcher-fixture")
    return value


def build(tmp_path: Path, name: str = "candidate") -> PluginReleaseBundle:
    tmp_path.mkdir(parents=True, exist_ok=True)
    runtime, trust = signed_runtime(tmp_path)
    result = build_plugin_release_candidate(
        (tmp_path / name).resolve(),
        version=PLUGIN_VERSION,
        created_at="2026-07-18T00:00:00Z",
        plugin_root=PLUGIN_ROOT,
        launcher=launcher(tmp_path),
        runtime_root=runtime,
        runtime_trust_policy=trust,
    )
    assert result.manifest_sha256
    return PluginReleaseBundle(result.root)


def test_builder_is_deterministic_exact_and_explicitly_non_installable(
    tmp_path: Path,
) -> None:
    runtime, trust = signed_runtime(tmp_path)
    launcher_path = launcher(tmp_path)
    first = build_plugin_release_candidate(
        (tmp_path / "candidate-a").resolve(),
        version=PLUGIN_VERSION,
        created_at="2026-07-18T00:00:00Z",
        plugin_root=PLUGIN_ROOT,
        launcher=launcher_path,
        runtime_root=runtime,
        runtime_trust_policy=trust,
    )
    second = build_plugin_release_candidate(
        (tmp_path / "candidate-b").resolve(),
        version=PLUGIN_VERSION,
        created_at="2026-07-18T00:00:00Z",
        plugin_root=PLUGIN_ROOT,
        launcher=launcher_path,
        runtime_root=runtime,
        runtime_trust_policy=trust,
    )

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
    assert first.sbom_path.read_bytes() == second.sbom_path.read_bytes()
    bundle = PluginReleaseBundle(first.root)
    summary = bundle.public_summary()
    assert summary["runtimeSignatureVerified"] is True
    assert summary["sbomVerified"] is True
    assert summary["bundleDaclVerified"] is True
    assert summary["runtimeDaclVerified"] is True
    assert summary["installable"] is False
    assert summary["outerSignatureVerified"] is False
    assert summary["complete"] is False
    assert not (first.root / ".mcp.json").exists()
    assert not (first.root / ".app.json").exists()
    assert (first.root / LAUNCHER_PATH).read_bytes() == launcher_path.read_bytes()
    actual = {
        path.relative_to(first.root).as_posix()
        for path in first.root.rglob("*")
        if path.is_file()
    }
    listed = {str(entry["relativePath"]) for entry in bundle.value["resources"]} | {
        RELEASE_MANIFEST_NAME
    }
    assert actual == listed


def test_builder_rejects_mcp_or_app_declarations_before_output(
    tmp_path: Path,
) -> None:
    plugin = (tmp_path / "plugin").resolve()
    shutil.copytree(PLUGIN_ROOT, plugin)
    (plugin / ".mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
    runtime, trust = signed_runtime(tmp_path)
    output = (tmp_path / "candidate").resolve()

    with pytest.raises(PluginBundleError) as blocked:
        build_plugin_release_candidate(
            output,
            version=PLUGIN_VERSION,
            created_at="2026-07-18T00:00:00Z",
            plugin_root=plugin,
            launcher=launcher(tmp_path),
            runtime_root=runtime,
            runtime_trust_policy=trust,
        )

    assert blocked.value.code == "PLUGIN_BUNDLE_NOT_PASSIVE"
    assert not output.exists()

    (plugin / ".mcp.json").unlink()
    manifest_path = plugin / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["mcpServers"] = "./.mcp.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PluginBundleError) as declared:
        build_plugin_release_candidate(
            output,
            version=PLUGIN_VERSION,
            created_at="2026-07-18T00:00:00Z",
            plugin_root=plugin,
            launcher=launcher(tmp_path),
            runtime_root=runtime,
            runtime_trust_policy=trust,
        )
    assert declared.value.code == "PLUGIN_BUNDLE_NOT_PASSIVE"
    assert not output.exists()

    manifest.pop("mcpServers")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (plugin / "server").mkdir()
    with pytest.raises(PluginBundleError) as preassembled:
        build_plugin_release_candidate(
            output,
            version=PLUGIN_VERSION,
            created_at="2026-07-18T00:00:00Z",
            plugin_root=plugin,
            launcher=launcher(tmp_path),
            runtime_root=runtime,
            runtime_trust_policy=trust,
        )
    assert preassembled.value.code == "PLUGIN_BUNDLE_PATH_COLLISION"
    assert not output.exists()


def test_verifier_rejects_tamper_and_unlisted_files(tmp_path: Path) -> None:
    bundle = build(tmp_path)
    launcher_path = bundle.root / LAUNCHER_PATH
    launcher_path.write_bytes(b"tampered")
    with pytest.raises(PluginBundleError) as changed:
        PluginReleaseBundle(bundle.root)
    assert changed.value.code == "PLUGIN_BUNDLE_RESOURCE_CHANGED"

    bundle = build(tmp_path / "other")
    (bundle.root / "unlisted.txt").write_text("not listed", encoding="utf-8")
    with pytest.raises(PluginBundleError) as unlisted:
        PluginReleaseBundle(bundle.root)
    assert unlisted.value.code == "PLUGIN_BUNDLE_UNLISTED_RESOURCE"

    bundle = build(tmp_path / "state")
    manifest_path = bundle.root / RELEASE_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    manifest["releaseState"]["installable"] = True
    manifest_path.write_bytes(canonical_bytes(manifest))
    with pytest.raises(PluginBundleError) as installable:
        PluginReleaseBundle(bundle.root)
    assert installable.value.code == "PLUGIN_BUNDLE_RELEASE_STATE_INVALID"


def test_builder_preserves_existing_output(tmp_path: Path) -> None:
    runtime, trust = signed_runtime(tmp_path)
    output = (tmp_path / "candidate").resolve()
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(PluginBundleError) as existing:
        build_plugin_release_candidate(
            output,
            version=PLUGIN_VERSION,
            created_at="2026-07-18T00:00:00Z",
            plugin_root=PLUGIN_ROOT,
            launcher=launcher(tmp_path),
            runtime_root=runtime,
            runtime_trust_policy=trust,
        )

    assert existing.value.code == "PLUGIN_BUNDLE_OUTPUT_EXISTS"
    assert marker.read_text(encoding="utf-8") == "keep"


def test_verifier_rejects_outer_dacl_drift(tmp_path: Path) -> None:
    bundle = build(tmp_path)
    apply_exact_dacl(
        bundle.root / LAUNCHER_PATH,
        ((current_user_sid(), FILE_GENERIC_READ_EXECUTE),),
        inherit_to_children=False,
    )

    with pytest.raises(PluginBundleError) as mismatch:
        PluginReleaseBundle(bundle.root)

    assert mismatch.value.code == "PLUGIN_BUNDLE_DACL_MISMATCH"


def test_cli_builds_a_verified_passive_candidate(tmp_path: Path) -> None:
    runtime, trust = signed_runtime(tmp_path)
    output = (tmp_path / "candidate").resolve()
    process = subprocess.run(
        [
            sys.executable,
            "scripts/build_plugin_release_candidate.py",
            "--output",
            str(output),
            "--version",
            PLUGIN_VERSION,
            "--created-at",
            "2026-07-18T00:00:00Z",
            "--plugin-root",
            str(PLUGIN_ROOT),
            "--launcher",
            str(launcher(tmp_path)),
            "--runtime-root",
            str(runtime),
            "--runtime-trust-policy",
            str(trust),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["installable"] is False
    assert summary["mcpDeclared"] is False
    assert summary["outerSignatureVerified"] is False
    assert summary["publisherKeyManaged"] is False
    assert summary["bundleDaclVerified"] is True
    assert summary["runtimeDaclVerified"] is True
    assert summary["privateKeyRead"] is False
    assert summary["networkUsed"] is False
    PluginReleaseBundle(output)
