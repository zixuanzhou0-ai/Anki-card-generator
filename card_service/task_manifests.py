from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from .artifact_registry import ArtifactAudienceBinding, ArtifactRegistryError, canonical_json_bytes, validate_persistable_json


_SHA256_LENGTH = 64
_MAX_SAFE_INTEGER = 9_007_199_254_740_991

WORKFLOW_ACTIONS = frozenset(
    {
        "select_source",
        "request_source_grant",
        "request_output_grant",
        "request_network_grant",
        "open_settings",
        "validate_profile",
        "register_inputs",
        "confirm_operation",
        "inspect_source",
        "discover_candidates",
        "review_candidates",
        "save_selection",
        "plan_cards",
        "edit_card_plan",
        "validate_card_plans",
        "generate_cards",
        "export_apkg",
        "prepare_anki_import",
        "confirm_anki_import",
        "resolve_anki_conflict",
        "import_and_verify",
        "resume_task",
        "cancel_task",
        "resolve_issue",
        "retry",
        "view_results",
        "open_anki",
    }
)
SERVICE_CAPABILITIES = frozenset({"model", "tts", "anki_connect"})
FIXED_CAPABILITIES = frozenset(
    {
        "host.plugin_manifest", "host.stdio_service_launch", "host.tool_registration",
        "host.trusted_local_ui", "host.attachment_bridge", "host.mcp_app_resources",
        "runtime.card_service", "runtime.worker", "runtime.python", "runtime.ffmpeg",
        "runtime.yt_dlp", "runtime.document_parsers", "source.local_video",
        "source.subtitle", "source.public_video_url", "source.text", "source.pdf_text",
        "source.web_snapshot", "source.audio_podcast", "source.directory",
        "source.media_embedded_transcript",
        "source.codex_attachment_bridge", "source.ocr_visual", "source.code_repository",
        "service.anki", "service.anki_runtime_verifier",
    }
)
AUTHORIZATION_ACTIONS = frozenset(
    {"read_source", "read_directory", "write_output", "call_model", "call_tts", "access_network", "access_private_network", "import_anki"}
)


class TaskManifestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _digest(value: Mapping[str, Any]) -> str:
    try:
        validate_persistable_json(dict(value))
        return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()
    except ArtifactRegistryError as error:
        raise TaskManifestError("TASK_MANIFEST_FORBIDDEN_DATA", error.message) from error


def manifest_digest(value: Mapping[str, Any]) -> str:
    return _digest(value)


def _require_exact_fields(value: Mapping[str, Any], required: set[str], optional: set[str], label: str) -> None:
    if not isinstance(value, Mapping) or not required.issubset(value) or not set(value).issubset(required | optional):
        raise TaskManifestError("TASK_MANIFEST_INVALID", f"{label} fields are invalid")


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise TaskManifestError("TASK_MANIFEST_INVALID", f"{label} must be a non-empty bounded string")
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH or any(character not in "0123456789abcdef" for character in value):
        raise TaskManifestError("TASK_MANIFEST_INVALID", f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_revision(value: Any, label: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > _MAX_SAFE_INTEGER:
        raise TaskManifestError("TASK_MANIFEST_INVALID", f"{label} must be a safe integer")
    return value


def _action(value: Any) -> str:
    if value not in WORKFLOW_ACTIONS:
        raise TaskManifestError("TASK_MANIFEST_INVALID", "Workflow action is not a frozen control-plane value")
    return str(value)


def _artifact_inputs(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TaskManifestError("TASK_MANIFEST_INVALID", "inputArtifacts must be a list")
    normalized: list[dict[str, Any]] = []
    for item in values:
        _require_exact_fields(item, {"artifactId", "artifactRevision", "artifactDigest"}, set(), "input artifact")
        normalized.append(
            {
                "artifactId": _require_text(item["artifactId"], "artifactId"),
                "artifactRevision": _require_revision(item["artifactRevision"], "artifactRevision"),
                "artifactDigest": _require_digest(item["artifactDigest"], "artifactDigest"),
            }
        )
    normalized.sort(key=lambda item: (item["artifactId"].encode("utf-8"), item["artifactRevision"], item["artifactDigest"]))
    keys = [(item["artifactId"], item["artifactRevision"], item["artifactDigest"]) for item in normalized]
    if len(keys) != len(set(keys)):
        raise TaskManifestError("TASK_MANIFEST_DUPLICATE", "inputArtifacts contains a duplicate")
    return normalized


def _sorted_digests(values: Any, label: str) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TaskManifestError("TASK_MANIFEST_INVALID", f"{label} must be a list")
    normalized = sorted((_require_digest(value, label) for value in values), key=lambda value: value.encode("utf-8"))
    if len(normalized) != len(set(normalized)):
        raise TaskManifestError("TASK_MANIFEST_DUPLICATE", f"{label} contains a duplicate")
    return normalized


def _component_versions(value: Any) -> dict[str, Any]:
    required = {"cardService", "worker", "sourceAdapterSetDigest", "gateRuleSetVersion"}
    optional = {"templateFamily", "templateSchemaVersion", "compatibilityContractVersion"}
    _require_exact_fields(value, required, optional, "componentVersions")
    result: dict[str, Any] = {
        "cardService": _require_text(value["cardService"], "cardService"),
        "worker": _require_text(value["worker"], "worker"),
        "sourceAdapterSetDigest": _require_digest(value["sourceAdapterSetDigest"], "sourceAdapterSetDigest"),
        "gateRuleSetVersion": _require_text(value["gateRuleSetVersion"], "gateRuleSetVersion"),
    }
    for name in sorted(optional):
        if name in value:
            result[name] = _require_text(value[name], name)
    return result


def _work_service_configurations(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TaskManifestError("TASK_MANIFEST_INVALID", "serviceConfigurations must be a list")
    normalized: list[dict[str, Any]] = []
    for item in values:
        _require_exact_fields(item, {"capability", "profileRef", "configurationFingerprint"}, set(), "service configuration")
        if item["capability"] not in SERVICE_CAPABILITIES:
            raise TaskManifestError("TASK_MANIFEST_INVALID", "Service capability is invalid")
        normalized.append(
            {
                "capability": item["capability"],
                "profileRef": _require_text(item["profileRef"], "profileRef"),
                "configurationFingerprint": _require_digest(item["configurationFingerprint"], "configurationFingerprint"),
            }
        )
    normalized.sort(key=lambda item: (item["capability"], item["profileRef"].encode("utf-8"), item["configurationFingerprint"]))
    keys = [(item["capability"], item["profileRef"]) for item in normalized]
    if len(keys) != len(set(keys)):
        raise TaskManifestError("TASK_MANIFEST_DUPLICATE", "serviceConfigurations contains a duplicate capability/profile")
    return normalized


def _subject(value: Any, *, work_reuse: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TaskManifestError("TASK_MANIFEST_INVALID", "Task subject must be an object")
    kind = value.get("kind")
    if kind == "project_task":
        optional = {"cardPlanSetDigest"} if work_reuse else set()
        _require_exact_fields(
            value,
            {"kind", "projectId", "projectRevision", "inputArtifacts", "sourceSnapshotDigests", "learningContractRevision"},
            optional,
            "project task subject",
        )
        result = {
            "kind": kind,
            "projectId": _require_text(value["projectId"], "projectId"),
            "projectRevision": _require_revision(value["projectRevision"], "projectRevision"),
            "inputArtifacts": _artifact_inputs(value["inputArtifacts"]),
            "sourceSnapshotDigests": _sorted_digests(value["sourceSnapshotDigests"], "sourceSnapshotDigest"),
            "learningContractRevision": _require_revision(value["learningContractRevision"], "learningContractRevision"),
        }
        if work_reuse and "cardPlanSetDigest" in value:
            result["cardPlanSetDigest"] = _require_digest(value["cardPlanSetDigest"], "cardPlanSetDigest")
        return result
    if kind == "profile_validation":
        optional = set() if work_reuse else {"configurationSessionRef"}
        _require_exact_fields(value, {"kind", "profileRef", "configurationFingerprint", "credentialRevision"}, optional, "profile validation subject")
        result = {
            "kind": kind,
            "profileRef": _require_text(value["profileRef"], "profileRef"),
            "configurationFingerprint": _require_digest(value["configurationFingerprint"], "configurationFingerprint"),
            "credentialRevision": _require_revision(value["credentialRevision"], "credentialRevision", allow_zero=True),
        }
        if not work_reuse and "configurationSessionRef" in value:
            result["configurationSessionRef"] = _require_text(value["configurationSessionRef"], "configurationSessionRef")
        return result
    raise TaskManifestError("TASK_MANIFEST_INVALID", "Task subject kind is invalid")


def build_work_reuse_manifest(
    *,
    action_id: str,
    subject: Mapping[str, Any],
    component_versions: Mapping[str, Any],
    service_configurations: Sequence[Mapping[str, Any]],
    generation_policy_digest: str | None = None,
    work_partition_policy_digest: str | None = None,
) -> tuple[dict[str, Any], str]:
    manifest: dict[str, Any] = {
        "schema": "study.work-reuse.manifest",
        "schemaVersion": 1,
        "actionId": _action(action_id),
        "subject": _subject(subject, work_reuse=True),
        "componentVersions": _component_versions(component_versions),
        "serviceConfigurations": _work_service_configurations(service_configurations),
    }
    if generation_policy_digest is not None:
        manifest["generationPolicyDigest"] = _require_digest(generation_policy_digest, "generationPolicyDigest")
    if work_partition_policy_digest is not None:
        manifest["workPartitionPolicyDigest"] = _require_digest(work_partition_policy_digest, "workPartitionPolicyDigest")
    return manifest, _digest(manifest)


def build_capability_binding(required: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], str]:
    if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
        raise TaskManifestError("TASK_MANIFEST_INVALID", "Capability requirements must be a list")
    normalized: list[dict[str, Any]] = []
    for item in required:
        if item.get("kind") == "fixed":
            _require_exact_fields(item, {"kind", "capabilityId", "implementationVersionOrDigest", "compatibilityContractVersion"}, set(), "fixed capability")
            if item["capabilityId"] not in FIXED_CAPABILITIES:
                raise TaskManifestError("TASK_MANIFEST_INVALID", "Fixed capability is invalid")
            normalized.append({name: _require_text(item[name], name) for name in ("kind", "capabilityId", "implementationVersionOrDigest", "compatibilityContractVersion")})
        elif item.get("kind") == "service_profile":
            fields = {"kind", "capability", "profileRef", "configurationFingerprint", "credentialRevision", "implementationVersionOrDigest", "compatibilityContractVersion"}
            _require_exact_fields(item, fields, set(), "service profile capability")
            if item["capability"] not in SERVICE_CAPABILITIES:
                raise TaskManifestError("TASK_MANIFEST_INVALID", "Service capability is invalid")
            normalized.append(
                {
                    "kind": "service_profile",
                    "capability": item["capability"],
                    "profileRef": _require_text(item["profileRef"], "profileRef"),
                    "configurationFingerprint": _require_digest(item["configurationFingerprint"], "configurationFingerprint"),
                    "credentialRevision": _require_revision(item["credentialRevision"], "credentialRevision", allow_zero=True),
                    "implementationVersionOrDigest": _require_text(item["implementationVersionOrDigest"], "implementationVersionOrDigest"),
                    "compatibilityContractVersion": _require_text(item["compatibilityContractVersion"], "compatibilityContractVersion"),
                }
            )
        else:
            raise TaskManifestError("TASK_MANIFEST_INVALID", "Capability requirement kind is invalid")
    normalized.sort(key=lambda item: canonical_json_bytes(item))
    encoded = [canonical_json_bytes(item) for item in normalized]
    if len(encoded) != len(set(encoded)):
        raise TaskManifestError("TASK_MANIFEST_DUPLICATE", "Capability requirements contain a duplicate")
    manifest = {"schema": "study.capability.binding", "schemaVersion": 1, "required": normalized}
    return manifest, _digest(manifest)


def build_authorization_binding(
    *,
    audience: ArtifactAudienceBinding,
    service_instance_id: str,
    bindings: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], str]:
    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
        raise TaskManifestError("TASK_MANIFEST_INVALID", "Authorization bindings must be a list")
    normalized: list[dict[str, Any]] = []
    for item in bindings:
        fields = {"action", "authorizationRecordDigest", "constraintsDigest", "exactScopeDigest", "expectedRevocationEpoch"}
        _require_exact_fields(item, fields, set(), "authorization binding")
        normalized.append(
            {
                "action": _require_text(item["action"], "authorization action"),
                "authorizationRecordDigest": _require_digest(item["authorizationRecordDigest"], "authorizationRecordDigest"),
                "constraintsDigest": _require_digest(item["constraintsDigest"], "constraintsDigest"),
                "exactScopeDigest": _require_digest(item["exactScopeDigest"], "exactScopeDigest"),
                "expectedRevocationEpoch": _require_revision(item["expectedRevocationEpoch"], "expectedRevocationEpoch", allow_zero=True),
            }
        )
        if normalized[-1]["action"] not in AUTHORIZATION_ACTIONS:
            raise TaskManifestError("TASK_MANIFEST_INVALID", "Authorization action is invalid")
    normalized.sort(key=lambda item: (item["action"].encode("utf-8"), item["authorizationRecordDigest"], item["exactScopeDigest"], item["expectedRevocationEpoch"]))
    encoded = [canonical_json_bytes(item) for item in normalized]
    if len(encoded) != len(set(encoded)):
        raise TaskManifestError("TASK_MANIFEST_DUPLICATE", "Authorization bindings contain a duplicate")
    manifest = {
        "schema": "study.authorization.binding",
        "schemaVersion": 1,
        "audience": {
            "osUserSidDigest": _require_digest(audience.owner_digest, "osUserSidDigest"),
            "hostInstanceId": _require_text(audience.host_id, "hostInstanceId"),
            "pluginInstanceId": _require_text(audience.plugin_id, "pluginInstanceId"),
            "serviceInstanceId": _require_text(service_instance_id, "serviceInstanceId"),
            "sessionId": _require_text(audience.session_id, "sessionId"),
        },
        "bindings": normalized,
    }
    return manifest, _digest(manifest)


def _task_service_bindings(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in values:
        fields = {"capability", "profileRef", "configurationFingerprint", "credentialRevision"}
        _require_exact_fields(item, fields, {"egressManifestDigest"}, "task service binding")
        if item["capability"] not in SERVICE_CAPABILITIES:
            raise TaskManifestError("TASK_MANIFEST_INVALID", "Service capability is invalid")
        result = {
            "capability": item["capability"],
            "profileRef": _require_text(item["profileRef"], "profileRef"),
            "configurationFingerprint": _require_digest(item["configurationFingerprint"], "configurationFingerprint"),
            "credentialRevision": _require_revision(item["credentialRevision"], "credentialRevision", allow_zero=True),
        }
        if "egressManifestDigest" in item:
            result["egressManifestDigest"] = _require_digest(item["egressManifestDigest"], "egressManifestDigest")
        normalized.append(result)
    normalized.sort(key=lambda item: (item["capability"], item["profileRef"].encode("utf-8"), item["configurationFingerprint"], item["credentialRevision"]))
    keys = [(item["capability"], item["profileRef"]) for item in normalized]
    if len(keys) != len(set(keys)):
        raise TaskManifestError("TASK_MANIFEST_DUPLICATE", "Task service bindings contain a duplicate")
    return normalized


def build_task_input_manifest(
    *,
    action_id: str,
    work_reuse_manifest: Mapping[str, Any],
    work_reuse_digest: str,
    subject: Mapping[str, Any],
    authorization_binding_digest: str,
    capability_binding_digest: str,
    component_versions: Mapping[str, Any],
    service_bindings: Sequence[Mapping[str, Any]],
    operation_intent_digest: str | None = None,
    generation_policy_digest: str | None = None,
    cost_budget_digest: str | None = None,
    batch_policy_digest: str | None = None,
    successor_rebase_digest: str | None = None,
) -> tuple[dict[str, Any], str]:
    _require_exact_fields(
        work_reuse_manifest,
        {"schema", "schemaVersion", "actionId", "subject", "componentVersions", "serviceConfigurations"},
        {"generationPolicyDigest", "workPartitionPolicyDigest"},
        "work reuse manifest",
    )
    if work_reuse_manifest.get("schema") != "study.work-reuse.manifest" or work_reuse_manifest.get("schemaVersion") != 1:
        raise TaskManifestError("TASK_MANIFEST_INVALID", "Work reuse manifest schema is invalid")
    if _digest(work_reuse_manifest) != _require_digest(work_reuse_digest, "workReuseDigest"):
        raise TaskManifestError("TASK_MANIFEST_MISMATCH", "Work reuse manifest digest does not match")
    if work_reuse_manifest.get("actionId") != action_id:
        raise TaskManifestError("TASK_MANIFEST_MISMATCH", "Task action does not match work reuse action")
    normalized_subject = _subject(subject, work_reuse=False)
    work_subject = work_reuse_manifest.get("subject")
    comparable = dict(work_subject) if isinstance(work_subject, Mapping) else {}
    comparable.pop("cardPlanSetDigest", None)
    comparable.pop("configurationSessionRef", None)
    subject_comparable = dict(normalized_subject)
    subject_comparable.pop("configurationSessionRef", None)
    if comparable != subject_comparable:
        raise TaskManifestError("TASK_MANIFEST_MISMATCH", "Task subject does not match work reuse subject")
    normalized_components = _component_versions(component_versions)
    if normalized_components != work_reuse_manifest.get("componentVersions"):
        raise TaskManifestError("TASK_MANIFEST_MISMATCH", "Task component versions do not match work reuse identity")
    normalized_services = _task_service_bindings(service_bindings)
    work_services = _work_service_configurations(work_reuse_manifest.get("serviceConfigurations"))
    projected_services = [
        {name: item[name] for name in ("capability", "profileRef", "configurationFingerprint")}
        for item in normalized_services
    ]
    if projected_services != work_services:
        raise TaskManifestError("TASK_MANIFEST_MISMATCH", "Task service bindings do not match work reuse configuration")
    if generation_policy_digest != work_reuse_manifest.get("generationPolicyDigest"):
        raise TaskManifestError("TASK_MANIFEST_MISMATCH", "Task generation policy does not match work reuse identity")
    manifest: dict[str, Any] = {
        "schema": "study.task.input-manifest",
        "schemaVersion": 1,
        "actionId": _action(action_id),
        "workReuseDigest": work_reuse_digest,
        "subject": normalized_subject,
        "authorizationBindingDigest": _require_digest(authorization_binding_digest, "authorizationBindingDigest"),
        "capabilityBindingDigest": _require_digest(capability_binding_digest, "capabilityBindingDigest"),
        "componentVersions": normalized_components,
        "serviceBindings": normalized_services,
    }
    optional = {
        "operationIntentDigest": operation_intent_digest,
        "generationPolicyDigest": generation_policy_digest,
        "costBudgetDigest": cost_budget_digest,
        "batchPolicyDigest": batch_policy_digest,
        "successorRebaseDigest": successor_rebase_digest,
    }
    for name, value in optional.items():
        if value is not None:
            manifest[name] = _require_digest(value, name)
    return manifest, _digest(manifest)


def build_successor_rebase(
    *,
    predecessor_task_id: str,
    predecessor_task_input_digest: str,
    successor_task_id: str,
    work_reuse_digest: str,
    scope_relation: str,
    reused_work_units: Sequence[Mapping[str, Any]],
    predecessor_authorization_audit_ref: str,
    successor_authorization_audit_ref: str,
) -> tuple[dict[str, Any], str]:
    if scope_relation not in {"equivalent", "narrower"}:
        raise TaskManifestError("TASK_MANIFEST_INVALID", "Successor authorization scope must be equivalent or narrower")
    normalized_units: list[dict[str, Any]] = []
    for unit in reused_work_units:
        _require_exact_fields(unit, {"workUnitId", "resultArtifactDigests"}, set(), "reused work unit")
        normalized_units.append(
            {
                "workUnitId": _require_text(unit["workUnitId"], "workUnitId"),
                "resultArtifactDigests": _sorted_digests(unit["resultArtifactDigests"], "resultArtifactDigest"),
            }
        )
    normalized_units.sort(key=lambda item: item["workUnitId"].encode("utf-8"))
    if len(normalized_units) != len({item["workUnitId"] for item in normalized_units}):
        raise TaskManifestError("TASK_MANIFEST_DUPLICATE", "Reused work units contain a duplicate")
    manifest = {
        "schema": "study.task.successor-rebase",
        "schemaVersion": 1,
        "predecessorTaskId": _require_text(predecessor_task_id, "predecessorTaskId"),
        "predecessorTaskInputDigest": _require_digest(predecessor_task_input_digest, "predecessorTaskInputDigest"),
        "successorTaskId": _require_text(successor_task_id, "successorTaskId"),
        "workReuseDigest": _require_digest(work_reuse_digest, "workReuseDigest"),
        "scopeRelation": scope_relation,
        "reusedWorkUnits": normalized_units,
        "predecessorAuthorizationAuditRef": _require_text(predecessor_authorization_audit_ref, "predecessorAuthorizationAuditRef"),
        "successorAuthorizationAuditRef": _require_text(successor_authorization_audit_ref, "successorAuthorizationAuditRef"),
    }
    return manifest, _digest(manifest)
