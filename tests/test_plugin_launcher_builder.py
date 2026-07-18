from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from card_service.plugin_launcher_builder import (
    LAUNCHER_BINARY_NAME,
    PluginLauncherBuildError,
    build_plugin_launcher,
)
from tests.test_runtime_package import trust_policy_path, write_package


ROOT = Path(__file__).resolve().parents[1]


def test_launcher_builder_pins_signed_inputs_and_builds_offline_atomically(tmp_path: Path) -> None:
    runtime = (tmp_path / "runtime").resolve()
    write_package(runtime)
    trust = trust_policy_path(runtime).resolve()
    output = (tmp_path / "output" / "anki-study-agent.exe").resolve()
    output.parent.mkdir()
    observed: dict[str, object] = {}

    def fake_runner(command, **kwargs):
        observed["command"] = list(command)
        observed["environment"] = kwargs["env"]
        target = Path(command[command.index("--target-dir") + 1])
        binary = target / "release" / LAUNCHER_BINARY_NAME
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"signed-launcher-fixture")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = build_plugin_launcher(
        runtime_root=runtime,
        runtime_trust_policy=trust,
        output=output,
        cargo_manifest=(ROOT / "runtime-tools" / "anki-study-launcher" / "Cargo.toml").resolve(),
        runner=fake_runner,
    )

    assert output.read_bytes() == b"signed-launcher-fixture"
    assert result.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert result.runtime_manifest_sha256 == hashlib.sha256(
        (runtime / "runtime-package-v1.json").read_bytes()
    ).hexdigest()
    assert result.runtime_trust_policy_sha256 == hashlib.sha256(trust.read_bytes()).hexdigest()
    assert "--locked" in observed["command"]
    assert "--offline" in observed["command"]
    environment = observed["environment"]
    assert environment["CARGO_NET_OFFLINE"] == "true"
    assert environment["CARGO_INCREMENTAL"] == "0"
    assert environment["SOURCE_DATE_EPOCH"] == "0"
    if __import__("os").name == "nt":
        assert environment["RUSTFLAGS"] == "-C link-arg=/Brepro"
    assert environment["ANKI_STUDY_RUNTIME_MANIFEST_SHA256"] == result.runtime_manifest_sha256
    assert environment["ANKI_STUDY_RUNTIME_TRUST_POLICY_SHA256"] == result.runtime_trust_policy_sha256


def test_launcher_builder_rejects_existing_output_and_invalid_trust(tmp_path: Path) -> None:
    runtime = (tmp_path / "runtime").resolve()
    write_package(runtime)
    trust = trust_policy_path(runtime).resolve()
    output = (tmp_path / "launcher.exe").resolve()
    output.write_bytes(b"keep")
    with pytest.raises(PluginLauncherBuildError) as existing:
        build_plugin_launcher(
            runtime_root=runtime,
            runtime_trust_policy=trust,
            output=output,
            cargo_manifest=(ROOT / "runtime-tools" / "anki-study-launcher" / "Cargo.toml").resolve(),
        )
    assert existing.value.code == "PLUGIN_LAUNCHER_OUTPUT_EXISTS"
    assert output.read_bytes() == b"keep"

    output.unlink()
    trust.write_bytes(b"{}")
    with pytest.raises(PluginLauncherBuildError) as invalid:
        build_plugin_launcher(
            runtime_root=runtime,
            runtime_trust_policy=trust,
            output=output,
            cargo_manifest=(ROOT / "runtime-tools" / "anki-study-launcher" / "Cargo.toml").resolve(),
        )
    assert invalid.value.code == "PLUGIN_LAUNCHER_INPUT_INVALID"
    assert not output.exists()


def test_launcher_builder_does_not_overwrite_output_created_during_build(tmp_path: Path) -> None:
    runtime = (tmp_path / "runtime").resolve()
    write_package(runtime)
    trust = trust_policy_path(runtime).resolve()
    output = (tmp_path / "output" / "anki-study-agent.exe").resolve()
    output.parent.mkdir()

    def racing_runner(command, **_kwargs):
        target = Path(command[command.index("--target-dir") + 1])
        binary = target / "release" / LAUNCHER_BINARY_NAME
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"trusted-launcher")
        output.write_bytes(b"concurrent-owner")
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(PluginLauncherBuildError) as collision:
        build_plugin_launcher(
            runtime_root=runtime,
            runtime_trust_policy=trust,
            output=output,
            cargo_manifest=(ROOT / "runtime-tools" / "anki-study-launcher" / "Cargo.toml").resolve(),
            runner=racing_runner,
        )

    assert collision.value.code == "PLUGIN_LAUNCHER_OUTPUT_EXISTS"
    assert output.read_bytes() == b"concurrent-owner"
