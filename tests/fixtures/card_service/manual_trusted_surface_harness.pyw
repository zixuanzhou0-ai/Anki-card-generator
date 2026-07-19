from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from card_service.credentials import InMemoryCredentialBackend
from card_service.trusted_surfaces import TrustedSurfaceManager


def main() -> None:
    state_dir = Path(tempfile.mkdtemp(prefix="codex-study-trusted-surface-", dir=ROOT / "test-results")).resolve()
    manager = TrustedSurfaceManager(
        state_dir=state_dir,
        python_path=Path(sys.executable).resolve(),
        credential_backend=InMemoryCredentialBackend(),
    )
    if "--picker" in sys.argv[1:]:
        session = manager.create_local_resource_session(
            kind="file",
            scope_summary="读取所选文件一次，最多 16 MiB，仅用于受信选择器视觉验收。",
        )
    else:
        session = _create_broker_session(manager)
    manager.launch(str(session["sessionRef"]))
    deadline = time.monotonic() + 120
    result: dict[str, object] = {"state": "timeout"}
    while time.monotonic() < deadline:
        result = manager.get_session(str(session["sessionRef"]))
        if result["state"] not in {"created", "open"}:
            break
        time.sleep(0.05)
    (state_dir / "visual-result.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _create_broker_session(manager: TrustedSurfaceManager) -> dict[str, object]:
    profiles = [
        {
            "profileRef": f"model.hermes-{index}",
            "capability": "model",
            "provider": "hermes",
            "baseUrl": "http://127.0.0.1:8317/v1",
            "model": f"grok-4.5-visual-check-{index}",
            "voice": "",
            "timeoutSeconds": 120,
            "maximumResponseBytes": 4096,
            "reservedCostMinorUnits": 5,
        }
        for index in range(1, 5)
    ]
    return manager.create_broker_authorization_session(
        {
            "lifetimeSeconds": 600,
            "budget": {
                "maxRemoteCalls": 18,
                "maxRequestBytes": 1_500_000,
                "maxResponseBytes": 24 * 1024 * 1024,
                "maxCostMinorUnits": 300,
            },
            "profiles": profiles,
            "methodBindings": {
                "runtime.extract_learning_points": {
                    "model": "model.hermes-1",
                    "source": "source.youtube_subtitles",
                },
                "runtime.generate_cards": {"model": "model.hermes-2"},
                "runtime.generate_legacy_project": {"model": "model.hermes-3"},
                "runtime.test_model": {"model": "model.hermes-4"},
            },
            "sourceAcquisition": {
                "youtubeSubtitles": {"enabled": True, "timeoutSeconds": 30}
            },
        }
    )


if __name__ == "__main__":
    main()
