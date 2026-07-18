from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtensionOID

from .runtime_manifest import canonical_bytes, file_sha256


POLICY_SCHEMA_VERSION = 1
MAX_POLICY_BYTES = 256 * 1024
MAX_SIGNED_FILE_BYTES = 128 * 1024 * 1024
CODE_SIGNING_EKU_OID = "1.3.6.1.5.5.7.3.3"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_OID_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)+$")
_SUBJECT_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class AuthenticodeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _stable_signed_file(path: Path) -> Path:
    if not path.is_absolute():
        raise AuthenticodeError("AUTHENTICODE_PATH_INVALID", "Signed file path must be absolute")
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if current.is_symlink() or (current.exists() and _has_reparse_attribute(current)):
                raise AuthenticodeError("AUTHENTICODE_REPARSE_BLOCKED", "Signed file path contains a reparse point")
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except AuthenticodeError:
        raise
    except OSError as error:
        raise AuthenticodeError("AUTHENTICODE_PATH_INVALID", "Signed file is unavailable") from error
    if not resolved.is_file() or metadata.st_size <= 0 or metadata.st_size > MAX_SIGNED_FILE_BYTES:
        raise AuthenticodeError("AUTHENTICODE_PATH_INVALID", "Signed file size is invalid")
    return resolved


def _read_policy(path: Path) -> bytes:
    resolved = _stable_signed_file(path)
    if resolved.stat().st_size > MAX_POLICY_BYTES:
        raise AuthenticodeError("AUTHENTICODE_POLICY_INVALID", "Authenticode policy is too large")
    try:
        with resolved.open("rb") as handle:
            source = handle.read(MAX_POLICY_BYTES + 1)
    except OSError as error:
        raise AuthenticodeError("AUTHENTICODE_POLICY_INVALID", "Authenticode policy is unavailable") from error
    if not source or len(source) > MAX_POLICY_BYTES:
        raise AuthenticodeError("AUTHENTICODE_POLICY_INVALID", "Authenticode policy is empty or too large")
    return source


@dataclass(frozen=True)
class AuthenticodeSigner:
    certificate_sha256: str
    subject: str
    status: str


class AuthenticodePolicy:
    """External publisher certificate pins for the Windows launcher."""

    def __init__(self, value: dict[str, Any], *, source_digest: str | None = None) -> None:
        expected = {
            "schemaVersion",
            "authority",
            "sequence",
            "requireTimestamp",
            "minimumRsaBits",
            "allowedEcCurves",
            "requiredEkuOids",
            "signers",
        }
        if set(value) != expected or value.get("schemaVersion") != POLICY_SCHEMA_VERSION:
            raise AuthenticodeError("AUTHENTICODE_POLICY_INVALID", "Authenticode policy shape is invalid")
        authority = value.get("authority")
        sequence = value.get("sequence")
        require_timestamp = value.get("requireTimestamp")
        minimum_rsa_bits = value.get("minimumRsaBits")
        curves = value.get("allowedEcCurves")
        eku_oids = value.get("requiredEkuOids")
        signers = value.get("signers")
        if (
            not isinstance(authority, str)
            or _IDENTIFIER_RE.fullmatch(authority) is None
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
            or not isinstance(require_timestamp, bool)
            or isinstance(minimum_rsa_bits, bool)
            or not isinstance(minimum_rsa_bits, int)
            or minimum_rsa_bits < 2048
            or minimum_rsa_bits > 16384
            or not isinstance(curves, list)
            or not curves
            or curves != sorted(set(curves), key=lambda item: item.encode("ascii") if isinstance(item, str) else b"")
            or not all(item in {"secp256r1", "secp384r1", "secp521r1"} for item in curves)
            or not isinstance(eku_oids, list)
            or not eku_oids
            or eku_oids != sorted(set(eku_oids), key=lambda item: item.encode("ascii") if isinstance(item, str) else b"")
            or not all(isinstance(item, str) and _OID_RE.fullmatch(item) for item in eku_oids)
            or CODE_SIGNING_EKU_OID not in eku_oids
            or not isinstance(signers, list)
            or not signers
        ):
            raise AuthenticodeError("AUTHENTICODE_POLICY_INVALID", "Authenticode policy is invalid")

        parsed: dict[str, AuthenticodeSigner] = {}
        order: list[str] = []
        for raw in signers:
            if not isinstance(raw, dict) or set(raw) != {"certificateSha256", "subject", "status"}:
                raise AuthenticodeError("AUTHENTICODE_POLICY_INVALID", "Authenticode signer is invalid")
            digest = raw.get("certificateSha256")
            subject = raw.get("subject")
            status = raw.get("status")
            if (
                not isinstance(digest, str)
                or _SHA256_RE.fullmatch(digest) is None
                or not isinstance(subject, str)
                or not subject
                or len(subject) > 1024
                or _SUBJECT_CONTROL_RE.search(subject) is not None
                or status not in {"active", "revoked"}
                or digest in parsed
            ):
                raise AuthenticodeError("AUTHENTICODE_POLICY_INVALID", "Authenticode signer is invalid")
            parsed[digest] = AuthenticodeSigner(digest, subject, status)
            order.append(digest)
        if order != sorted(order, key=lambda item: item.encode("ascii")):
            raise AuthenticodeError("AUTHENTICODE_POLICY_NONCANONICAL", "Authenticode signers must be sorted")

        self.value = value
        self.authority = authority
        self.sequence = sequence
        self.require_timestamp = require_timestamp
        self.minimum_rsa_bits = minimum_rsa_bits
        self.allowed_ec_curves = frozenset(curves)
        self.required_eku_oids = frozenset(eku_oids)
        self.signers = parsed
        self.digest = source_digest or hashlib.sha256(canonical_bytes(value)).hexdigest()

    @classmethod
    def load(cls, path: str | Path) -> "AuthenticodePolicy":
        source = _read_policy(Path(path))
        try:
            value = json.loads(source)
        except ValueError as error:
            raise AuthenticodeError("AUTHENTICODE_POLICY_INVALID", "Authenticode policy is invalid JSON") from error
        if not isinstance(value, dict) or canonical_bytes(value) != source:
            raise AuthenticodeError("AUTHENTICODE_POLICY_NONCANONICAL", "Authenticode policy must use canonical JSON")
        return cls(value, source_digest=hashlib.sha256(source).hexdigest())

    def active_signer(self, certificate_sha256: str) -> AuthenticodeSigner:
        signer = self.signers.get(certificate_sha256)
        if signer is None:
            raise AuthenticodeError("AUTHENTICODE_SIGNER_UNTRUSTED", "Authenticode signer certificate is not trusted")
        if signer.status != "active":
            raise AuthenticodeError("AUTHENTICODE_SIGNER_REVOKED", "Authenticode signer certificate is revoked")
        return signer


@dataclass(frozen=True)
class NativeAuthenticodeEvidence:
    signer_certificate_der: bytes
    verified_at: datetime
    timestamp_present: bool
    status_code: int


@dataclass(frozen=True)
class VerifiedAuthenticode:
    file_sha256: str
    certificate_sha256: str
    subject: str
    verified_at: str
    timestamp_present: bool
    policy_sequence: int
    policy_digest: str

    def public_summary(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "fileSha256": self.file_sha256,
            "certificateSha256": self.certificate_sha256,
            "subject": self.subject,
            "verifiedAt": self.verified_at,
            "timestampPresent": self.timestamp_present,
            "policySequence": self.policy_sequence,
            "policyDigest": self.policy_digest,
            "signatureVerified": True,
            "publisherPinned": True,
            "cacheOnlyUrlRetrieval": True,
            "revocationMode": "chainExcludeRootCacheOnly",
            "networkUsed": False,
        }


if os.name == "nt":
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]


    class WINTRUST_FILE_INFO(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pcwszFilePath", wintypes.LPCWSTR),
            ("hFile", wintypes.HANDLE),
            ("pgKnownSubject", ctypes.POINTER(GUID)),
        ]


    class WINTRUST_DATA(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pPolicyCallbackData", ctypes.c_void_p),
            ("pSIPClientData", ctypes.c_void_p),
            ("dwUIChoice", wintypes.DWORD),
            ("fdwRevocationChecks", wintypes.DWORD),
            ("dwUnionChoice", wintypes.DWORD),
            ("pFile", ctypes.POINTER(WINTRUST_FILE_INFO)),
            ("dwStateAction", wintypes.DWORD),
            ("hWVTStateData", wintypes.HANDLE),
            ("pwszURLReference", wintypes.LPCWSTR),
            ("dwProvFlags", wintypes.DWORD),
            ("dwUIContext", wintypes.DWORD),
            ("pSignatureSettings", ctypes.c_void_p),
        ]


    class CERT_CONTEXT(ctypes.Structure):
        _fields_ = [
            ("dwCertEncodingType", wintypes.DWORD),
            ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
            ("cbCertEncoded", wintypes.DWORD),
            ("pCertInfo", ctypes.c_void_p),
            ("hCertStore", wintypes.HANDLE),
        ]


    class CRYPT_PROVIDER_CERT(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pCert", ctypes.POINTER(CERT_CONTEXT)),
            ("fCommercial", wintypes.BOOL),
            ("fTrustedRoot", wintypes.BOOL),
            ("fSelfSigned", wintypes.BOOL),
            ("fTestCert", wintypes.BOOL),
            ("dwRevokedReason", wintypes.DWORD),
            ("dwConfidence", wintypes.DWORD),
            ("dwError", wintypes.DWORD),
            ("pTrustListContext", ctypes.c_void_p),
            ("fTrustListSignerCert", wintypes.BOOL),
            ("pCtlContext", ctypes.c_void_p),
            ("dwCtlError", wintypes.DWORD),
            ("fIsCyclic", wintypes.BOOL),
            ("pChainElement", ctypes.c_void_p),
        ]


    class CRYPT_PROVIDER_SGNR(ctypes.Structure):
        pass


    CRYPT_PROVIDER_SGNR._fields_ = [
        ("cbStruct", wintypes.DWORD),
        ("sftVerifyAsOf", wintypes.FILETIME),
        ("csCertChain", wintypes.DWORD),
        ("pasCertChain", ctypes.POINTER(CRYPT_PROVIDER_CERT)),
        ("dwSignerType", wintypes.DWORD),
        ("psSigner", ctypes.c_void_p),
        ("dwError", wintypes.DWORD),
        ("csCounterSigners", wintypes.DWORD),
        ("pasCounterSigners", ctypes.POINTER(CRYPT_PROVIDER_SGNR)),
        ("pChainContext", ctypes.c_void_p),
    ]


def _filetime_to_datetime(value: Any) -> datetime:
    ticks = (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)
    if ticks <= 116444736000000000:
        raise AuthenticodeError("AUTHENTICODE_EVIDENCE_INVALID", "Authenticode verification time is invalid")
    seconds = (ticks - 116444736000000000) / 10_000_000
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OSError, OverflowError, ValueError) as error:
        raise AuthenticodeError("AUTHENTICODE_EVIDENCE_INVALID", "Authenticode verification time is invalid") from error


def _native_authenticode_evidence(path: Path) -> NativeAuthenticodeEvidence:
    if os.name != "nt":
        raise AuthenticodeError("AUTHENTICODE_PLATFORM_UNSUPPORTED", "Authenticode verification requires Windows")
    wintrust = ctypes.WinDLL("wintrust", use_last_error=True)
    action = GUID(
        0x00AAC56B,
        0xCD44,
        0x11D0,
        (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE),
    )
    file_info = WINTRUST_FILE_INFO(
        ctypes.sizeof(WINTRUST_FILE_INFO),
        str(path),
        None,
        None,
    )
    data = WINTRUST_DATA()
    data.cbStruct = ctypes.sizeof(WINTRUST_DATA)
    data.dwUIChoice = 2
    data.fdwRevocationChecks = 0
    data.dwUnionChoice = 1
    data.pFile = ctypes.pointer(file_info)
    data.dwStateAction = 1
    # WTD_CACHE_ONLY_URL_RETRIEVAL | WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT.
    # Verification therefore cannot fetch over the network and fails closed when
    # Windows cannot establish the cached chain/revocation state.
    data.dwProvFlags = 0x00001000 | 0x00000080
    data.dwUIContext = 0
    wintrust.WinVerifyTrust.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(WINTRUST_DATA)]
    wintrust.WinVerifyTrust.restype = ctypes.c_long
    wintrust.WTHelperProvDataFromStateData.argtypes = [wintypes.HANDLE]
    wintrust.WTHelperProvDataFromStateData.restype = ctypes.c_void_p
    wintrust.WTHelperGetProvSignerFromChain.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    wintrust.WTHelperGetProvSignerFromChain.restype = ctypes.POINTER(CRYPT_PROVIDER_SGNR)
    wintrust.WTHelperGetProvCertFromChain.argtypes = [ctypes.POINTER(CRYPT_PROVIDER_SGNR), wintypes.DWORD]
    wintrust.WTHelperGetProvCertFromChain.restype = ctypes.POINTER(CRYPT_PROVIDER_CERT)
    status = int(wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(data))) & 0xFFFFFFFF
    try:
        if status != 0:
            code = "AUTHENTICODE_NOT_SIGNED" if status == 0x800B0100 else "AUTHENTICODE_INVALID"
            raise AuthenticodeError(code, f"Windows rejected the Authenticode signature: 0x{status:08X}")
        provider = wintrust.WTHelperProvDataFromStateData(data.hWVTStateData)
        if not provider:
            raise AuthenticodeError("AUTHENTICODE_EVIDENCE_INVALID", "Windows returned no Authenticode provider evidence")
        signer = wintrust.WTHelperGetProvSignerFromChain(provider, 0, False, 0)
        if not signer or signer.contents.dwError != 0 or signer.contents.csCertChain < 1:
            raise AuthenticodeError("AUTHENTICODE_EVIDENCE_INVALID", "Windows returned no Authenticode signer")
        provider_certificate = wintrust.WTHelperGetProvCertFromChain(signer, 0)
        if (
            not provider_certificate
            or provider_certificate.contents.dwError != 0
            or not provider_certificate.contents.pCert
        ):
            raise AuthenticodeError("AUTHENTICODE_EVIDENCE_INVALID", "Windows returned no signer certificate")
        certificate_context = provider_certificate.contents.pCert.contents
        if not certificate_context.pbCertEncoded or certificate_context.cbCertEncoded <= 0:
            raise AuthenticodeError("AUTHENTICODE_EVIDENCE_INVALID", "Windows returned an empty signer certificate")
        certificate_der = ctypes.string_at(
            certificate_context.pbCertEncoded,
            certificate_context.cbCertEncoded,
        )
        timestamp_present = False
        for index in range(int(signer.contents.csCounterSigners)):
            counter_signer = signer.contents.pasCounterSigners[index]
            if (
                counter_signer.dwError == 0
                and counter_signer.csCertChain > 0
                and bool(counter_signer.pasCertChain)
                and counter_signer.pasCertChain[0].dwError == 0
                and bool(counter_signer.pasCertChain[0].pCert)
            ):
                timestamp_present = True
                break
        return NativeAuthenticodeEvidence(
            signer_certificate_der=certificate_der,
            verified_at=_filetime_to_datetime(signer.contents.sftVerifyAsOf),
            timestamp_present=timestamp_present,
            status_code=status,
        )
    finally:
        if data.hWVTStateData:
            data.dwStateAction = 2
            wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(data))


def _certificate_time(certificate: x509.Certificate, name: str) -> datetime:
    utc_name = name + "_utc"
    value = getattr(certificate, utc_name, None)
    if value is None:
        value = getattr(certificate, name).replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def verify_authenticode(
    path: Path,
    *,
    policy: AuthenticodePolicy,
) -> VerifiedAuthenticode:
    resolved = _stable_signed_file(path)
    file_digest_before = file_sha256(resolved)
    evidence = _native_authenticode_evidence(resolved)
    if (
        evidence.status_code != 0
        or not evidence.signer_certificate_der
        or evidence.verified_at.tzinfo is None
        or evidence.verified_at.utcoffset() is None
    ):
        raise AuthenticodeError("AUTHENTICODE_EVIDENCE_INVALID", "Authenticode evidence is invalid")
    try:
        certificate = x509.load_der_x509_certificate(evidence.signer_certificate_der)
    except ValueError as error:
        raise AuthenticodeError("AUTHENTICODE_EVIDENCE_INVALID", "Signer certificate is invalid") from error
    certificate_digest = hashlib.sha256(evidence.signer_certificate_der).hexdigest()
    signer = policy.active_signer(certificate_digest)
    subject = certificate.subject.rfc4514_string()
    if subject != signer.subject:
        raise AuthenticodeError("AUTHENTICODE_SIGNER_SUBJECT_MISMATCH", "Signer certificate subject does not match policy")
    if policy.require_timestamp and not evidence.timestamp_present:
        raise AuthenticodeError("AUTHENTICODE_TIMESTAMP_REQUIRED", "Authenticode signature has no trusted timestamp")
    verified_at = evidence.verified_at.astimezone(timezone.utc)
    if verified_at < _certificate_time(certificate, "not_valid_before") or verified_at > _certificate_time(certificate, "not_valid_after"):
        raise AuthenticodeError("AUTHENTICODE_CERTIFICATE_TIME_INVALID", "Signer certificate was not valid at verification time")
    try:
        eku = certificate.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
    except x509.ExtensionNotFound as error:
        raise AuthenticodeError("AUTHENTICODE_EKU_INVALID", "Signer certificate has no extended key usage") from error
    observed_eku = {oid.dotted_string for oid in eku}
    if not policy.required_eku_oids.issubset(observed_eku):
        raise AuthenticodeError("AUTHENTICODE_EKU_INVALID", "Signer certificate lacks the required code-signing EKU")
    try:
        key_usage = certificate.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
    except x509.ExtensionNotFound as error:
        raise AuthenticodeError("AUTHENTICODE_KEY_USAGE_INVALID", "Signer certificate has no key usage") from error
    if not key_usage.digital_signature:
        raise AuthenticodeError("AUTHENTICODE_KEY_USAGE_INVALID", "Signer certificate cannot create digital signatures")
    try:
        basic_constraints = certificate.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
    except x509.ExtensionNotFound:
        basic_constraints = None
    if basic_constraints is not None and basic_constraints.ca:
        raise AuthenticodeError("AUTHENTICODE_SIGNER_CA_REJECTED", "A CA certificate cannot be the launcher signer")
    public_key = certificate.public_key()
    if isinstance(public_key, rsa.RSAPublicKey):
        if public_key.key_size < policy.minimum_rsa_bits:
            raise AuthenticodeError("AUTHENTICODE_KEY_TOO_WEAK", "Signer RSA key is below the policy minimum")
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        if public_key.curve.name not in policy.allowed_ec_curves:
            raise AuthenticodeError("AUTHENTICODE_KEY_UNSUPPORTED", "Signer EC curve is not allowed")
    else:
        raise AuthenticodeError("AUTHENTICODE_KEY_UNSUPPORTED", "Signer key algorithm is not allowed")
    file_digest_after = file_sha256(resolved)
    if file_digest_after != file_digest_before:
        raise AuthenticodeError("AUTHENTICODE_FILE_CHANGED", "Launcher changed during Authenticode verification")
    return VerifiedAuthenticode(
        file_sha256=file_digest_after,
        certificate_sha256=certificate_digest,
        subject=subject,
        verified_at=verified_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        timestamp_present=evidence.timestamp_present,
        policy_sequence=policy.sequence,
        policy_digest=policy.digest,
    )
