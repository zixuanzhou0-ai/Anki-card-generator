from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class AtomicJsonStore:
    """Small atomic JSON store used for task snapshots and result references."""

    def __init__(self, root: Path) -> None:
        expanded = root.expanduser()
        if not expanded.is_absolute():
            raise ValueError("Card Service state directory must be absolute")
        resolved = expanded.resolve()
        self.root = resolved
        self.tasks_dir = self.root / "tasks"
        self.results_dir = self.root / "results"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_atomic(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    @staticmethod
    def _read(path: Path) -> Any:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def write_task(self, task_id: str, snapshot: dict[str, Any]) -> None:
        self._write_atomic(self.tasks_dir / f"{task_id}.json", snapshot)

    def read_task(self, task_id: str) -> dict[str, Any] | None:
        path = self.tasks_dir / f"{task_id}.json"
        if not path.is_file():
            return None
        value = self._read(path)
        return value if isinstance(value, dict) else None

    def list_tasks(self) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for path in sorted(self.tasks_dir.glob("*.json")):
            try:
                value = self._read(path)
            except (OSError, ValueError):
                continue
            if isinstance(value, dict):
                snapshots.append(value)
        return snapshots

    def write_result(self, task_id: str, result: Any) -> str:
        self._write_atomic(self.results_dir / f"{task_id}.json", result)
        return f"result:{task_id}"

    def read_result(self, result_ref: str) -> Any:
        prefix = "result:"
        if not result_ref.startswith(prefix):
            raise ValueError("Invalid Card Service result reference")
        task_id = result_ref[len(prefix) :]
        if not task_id or any(character not in "0123456789abcdef-" for character in task_id.lower()):
            raise ValueError("Invalid Card Service result reference")
        path = self.results_dir / f"{task_id}.json"
        if not path.is_file():
            raise FileNotFoundError("Card Service result does not exist")
        return self._read(path)
