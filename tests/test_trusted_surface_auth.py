from __future__ import annotations

import json

import pytest

from card_service.trusted_surface_auth import (
    new_response_key,
    open_private_payload,
    seal_private_payload,
)


SESSION_REF = "trusted-picker-session"
REQUEST_NONCE = "n" * 64
SURFACE = "local_resource_picker"


def test_private_picker_payload_round_trips_without_plaintext_disclosure() -> None:
    key = new_response_key()
    raw_path = r"C:\private\lesson.mp4"
    sealed = seal_private_payload(
        {"schemaVersion": 1, "selectedPath": raw_path},
        key,
        session_ref=SESSION_REF,
        request_nonce=REQUEST_NONCE,
        surface=SURFACE,
    )

    serialized = json.dumps(sealed, sort_keys=True)
    assert raw_path not in serialized
    assert open_private_payload(
        sealed,
        key,
        session_ref=SESSION_REF,
        request_nonce=REQUEST_NONCE,
        surface=SURFACE,
    ) == {"schemaVersion": 1, "selectedPath": raw_path}


@pytest.mark.parametrize(
    "change",
    [
        "ciphertext",
        "nonce",
        "session",
        "request_nonce",
    ],
)
def test_private_picker_payload_is_bound_to_ciphertext_and_request_context(
    change: str,
) -> None:
    key = new_response_key()
    sealed = seal_private_payload(
        {"schemaVersion": 1, "selectedPath": r"C:\lesson.mp4"},
        key,
        session_ref=SESSION_REF,
        request_nonce=REQUEST_NONCE,
        surface=SURFACE,
    )
    session_ref = SESSION_REF
    request_nonce = REQUEST_NONCE
    if change in {"ciphertext", "nonce"}:
        field = str(sealed[change])
        sealed[change] = ("A" if field[0] != "A" else "B") + field[1:]
    elif change == "session":
        session_ref = "another-session"
    else:
        request_nonce = "x" * 64

    with pytest.raises(ValueError):
        open_private_payload(
            sealed,
            key,
            session_ref=session_ref,
            request_nonce=request_nonce,
            surface=SURFACE,
        )


def test_private_picker_payload_rejects_open_envelopes_and_wrong_keys() -> None:
    key = new_response_key()
    sealed = seal_private_payload(
        {"schemaVersion": 1, "selectedPath": r"C:\lesson.mp4"},
        key,
        session_ref=SESSION_REF,
        request_nonce=REQUEST_NONCE,
        surface=SURFACE,
    )
    with pytest.raises(ValueError):
        open_private_payload(
            {**sealed, "selectedPath": r"C:\leaked.mp4"},
            key,
            session_ref=SESSION_REF,
            request_nonce=REQUEST_NONCE,
            surface=SURFACE,
        )
    with pytest.raises(ValueError):
        open_private_payload(
            sealed,
            new_response_key(),
            session_ref=SESSION_REF,
            request_nonce=REQUEST_NONCE,
            surface=SURFACE,
        )
