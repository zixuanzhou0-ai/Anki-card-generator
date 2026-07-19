from __future__ import annotations

import time
from typing import Any

from .provider_egress import MAX_MODEL_RESPONSE_BYTES
from .service import CardService


AUTHORIZE_DISCOVERY_TOOL = "system.authorize_candidate_discovery"
SYSTEM_TOOL_NAMES = frozenset({AUTHORIZE_DISCOVERY_TOOL})


class McpSystemToolInputError(ValueError):
    pass


def _hermes_discovery_draft() -> dict[str, Any]:
    return {
        "lifetimeSeconds": 3600,
        "budget": {
            "maxRemoteCalls": 64,
            "maxRequestBytes": 16 * 1024 * 1024,
            "maxResponseBytes": 64 * 1024 * 1024,
            "maxCostMinorUnits": 0,
        },
        "profiles": [
            {
                "profileRef": "model.hermes-grok-4.5",
                "capability": "model",
                "provider": "hermes",
                "baseUrl": "http://127.0.0.1:8317/v1",
                "model": "grok-4.5",
                "voice": "",
                "timeoutSeconds": 120,
                "maximumResponseBytes": MAX_MODEL_RESPONSE_BYTES,
                "reservedCostMinorUnits": 0,
            }
        ],
        "methodBindings": {
            "study.discover_candidates": {"model": "model.hermes-grok-4.5"}
        },
        "sourceAcquisition": {
            "youtubeSubtitles": {"enabled": False, "timeoutSeconds": 30}
        },
    }


def system_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": AUTHORIZE_DISCOVERY_TOOL,
            "title": "Authorize Hermes Candidate Discovery",
            "description": (
                "Open a trusted local confirmation for a fixed Hermes Grok 4.5 candidate "
                "discovery profile. The tool accepts no URL, model, credential, or budget input."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "preset": {
                        "type": "string",
                        "const": "hermes_grok_4_5",
                    }
                },
                "required": ["preset"],
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "preset": {"type": "string", "const": "hermes_grok_4_5"},
                    "state": {
                        "type": "string",
                        "enum": [
                            "approved",
                            "declined",
                            "cancelled",
                            "failed",
                            "timed_out",
                        ],
                    },
                    "capabilityAvailable": {"type": "boolean"},
                    "authorization": {"type": "object"},
                    "errorCode": {"type": "string"},
                },
                "required": ["schemaVersion", "preset", "state", "capabilityAvailable"],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        }
    ]


def call_system_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    user_action_timeout_seconds: float,
) -> dict[str, Any]:
    if tool_name != AUTHORIZE_DISCOVERY_TOOL:
        raise McpSystemToolInputError("unknown system tool")
    if not isinstance(arguments, dict) or arguments != {"preset": "hermes_grok_4_5"}:
        raise McpSystemToolInputError("invalid system tool arguments")
    opened = service.dispatch("system.open_broker_authorization", _hermes_discovery_draft())
    session_ref = str(opened.get("sessionRef") or "")
    deadline = time.monotonic() + max(0.0, user_action_timeout_seconds)
    while time.monotonic() < deadline:
        result = service.dispatch("system.get_trusted_surface", {"sessionRef": session_ref})
        state = str(result.get("state") or "failed")
        if state not in {"created", "open"}:
            public: dict[str, Any] = {
                "schemaVersion": 1,
                "preset": "hermes_grok_4_5",
                "state": (
                    state
                    if state in {"approved", "declined", "cancelled", "failed"}
                    else "failed"
                ),
                "capabilityAvailable": state == "approved",
            }
            authorization = result.get("authorization")
            if state == "approved" and isinstance(authorization, dict):
                public["authorization"] = dict(authorization)
            if state == "failed" and isinstance(result.get("errorCode"), str):
                public["errorCode"] = result["errorCode"]
            return _tool_result(public)
        time.sleep(0.05)
    return _tool_result(
        {
            "schemaVersion": 1,
            "preset": "hermes_grok_4_5",
            "state": "timed_out",
            "capabilityAvailable": False,
        }
    )


def _tool_result(public: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "Hermes candidate discovery is authorized for this Card Service session."
                    if public["state"] == "approved"
                    else "Hermes candidate discovery authorization was not activated."
                ),
            }
        ],
        "structuredContent": public,
    }


__all__ = [
    "AUTHORIZE_DISCOVERY_TOOL",
    "McpSystemToolInputError",
    "SYSTEM_TOOL_NAMES",
    "call_system_tool",
    "system_tool_definitions",
]
