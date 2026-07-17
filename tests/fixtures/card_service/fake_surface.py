from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> None:
    surface, request_path = sys.argv[1:]
    request = json.loads(sys.stdin.read())
    response = {
        "schemaVersion": 1,
        "sessionRef": request["sessionRef"],
        "requestNonce": request["requestNonce"],
        "state": "approved" if surface == "consent" else "completed",
        "userGestureRecorded": surface == "consent",
    }
    temporary = Path(request["responsePath"] + ".tmp")
    temporary.write_text(json.dumps(response), encoding="utf-8")
    os.replace(temporary, request["responsePath"])


if __name__ == "__main__":
    main()
