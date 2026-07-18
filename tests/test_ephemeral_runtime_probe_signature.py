from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from card_service.runtime_package import ManagedRuntimePackage
from card_service.runtime_trust import SIGNATURE_FILE_NAME, RuntimePackageTrustPolicy
from tests.test_runtime_package import write_package


ROOT = Path(__file__).resolve().parents[1]


def test_probe_signature_is_short_lived_verified_and_never_persists_a_private_key(tmp_path: Path) -> None:
    runtime = (tmp_path / "runtime").resolve()
    write_package(runtime)
    (runtime / SIGNATURE_FILE_NAME).unlink()
    trust = (tmp_path / "ephemeral-trust.json").resolve()
    process = subprocess.run(
        [
            sys.executable,
            "scripts/create_ephemeral_runtime_probe_signature.py",
            "--runtime-root",
            str(runtime),
            "--trust-policy",
            str(trust),
            "--valid-hours",
            "1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["ephemeralProbeOnly"] is True
    assert result["signatureVerified"] is True
    assert result["privateKeyPersisted"] is False
    serialized = (runtime / SIGNATURE_FILE_NAME).read_bytes() + trust.read_bytes()
    assert b"privateKey" not in serialized
    assert b"PRIVATE KEY" not in serialized
    package = ManagedRuntimePackage(
        runtime,
        trust_policy=RuntimePackageTrustPolicy.load(trust),
        require_signature=True,
    )
    assert package.public_summary()["signatureVerified"] is True


def test_probe_signature_refuses_to_overwrite_existing_trust_material(tmp_path: Path) -> None:
    runtime = (tmp_path / "runtime").resolve()
    write_package(runtime)
    trust = (tmp_path / "existing-trust.json").resolve()
    trust.write_text("keep", encoding="utf-8")
    process = subprocess.run(
        [
            sys.executable,
            "scripts/create_ephemeral_runtime_probe_signature.py",
            "--runtime-root",
            str(runtime),
            "--trust-policy",
            str(trust),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode != 0
    assert trust.read_text(encoding="utf-8") == "keep"
