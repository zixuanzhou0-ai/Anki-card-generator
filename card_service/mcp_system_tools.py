from __future__ import annotations

import time
from typing import Any

from .hermes_proxy import HERMES_PROXY_BASE_URL
from .provider_egress import MAX_MODEL_RESPONSE_BYTES
from .service import CardService, CardServiceError


AUTHORIZE_DISCOVERY_TOOL = "system.authorize_candidate_discovery"
LIST_PROFILES_TOOL = "system.list_profiles"
OPEN_LOCAL_SETTINGS_TOOL = "system.open_local_settings"
SYSTEM_TOOL_NAMES = frozenset(
    {AUTHORIZE_DISCOVERY_TOOL, LIST_PROFILES_TOOL, OPEN_LOCAL_SETTINGS_TOOL}
)


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
                "baseUrl": HERMES_PROXY_BASE_URL,
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
        },
        {
            "name": LIST_PROFILES_TOOL,
            "title": "List Service Profiles",
            "description": (
                "List configured model, speech, and AnkiConnect profiles with their exact "
                "credential binding and latest verification state. Secrets are never returned."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "profiles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "schemaVersion": {"type": "integer", "const": 1},
                                "profileRef": {"type": "string"},
                                "capability": {
                                    "type": "string",
                                    "enum": ["model", "tts", "anki_connect"],
                                },
                                "profileRevision": {"type": "integer", "minimum": 1},
                                "configurationFingerprint": {
                                    "type": "string",
                                    "pattern": "^[0-9a-f]{64}$",
                                },
                                "provider": {"type": "string"},
                                "endpointOrigin": {"type": "string"},
                                "model": {"type": "string"},
                                "voice": {"type": "string"},
                                "apiVersion": {"type": "integer"},
                                "credentialRevision": {"type": "integer", "minimum": 0},
                                "credentialState": {
                                    "type": "string",
                                    "enum": ["committed", "missing", "uncertain"],
                                },
                                "secretRequired": {"type": "boolean"},
                                "secretExists": {"type": "boolean"},
                                "state": {
                                    "type": "string",
                                    "enum": [
                                        "unknown",
                                        "ready",
                                        "stale",
                                        "action_required",
                                        "blocked",
                                    ],
                                },
                                "reasonCode": {"type": "string"},
                                "latestVerification": {
                                    "type": "object",
                                    "properties": {
                                        "recordId": {"type": "string"},
                                        "sequence": {"type": "integer", "minimum": 1},
                                        "capability": {"type": "string"},
                                        "profileRef": {"type": "string"},
                                        "configurationFingerprint": {"type": "string"},
                                        "credentialRevision": {"type": "integer", "minimum": 0},
                                        "status": {"type": "string", "enum": ["passed", "failed"]},
                                        "errorCode": {
                                            "anyOf": [{"type": "string"}, {"type": "null"}]
                                        },
                                        "retryable": {
                                            "anyOf": [{"type": "boolean"}, {"type": "null"}]
                                        },
                                        "latencyMs": {
                                            "anyOf": [{"type": "integer"}, {"type": "null"}]
                                        },
                                        "publishState": {
                                            "type": "string",
                                            "enum": ["current", "stale_at_publish"],
                                        },
                                        "checkedAt": {"type": "integer"},
                                    },
                                    "required": [
                                        "recordId",
                                        "sequence",
                                        "capability",
                                        "profileRef",
                                        "configurationFingerprint",
                                        "credentialRevision",
                                        "status",
                                        "errorCode",
                                        "retryable",
                                        "latencyMs",
                                        "publishState",
                                        "checkedAt",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                            "required": [
                                "schemaVersion",
                                "profileRef",
                                "capability",
                                "profileRevision",
                                "configurationFingerprint",
                                "provider",
                                "endpointOrigin",
                                "credentialRevision",
                                "credentialState",
                                "secretRequired",
                                "secretExists",
                                "state",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["schemaVersion", "profiles"],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": OPEN_LOCAL_SETTINGS_TOOL,
            "title": "Open Local Service Settings",
            "description": (
                "Open or poll a trusted local credential window for an existing service profile. "
                "Credential material never enters tool arguments or results."
            ),
            "inputSchema": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "profileRef": {"type": "string"},
                            "capability": {
                                "type": "string",
                                "enum": ["model", "tts", "anki_connect"],
                            },
                        },
                        "required": ["profileRef", "capability"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "configurationSessionRef": {"type": "string"},
                        },
                        "required": ["configurationSessionRef"],
                        "additionalProperties": False,
                    },
                ]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "schemaVersion": {"type": "integer", "const": 1},
                    "configurationSessionRef": {"type": "string"},
                    "state": {
                        "type": "string",
                        "enum": ["open", "created", "completed", "cancelled", "failed"],
                    },
                    "credentialRevision": {"type": "integer", "minimum": 0},
                    "credentialState": {
                        "type": "string",
                        "enum": ["committed", "missing", "uncertain"],
                    },
                    "secretExists": {"type": "boolean"},
                    "errorCode": {"type": "string"},
                },
                "required": ["schemaVersion", "configurationSessionRef", "state"],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": False,
            },
        },
    ]


def call_system_tool(
    service: CardService,
    *,
    tool_name: str,
    arguments: Any,
    user_action_timeout_seconds: float,
) -> dict[str, Any]:
    if tool_name == LIST_PROFILES_TOOL:
        if arguments != {}:
            raise McpSystemToolInputError("invalid system tool arguments")
        return _profiles_tool_result(service.dispatch("system.list_profiles", {}))
    if tool_name == OPEN_LOCAL_SETTINGS_TOOL:
        if not isinstance(arguments, dict):
            raise McpSystemToolInputError("invalid system tool arguments")
        if set(arguments) == {"profileRef", "capability"}:
            if (
                not isinstance(arguments["profileRef"], str)
                or arguments["capability"] not in {"model", "tts", "anki_connect"}
            ):
                raise McpSystemToolInputError("invalid system tool arguments")
            result = service.dispatch("system.open_local_settings", arguments)
            return _settings_tool_result(result)
        if set(arguments) == {"configurationSessionRef"} and isinstance(
            arguments["configurationSessionRef"], str
        ):
            result = service.dispatch("system.get_local_settings", arguments)
            return _settings_tool_result(result)
        raise McpSystemToolInputError("invalid system tool arguments")
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
                "capabilityAvailable": False,
            }
            authorization = result.get("authorization")
            if state == "approved" and isinstance(authorization, dict):
                public["authorization"] = dict(authorization)
                try:
                    service.ensure_candidate_discovery_provider()
                    public["capabilityAvailable"] = True
                except CardServiceError as error:
                    public["errorCode"] = error.code
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
                    if public["state"] == "approved" and public["capabilityAvailable"]
                    else "Hermes candidate discovery authorization was not activated."
                ),
            }
        ],
        "structuredContent": public,
    }


def _profiles_tool_result(public: dict[str, Any]) -> dict[str, Any]:
    count = len(public.get("profiles") or [])
    return {
        "content": [
            {
                "type": "text",
                "text": f"Card Service returned {count} configured service profile(s).",
            }
        ],
        "structuredContent": public,
    }


def _settings_tool_result(public: dict[str, Any]) -> dict[str, Any]:
    state = str(public.get("state") or "failed")
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "The trusted local settings window is open."
                    if state in {"open", "created"}
                    else "The trusted local settings operation completed."
                    if state == "completed"
                    else "The trusted local settings operation did not change credentials."
                ),
            }
        ],
        "structuredContent": public,
    }


__all__ = [
    "AUTHORIZE_DISCOVERY_TOOL",
    "LIST_PROFILES_TOOL",
    "McpSystemToolInputError",
    "OPEN_LOCAL_SETTINGS_TOOL",
    "SYSTEM_TOOL_NAMES",
    "call_system_tool",
    "system_tool_definitions",
]
