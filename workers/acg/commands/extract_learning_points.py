from __future__ import annotations

from typing import Any

from acg.pipeline.learning_point_pipeline import extract_learning_points_from_subtitles


def handle_extract_learning_points(payload: dict[str, Any]) -> dict[str, Any]:
    return extract_learning_points_from_subtitles(payload)


__all__ = ["handle_extract_learning_points"]

