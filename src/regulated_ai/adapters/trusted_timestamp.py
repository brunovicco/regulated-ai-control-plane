"""Strict verification of provider-neutral signed time-authority receipts."""

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from regulated_ai.adapters.trust_key_lifecycle import TrustKeyLifecycleModel

_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"


class TrustedTimestampError(ValueError):
    """Signed time-authority receipt failed closed verification."""

    code = "TRUSTED_TIMESTAMP_INVALID"


class TimestampSubjectKind(StrEnum):
    """Bounded evidence artifacts accepted by the timestamp verifier."""

    RELEASE_EVIDENCE_BUNDLE = "RELEASE_EVIDENCE_BUNDLE"
    PROMOTION_AUTHORIZATION_REPORT = "PROMOTION_AUTHORIZATION_REPORT"
    RELEASE_CUSTODY_MANIFEST = "RELEASE_CUSTODY_MANIFEST"
    TRUST_STORE_CHECKPOINT = "TRUST_STORE_CHECKPOINT"
    TRUST_STORE_ROLLOUT_REPORT = "TRUST_STORE_ROLLOUT_REPORT"
    RUNTIME_TRUST_STATE_REPORT = "RUNTIME_TRUST_STATE_REPORT"


@dataclass(frozen=True, slots=True)
class TrustedTimestampIdentity:
    """Verified identity of one external authority time assertion."""

    receipt_id: str
    subject_kind: TimestampSubjectKind
    subject_digest: str
    issued_at: datetime
    authority_id: str
    signing_key_id: str
    receipt_digest: str
    signature_digest: str


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _TimestampKeyModel(TrustKeyLifecycleModel):
    algorithm: Literal["ed25519"]
    public_key: str = Field(min_length=1, max_length=128)
    authority_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)


class _TimestampTrustStoreModel(_StrictModel):
    schema_version: Literal["2"]
    keys: dict[str, _TimestampKeyModel] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def valid_key_ids(self) -> "_TimestampTrustStoreModel":
        if any(re.fullmatch(_IDENTIFIER, item) is None for item in self.keys):
            raise ValueError("timestamp trust-store key id is invalid")
        return self


class _TimestampReceiptModel(_StrictModel):
    schema_version: Literal["1"]
    receipt_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    subject_kind: TimestampSubjectKind
    subject_digest: str = Field(pattern=_DIGEST)
    issued_at: datetime
    authority_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    signing_key_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    signature: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def utc_time(self) -> "_TimestampReceiptModel":
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() != UTC.utcoffset(
            self.issued_at
        ):
            raise ValueError("timestamp receipt time must be timezone-aware UTC")
        return self


def verify_trusted_timestamp(
    artifact_path: Path,
    receipt_path: Path,
    trust_store_path: Path,
    *,
    expected_subject_kind: TimestampSubjectKind,
    evaluated_at: datetime,
    minimum_issued_at: datetime | None = None,
) -> TrustedTimestampIdentity:
    """Verify an artifact digest and its signed external authority time assertion."""
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
        raise TrustedTimestampError("Timestamp evaluation time must be timezone-aware UTC")
    if minimum_issued_at is not None and (
        minimum_issued_at.tzinfo is None
        or minimum_issued_at.utcoffset() != UTC.utcoffset(minimum_issued_at)
    ):
        raise TrustedTimestampError("Minimum timestamp time must be timezone-aware UTC")
    artifact = _read_artifact(artifact_path)
    try:
        receipt = _TimestampReceiptModel.model_validate(_read_strict_yaml(receipt_path))
        trust_store = _TimestampTrustStoreModel.model_validate(_read_strict_yaml(trust_store_path))
    except ValidationError as exc:
        raise TrustedTimestampError("Timestamp metadata failed schema validation") from exc
    if receipt.subject_kind is not expected_subject_kind:
        raise TrustedTimestampError("Timestamp receipt subject kind is not expected")
    if receipt.subject_digest != _digest(artifact):
        raise TrustedTimestampError("Timestamp receipt does not bind the artifact bytes")
    if receipt.issued_at > evaluated_at:
        raise TrustedTimestampError("Timestamp receipt is later than the evaluation time")
    if minimum_issued_at is not None and receipt.issued_at < minimum_issued_at:
        raise TrustedTimestampError("Timestamp receipt is older than the required floor")
    key = trust_store.keys.get(receipt.signing_key_id)
    if key is None:
        raise TrustedTimestampError("Timestamp authority key is not trusted")
    if key.authority_id != receipt.authority_id:
        raise TrustedTimestampError("Timestamp authority does not match its key")
    if not key.active_at(receipt.issued_at):
        raise TrustedTimestampError("Timestamp authority key is not active")
    payload = _receipt_payload(receipt)
    signature = _decode_base64(receipt.signature, expected_length=64)
    public_key = _decode_base64(key.public_key, expected_length=32)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
    except (InvalidSignature, ValueError) as exc:
        raise TrustedTimestampError("Timestamp receipt signature is invalid") from exc
    return TrustedTimestampIdentity(
        receipt_id=receipt.receipt_id,
        subject_kind=receipt.subject_kind,
        subject_digest=receipt.subject_digest,
        issued_at=receipt.issued_at,
        authority_id=receipt.authority_id,
        signing_key_id=receipt.signing_key_id,
        receipt_digest=_digest(payload),
        signature_digest=_digest(signature),
    )


def _receipt_payload(receipt: _TimestampReceiptModel) -> bytes:
    return _canonical_json(
        {
            "authority_id": receipt.authority_id,
            "issued_at": receipt.issued_at.isoformat(),
            "receipt_id": receipt.receipt_id,
            "schema_version": receipt.schema_version,
            "signing_key_id": receipt.signing_key_id,
            "subject_digest": receipt.subject_digest,
            "subject_kind": receipt.subject_kind.value,
        }
    )


def _read_artifact(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise TrustedTimestampError("Timestamp subject path is not allowed")
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise TrustedTimestampError("Timestamp subject could not be read") from exc
    if not value or len(value) > 8_388_608:
        raise TrustedTimestampError("Timestamp subject has an invalid size")
    return value


def _read_strict_yaml(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TrustedTimestampError("Timestamp metadata path is not allowed")
    try:
        encoded = path.read_bytes()
        if not encoded or len(encoded) > 262_144:
            raise TrustedTimestampError("Timestamp metadata has an invalid size")
        text = encoded.decode("utf-8")
        syntax_tree = yaml.compose(text, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw: Any = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise TrustedTimestampError("Timestamp metadata is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise TrustedTimestampError("Timestamp metadata must be a mapping")
    return raw


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("timestamp metadata keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("timestamp metadata contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)


def _decode_base64(value: str, *, expected_length: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TrustedTimestampError("Timestamp metadata contains invalid base64") from exc
    if len(decoded) != expected_length:
        raise TrustedTimestampError("Timestamp cryptographic length is invalid")
    return decoded


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
