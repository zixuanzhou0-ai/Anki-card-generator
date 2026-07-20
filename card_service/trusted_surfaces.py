from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .broker_authorization_issuer import (
    BrokerAuthorizationIssuer,
    BrokerAuthorizationIssuerError,
    IssuedBrokerAuthorization,
)
from .credentials import PROFILE_REF_PATTERN, CredentialBackend
from .process_isolation import ProcessIsolationError, TaskOwnedProcessGroup
from .storage import AtomicJsonStore
from .trusted_surface_auth import (
    encode_response_key,
    new_response_key,
    open_private_payload,
    verify_response,
)


RESOURCE_ATTESTATION_LIFETIME_MS = 5 * 60 * 1_000
IMPORT_CONSENT_ATTESTATION_LIFETIME_MS = 5 * 60 * 1_000
AUTHORIZATION_REVOCATION_ATTESTATION_LIFETIME_MS = 5 * 60 * 1_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMPORT_INTENT_RE = re.compile(r"^anki_intent_[0-9a-f]{48}$")
OPERATION_INTENT_RE = re.compile(r"^intent_[0-9a-f]{48}$")
AUTHORIZATION_SELECTION_RE = re.compile(r"^authsel_[A-Za-z0-9_-]{32}$")


class TrustedSurfaceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TrustedLocalResourceSelection:
    session_ref: str
    kind: str
    path: Path
    attestation_ref: str
    selected_at: int


@dataclass(frozen=True)
class TrustedNetworkResourceSelection:
    session_ref: str
    source_kind: str
    raw_url: str
    attestation_ref: str
    selected_at: int


@dataclass(frozen=True)
class TrustedImportConsentDecision:
    session_ref: str
    import_intent_id: str
    decision: str
    attestation_ref: str
    decided_at: int


@dataclass(frozen=True)
class TrustedOperationConsentDecision:
    session_ref: str
    operation_intent_id: str
    decision: str
    attestation_digest: str
    decided_at: int


@dataclass(frozen=True)
class TrustedAuthorizationRevocationSelection:
    session_ref: str
    selection_ref: str
    kind: str
    locator: dict[str, Any]
    attestation_ref: str
    selected_at: int


@dataclass
class _SurfaceProcess:
    process: subprocess.Popen[str]
    process_group: TaskOwnedProcessGroup


class TrustedSurfaceManager:
    """Launches digest-pinned local settings/consent windows outside model context."""

    def __init__(
        self,
        *,
        state_dir: str | Path,
        python_path: str | Path | None = None,
        surface_path: str | Path | None = None,
        credential_backend: CredentialBackend | None = None,
    ) -> None:
        root = Path(state_dir).expanduser()
        if not root.is_absolute():
            raise TrustedSurfaceError("INVALID_STATE_PATH", "Trusted surface state directory must be absolute")
        self.root = root.resolve()
        self.sessions_dir = self.root / "sessions"
        self.responses_dir = self.root / "responses"
        self.credential_state_dir = self.root / "credentials"
        for directory in (self.sessions_dir, self.responses_dir, self.credential_state_dir):
            directory.mkdir(parents=True, exist_ok=True)
        package_dir = Path(__file__).resolve().parent
        python_candidate = Path(python_path) if python_path is not None else Path(sys.executable)
        surface_candidate = Path(surface_path) if surface_path is not None else package_dir / "trusted_surface_ui.py"
        if not python_candidate.is_absolute() or not surface_candidate.is_absolute():
            raise TrustedSurfaceError("RELATIVE_RUNTIME_PATH", "Trusted surface runtime paths must be absolute")
        self.python_path = python_candidate.resolve(strict=True)
        self.surface_path = surface_candidate.resolve(strict=True)
        self.bootstrap_path = (package_dir / "trusted_surface_bootstrap.py").resolve(strict=True)
        self.surface_sha256 = self._sha256(self.surface_path)
        self._processes: dict[str, _SurfaceProcess] = {}
        self._session_digests: dict[str, str] = {}
        self._response_keys: dict[str, bytes] = {}
        self._verified_responses: dict[str, dict[str, Any]] = {}
        self._credential_backend = credential_backend
        self._authorization_issuer: BrokerAuthorizationIssuer | None = None
        self._local_resource_selections: dict[str, TrustedLocalResourceSelection] = {}
        self._network_resource_selections: dict[
            str, TrustedNetworkResourceSelection
        ] = {}
        self._resource_attestations: dict[str, dict[str, Any]] = {}
        self._import_consent_decisions: dict[str, TrustedImportConsentDecision] = {}
        self._import_consent_attestations: dict[str, dict[str, Any]] = {}
        self._operation_consent_decisions: dict[
            str, TrustedOperationConsentDecision
        ] = {}
        self._operation_consent_attestations: dict[str, dict[str, Any]] = {}
        self._authorization_manager_bindings: dict[
            str, dict[str, dict[str, Any]]
        ] = {}
        self._authorization_revocation_selections: dict[
            str, tuple[TrustedAuthorizationRevocationSelection, ...]
        ] = {}
        self._authorization_revocation_attestations: dict[str, dict[str, Any]] = {}
        self._issued_authorizations: dict[str, IssuedBrokerAuthorization] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _managed_environment(self) -> dict[str, str]:
        """Return the minimal environment required by the trusted GUI child.

        Trusted surfaces execute from an integrity-checked runtime snapshot.  They
        must never write import caches back into that snapshot, otherwise a
        successful first launch makes the next runtime verification fail.
        """

        safe_keys = (
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "PROGRAMDATA",
            "LANG",
        )
        environment = {key: os.environ[key] for key in safe_keys if key in os.environ}
        environment["PATH"] = str(self.python_path.parent)
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return environment

    def capabilities(self) -> dict[str, Any]:
        return {
            "localResourcePicker": True,
            "localResourcePickerResponseEncryptedAtRest": True,
            "localResourceAttestation": True,
            "localResourcePathDisclosure": False,
            "networkResourceInput": True,
            "networkResourceInputResponseEncryptedAtRest": True,
            "networkResourceUrlDisclosure": False,
            "localSettings": True,
            "consentWindow": True,
            "ankiImportConsentAttestation": True,
            "operationConsentAttestation": True,
            "authorizationManager": True,
            "authorizationRevocationAttestation": True,
            "digestPinned": True,
            "authenticatedResponse": True,
            "brokerAuthorizationIssuance": True,
            "authorizationPathDisclosure": False,
            "secretViaModel": False,
            # The manager coordinates multiple independently authenticated ledgers.
            # It is not a single transactional authorization ledger.
            "authorizationLedger": False,
            "complete": False,
        }

    def _write_request(self, request: dict[str, Any]) -> Path:
        path = self.sessions_dir / f"{request['sessionRef']}.json"
        AtomicJsonStore._write_atomic(path, request)
        serialized = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self._session_digests[str(request["sessionRef"])] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return path

    def create_local_settings_session(self, *, profile_ref: str, capability: str) -> dict[str, Any]:
        if not PROFILE_REF_PATTERN.fullmatch(profile_ref):
            raise TrustedSurfaceError("INVALID_PROFILE_REF", "Invalid local settings profile reference")
        if capability not in {"model", "tts", "anki_connect"}:
            raise TrustedSurfaceError("INVALID_CAPABILITY", "Invalid local settings capability")
        return self._create_session(
            "local_settings",
            profileRef=profile_ref,
            capability=capability,
            credentialStateDir=str(self.credential_state_dir),
        )

    def create_consent_session(self, *, title: str, summary: str, purpose: str) -> dict[str, Any]:
        if purpose not in {"source_access", "output_access", "network_access", "operation", "anki_import"}:
            raise TrustedSurfaceError("INVALID_CONSENT_PURPOSE", "Invalid consent purpose")
        if not title.strip() or not summary.strip() or len(title) > 120 or len(summary) > 2_000:
            raise TrustedSurfaceError("INVALID_CONSENT_COPY", "Consent title or summary is invalid")
        return self._create_session("consent", title=title.strip(), summary=summary.strip(), purpose=purpose)

    def create_anki_import_consent_session(
        self,
        *,
        import_intent_id: str,
        audience_digest: str,
        import_plan_digest: str,
        summary: str,
    ) -> dict[str, Any]:
        if not IMPORT_INTENT_RE.fullmatch(import_intent_id):
            raise TrustedSurfaceError(
                "INVALID_IMPORT_INTENT", "Invalid Anki import intent"
            )
        if not SHA256_RE.fullmatch(audience_digest) or not SHA256_RE.fullmatch(
            import_plan_digest
        ):
            raise TrustedSurfaceError(
                "INVALID_IMPORT_CONSENT_BINDING", "Invalid Anki consent binding"
            )
        copy = str(summary or "").strip()
        if not copy or len(copy) > 2_000:
            raise TrustedSurfaceError(
                "INVALID_CONSENT_COPY", "Consent summary is invalid"
            )
        return self._create_session(
            "consent",
            title="确认导入 Anki",
            summary=copy,
            purpose="anki_import",
            confirmationKind="anki_import",
            importIntentId=import_intent_id,
            audienceDigest=audience_digest,
            importPlanDigest=import_plan_digest,
        )

    def create_operation_consent_session(
        self,
        *,
        operation_intent_id: str,
        audience_digest: str,
        intent_digest: str,
        action_id: str,
        summary: str,
    ) -> dict[str, Any]:
        if not OPERATION_INTENT_RE.fullmatch(operation_intent_id):
            raise TrustedSurfaceError(
                "INVALID_OPERATION_INTENT", "Invalid operation intent"
            )
        if not SHA256_RE.fullmatch(audience_digest) or not SHA256_RE.fullmatch(
            intent_digest
        ):
            raise TrustedSurfaceError(
                "INVALID_OPERATION_CONSENT_BINDING",
                "Invalid operation consent binding",
            )
        if (
            not isinstance(action_id, str)
            or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", action_id) is None
        ):
            raise TrustedSurfaceError(
                "INVALID_OPERATION_CONSENT_BINDING",
                "Invalid operation consent action",
            )
        copy = str(summary or "").strip()
        if not copy or len(copy) > 2_000:
            raise TrustedSurfaceError(
                "INVALID_CONSENT_COPY", "Consent summary is invalid"
            )
        return self._create_session(
            "consent",
            title="确认远程服务操作",
            summary=copy,
            purpose="operation",
            confirmationKind="operation_intent",
            operationIntentId=operation_intent_id,
            audienceDigest=audience_digest,
            intentDigest=intent_digest,
            actionId=action_id,
        )

    def create_local_resource_session(
        self, *, kind: str, scope_summary: str
    ) -> dict[str, Any]:
        if kind not in {"file", "directory", "output_directory"}:
            raise TrustedSurfaceError(
                "INVALID_RESOURCE_KIND", "Invalid local resource selection kind"
            )
        summary = str(scope_summary or "").strip()
        if not summary or len(summary) > 1_000:
            raise TrustedSurfaceError(
                "INVALID_RESOURCE_SCOPE", "Invalid local resource scope summary"
            )
        return self._create_session(
            "local_resource_picker", selectionKind=kind, scopeSummary=summary
        )

    def create_network_resource_session(
        self, *, source_kind: str, scope_summary: str
    ) -> dict[str, Any]:
        if source_kind not in {"public_video", "web", "podcast", "other"}:
            raise TrustedSurfaceError(
                "INVALID_NETWORK_SOURCE_KIND", "Invalid network source kind"
            )
        summary = str(scope_summary or "").strip()
        if not summary or len(summary) > 1_000:
            raise TrustedSurfaceError(
                "INVALID_NETWORK_SCOPE", "Invalid network resource scope summary"
            )
        return self._create_session(
            "network_resource_input",
            sourceKind=source_kind,
            scopeSummary=summary,
        )

    def create_authorization_manager_session(
        self,
        *,
        audience_digest: str,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not SHA256_RE.fullmatch(audience_digest):
            raise TrustedSurfaceError(
                "INVALID_AUTHORIZATION_AUDIENCE",
                "Authorization manager audience is invalid",
            )
        if not isinstance(items, list) or not 1 <= len(items) <= 256:
            raise TrustedSurfaceError(
                "INVALID_AUTHORIZATION_ITEMS",
                "Authorization manager items are invalid",
            )
        public_items: list[dict[str, Any]] = []
        bindings: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict) or set(item) != {
                "kind",
                "title",
                "detail",
                "state",
                "locator",
            }:
                raise TrustedSurfaceError(
                    "INVALID_AUTHORIZATION_ITEMS",
                    "Authorization manager item is invalid",
                )
            kind = str(item["kind"])
            if kind not in {
                "local_resource",
                "network_resource",
                "anki_import",
                "broker_authorization",
                "operation_approval",
            }:
                raise TrustedSurfaceError(
                    "INVALID_AUTHORIZATION_ITEMS",
                    "Authorization manager item kind is invalid",
                )
            title = str(item["title"] or "").strip()
            detail = str(item["detail"] or "").strip()
            state = str(item["state"] or "")
            locator = item["locator"]
            if (
                not title
                or len(title) > 160
                or not detail
                or len(detail) > 500
                or state not in {"active", "approved", "pending"}
                or not isinstance(locator, dict)
                or not locator
            ):
                raise TrustedSurfaceError(
                    "INVALID_AUTHORIZATION_ITEMS",
                    "Authorization manager item metadata is invalid",
                )
            selection_ref = "authsel_" + secrets.token_urlsafe(24)
            bindings[selection_ref] = {
                "kind": kind,
                "locator": json.loads(json.dumps(locator, ensure_ascii=False)),
            }
            public_items.append(
                {
                    "selectionRef": selection_ref,
                    "kind": kind,
                    "title": title,
                    "detail": detail,
                    "state": state,
                }
            )
        session = self._create_session(
            "authorization_manager",
            audienceDigest=audience_digest,
            authorizationItems=public_items,
        )
        with self._lock:
            self._authorization_manager_bindings[str(session["sessionRef"])] = bindings
        return session

    def _issuer(self) -> BrokerAuthorizationIssuer:
        with self._lock:
            if self._authorization_issuer is None:
                try:
                    self._authorization_issuer = BrokerAuthorizationIssuer(
                        state_dir=self.root,
                        credential_backend=self._credential_backend,
                    )
                except (BrokerAuthorizationIssuerError, RuntimeError) as error:
                    code = getattr(error, "code", "BROKER_AUTHORIZATION_ISSUER_UNAVAILABLE")
                    raise TrustedSurfaceError(code, str(error)) from error
            return self._authorization_issuer

    def create_broker_authorization_session(self, draft: Any) -> dict[str, Any]:
        try:
            prepared = self._issuer().prepare(draft)
        except BrokerAuthorizationIssuerError as error:
            raise TrustedSurfaceError(error.code, str(error)) from error
        return self._create_session(
            "consent",
            title=prepared.title,
            summary=prepared.summary,
            purpose="network_access",
            authorizationKind="broker_startup",
            brokerAuthorization=prepared.value,
        )

    def issued_authorization(self, session_ref: str) -> IssuedBrokerAuthorization | None:
        """Internal-only handoff; public session results never contain this object or path."""
        with self._lock:
            return self._issued_authorizations.get(session_ref)

    def _create_session(self, surface: str, **fields: Any) -> dict[str, Any]:
        session_ref = str(uuid.uuid4())
        nonce = uuid.uuid4().hex + uuid.uuid4().hex
        response_path = (self.responses_dir / f"{session_ref}.json").resolve()
        request = {
            "schemaVersion": 1,
            "sessionRef": session_ref,
            "requestNonce": nonce,
            "surface": surface,
            "responsePath": str(response_path),
            "createdAt": int(time.time() * 1000),
            **fields,
        }
        self._write_request(request)
        return {
            "sessionRef": session_ref,
            "surface": surface,
            "state": "created",
        }

    def _load_request(self, session_ref: str) -> tuple[Path, dict[str, Any]]:
        request_path = self.sessions_dir / f"{session_ref}.json"
        if not request_path.is_file():
            raise TrustedSurfaceError("SESSION_NOT_FOUND", "Trusted surface session does not exist")
        with request_path.open("r", encoding="utf-8") as handle:
            request = json.load(handle)
        expected_response = (self.responses_dir / f"{session_ref}.json").resolve()
        if (
            not isinstance(request, dict)
            or request.get("sessionRef") != session_ref
            or request.get("surface") not in {
                "local_settings",
                "consent",
                "local_resource_picker",
                "network_resource_input",
                "authorization_manager",
            }
            or not isinstance(request.get("requestNonce"), str)
            or len(request["requestNonce"]) != 64
            or Path(str(request.get("responsePath") or "")) != expected_response
        ):
            raise TrustedSurfaceError("SESSION_REQUEST_INVALID", "Trusted surface request was modified")
        serialized = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected_digest = self._session_digests.get(session_ref)
        if expected_digest is None or hashlib.sha256(serialized.encode("utf-8")).hexdigest() != expected_digest:
            raise TrustedSurfaceError("SESSION_REQUEST_INVALID", "Trusted surface request digest changed")
        return request_path, request

    def launch(self, session_ref: str) -> dict[str, Any]:
        request_path, request = self._load_request(session_ref)
        with self._lock:
            if (
                session_ref in self._processes
                or session_ref in self._response_keys
                or session_ref in self._verified_responses
            ):
                raise TrustedSurfaceError("SESSION_ALREADY_LAUNCHED", "Trusted surface session was already launched")
        if self._sha256(self.surface_path) != self.surface_sha256:
            raise TrustedSurfaceError("SURFACE_DIGEST_CHANGED", "Trusted surface code changed after service start")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            [
                str(self.python_path), "-I", "-B", str(self.bootstrap_path), str(self.surface_path),
                self.surface_sha256, str(request["surface"]), str(request_path.resolve()),
            ],
            cwd=str(self.surface_path.parent.parent),
            env=self._managed_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creationflags,
        )
        process_group = TaskOwnedProcessGroup(memory_limit_bytes=512 * 1024 * 1024, active_process_limit=2)
        try:
            process_group.assign(process)
        except ProcessIsolationError as error:
            process.terminate()
            process_group.close()
            raise TrustedSurfaceError("SURFACE_ISOLATION_FAILED", str(error)) from error
        assert process.stdin is not None
        response_key = new_response_key()
        frozen_request = json.dumps(
            {**request, "responseAuthKey": encode_response_key(response_key)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        process.stdin.write(b"START\n" + frozen_request)
        process.stdin.close()
        with self._lock:
            self._processes[session_ref] = _SurfaceProcess(process=process, process_group=process_group)
            self._response_keys[session_ref] = response_key
        threading.Thread(target=self._monitor, args=(session_ref,), daemon=True).start()
        return {"sessionRef": session_ref, "surface": request["surface"], "state": "open"}

    def _monitor(self, session_ref: str) -> None:
        with self._lock:
            runtime = self._processes.get(session_ref)
        if runtime is None:
            return
        exit_code = runtime.process.wait()
        try:
            runtime.process_group.close()
        except ProcessIsolationError:
            pass
        with self._lock:
            self._processes.pop(session_ref, None)
        response_path = self.responses_dir / f"{session_ref}.json"
        if exit_code != 0 and not response_path.exists():
            failure = {"schemaVersion": 1, "sessionRef": session_ref, "state": "failed", "errorCode": "SURFACE_EXITED"}
            AtomicJsonStore._write_atomic(response_path, failure)
            with self._lock:
                self._verified_responses[session_ref] = failure
                self._response_keys.pop(session_ref, None)

    def _finalize_local_resource_response(
        self,
        request: dict[str, Any],
        response: dict[str, Any],
        response_key: bytes,
    ) -> dict[str, Any]:
        session_ref = str(request["sessionRef"])
        if response.get("state") == "cancelled":
            return {
                "schemaVersion": 1,
                "sessionRef": session_ref,
                "state": "cancelled",
                "userGestureRecorded": False,
            }
        if response.get("state") != "selected" or response.get("userGestureRecorded") is not True:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID", "Trusted resource selection was not user approved"
            )
        try:
            private = open_private_payload(
                response.get("privatePayload") or {},
                response_key,
                session_ref=session_ref,
                request_nonce=str(request["requestNonce"]),
                surface="local_resource_picker",
            )
        except (TypeError, ValueError) as error:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID", "Trusted resource selection payload is invalid"
            ) from error
        if set(private) != {"schemaVersion", "selectedPath"} or private.get("schemaVersion") != 1:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID", "Trusted resource selection payload is invalid"
            )
        raw_path = private.get("selectedPath")
        if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID", "Trusted resource selection path is invalid"
            )
        selected = Path(raw_path).expanduser()
        if not selected.is_absolute():
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID", "Trusted resource selection path is invalid"
            )
        selected = Path(os.path.normpath(os.path.abspath(os.fspath(selected))))
        try:
            selected_info = selected.lstat()
        except OSError as error:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID", "Trusted resource selection is unavailable"
            ) from error
        kind = str(request.get("selectionKind") or "")
        is_reparse = bool(
            getattr(selected_info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        if stat.S_ISLNK(selected_info.st_mode) or is_reparse or (
            kind == "file" and not stat.S_ISREG(selected_info.st_mode)
        ) or (
            kind in {"directory", "output_directory"}
            and not stat.S_ISDIR(selected_info.st_mode)
        ):
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID", "Trusted resource selection type changed"
            )
        try:
            selected.relative_to(self.root)
        except ValueError:
            pass
        else:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID", "Trusted surface state cannot be selected"
            )
        attestation_ref = "resource-attestation-" + secrets.token_urlsafe(24)
        selection = TrustedLocalResourceSelection(
            session_ref=session_ref,
            kind=kind,
            path=selected,
            attestation_ref=attestation_ref,
            selected_at=int(time.time() * 1000),
        )
        with self._lock:
            self._local_resource_selections[session_ref] = selection
            self._resource_attestations[attestation_ref] = {
                "sessionRef": session_ref,
                "action": "approve_local_resource",
                "audienceDigest": None,
                "requestDigest": None,
                "expiresAt": selection.selected_at + RESOURCE_ATTESTATION_LIFETIME_MS,
            }
        display_name = {
            "file": "Selected file",
            "directory": "Selected folder",
            "output_directory": "Selected output folder",
        }[kind]
        return {
            "schemaVersion": 1,
            "sessionRef": session_ref,
            "state": "selected",
            "userGestureRecorded": True,
            "resourceSelection": {
                "kind": kind,
                "displayName": display_name[:160],
                "pathDisclosure": False,
            },
        }

    def _finalize_network_resource_response(
        self,
        request: dict[str, Any],
        response: dict[str, Any],
        response_key: bytes,
    ) -> dict[str, Any]:
        session_ref = str(request["sessionRef"])
        if response.get("state") == "cancelled":
            return {
                "schemaVersion": 1,
                "sessionRef": session_ref,
                "state": "cancelled",
                "userGestureRecorded": False,
            }
        if response.get("state") != "selected" or response.get(
            "userGestureRecorded"
        ) is not True:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID",
                "Trusted network resource input was not user approved",
            )
        try:
            private = open_private_payload(
                response.get("privatePayload") or {},
                response_key,
                session_ref=session_ref,
                request_nonce=str(request["requestNonce"]),
                surface="network_resource_input",
            )
        except (TypeError, ValueError) as error:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID",
                "Trusted network resource payload is invalid",
            ) from error
        if set(private) != {"schemaVersion", "rawUrl"} or private.get(
            "schemaVersion"
        ) != 1:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID",
                "Trusted network resource payload is invalid",
            )
        raw_url = private.get("rawUrl")
        if (
            not isinstance(raw_url, str)
            or not raw_url.strip()
            or len(raw_url) > 16 * 1024
            or any(ord(character) < 0x20 for character in raw_url)
        ):
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID",
                "Trusted network resource URL is invalid",
            )
        selected_at = int(time.time() * 1000)
        attestation_ref = "network-attestation-" + secrets.token_urlsafe(24)
        selection = TrustedNetworkResourceSelection(
            session_ref=session_ref,
            source_kind=str(request["sourceKind"]),
            raw_url=raw_url.strip(),
            attestation_ref=attestation_ref,
            selected_at=selected_at,
        )
        with self._lock:
            self._network_resource_selections[session_ref] = selection
            self._resource_attestations[attestation_ref] = {
                "sessionRef": session_ref,
                "action": "approve_network_resource",
                "audienceDigest": None,
                "requestDigest": None,
                "expiresAt": selected_at + RESOURCE_ATTESTATION_LIFETIME_MS,
            }
        return {
            "schemaVersion": 1,
            "sessionRef": session_ref,
            "state": "selected",
            "userGestureRecorded": True,
            "networkSelection": {
                "sourceKind": selection.source_kind,
                "urlDisclosure": False,
            },
        }

    def _finalize_authorization_manager_response(
        self,
        request: dict[str, Any],
        response: dict[str, Any],
        response_key: bytes,
    ) -> dict[str, Any]:
        session_ref = str(request["sessionRef"])
        if response.get("state") == "cancelled":
            return {
                "schemaVersion": 1,
                "sessionRef": session_ref,
                "state": "cancelled",
                "userGestureRecorded": False,
                "authorizationRevocation": {
                    "selectedCount": 0,
                    "availableCount": len(request.get("authorizationItems") or []),
                },
            }
        if response.get("state") != "approved" or response.get(
            "userGestureRecorded"
        ) is not True:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID",
                "Trusted authorization revocation was not user approved",
            )
        try:
            private = open_private_payload(
                response.get("privatePayload") or {},
                response_key,
                session_ref=session_ref,
                request_nonce=str(request["requestNonce"]),
                surface="authorization_manager",
            )
        except (TypeError, ValueError) as error:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID",
                "Trusted authorization revocation payload is invalid",
            ) from error
        if set(private) != {"schemaVersion", "selectedRefs"} or private.get(
            "schemaVersion"
        ) != 1:
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID",
                "Trusted authorization revocation payload is invalid",
            )
        selected_refs = private.get("selectedRefs")
        if (
            not isinstance(selected_refs, list)
            or not 1 <= len(selected_refs) <= 256
            or any(
                not isinstance(value, str)
                or not AUTHORIZATION_SELECTION_RE.fullmatch(value)
                for value in selected_refs
            )
            or len(set(selected_refs)) != len(selected_refs)
        ):
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID",
                "Trusted authorization revocation selection is invalid",
            )
        with self._lock:
            bindings = self._authorization_manager_bindings.get(session_ref)
        if bindings is None or any(value not in bindings for value in selected_refs):
            raise TrustedSurfaceError(
                "SESSION_RESPONSE_INVALID",
                "Trusted authorization revocation selection is stale",
            )
        selected_at = int(time.time() * 1000)
        audience_digest = str(request.get("audienceDigest") or "")
        selections: list[TrustedAuthorizationRevocationSelection] = []
        for selection_ref in selected_refs:
            binding = bindings[selection_ref]
            kind = str(binding["kind"])
            locator = json.loads(json.dumps(binding["locator"], ensure_ascii=False))
            if kind == "local_resource":
                if (
                    set(locator) != {"resourceRef", "revocationEpoch"}
                    or not isinstance(locator.get("resourceRef"), str)
                    or isinstance(locator.get("revocationEpoch"), bool)
                    or not isinstance(locator.get("revocationEpoch"), int)
                ):
                    raise TrustedSurfaceError(
                        "SESSION_RESPONSE_INVALID",
                        "Trusted resource revocation binding is invalid",
                    )
                action = "revoke_local_resource"
            elif kind == "network_resource":
                if (
                    set(locator) != {"networkResourceRef", "revocationEpoch"}
                    or not isinstance(locator.get("networkResourceRef"), str)
                    or re.fullmatch(
                        r"network_[A-Za-z0-9_-]{43}",
                        locator["networkResourceRef"],
                    )
                    is None
                    or isinstance(locator.get("revocationEpoch"), bool)
                    or not isinstance(locator.get("revocationEpoch"), int)
                ):
                    raise TrustedSurfaceError(
                        "SESSION_RESPONSE_INVALID",
                        "Trusted network revocation binding is invalid",
                    )
                action = "revoke_network_resource"
            elif kind == "anki_import":
                if set(locator) != {"importIntentId"} or not IMPORT_INTENT_RE.fullmatch(
                    str(locator.get("importIntentId") or "")
                ):
                    raise TrustedSurfaceError(
                        "SESSION_RESPONSE_INVALID",
                        "Trusted import revocation binding is invalid",
                    )
                action = "revoke"
            elif kind == "broker_authorization":
                if (
                    set(locator) != {"activeAuthorization", "authorizationDigest"}
                    or locator.get("activeAuthorization") is not True
                    or not isinstance(locator.get("authorizationDigest"), str)
                    or not re.fullmatch(
                        r"sha256:[0-9a-f]{64}", locator["authorizationDigest"]
                    )
                ):
                    raise TrustedSurfaceError(
                        "SESSION_RESPONSE_INVALID",
                        "Trusted broker revocation binding is invalid",
                    )
                action = "revoke_broker_authorization"
            elif kind == "operation_approval":
                if (
                    set(locator)
                    != {"operationIntentId", "intentDigest", "audienceDigest"}
                    or not OPERATION_INTENT_RE.fullmatch(
                        str(locator.get("operationIntentId") or "")
                    )
                    or not SHA256_RE.fullmatch(
                        str(locator.get("intentDigest") or "")
                    )
                    or not SHA256_RE.fullmatch(
                        str(locator.get("audienceDigest") or "")
                    )
                ):
                    raise TrustedSurfaceError(
                        "SESSION_RESPONSE_INVALID",
                        "Trusted operation approval binding is invalid",
                    )
                action = "revoke_operation"
            else:
                raise TrustedSurfaceError(
                    "SESSION_RESPONSE_INVALID",
                    "Trusted authorization revocation kind is invalid",
                )
            attestation_ref = (
                secrets.token_hex(32)
                if kind == "operation_approval"
                else "revoke-attestation-" + secrets.token_urlsafe(24)
            )
            selection = TrustedAuthorizationRevocationSelection(
                session_ref=session_ref,
                selection_ref=selection_ref,
                kind=kind,
                locator=locator,
                attestation_ref=attestation_ref,
                selected_at=selected_at,
            )
            selections.append(selection)
            with self._lock:
                if kind in {"local_resource", "network_resource"}:
                    self._resource_attestations[attestation_ref] = {
                        "sessionRef": session_ref,
                        "action": action,
                        "audienceDigest": audience_digest,
                        "requestDigest": None,
                        "expiresAt": (
                            selected_at
                            + AUTHORIZATION_REVOCATION_ATTESTATION_LIFETIME_MS
                        ),
                    }
                elif kind == "operation_approval":
                    self._operation_consent_attestations[attestation_ref] = {
                        "audienceDigest": locator["audienceDigest"],
                        "operationIntentId": locator["operationIntentId"],
                        "intentDigest": locator["intentDigest"],
                        "action": action,
                        "expiresAt": (
                            selected_at
                            + AUTHORIZATION_REVOCATION_ATTESTATION_LIFETIME_MS
                        ),
                    }
                else:
                    self._authorization_revocation_attestations[attestation_ref] = {
                        "sessionRef": session_ref,
                        "selectionRef": selection_ref,
                        "kind": kind,
                        "targetId": (
                            locator["importIntentId"]
                            if kind == "anki_import"
                            else selection_ref
                        ),
                        "action": action,
                        "audienceDigest": audience_digest,
                        "expiresAt": (
                            selected_at
                            + AUTHORIZATION_REVOCATION_ATTESTATION_LIFETIME_MS
                        ),
                    }
        with self._lock:
            self._authorization_revocation_selections[session_ref] = tuple(selections)
        return {
            "schemaVersion": 1,
            "sessionRef": session_ref,
            "state": "approved",
            "userGestureRecorded": True,
            "authorizationRevocation": {
                "selectedCount": len(selections),
                "availableCount": len(bindings),
            },
        }

    def selected_local_resource(self, session_ref: str) -> TrustedLocalResourceSelection | None:
        with self._lock:
            return self._local_resource_selections.get(session_ref)

    def selected_network_resource(
        self, session_ref: str
    ) -> TrustedNetworkResourceSelection | None:
        with self._lock:
            return self._network_resource_selections.get(session_ref)

    def verify_resource_gesture(
        self, audience_digest: str, request_digest: str, attestation_ref: str, action: str
    ) -> bool:
        if (
            not SHA256_RE.fullmatch(audience_digest)
            or not SHA256_RE.fullmatch(request_digest)
        ):
            return False
        with self._lock:
            pending = self._resource_attestations.get(attestation_ref)
            if pending is None or pending["action"] != action:
                return False
            if int(pending["expiresAt"]) <= int(time.time() * 1000):
                session_ref = str(pending["sessionRef"])
                self._local_resource_selections.pop(session_ref, None)
                self._network_resource_selections.pop(session_ref, None)
                self._resource_attestations.pop(attestation_ref, None)
                return False
            if pending["audienceDigest"] is None:
                pending["audienceDigest"] = audience_digest
            if pending["audienceDigest"] != audience_digest:
                return False
            if pending["requestDigest"] is None:
                pending["requestDigest"] = request_digest
            return (
                pending["audienceDigest"] == audience_digest
                and pending["requestDigest"] == request_digest
            )

    def complete_resource_selection(self, session_ref: str) -> None:
        with self._lock:
            selection = self._local_resource_selections.pop(session_ref, None)
            if selection is not None:
                self._resource_attestations.pop(selection.attestation_ref, None)

    def complete_network_resource_selection(self, session_ref: str) -> None:
        with self._lock:
            selection = self._network_resource_selections.pop(session_ref, None)
            if selection is not None:
                self._resource_attestations.pop(selection.attestation_ref, None)

    def import_consent_decision(
        self, session_ref: str
    ) -> TrustedImportConsentDecision | None:
        with self._lock:
            return self._import_consent_decisions.get(session_ref)

    def operation_consent_decision(
        self, session_ref: str
    ) -> TrustedOperationConsentDecision | None:
        with self._lock:
            return self._operation_consent_decisions.get(session_ref)

    def verify_operation_consent_gesture(
        self,
        gesture_digest: str,
        audience_digest: str,
        operation_intent_id: str,
        action: str,
    ) -> bool:
        if (
            not SHA256_RE.fullmatch(str(gesture_digest or ""))
            or not SHA256_RE.fullmatch(str(audience_digest or ""))
            or not OPERATION_INTENT_RE.fullmatch(str(operation_intent_id or ""))
            or action
            not in {"decide:approved", "decide:declined", "revoke_operation"}
        ):
            return False
        with self._lock:
            pending = self._operation_consent_attestations.get(gesture_digest)
            if pending is None:
                return False
            if int(pending["expiresAt"]) <= int(time.time() * 1000):
                self._operation_consent_attestations.pop(gesture_digest, None)
                return False
            return (
                pending["audienceDigest"] == audience_digest
                and pending["operationIntentId"] == operation_intent_id
                and pending["action"] == action
            )

    def complete_operation_consent(self, session_ref: str) -> None:
        with self._lock:
            decision = self._operation_consent_decisions.pop(session_ref, None)
            if decision is not None:
                self._operation_consent_attestations.pop(
                    decision.attestation_digest, None
                )

    def verify_import_consent_gesture(
        self,
        attestation_ref: str,
        audience_digest: str,
        import_intent_id: str,
        action: str,
    ) -> bool:
        if not SHA256_RE.fullmatch(audience_digest) or not IMPORT_INTENT_RE.fullmatch(
            import_intent_id
        ):
            return False
        if action == "revoke":
            with self._lock:
                pending = self._authorization_revocation_attestations.get(
                    attestation_ref
                )
                if pending is None:
                    return False
                if int(pending["expiresAt"]) <= int(time.time() * 1000):
                    self._authorization_revocation_attestations.pop(
                        attestation_ref, None
                    )
                    return False
                return (
                    pending["kind"] == "anki_import"
                    and pending["audienceDigest"] == audience_digest
                    and pending["targetId"] == import_intent_id
                    and pending["action"] == "revoke"
                )
        if action not in {"decide:approved", "decide:declined"}:
            return False
        with self._lock:
            pending = self._import_consent_attestations.get(attestation_ref)
            if pending is None:
                return False
            if int(pending["expiresAt"]) <= int(time.time() * 1000):
                self._import_consent_attestations.pop(attestation_ref, None)
                return False
            return (
                pending["audienceDigest"] == audience_digest
                and pending["importIntentId"] == import_intent_id
                and pending["action"] == action
            )

    def complete_import_consent(self, session_ref: str) -> None:
        with self._lock:
            decision = self._import_consent_decisions.pop(session_ref, None)
            if decision is not None:
                self._import_consent_attestations.pop(
                    decision.attestation_ref, None
                )

    def authorization_revocation_selections(
        self, session_ref: str
    ) -> tuple[TrustedAuthorizationRevocationSelection, ...]:
        with self._lock:
            return self._authorization_revocation_selections.get(session_ref, ())

    def verify_authorization_revocation(
        self,
        *,
        attestation_ref: str,
        audience_digest: str,
        selection_ref: str,
        action: str,
    ) -> bool:
        if (
            not SHA256_RE.fullmatch(audience_digest)
            or not AUTHORIZATION_SELECTION_RE.fullmatch(selection_ref)
            or action != "revoke_broker_authorization"
        ):
            return False
        with self._lock:
            pending = self._authorization_revocation_attestations.get(
                attestation_ref
            )
            if pending is None:
                return False
            if int(pending["expiresAt"]) <= int(time.time() * 1000):
                self._authorization_revocation_attestations.pop(
                    attestation_ref, None
                )
                return False
            return (
                pending["kind"] == "broker_authorization"
                and pending["audienceDigest"] == audience_digest
                and pending["selectionRef"] == selection_ref
                and pending["action"] == action
            )

    def complete_authorization_manager(self, session_ref: str) -> None:
        with self._lock:
            selections = self._authorization_revocation_selections.pop(
                session_ref, ()
            )
            self._authorization_manager_bindings.pop(session_ref, None)
            for selection in selections:
                self._authorization_revocation_attestations.pop(
                    selection.attestation_ref, None
                )
                self._operation_consent_attestations.pop(
                    selection.attestation_ref, None
                )
                self._resource_attestations.pop(selection.attestation_ref, None)

    def get_session(self, session_ref: str) -> dict[str, Any]:
        _, request = self._load_request(session_ref)
        with self._lock:
            verified = self._verified_responses.get(session_ref)
        if verified is not None:
            allowed = {
                "schemaVersion", "sessionRef", "state", "credential", "userGestureRecorded",
                "authorization", "resourceSelection", "networkSelection",
                "authorizationRevocation", "errorCode",
            }
            return {key: value for key, value in verified.items() if key in allowed}
        response_path = self.responses_dir / f"{session_ref}.json"
        if not response_path.is_file():
            with self._lock:
                running = session_ref in self._processes
            return {"sessionRef": session_ref, "surface": request["surface"], "state": "open" if running else "created"}
        response: dict[str, Any] | None = None
        for attempt in range(5):
            try:
                with response_path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if not isinstance(loaded, dict):
                    raise TrustedSurfaceError(
                        "SESSION_RESPONSE_INVALID",
                        "Trusted surface response is not an object",
                    )
                response = loaded
                break
            except PermissionError as error:
                if attempt == 4:
                    raise TrustedSurfaceError(
                        "SESSION_RESPONSE_UNREADABLE",
                        "Trusted surface response is temporarily unreadable",
                    ) from error
                time.sleep(0.02)
            except json.JSONDecodeError as error:
                if attempt == 4:
                    raise TrustedSurfaceError(
                        "SESSION_RESPONSE_INVALID",
                        "Trusted surface response is incomplete or invalid",
                    ) from error
                time.sleep(0.02)
        assert response is not None
        with self._lock:
            response_key = self._response_keys.get(session_ref)
        if response_key is None:
            raise TrustedSurfaceError("SESSION_RESPONSE_INVALID", "Trusted surface response key is unavailable")
        try:
            response = verify_response(response, response_key)
        except (TypeError, ValueError) as error:
            raise TrustedSurfaceError("SESSION_RESPONSE_INVALID", "Trusted surface response authentication failed") from error
        if response.get("sessionRef") != session_ref:
            raise TrustedSurfaceError("SESSION_RESPONSE_INVALID", "Trusted surface response session mismatch")
        if response.get("requestNonce") != request.get("requestNonce"):
            raise TrustedSurfaceError("SESSION_RESPONSE_INVALID", "Trusted surface response nonce mismatch")
        finalized = dict(response)
        if request.get("surface") == "local_resource_picker":
            finalized = self._finalize_local_resource_response(request, response, response_key)
            try:
                response_path.unlink(missing_ok=True)
            except OSError:
                pass
        elif request.get("surface") == "authorization_manager":
            finalized = self._finalize_authorization_manager_response(
                request, response, response_key
            )
            try:
                response_path.unlink(missing_ok=True)
            except OSError:
                pass
        elif request.get("surface") == "network_resource_input":
            finalized = self._finalize_network_resource_response(
                request, response, response_key
            )
            try:
                response_path.unlink(missing_ok=True)
            except OSError:
                pass
        elif request.get("confirmationKind") == "operation_intent":
            state = response.get("state")
            if state in {"approved", "declined"}:
                if response.get("userGestureRecorded") is not True:
                    raise TrustedSurfaceError(
                        "SESSION_RESPONSE_INVALID",
                        "Trusted operation consent has no user gesture",
                    )
                decided_at = int(time.time() * 1000)
                attestation_digest = secrets.token_hex(32)
                decision = TrustedOperationConsentDecision(
                    session_ref=session_ref,
                    operation_intent_id=str(request["operationIntentId"]),
                    decision=str(state),
                    attestation_digest=attestation_digest,
                    decided_at=decided_at,
                )
                with self._lock:
                    self._operation_consent_decisions[session_ref] = decision
                    self._operation_consent_attestations[attestation_digest] = {
                        "audienceDigest": str(request["audienceDigest"]),
                        "operationIntentId": decision.operation_intent_id,
                        "intentDigest": str(request["intentDigest"]),
                        "action": f"decide:{state}",
                        "expiresAt": (
                            decided_at + IMPORT_CONSENT_ATTESTATION_LIFETIME_MS
                        ),
                    }
            elif state not in {"cancelled", "failed"}:
                raise TrustedSurfaceError(
                    "SESSION_RESPONSE_INVALID",
                    "Trusted operation consent response is invalid",
                )
            try:
                response_path.unlink(missing_ok=True)
            except OSError:
                pass
        elif request.get("confirmationKind") == "anki_import":
            state = response.get("state")
            if state in {"approved", "declined"}:
                if response.get("userGestureRecorded") is not True:
                    raise TrustedSurfaceError(
                        "SESSION_RESPONSE_INVALID",
                        "Trusted Anki import consent has no user gesture",
                    )
                decided_at = int(time.time() * 1000)
                attestation_ref = "import-consent-" + secrets.token_urlsafe(24)
                decision = TrustedImportConsentDecision(
                    session_ref=session_ref,
                    import_intent_id=str(request["importIntentId"]),
                    decision=str(state),
                    attestation_ref=attestation_ref,
                    decided_at=decided_at,
                )
                with self._lock:
                    self._import_consent_decisions[session_ref] = decision
                    self._import_consent_attestations[attestation_ref] = {
                        "audienceDigest": str(request["audienceDigest"]),
                        "importIntentId": decision.import_intent_id,
                        "importPlanDigest": str(request["importPlanDigest"]),
                        "action": f"decide:{state}",
                        "expiresAt": (
                            decided_at + IMPORT_CONSENT_ATTESTATION_LIFETIME_MS
                        ),
                    }
            elif state not in {"cancelled", "failed"}:
                raise TrustedSurfaceError(
                    "SESSION_RESPONSE_INVALID",
                    "Trusted Anki import consent response is invalid",
                )
            try:
                response_path.unlink(missing_ok=True)
            except OSError:
                pass
        elif request.get("authorizationKind") == "broker_startup":
            if response.get("state") == "approved" and response.get("userGestureRecorded") is True:
                try:
                    issued = self._issuer().issue(
                        session_ref=session_ref,
                        prepared=request.get("brokerAuthorization") or {},
                    )
                except BrokerAuthorizationIssuerError as error:
                    finalized = {
                        "schemaVersion": 1,
                        "sessionRef": session_ref,
                        "state": "failed",
                        "userGestureRecorded": True,
                        "errorCode": error.code,
                    }
                else:
                    finalized["authorization"] = dict(issued.public_summary)
                    with self._lock:
                        self._issued_authorizations[session_ref] = issued
        with self._lock:
            self._verified_responses[session_ref] = finalized
            self._response_keys.pop(session_ref, None)
        allowed = {
            "schemaVersion", "sessionRef", "state", "credential", "userGestureRecorded",
            "authorization", "resourceSelection", "networkSelection",
            "authorizationRevocation", "errorCode",
        }
        return {key: value for key, value in finalized.items() if key in allowed}
