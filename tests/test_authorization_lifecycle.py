from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from card_service.service import CardService


class _Ledger:
    def __init__(self) -> None:
        self.calls: list[set[str]] = []

    def revoke_profiles(self, profile_refs: set[str]) -> int:
        self.calls.append(set(profile_refs))
        return len(profile_refs)


def test_active_broker_authorization_summary_and_revoke_are_bounded() -> None:
    ledger = _Ledger()
    runtime = SimpleNamespace(
        configuration=SimpleNamespace(
            method_bindings={
                "generate": {"model": "model.primary", "tts": "tts.primary"},
                "discover": {"source": "source.youtube", "model": "model.primary"},
            },
            expires_at_unix_ms=int(time.time() * 1000) + 60_000,
        ),
        ledger=ledger,
    )
    service = object.__new__(CardService)
    service._broker_runtime_lock = threading.RLock()
    service._active_broker_runtime = runtime

    summary = service._active_broker_authorization_summary()
    assert summary == {
        "schemaVersion": 1,
        "kind": "broker_authorization",
        "capabilities": ["model", "source", "tts"],
        "profileCount": 3,
        "expiresAtUnixMs": runtime.configuration.expires_at_unix_ms,
        "state": "active",
    }

    revoked = service._revoke_active_broker_authorization()
    assert revoked == {
        "schemaVersion": 1,
        "kind": "broker_authorization",
        "state": "revoked",
        "revokedProfileCount": 3,
        "newlyRevokedProfileCount": 3,
    }
    assert ledger.calls == [{"model.primary", "tts.primary", "source.youtube"}]
    assert service._active_broker_runtime is None
    assert service._active_broker_authorization_summary() is None
    assert service._revoke_active_broker_authorization()["state"] == "not_found"
