from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from card_service.storage import AtomicJsonStore
from card_service.trusted_surfaces import TrustedSurfaceError, TrustedSurfaceManager


ROOT = Path(__file__).resolve().parents[1]
FAKE_SURFACE = ROOT / "tests" / "fixtures" / "card_service" / "fake_surface.py"


def manager(tmp_path: Path, surface: Path = FAKE_SURFACE) -> TrustedSurfaceManager:
    return TrustedSurfaceManager(
        state_dir=(tmp_path / "surfaces").resolve(),
        python_path=Path(sys.executable).resolve(),
        surface_path=surface.resolve(),
    )


def wait_session(surfaces: TrustedSurfaceManager, session_ref: str) -> dict[str, object]:
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        state = surfaces.get_session(session_ref)
        if state["state"] not in {"created", "open"}:
            return state
        time.sleep(0.02)
    raise AssertionError("trusted surface did not finish")


def test_settings_session_contains_no_secret_and_returns_no_path(tmp_path: Path) -> None:
    surfaces = manager(tmp_path)
    session = surfaces.create_local_settings_session(profile_ref="model.primary", capability="model")
    assert session == {"sessionRef": session["sessionRef"], "surface": "local_settings", "state": "created"}
    request = json.loads((surfaces.sessions_dir / f"{session['sessionRef']}.json").read_text(encoding="utf-8"))
    assert request["profileRef"] == "model.primary"
    assert "secret" not in json.dumps(request).lower()
    assert "api_key" not in json.dumps(request).lower()


def test_digest_pinned_launcher_completes_over_private_response_file(tmp_path: Path) -> None:
    surfaces = manager(tmp_path)
    session = surfaces.create_consent_session(
        title="导入 Anki", summary="将 3 张卡片写入隔离牌组。", purpose="anki_import"
    )
    assert surfaces.launch(session["sessionRef"])["state"] == "open"
    assert wait_session(surfaces, session["sessionRef"]) == {
        "schemaVersion": 1,
        "sessionRef": session["sessionRef"],
        "state": "approved",
        "userGestureRecorded": True,
    }


def test_tampered_surface_code_fails_before_launch(tmp_path: Path) -> None:
    mutable_surface = tmp_path / "surface.py"
    mutable_surface.write_bytes(FAKE_SURFACE.read_bytes())
    surfaces = manager(tmp_path, mutable_surface)
    session = surfaces.create_consent_session(title="确认", summary="执行本地测试。", purpose="operation")
    mutable_surface.write_text(mutable_surface.read_text(encoding="utf-8") + "\n# changed", encoding="utf-8")
    with pytest.raises(TrustedSurfaceError) as caught:
        surfaces.launch(session["sessionRef"])
    assert caught.value.code == "SURFACE_DIGEST_CHANGED"


def test_tampered_request_or_response_nonce_is_rejected(tmp_path: Path) -> None:
    surfaces = manager(tmp_path)
    session = surfaces.create_consent_session(title="确认", summary="执行本地测试。", purpose="operation")
    request_path = surfaces.sessions_dir / f"{session['sessionRef']}.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    original_response = request["responsePath"]
    request["responsePath"] = str(tmp_path / "escape.json")
    AtomicJsonStore._write_atomic(request_path, request)
    with pytest.raises(TrustedSurfaceError) as changed:
        surfaces.get_session(session["sessionRef"])
    assert changed.value.code == "SESSION_REQUEST_INVALID"

    request["responsePath"] = original_response
    AtomicJsonStore._write_atomic(request_path, request)
    AtomicJsonStore._write_atomic(
        Path(original_response),
        {"schemaVersion": 1, "sessionRef": session["sessionRef"], "requestNonce": "wrong", "state": "approved"},
    )
    with pytest.raises(TrustedSurfaceError) as nonce:
        surfaces.get_session(session["sessionRef"])
    assert nonce.value.code == "SESSION_RESPONSE_INVALID"


@pytest.mark.parametrize("profile_ref", ["", "../escape", "model primary", "x" * 129])
def test_invalid_profile_refs_are_rejected(tmp_path: Path, profile_ref: str) -> None:
    with pytest.raises(TrustedSurfaceError) as caught:
        manager(tmp_path).create_local_settings_session(profile_ref=profile_ref, capability="model")
    assert caught.value.code == "INVALID_PROFILE_REF"
