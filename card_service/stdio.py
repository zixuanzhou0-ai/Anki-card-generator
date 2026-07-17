from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .service import CardService, CardServiceError


def _response(request_id: Any, *, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def serve(service: CardService) -> None:
    for raw_line in sys.stdin:
        request_id: Any = None
        try:
            request = json.loads(raw_line)
            if not isinstance(request, dict):
                raise CardServiceError("INVALID_REQUEST", "Request must be a JSON object")
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params") or {}
            if request.get("jsonrpc") != "2.0" or not isinstance(method, str) or not isinstance(params, dict):
                raise CardServiceError("INVALID_REQUEST", "Invalid local Card Service request")
            response = _response(request_id, result=service.dispatch(method, params))
        except CardServiceError as error:
            response = _response(request_id, error={"code": error.code, "message": str(error)})
        except (TypeError, ValueError):
            response = _response(request_id, error={"code": "INVALID_JSON", "message": "Invalid JSON request"})
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex Study local Card Service")
    parser.add_argument("--state-dir", type=Path, required=True)
    runtime_mode = parser.add_mutually_exclusive_group(required=True)
    runtime_mode.add_argument("--runtime-package", type=Path)
    runtime_mode.add_argument("--development-unpackaged-runtime", action="store_true")
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--tool-dir", action="append", type=Path, default=[])
    arguments = parser.parse_args()
    if not arguments.development_unpackaged_runtime and (
        arguments.worker is not None or arguments.python is not None or arguments.tool_dir
    ):
        parser.error("--worker, --python, and --tool-dir require --development-unpackaged-runtime")
    service = CardService(
        state_dir=arguments.state_dir,
        worker_path=arguments.worker,
        python_path=arguments.python,
        runtime_package=arguments.runtime_package,
        managed_tool_directories=arguments.tool_dir,
    )
    serve(service)


if __name__ == "__main__":
    main()
