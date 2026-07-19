from __future__ import annotations

import io
import json

import pytest

from card_service.anki_target_probe import (
    ANKI_CONNECT_URL,
    AnkiTargetProbeError,
    LocalAnkiConnectTargetProbe,
    normalize_anki_connect_url,
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


def test_probe_accepts_a_configured_ipv4_loopback_port() -> None:
    opener = _Opener(
        [6, "Account 1", r"C:\private\collection.media", ["Default"]]
    )
    probe = LocalAnkiConnectTargetProbe(endpoint="http://127.0.0.1:8785/")
    probe._opener = opener

    probe()

    assert {request.full_url for request, _timeout in opener.requests} == {
        "http://127.0.0.1:8785"
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://192.0.2.1:8765",
        "https://127.0.0.1:8765",
        "http://localhost:8765",
        "http://user@127.0.0.1:8765",
        "http://127.0.0.1:8765/path",
        "http://127.0.0.1:8765?query=1",
        "http://127.0.0.1",
    ],
)
def test_probe_rejects_non_loopback_or_ambiguous_configuration(endpoint: str) -> None:
    with pytest.raises(AnkiTargetProbeError) as captured:
        LocalAnkiConnectTargetProbe(endpoint=endpoint)
    assert captured.value.code == "ANKI_TARGET_INVALID"


def test_normalized_endpoint_is_canonical() -> None:
    assert normalize_anki_connect_url("http://127.0.0.1:8785/") == (
        "http://127.0.0.1:8785"
    )


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
