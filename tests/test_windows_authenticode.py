from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from card_service.runtime_manifest import canonical_bytes
from card_service.windows_authenticode import (
    AuthenticodeError,
    AuthenticodePolicy,
    NativeAuthenticodeEvidence,
    verify_authenticode,
)


ROOT = Path(__file__).resolve().parents[1]
TEST_NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


def certificate(
    *,
    key_size: int = 3072,
    code_signing: bool = True,
    digital_signature: bool = True,
    is_ca: bool = False,
) -> tuple[bytes, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Anki Study Test Signer")])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before((TEST_NOW - timedelta(days=1)).replace(tzinfo=None))
        .not_valid_after((TEST_NOW + timedelta(days=365)).replace(tzinfo=None))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=digital_signature,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=is_ca,
                crl_sign=is_ca,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
    )
    if code_signing:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]),
            critical=False,
        )
    cert = builder.sign(key, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.DER), cert.subject.rfc4514_string()


def policy_value(der: bytes, subject: str, *, status: str = "active", require_timestamp: bool = True):
    return {
        "schemaVersion": 1,
        "authority": "anki-study-agent.authenticode",
        "sequence": 1,
        "requireTimestamp": require_timestamp,
        "minimumRsaBits": 3072,
        "allowedEcCurves": ["secp256r1", "secp384r1", "secp521r1"],
        "requiredEkuOids": ["1.3.6.1.5.5.7.3.3"],
        "signers": [
            {
                "certificateSha256": hashlib.sha256(der).hexdigest(),
                "subject": subject,
                "status": status,
            }
        ],
    }


def write_policy(root: Path, der: bytes, subject: str, **kwargs) -> Path:
    path = (root / "authenticode-policy-v1.json").resolve()
    path.write_bytes(canonical_bytes(policy_value(der, subject, **kwargs)))
    return path


def evidence(der: bytes, *, timestamp: bool = True) -> NativeAuthenticodeEvidence:
    return NativeAuthenticodeEvidence(
        signer_certificate_der=der,
        verified_at=TEST_NOW,
        timestamp_present=timestamp,
        status_code=0,
    )


def launcher(root: Path) -> Path:
    path = (root / "launcher.exe").resolve()
    path.write_bytes(b"MZ" + b"\0" * 2048)
    return path


def test_external_policy_and_pinned_codesigning_certificate_verify(tmp_path: Path, monkeypatch) -> None:
    der, subject = certificate()
    policy_path = write_policy(tmp_path, der, subject)
    policy = AuthenticodePolicy.load(policy_path)
    executable = launcher(tmp_path)
    monkeypatch.setattr(
        "card_service.windows_authenticode._native_authenticode_evidence",
        lambda path: evidence(der),
    )

    verified = verify_authenticode(executable, policy=policy)

    assert verified.file_sha256 == hashlib.sha256(executable.read_bytes()).hexdigest()
    assert verified.certificate_sha256 == hashlib.sha256(der).hexdigest()
    assert verified.subject == subject
    assert verified.timestamp_present is True
    assert verified.policy_sequence == 1
    assert verified.policy_digest == hashlib.sha256(policy_path.read_bytes()).hexdigest()
    assert verified.public_summary()["cacheOnlyUrlRetrieval"] is True
    assert verified.public_summary()["revocationMode"] == "chainExcludeRootCacheOnly"
    assert verified.public_summary()["networkUsed"] is False


@pytest.mark.parametrize(
    ("policy_status", "timestamp", "expected"),
    [
        ("revoked", True, "AUTHENTICODE_SIGNER_REVOKED"),
        ("active", False, "AUTHENTICODE_TIMESTAMP_REQUIRED"),
    ],
)
def test_revoked_signer_and_missing_timestamp_are_rejected(
    tmp_path: Path,
    monkeypatch,
    policy_status: str,
    timestamp: bool,
    expected: str,
) -> None:
    der, subject = certificate()
    policy = AuthenticodePolicy(policy_value(der, subject, status=policy_status))
    monkeypatch.setattr(
        "card_service.windows_authenticode._native_authenticode_evidence",
        lambda path: evidence(der, timestamp=timestamp),
    )
    with pytest.raises(AuthenticodeError) as failure:
        verify_authenticode(launcher(tmp_path), policy=policy)
    assert failure.value.code == expected


@pytest.mark.parametrize(
    ("certificate_options", "expected"),
    [
        ({"code_signing": False}, "AUTHENTICODE_EKU_INVALID"),
        ({"digital_signature": False}, "AUTHENTICODE_KEY_USAGE_INVALID"),
        ({"is_ca": True}, "AUTHENTICODE_SIGNER_CA_REJECTED"),
        ({"key_size": 2048}, "AUTHENTICODE_KEY_TOO_WEAK"),
    ],
)
def test_certificate_constraints_are_enforced(tmp_path: Path, monkeypatch, certificate_options, expected) -> None:
    der, subject = certificate(**certificate_options)
    policy = AuthenticodePolicy(policy_value(der, subject))
    monkeypatch.setattr(
        "card_service.windows_authenticode._native_authenticode_evidence",
        lambda path: evidence(der),
    )
    with pytest.raises(AuthenticodeError) as failure:
        verify_authenticode(launcher(tmp_path), policy=policy)
    assert failure.value.code == expected


def test_untrusted_subject_invalid_evidence_and_file_change_are_rejected(tmp_path: Path, monkeypatch) -> None:
    der, subject = certificate()
    executable = launcher(tmp_path)

    other_der, _ = certificate()
    monkeypatch.setattr(
        "card_service.windows_authenticode._native_authenticode_evidence",
        lambda path: evidence(other_der),
    )
    with pytest.raises(AuthenticodeError) as untrusted:
        verify_authenticode(executable, policy=AuthenticodePolicy(policy_value(der, subject)))
    assert untrusted.value.code == "AUTHENTICODE_SIGNER_UNTRUSTED"

    monkeypatch.setattr(
        "card_service.windows_authenticode._native_authenticode_evidence",
        lambda path: NativeAuthenticodeEvidence(der, TEST_NOW.replace(tzinfo=None), True, 0),
    )
    with pytest.raises(AuthenticodeError) as invalid_evidence:
        verify_authenticode(executable, policy=AuthenticodePolicy(policy_value(der, subject)))
    assert invalid_evidence.value.code == "AUTHENTICODE_EVIDENCE_INVALID"

    def change_file(path: Path) -> NativeAuthenticodeEvidence:
        path.write_bytes(path.read_bytes() + b"changed")
        return evidence(der)

    monkeypatch.setattr("card_service.windows_authenticode._native_authenticode_evidence", change_file)
    with pytest.raises(AuthenticodeError) as changed:
        verify_authenticode(executable, policy=AuthenticodePolicy(policy_value(der, subject)))
    assert changed.value.code == "AUTHENTICODE_FILE_CHANGED"


def test_policy_requires_canonical_external_document(tmp_path: Path) -> None:
    der, subject = certificate()
    path = write_policy(tmp_path, der, subject)
    value = json.loads(path.read_bytes())
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    with pytest.raises(AuthenticodeError) as noncanonical:
        AuthenticodePolicy.load(path)
    assert noncanonical.value.code == "AUTHENTICODE_POLICY_NONCANONICAL"

    invalid = policy_value(der, subject)
    invalid["minimumRsaBits"] = 1024
    with pytest.raises(AuthenticodeError) as weak_policy:
        AuthenticodePolicy(invalid)
    assert weak_policy.value.code == "AUTHENTICODE_POLICY_INVALID"


def test_policy_allows_certificate_rotation_with_same_subject() -> None:
    old_der, subject = certificate()
    new_der, same_subject = certificate()
    assert same_subject == subject
    value = policy_value(old_der, subject)
    value["signers"].append(
        {
            "certificateSha256": hashlib.sha256(new_der).hexdigest(),
            "subject": subject,
            "status": "active",
        }
    )
    value["signers"].sort(key=lambda item: item["certificateSha256"].encode("ascii"))

    policy = AuthenticodePolicy(value)

    assert len(policy.signers) == 2
    assert policy.active_signer(hashlib.sha256(old_der).hexdigest()).subject == subject
    assert policy.active_signer(hashlib.sha256(new_der).hexdigest()).subject == subject


@pytest.mark.skipif(os.name != "nt", reason="Native Authenticode is Windows-only")
def test_native_verifier_safely_rejects_unsigned_executable(tmp_path: Path) -> None:
    der, subject = certificate()
    with pytest.raises(AuthenticodeError) as unsigned:
        verify_authenticode(
            launcher(tmp_path),
            policy=AuthenticodePolicy(policy_value(der, subject)),
        )
    assert unsigned.value.code in {"AUTHENTICODE_NOT_SIGNED", "AUTHENTICODE_INVALID"}


@pytest.mark.skipif(os.name != "nt", reason="Native Authenticode is Windows-only")
def test_cli_rejects_unsigned_executable_without_success_json(tmp_path: Path) -> None:
    der, subject = certificate()
    policy_path = write_policy(tmp_path, der, subject)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_launcher_authenticode.py"),
            "--launcher",
            str(launcher(tmp_path)),
            "--policy",
            str(policy_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "AUTHENTICODE_" in result.stderr
    assert '"signatureVerified":true' not in result.stdout
