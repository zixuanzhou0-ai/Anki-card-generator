from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from card_service.storage import AtomicJsonStore
from card_service.trusted_surface_auth import encode_response_key, new_response_key, verify_response
from card_service.trusted_surface_ui import write_response
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


def test_real_trusted_surface_writer_authenticates_response_without_persisting_key(tmp_path: Path) -> None:
    key = new_response_key()
    response_path = (tmp_path / "response.json").resolve()
    request = {
        "sessionRef": "session-auth-proof",
        "requestNonce": "n" * 64,
        "responsePath": str(response_path),
        "responseAuthKey": encode_response_key(key),
    }
    write_response(request, "approved", userGestureRecorded=True)
    stored = json.loads(response_path.read_text(encoding="utf-8"))
    verified = verify_response(stored, key)
    assert verified["state"] == "approved"
    assert verified["userGestureRecorded"] is True
    assert "responseAuthKey" not in response_path.read_text(encoding="utf-8")


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
    request_text = (surfaces.sessions_dir / f"{session['sessionRef']}.json").read_text(encoding="utf-8")
    response_text = (surfaces.responses_dir / f"{session['sessionRef']}.json").read_text(encoding="utf-8")
    assert "responseAuthKey" not in request_text
    assert "responseAuthKey" not in response_text
    assert "responseMac" in response_text


def test_one_trusted_surface_session_cannot_be_launched_twice(tmp_path: Path) -> None:
    surfaces = manager(tmp_path)
    session = surfaces.create_consent_session(title="确认", summary="执行本地测试。", purpose="operation")
    surfaces.launch(session["sessionRef"])
    with pytest.raises(TrustedSurfaceError) as caught:
        surfaces.launch(session["sessionRef"])
    assert caught.value.code == "SESSION_ALREADY_LAUNCHED"


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


def test_same_user_forged_approval_with_readable_nonce_but_no_private_mac_is_rejected(tmp_path: Path) -> None:
    surfaces = manager(tmp_path)
    session = surfaces.create_consent_session(title="确认", summary="执行本地测试。", purpose="operation")
    surfaces.launch(session["sessionRef"])
    deadline = time.monotonic() + 4
    response_path = surfaces.responses_dir / f"{session['sessionRef']}.json"
    running = True
    while time.monotonic() < deadline:
        with surfaces._lock:
            running = session["sessionRef"] in surfaces._processes
        if response_path.is_file() and not running:
            break
        time.sleep(0.02)
    assert response_path.is_file() and not running
    request = json.loads(
        (surfaces.sessions_dir / f"{session['sessionRef']}.json").read_text(encoding="utf-8")
    )
    AtomicJsonStore._write_atomic(
        response_path,
        {
            "schemaVersion": 1,
            "sessionRef": session["sessionRef"],
            "requestNonce": request["requestNonce"],
            "state": "approved",
            "userGestureRecorded": True,
        },
    )
    with pytest.raises(TrustedSurfaceError) as caught:
        surfaces.get_session(session["sessionRef"])
    assert caught.value.code == "SESSION_RESPONSE_INVALID"


def test_local_resource_picker_keeps_raw_path_out_of_request_response_and_public_result(
    tmp_path: Path,
) -> None:
    surfaces = manager(tmp_path)
    capabilities = surfaces.capabilities()
    assert capabilities["localResourcePickerResponseEncryptedAtRest"] is True
    assert "localResourcePathEncryptedAtRest" not in capabilities

    audience_digest = "a" * 64
    request_digest = "b" * 64
    session = surfaces.create_local_resource_session(
        kind="file",
        scope_summary="读取一次所选文件，最多 16 MiB，用于当前素材分析。",
    )
    request_path = surfaces.sessions_dir / f"{session['sessionRef']}.json"
    selected_path = (
        request_path.parents[3] / f"trusted-picker-{session['sessionRef']}.txt"
    ).resolve()
    selected_path.write_text("trusted picker content", encoding="utf-8")
    request_text = request_path.read_text(encoding="utf-8")
    assert str(selected_path) not in request_text
    assert "selectedPath" not in request_text

    assert surfaces.launch(session["sessionRef"])["state"] == "open"
    result = wait_session(surfaces, session["sessionRef"])
    assert result == {
        "schemaVersion": 1,
        "sessionRef": session["sessionRef"],
        "state": "selected",
        "userGestureRecorded": True,
        "resourceSelection": {
            "kind": "file",
            "displayName": "Selected file",
            "pathDisclosure": False,
        },
    }
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert str(selected_path) not in serialized
    assert "privatePayload" not in serialized
    assert "attestation" not in serialized.lower()
    assert not (surfaces.responses_dir / f"{session['sessionRef']}.json").exists()

    selection = surfaces.selected_local_resource(session["sessionRef"])
    assert selection is not None
    assert selection.path == selected_path
    assert surfaces.verify_resource_gesture(
        audience_digest, request_digest, selection.attestation_ref,
        "approve_local_resource"
    ) is True
    assert surfaces.verify_resource_gesture(
        audience_digest, request_digest, selection.attestation_ref,
        "approve_local_resource"
    ) is True
    assert surfaces.verify_resource_gesture(
        "c" * 64, request_digest, selection.attestation_ref,
        "approve_local_resource"
    ) is False
    assert surfaces.verify_resource_gesture(
        audience_digest, "d" * 64, selection.attestation_ref,
        "approve_local_resource"
    ) is False

    with surfaces._lock:
        surfaces._resource_attestations[selection.attestation_ref]["expiresAt"] = 0
    assert surfaces.verify_resource_gesture(
        audience_digest, request_digest, selection.attestation_ref,
        "approve_local_resource"
    ) is False

    surfaces.complete_resource_selection(session["sessionRef"])
    assert surfaces.selected_local_resource(session["sessionRef"]) is None
    assert surfaces.verify_resource_gesture(
        audience_digest, request_digest, selection.attestation_ref,
        "approve_local_resource"
    ) is False


def test_authorization_manager_keeps_private_targets_out_of_public_files_and_attests_exact_selection(
    tmp_path: Path,
) -> None:
    surfaces = manager(tmp_path)
    audience_digest = "a" * 64
    import_intent_id = "anki_intent_" + "b" * 48
    resource_ref = "resource_" + "c" * 43
    authorization_digest = "sha256:" + "d" * 64
    session = surfaces.create_authorization_manager_session(
        audience_digest=audience_digest,
        items=[
            {
                "kind": "local_resource",
                "title": "本地资源 · lesson.srt",
                "detail": "允许读取；剩余 8 次",
                "state": "active",
                "locator": {"resourceRef": resource_ref, "revocationEpoch": 0},
            },
            {
                "kind": "anki_import",
                "title": "Anki 导入批准",
                "detail": "状态：已批准",
                "state": "approved",
                "locator": {"importIntentId": import_intent_id},
            },
            {
                "kind": "broker_authorization",
                "title": "模型、语音与来源服务授权",
                "detail": "能力：model",
                "state": "active",
                "locator": {
                    "activeAuthorization": True,
                    "authorizationDigest": authorization_digest,
                },
            },
        ],
    )
    request_path = surfaces.sessions_dir / f"{session['sessionRef']}.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    serialized_request = json.dumps(request, ensure_ascii=False, sort_keys=True)
    assert resource_ref not in serialized_request
    assert import_intent_id not in serialized_request
    assert authorization_digest not in serialized_request
    assert "locator" not in serialized_request
    assert len(request["authorizationItems"]) == 3

    surfaces.launch(str(session["sessionRef"]))
    result = wait_session(surfaces, str(session["sessionRef"]))
    assert result["state"] == "approved"
    assert result["authorizationRevocation"] == {
        "selectedCount": 3,
        "availableCount": 3,
    }
    serialized_result = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert resource_ref not in serialized_result
    assert import_intent_id not in serialized_result
    assert authorization_digest not in serialized_result
    assert "privatePayload" not in serialized_result
    assert not (surfaces.responses_dir / f"{session['sessionRef']}.json").exists()

    selections = surfaces.authorization_revocation_selections(
        str(session["sessionRef"])
    )
    assert [selection.kind for selection in selections] == [
        "local_resource",
        "anki_import",
        "broker_authorization",
    ]
    local, anki, broker = selections
    assert local.locator == {"resourceRef": resource_ref, "revocationEpoch": 0}
    assert surfaces.verify_resource_gesture(
        audience_digest,
        "e" * 64,
        local.attestation_ref,
        "revoke_local_resource",
    ) is True
    assert surfaces.verify_import_consent_gesture(
        anki.attestation_ref,
        audience_digest,
        import_intent_id,
        "revoke",
    ) is True
    assert surfaces.verify_authorization_revocation(
        attestation_ref=broker.attestation_ref,
        audience_digest=audience_digest,
        selection_ref=broker.selection_ref,
        action="revoke_broker_authorization",
    ) is True
    surfaces.complete_authorization_manager(str(session["sessionRef"]))
    assert surfaces.authorization_revocation_selections(
        str(session["sessionRef"])
    ) == ()
    assert surfaces.verify_resource_gesture(
        audience_digest,
        "e" * 64,
        local.attestation_ref,
        "revoke_local_resource",
    ) is False


@pytest.mark.parametrize("profile_ref", ["", "../escape", "model primary", "x" * 129])
def test_invalid_profile_refs_are_rejected(tmp_path: Path, profile_ref: str) -> None:
    with pytest.raises(TrustedSurfaceError) as caught:
        manager(tmp_path).create_local_settings_session(profile_ref=profile_ref, capability="model")
    assert caught.value.code == "INVALID_PROFILE_REF"
