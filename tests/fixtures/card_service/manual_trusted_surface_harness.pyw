from __future__ import annotations

import hashlib
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
    if "--operation-confirmation" in sys.argv[1:]:
        session = _create_operation_confirmation_session(manager)
    elif "--authorization-manager" in sys.argv[1:]:
        session = _create_authorization_manager_session(manager)
    elif "--picker" in sys.argv[1:]:
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
            "baseUrl": "http://127.0.0.1:8645/v1",
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


def _create_operation_confirmation_session(
    manager: TrustedSurfaceManager,
) -> dict[str, object]:
    return manager.create_operation_consent_session(
        operation_intent_id="intent_" + "c" * 48,
        audience_digest=hashlib.sha256(b"manual-operation-consent-audience").hexdigest(),
        intent_digest=hashlib.sha256(b"manual-operation-consent-intent").hexdigest(),
        action_id="validate_profile",
        summary=(
            "操作：验证模型连接\n"
            "服务：Hermes Grok 4.5（本机代理）\n"
            "将发送：固定诊断文本；不包含学习素材、卡片内容或本机文件\n"
            "上限：1 次远程请求；请求最多 16 KiB；响应最多 64 KiB\n"
            "费用：价格未知，仍受上述硬上限约束\n"
            "有效范围：只批准这一次精确配置的连接验证；不能用于生成卡片"
        ),
    )


def _create_authorization_manager_session(
    manager: TrustedSurfaceManager,
) -> dict[str, object]:
    return manager.create_authorization_manager_session(
        audience_digest=hashlib.sha256(b"manual-visual-check").hexdigest(),
        items=[
            {
                "kind": "local_resource",
                "title": "本地资源 · 示例字幕.srt",
                "detail": "允许操作：读取；剩余 2 次；有效期至 2026-07-19 23:59",
                "state": "active",
                "locator": {
                    "resourceRef": "private-resource-ref-for-visual-check",
                    "revocationEpoch": 3,
                },
            },
            {
                "kind": "anki_import",
                "title": "Anki 导入批准",
                "detail": "状态：已批准；有效期至 2026-07-19 23:59",
                "state": "approved",
                "locator": {"importIntentId": "anki_intent_" + "a" * 48},
            },
            {
                "kind": "broker_authorization",
                "title": "模型、语音与来源服务授权",
                "detail": "能力：model、tts、source；配置 3 项；有效期至 2026-07-19 23:59",
                "state": "active",
                "locator": {
                    "activeAuthorization": True,
                    "authorizationDigest": "sha256:" + "b" * 64,
                },
            },
        ],
    )


if __name__ == "__main__":
    main()
