from __future__ import annotations

from typing import Any

from acg.card_reliability import export_reliability_blockers
from acg.legacy_worker import handle_export as _legacy_handle_export
from acg.protocol import fail


def handle_export(payload: dict[str, Any]) -> dict[str, Any]:
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    blocker_codes = export_reliability_blockers(project)
    if blocker_codes:
        fail(
            "可靠性门禁未通过，已阻止 APKG 导出。请先处理待复核、硬失败或验证已过期的卡片。",
            error_code="EXPORT_QUALITY_GATE_FAILED",
            stage="export",
            retryable=False,
            details={"reliability_blocker_codes": blocker_codes},
        )
    return _legacy_handle_export(payload)


__all__ = ["handle_export"]
