from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

WORKER_DIR = Path(__file__).resolve().parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from acg.commands.check_env import handle_check_env
from acg.commands.export import handle_export
from acg.commands.generate import handle_generate
from acg.commands.test_api import handle_test_api
from acg.commands.test_tts import handle_test_tts
from acg.commands.verify import handle_verify_anki_import
from acg import legacy_worker as _legacy_worker
from acg.legacy_worker import *  # noqa: F401,F403 - preserve test-facing worker helpers during staged refactor.
from acg.protocol import emit, fail, read_payload

WorkerHandler = Callable[[dict[str, Any]], dict[str, Any]]

COMMANDS: dict[str, WorkerHandler] = {
    "check_env": handle_check_env,
    "test_api": handle_test_api,
    "test_tts": handle_test_tts,
    "generate": handle_generate,
    "export": handle_export,
    "verify_anki_import": handle_verify_anki_import,
}


def review_phrase_candidates_with_mimo(*args: Any, **kwargs: Any) -> Any:
    original_chat = _legacy_worker.compatible_chat_completion
    _legacy_worker.compatible_chat_completion = globals()["compatible_chat_completion"]
    try:
        return _legacy_worker.review_phrase_candidates_with_mimo(*args, **kwargs)
    finally:
        _legacy_worker.compatible_chat_completion = original_chat


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    handler = COMMANDS.get(command)
    if not handler:
        fail(f"未知 worker 命令：{command}")
    emit(handler(read_payload()))


if __name__ == "__main__":
    main()
