from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from card_service.trusted_mcp_audience import (
    LAUNCHER_PID_ENV,
    SESSION_NONCE_ENV,
    TrustedMcpAudienceError,
    _derive_session,
    create_development_mcp_audience,
    create_packaged_mcp_audience,
    current_owner_digest,
)


def test_mcp_host_identity_is_stable_while_session_changes_with_nonce(
    tmp_path: Path,
) -> None:
    launcher = (tmp_path / "launcher.exe").resolve()
    first = _derive_session(
        owner_digest="a" * 64,
        launcher=launcher,
        nonce="b" * 64,
        mode="packaged_launcher",
    )
    repeated = _derive_session(
        owner_digest="a" * 64,
        launcher=launcher,
        nonce="b" * 64,
        mode="packaged_launcher",
    )
    changed = _derive_session(
        owner_digest="a" * 64,
        launcher=launcher,
        nonce="c" * 64,
        mode="packaged_launcher",
    )
    assert first.audience.host_id == changed.audience.host_id
    assert first.audience.plugin_id == "anki-study-agent-plugin"

    assert first == repeated
    assert first.audience.session_id != changed.audience.session_id


def test_mcp_host_identity_changes_with_owner_or_launcher(tmp_path: Path) -> None:
    launcher = (tmp_path / "launcher.exe").resolve()
    baseline = _derive_session(
        owner_digest="a" * 64,
        launcher=launcher,
        nonce="b" * 64,
        mode="packaged_launcher",
    )
    different_owner = _derive_session(
        owner_digest="c" * 64,
        launcher=launcher,
        nonce="b" * 64,
        mode="packaged_launcher",
    )
    different_launcher = _derive_session(
        owner_digest="a" * 64,
        launcher=(tmp_path / "other-launcher.exe").resolve(),
        nonce="b" * 64,
        mode="packaged_launcher",
    )
    assert baseline.audience.host_id != different_owner.audience.host_id
    assert baseline.audience.host_id != different_launcher.audience.host_id


def test_development_session_requires_explicit_factory_and_discloses_no_ids() -> None:
    first = create_development_mcp_audience()
    second = create_development_mcp_audience()

    assert first.audience.owner_digest == second.audience.owner_digest
    assert first.audience.session_id != second.audience.session_id
    summary = first.public_summary()
    assert summary == {
        "schemaVersion": 1,
        "available": True,
        "mode": "development_explicit",
        "identifiersDisclosed": False,
        "toolArgumentsCanDeclareAudience": False,
    }
    serialized = json.dumps(summary, sort_keys=True)
    assert first.audience.owner_digest not in serialized
    assert first.audience.host_id not in serialized
    assert first.audience.session_id not in serialized


def test_owner_digest_is_canonical_and_contains_no_account_name() -> None:
    value = current_owner_digest()
    assert len(value) == 64
    assert value == value.lower()
    assert all(character in "0123456789abcdef" for character in value)
    assert str(os.environ.get("USERNAME") or "").casefold() not in value.casefold()


def test_packaged_session_fails_closed_without_native_launcher_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(LAUNCHER_PID_ENV, raising=False)
    monkeypatch.delenv(SESSION_NONCE_ENV, raising=False)

    with pytest.raises(TrustedMcpAudienceError) as failure:
        create_packaged_mcp_audience(tmp_path)

    assert failure.value.code == "MCP_LAUNCH_ATTESTATION_REQUIRED"


def test_invalid_packaged_proof_is_consumed_and_cannot_linger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LAUNCHER_PID_ENV, str(os.getppid() + 1))
    monkeypatch.setenv(SESSION_NONCE_ENV, "d" * 64)

    with pytest.raises(TrustedMcpAudienceError) as failure:
        create_packaged_mcp_audience(tmp_path)

    assert failure.value.code == "MCP_LAUNCH_ATTESTATION_INVALID"
    assert LAUNCHER_PID_ENV not in os.environ
    assert SESSION_NONCE_ENV not in os.environ
