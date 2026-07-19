from __future__ import annotations

import io
import json

import pytest

from card_service.anki_target_probe import (
    ANKI_CONNECT_URL,
    AnkiTargetProbeError,
    LocalAnkiConnectTargetProbe,
)


class _Response:
    def __init__(self, payload, *, status: int = 200) -> None:
        self.status = status
        self.headers = {"Content-Length": str(len(payload))}
        self._stream = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int) -> bytes:
        return self._stream.read(size)


class _Opener:
    def __init__(self, values) -> None:
        self.values = list(values)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        payload = json.dumps({"result": value, "error": None}).encode("utf-8")
        return _Response(payload)


def test_probe_reads_only_fixed_loopback_and_returns_digests() -> None:
    opener = _Opener(
        [6, "Account 1", r"C:\private\collection.media", ["Default", "Study"]]
    )
    probe = LocalAnkiConnectTargetProbe()
    probe._opener = opener

    result = probe()

    assert result == {
        **result,
        "schemaVersion": 1,
        "credentialRevision": 0,
        "ankiConnectVersion": 6,
        "deckCount": 2,
        "transportAuthentication": "none",
    }
    assert result["profileRef"].startswith("anki_current_")
    encoded = json.dumps(result, sort_keys=True).casefold()
    assert "account 1" not in encoded
    assert "collection.media" not in encoded
    assert "c:\\private" not in encoded
    assert len(opener.requests) == 4
    for request, timeout in opener.requests:
        assert request.full_url == ANKI_CONNECT_URL
        assert timeout == 5.0


def test_probe_rejects_non_loopback_configuration() -> None:
    with pytest.raises(AnkiTargetProbeError) as captured:
        LocalAnkiConnectTargetProbe(endpoint="http://192.0.2.1:8765")
    assert captured.value.code == "ANKI_TARGET_INVALID"


@pytest.mark.parametrize(
    "response",
    [
        b"not-json",
        json.dumps({"result": 6}).encode("utf-8"),
        json.dumps({"result": 6, "error": "denied"}).encode("utf-8"),
    ],
)
def test_probe_rejects_untrusted_response_shapes(response) -> None:
    class Opener:
        def open(self, _request, *, timeout):
            assert timeout == 5.0
            return _Response(response)

    probe = LocalAnkiConnectTargetProbe()
    probe._opener = Opener()
    with pytest.raises(AnkiTargetProbeError):
        probe()
