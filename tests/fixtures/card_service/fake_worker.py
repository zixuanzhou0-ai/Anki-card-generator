from __future__ import annotations

import json
import sys
import time


PROGRESS_PREFIX = "__ANKI_CARD_PROGRESS__"
ERROR_PREFIX = "__ANKI_CARD_ERROR__"


def main() -> None:
    command = sys.argv[1]
    request = json.loads(sys.stdin.read() or "{}")
    mode = request.get("mode", "success")
    if mode == "slow":
        print(
            PROGRESS_PREFIX
            + json.dumps({"stage": "waiting", "percent": 10, "message": "waiting"}),
            file=sys.stderr,
            flush=True,
        )
        time.sleep(10)
    if mode == "fail":
        print(
            ERROR_PREFIX
            + json.dumps({"error_code": "FAKE_FAILURE", "message": "safe fake failure"}),
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(3)
    if mode == "secret_result":
        print(json.dumps({"api_key": "secret-canary"}))
        return
    if mode == "overflow":
        print(json.dumps({"data": "x" * 200_000}))
        return
    if mode == "broker":
        from acg.broker_client import configured_broker_client

        client = configured_broker_client()
        if client is None:
            raise RuntimeError("broker was not configured")
        brokered = client.request("model.openai_chat", {"workUnitRef": "unit-1", "value": 7})
        print(json.dumps({"ok": True, "command": command, "brokered": brokered}, ensure_ascii=False))
        return
    print(
        PROGRESS_PREFIX + json.dumps({"stage": "half", "percent": 50, "message": "halfway"}),
        file=sys.stderr,
        flush=True,
    )
    print(json.dumps({"ok": True, "command": command, "echo": request}, ensure_ascii=False))


if __name__ == "__main__":
    main()
