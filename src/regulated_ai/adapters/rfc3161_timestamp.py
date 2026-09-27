"""Offline RFC 3161 timestamp verification with strict artifact binding."""

import hashlib
import re
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asn1crypto import cms, tsp, x509

from regulated_ai.adapters.trusted_timestamp import TimestampSubjectKind

_ALLOWED_HASHES = {
    "sha256": hashlib.sha256,
    "sha384": hashlib.sha384,
    "sha512": hashlib.sha512,
}
_OID = re.compile(r"[0-2](?:\.(?:0|[1-9][0-9]*))+\Z")
_OPENSSL_TIMEOUT_SECONDS = 10.0


class Rfc3161TimestampError(ValueError):
    """RFC 3161 evidence failed closed verification."""

    code = "RFC3161_TIMESTAMP_INVALID"


@dataclass(frozen=True, slots=True)
class Rfc3161TimestampIdentity:
    """Metadata-only identity of one verified RFC 3161 timestamp response."""

    subject_kind: TimestampSubjectKind
    subject_digest: str
    hash_algorithm: str
    policy_oid: str
    serial_number: str
    generated_at: datetime
    request_digest: str
    response_digest: str
    signer_certificate_digest: str
    signature_digest: str


def verify_rfc3161_timestamp(
    artifact_path: Path,
    request_path: Path,
    response_path: Path,
    ca_bundle_path: Path,
    *,
    subject_kind: TimestampSubjectKind,
    allowed_policy_oids: tuple[str, ...],
    evaluated_at: datetime,
    minimum_generated_at: datetime | None = None,
    untrusted_certificates_path: Path | None = None,
) -> Rfc3161TimestampIdentity:
    """Verify request, response, PKIX authority and exact artifact bytes offline."""
    _require_utc(evaluated_at, "Timestamp evaluation time")
    if minimum_generated_at is not None:
        _require_utc(minimum_generated_at, "Minimum timestamp time")
    if not allowed_policy_oids or len(set(allowed_policy_oids)) != len(allowed_policy_oids):
        raise Rfc3161TimestampError("Timestamp policy allowlist is empty or duplicated")
    if any(_OID.fullmatch(item) is None for item in allowed_policy_oids):
        raise Rfc3161TimestampError("Timestamp policy allowlist contains an invalid OID")

    artifact = _read_regular_file(artifact_path, maximum_size=8_388_608, label="artifact")
    request_bytes = _read_regular_file(request_path, maximum_size=262_144, label="request")
    response_bytes = _read_regular_file(response_path, maximum_size=1_048_576, label="response")
    _read_regular_file(ca_bundle_path, maximum_size=1_048_576, label="CA bundle")
    if untrusted_certificates_path is not None:
        _read_regular_file(
            untrusted_certificates_path,
            maximum_size=1_048_576,
            label="untrusted certificate bundle",
        )

    request = _parse_request(request_bytes)
    timestamp_info, signed_data = _parse_response(response_bytes)
    request_imprint = _message_imprint(request["message_imprint"].native)
    response_imprint = _message_imprint(timestamp_info["message_imprint"].native)
    hash_algorithm, expected_digest = _artifact_digest(artifact, request_imprint[0])
    if request_imprint != response_imprint or request_imprint[1] != expected_digest:
        raise Rfc3161TimestampError("RFC 3161 message imprint does not bind the artifact")

    request_policy = _required_string(request["req_policy"].native, "request policy")
    response_policy = _required_string(timestamp_info["policy"].native, "response policy")
    if request_policy != response_policy or response_policy not in allowed_policy_oids:
        raise Rfc3161TimestampError("RFC 3161 policy is mismatched or not allowed")
    request_nonce = _required_integer(request["nonce"].native, "request nonce")
    response_nonce = _required_integer(timestamp_info["nonce"].native, "response nonce")
    if request_nonce != response_nonce:
        raise Rfc3161TimestampError("RFC 3161 nonce is missing or mismatched")

    generated_at = timestamp_info["gen_time"].native
    if not isinstance(generated_at, datetime):
        raise Rfc3161TimestampError("RFC 3161 generation time is invalid")
    _require_utc(generated_at, "RFC 3161 generation time")
    if generated_at > evaluated_at:
        raise Rfc3161TimestampError("RFC 3161 response is later than the evaluation time")
    if minimum_generated_at is not None and generated_at < minimum_generated_at:
        raise Rfc3161TimestampError("RFC 3161 response is older than the required floor")

    serial_number = _required_integer(timestamp_info["serial_number"].native, "serial number")
    signer_info = _single_signer(signed_data)
    signer_certificate = _find_signer_certificate(signed_data, signer_info)
    _verify_with_openssl(
        request_path=request_path,
        response_path=response_path,
        ca_bundle_path=ca_bundle_path,
        untrusted_certificates_path=untrusted_certificates_path,
        generated_at=generated_at,
    )
    return Rfc3161TimestampIdentity(
        subject_kind=subject_kind,
        subject_digest=_digest(artifact),
        hash_algorithm=hash_algorithm,
        policy_oid=response_policy,
        serial_number=str(serial_number),
        generated_at=generated_at,
        request_digest=_digest(request_bytes),
        response_digest=_digest(response_bytes),
        signer_certificate_digest=_digest(signer_certificate.dump()),
        signature_digest=_digest(signer_info["signature"].native),
    )


def _parse_request(value: bytes) -> tsp.TimeStampReq:
    try:
        request = tsp.TimeStampReq.load(value, strict=True)
        if request["version"].native != "v1":
            raise Rfc3161TimestampError("RFC 3161 request version is not supported")
        return request
    except (ValueError, TypeError, KeyError) as exc:
        raise Rfc3161TimestampError("RFC 3161 request is not strict DER") from exc


def _parse_response(value: bytes) -> tuple[tsp.TSTInfo, cms.SignedData]:
    try:
        response = tsp.TimeStampResp.load(value, strict=True)
        if response["status"]["status"].native not in {"granted", "granted_with_mods"}:
            raise Rfc3161TimestampError("RFC 3161 response status is not granted")
        token = response["time_stamp_token"]
        if token.native is None or token["content_type"].native != "signed_data":
            raise Rfc3161TimestampError("RFC 3161 response has no CMS signed-data token")
        signed_data = token["content"]
        if not isinstance(signed_data, cms.SignedData):
            raise Rfc3161TimestampError("RFC 3161 token content is invalid")
        encapsulated = signed_data["encap_content_info"]
        if encapsulated["content_type"].native != "tst_info":
            raise Rfc3161TimestampError("RFC 3161 token does not contain TSTInfo")
        parsed = encapsulated["content"].parsed
        if not isinstance(parsed, tsp.TSTInfo) or parsed["version"].native != "v1":
            raise Rfc3161TimestampError("RFC 3161 TSTInfo is invalid")
        return parsed, signed_data
    except (ValueError, TypeError, KeyError) as exc:
        raise Rfc3161TimestampError("RFC 3161 response is not strict DER") from exc


def _message_imprint(value: Any) -> tuple[str, bytes]:
    if not isinstance(value, dict):
        raise Rfc3161TimestampError("RFC 3161 message imprint is invalid")
    algorithm_value = value.get("hash_algorithm")
    hashed_message = value.get("hashed_message")
    if not isinstance(algorithm_value, dict) or not isinstance(hashed_message, bytes):
        raise Rfc3161TimestampError("RFC 3161 message imprint is invalid")
    algorithm = algorithm_value.get("algorithm")
    if not isinstance(algorithm, str) or algorithm not in _ALLOWED_HASHES:
        raise Rfc3161TimestampError("RFC 3161 hash algorithm is not allowed")
    if len(hashed_message) != _ALLOWED_HASHES[algorithm]().digest_size:
        raise Rfc3161TimestampError("RFC 3161 message imprint length is invalid")
    return algorithm, hashed_message


def _artifact_digest(value: bytes, algorithm: str) -> tuple[str, bytes]:
    digest = _ALLOWED_HASHES.get(algorithm)
    if digest is None:
        raise Rfc3161TimestampError("RFC 3161 hash algorithm is not allowed")
    return algorithm, digest(value).digest()


def _single_signer(signed_data: cms.SignedData) -> cms.SignerInfo:
    signers = signed_data["signer_infos"]
    if len(signers) != 1:
        raise Rfc3161TimestampError("RFC 3161 token must contain exactly one signer")
    signer = signers[0]
    if signer["sid"].name != "issuer_and_serial_number":
        raise Rfc3161TimestampError("RFC 3161 signer identifier is not supported")
    return signer


def _find_signer_certificate(
    signed_data: cms.SignedData, signer_info: cms.SignerInfo
) -> x509.Certificate:
    signer_id = signer_info["sid"].chosen
    serial = signer_id["serial_number"].native
    issuer = signer_id["issuer"].dump()
    for choice in signed_data["certificates"]:
        if choice.name != "certificate":
            continue
        certificate = choice.chosen
        if certificate.serial_number == serial and certificate.issuer.dump() == issuer:
            return certificate
    raise Rfc3161TimestampError("RFC 3161 signer certificate is missing")


def _verify_with_openssl(
    *,
    request_path: Path,
    response_path: Path,
    ca_bundle_path: Path,
    untrusted_certificates_path: Path | None,
    generated_at: datetime,
) -> None:
    binary = shutil.which("openssl")
    if binary is None:
        raise Rfc3161TimestampError("OpenSSL is required for RFC 3161 verification")
    command = [
        binary,
        "ts",
        "-verify",
        "-queryfile",
        str(request_path),
        "-in",
        str(response_path),
        "-CAfile",
        str(ca_bundle_path),
        "-attime",
        str(int(generated_at.timestamp())),
    ]
    if untrusted_certificates_path is not None:
        command.extend(("-untrusted", str(untrusted_certificates_path)))
    try:
        # The command uses the resolved OpenSSL binary and an argv list, never a shell.
        completed = subprocess.run(  # noqa: S603  # nosec B603
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_OPENSSL_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Rfc3161TimestampError("OpenSSL RFC 3161 verification could not complete") from exc
    if completed.returncode != 0:
        raise Rfc3161TimestampError("RFC 3161 signature or certificate verification failed")


def _read_regular_file(path: Path, *, maximum_size: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise Rfc3161TimestampError(f"RFC 3161 {label} path is not allowed")
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise Rfc3161TimestampError(f"RFC 3161 {label} could not be read") from exc
    if not value or len(value) > maximum_size:
        raise Rfc3161TimestampError(f"RFC 3161 {label} has an invalid size")
    return value


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Rfc3161TimestampError(f"RFC 3161 {label} is invalid")
    return value


def _required_integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise Rfc3161TimestampError(f"RFC 3161 {label} is invalid")
    return value


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise Rfc3161TimestampError(f"{label} must be timezone-aware UTC")


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
