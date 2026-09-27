import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from scripts.verify_rfc3161_timestamp import main as rfc3161_main

from regulated_ai.adapters import (
    Rfc3161TimestampError,
    TimestampSubjectKind,
    verify_rfc3161_timestamp,
)


@dataclass(frozen=True)
class _TimestampFixture:
    artifact: Path
    request: Path
    response: Path
    ca_bundle: Path
    now: datetime


def _run(*arguments: str) -> None:
    subprocess.run(arguments, check=True, capture_output=True, text=True)  # noqa: S603


def _write_private_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def _fixture(root: Path, *, include_nonce: bool = True) -> _TimestampFixture:
    openssl = shutil.which("openssl")
    assert openssl is not None
    now = datetime.now(UTC).replace(microsecond=0)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RegulaAI RFC3161 Test CA")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    tsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tsa_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RegulaAI RFC3161 Test TSA")])
    tsa_certificate = (
        x509.CertificateBuilder()
        .subject_name(tsa_name)
        .issuer_name(ca_name)
        .public_key(tsa_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    ca_bundle = root / "ca.pem"
    tsa_certificate_path = root / "tsa.pem"
    tsa_key_path = root / "tsa-key.pem"
    ca_bundle.write_bytes(ca_certificate.public_bytes(serialization.Encoding.PEM))
    tsa_certificate_path.write_bytes(tsa_certificate.public_bytes(serialization.Encoding.PEM))
    _write_private_key(tsa_key_path, tsa_key)

    serial = root / "tsa-serial"
    serial.write_text("01\n", encoding="ascii")
    config = root / "tsa.cnf"
    config.write_text(
        "\n".join(
            (
                "[tsa]",
                "default_tsa = tsa_config",
                "[tsa_config]",
                f"serial = {serial}",
                "crypto_device = builtin",
                f"signer_cert = {tsa_certificate_path}",
                f"certs = {ca_bundle}",
                f"signer_key = {tsa_key_path}",
                "signer_digest = sha256",
                "default_policy = 1.2.3.4.1",
                "other_policies = 1.2.3.4.2",
                "digests = sha256,sha384,sha512",
                "accuracy = secs:1",
                "ordering = yes",
                "tsa_name = yes",
                "ess_cert_id_chain = yes",
                "ess_cert_id_alg = sha256",
                "",
            )
        ),
        encoding="utf-8",
    )
    artifact = root / "release-evidence.json"
    artifact.write_text('{"release":"2026.09"}\n', encoding="utf-8")
    request = root / "timestamp.tsq"
    response = root / "timestamp.tsr"
    query_arguments = [
        openssl,
        "ts",
        "-query",
        "-data",
        str(artifact),
        "-sha256",
        "-cert",
        "-tspolicy",
        "1.2.3.4.1",
        "-out",
        str(request),
    ]
    if not include_nonce:
        query_arguments.insert(-2, "-no_nonce")
    _run(*query_arguments)
    _run(
        openssl,
        "ts",
        "-reply",
        "-config",
        str(config),
        "-queryfile",
        str(request),
        "-out",
        str(response),
    )
    return _TimestampFixture(artifact, request, response, ca_bundle, now)


def _verify(
    fixture: _TimestampFixture,
    *,
    allowed_policy_oids: tuple[str, ...] = ("1.2.3.4.1",),
    evaluated_at: datetime | None = None,
    minimum_generated_at: datetime | None = None,
) -> None:
    verify_rfc3161_timestamp(
        fixture.artifact,
        fixture.request,
        fixture.response,
        fixture.ca_bundle,
        subject_kind=TimestampSubjectKind.RELEASE_EVIDENCE_BUNDLE,
        allowed_policy_oids=allowed_policy_oids,
        evaluated_at=evaluated_at or fixture.now + timedelta(minutes=5),
        minimum_generated_at=minimum_generated_at,
    )


def test_cli_verifies_rfc3161_evidence_and_emits_metadata_only_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = _fixture(tmp_path)

    assert (
        rfc3161_main(
            [
                "--artifact",
                str(fixture.artifact),
                "--request",
                str(fixture.request),
                "--response",
                str(fixture.response),
                "--ca-bundle",
                str(fixture.ca_bundle),
                "--subject-kind",
                "RELEASE_EVIDENCE_BUNDLE",
                "--policy-oid",
                "1.2.3.4.1",
                "--evaluated-at",
                (fixture.now + timedelta(minutes=5)).isoformat(),
                "--minimum-generated-at",
                (fixture.now - timedelta(minutes=5)).isoformat(),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "RFC3161_TIMESTAMP_VERIFIED"
    assert report["hash_algorithm"] == "sha256"
    assert report["policy_oid"] == "1.2.3.4.1"
    assert report["subject_digest"].startswith("sha256:")
    assert "release" not in report


@pytest.mark.parametrize("failure", ["artifact", "policy", "future", "floor", "response"])
def test_changed_bytes_policy_time_floor_and_response_fail_closed(
    tmp_path: Path, failure: str
) -> None:
    fixture = _fixture(tmp_path)
    allowed_policy_oids = ("1.2.3.4.1",)
    evaluated_at = fixture.now + timedelta(minutes=5)
    minimum_generated_at = None
    if failure == "artifact":
        fixture.artifact.write_text('{"release":"tampered"}\n', encoding="utf-8")
    elif failure == "policy":
        allowed_policy_oids = ("1.2.3.4.99",)
    elif failure == "future":
        evaluated_at = fixture.now - timedelta(minutes=5)
    elif failure == "floor":
        minimum_generated_at = fixture.now + timedelta(minutes=5)
    else:
        encoded = bytearray(fixture.response.read_bytes())
        encoded[-1] ^= 1
        fixture.response.write_bytes(encoded)

    with pytest.raises(Rfc3161TimestampError):
        _verify(
            fixture,
            allowed_policy_oids=allowed_policy_oids,
            evaluated_at=evaluated_at,
            minimum_generated_at=minimum_generated_at,
        )


def test_nonce_is_required(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, include_nonce=False)

    with pytest.raises(Rfc3161TimestampError, match="nonce"):
        _verify(fixture)
