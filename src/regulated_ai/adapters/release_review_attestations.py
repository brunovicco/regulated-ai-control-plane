"""Strict verification for signed release-entity review attestations."""

import base64
import binascii
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from regulated_ai.domain import (
    ControlPackChangeType,
    ReleaseReviewArtifactKind,
    ReleaseReviewConclusion,
    VerifiedReleaseReviewAttestation,
)

_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"


class ReleaseReviewAttestationError(ValueError):
    """Review attestation metadata failed strict verification."""

    code = "RELEASE_REVIEW_ATTESTATION_INVALID"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ReviewTrustKeyModel(_StrictModel):
    algorithm: Literal["ed25519"]
    public_key: str = Field(min_length=1, max_length=128)
    roles: tuple[str, ...] = Field(min_length=1, max_length=16)
    artifact_kinds: tuple[ReleaseReviewArtifactKind, ...] = Field(min_length=1, max_length=2)
    change_types: tuple[ControlPackChangeType, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def normalized_authority(self) -> "_ReviewTrustKeyModel":
        """Require unique bounded roles and authority dimensions."""
        if any(re.fullmatch(_IDENTIFIER, role) is None or len(role) > 128 for role in self.roles):
            raise ValueError("release review trust key contains an invalid role")
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("release review trust key contains duplicate roles")
        if len(set(self.artifact_kinds)) != len(self.artifact_kinds):
            raise ValueError("release review trust key contains duplicate artifact kinds")
        if len(set(self.change_types)) != len(self.change_types):
            raise ValueError("release review trust key contains duplicate change types")
        return self


class _ReviewTrustStoreModel(_StrictModel):
    schema_version: Literal["1"]
    keys: dict[str, _ReviewTrustKeyModel] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def normalized_key_ids(self) -> "_ReviewTrustStoreModel":
        """Require bounded identifiers for every trusted reviewer key."""
        if any(
            re.fullmatch(_IDENTIFIER, key_id) is None or len(key_id) > 128 for key_id in self.keys
        ):
            raise ValueError("release review trust store contains an invalid key id")
        return self


class _ReviewAttestationModel(_StrictModel):
    schema_version: Literal["1"]
    attestation_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    artifact_kind: ReleaseReviewArtifactKind
    subject_id: str = Field(min_length=1, max_length=384, pattern=_IDENTIFIER)
    change_type: ControlPackChangeType
    base_pack_payload_digest: str = Field(pattern=_DIGEST)
    candidate_pack_payload_digest: str = Field(pattern=_DIGEST)
    reviewed_content_digest: str = Field(pattern=_DIGEST)
    review_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=_IDENTIFIER)
    review_digest: str | None = Field(default=None, pattern=_DIGEST)
    reviewer_role: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    conclusion: ReleaseReviewConclusion
    attested_at: datetime
    signing_key_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    signature: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def valid_review_binding(self) -> "_ReviewAttestationModel":
        """Bind modifications to detailed review records and lifecycle reviews directly."""
        if self.attested_at.tzinfo is None or self.attested_at.utcoffset() != UTC.utcoffset(
            self.attested_at
        ):
            raise ValueError("release review attestation time must be timezone-aware UTC")
        has_review = self.review_id is not None and self.review_digest is not None
        if self.change_type is ControlPackChangeType.MODIFIED and not has_review:
            raise ValueError("modified entity attestation requires a detailed review binding")
        if self.change_type is not ControlPackChangeType.MODIFIED and (
            self.review_id is not None or self.review_digest is not None
        ):
            raise ValueError("lifecycle attestation cannot bind an update-only review")
        return self


def verify_release_review_attestations(
    paths: tuple[Path, ...], trust_store_path: Path
) -> tuple[VerifiedReleaseReviewAttestation, ...]:
    """Verify review signatures and key authority without trusting file ordering."""
    try:
        trust_store = _ReviewTrustStoreModel.model_validate(_read_strict_yaml(trust_store_path))
    except ValidationError as exc:
        raise ReleaseReviewAttestationError(
            "Release review trust store failed schema validation"
        ) from exc

    verified = []
    for path in paths:
        try:
            attestation = _ReviewAttestationModel.model_validate(_read_strict_yaml(path))
        except ValidationError as exc:
            raise ReleaseReviewAttestationError(
                "Release review attestation failed schema validation"
            ) from exc
        key = trust_store.keys.get(attestation.signing_key_id)
        if key is None:
            raise ReleaseReviewAttestationError("Release review attestation key is not trusted")
        if attestation.reviewer_role not in key.roles:
            raise ReleaseReviewAttestationError(
                "Release review attestation role is not authorized for its key"
            )
        if attestation.artifact_kind not in key.artifact_kinds:
            raise ReleaseReviewAttestationError(
                "Release review attestation artifact kind is not authorized for its key"
            )
        if attestation.change_type not in key.change_types:
            raise ReleaseReviewAttestationError(
                "Release review attestation change type is not authorized for its key"
            )

        payload = _canonical_payload(attestation)
        signature = _decode_base64(attestation.signature, expected_length=64)
        public_key = _decode_base64(key.public_key, expected_length=32)
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
        except (InvalidSignature, ValueError) as exc:
            raise ReleaseReviewAttestationError(
                "Release review attestation signature is invalid"
            ) from exc
        verified.append(
            VerifiedReleaseReviewAttestation(
                attestation_id=attestation.attestation_id,
                kind=attestation.artifact_kind,
                subject_id=attestation.subject_id,
                change_type=attestation.change_type,
                base_pack_payload_digest=attestation.base_pack_payload_digest,
                candidate_pack_payload_digest=attestation.candidate_pack_payload_digest,
                reviewed_content_digest=attestation.reviewed_content_digest,
                review_id=attestation.review_id,
                review_digest=attestation.review_digest,
                reviewer_role=attestation.reviewer_role,
                conclusion=attestation.conclusion,
                attested_at=attestation.attested_at,
                signing_key_id=attestation.signing_key_id,
                attestation_digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
                signature_digest=f"sha256:{hashlib.sha256(signature).hexdigest()}",
            )
        )
    return tuple(verified)


def _canonical_payload(attestation: _ReviewAttestationModel) -> bytes:
    payload = {
        "artifact_kind": attestation.artifact_kind.value,
        "attestation_id": attestation.attestation_id,
        "attested_at": attestation.attested_at.isoformat(),
        "base_pack_payload_digest": attestation.base_pack_payload_digest,
        "candidate_pack_payload_digest": attestation.candidate_pack_payload_digest,
        "change_type": attestation.change_type.value,
        "conclusion": attestation.conclusion.value,
        "review_digest": attestation.review_digest,
        "review_id": attestation.review_id,
        "reviewed_content_digest": attestation.reviewed_content_digest,
        "reviewer_role": attestation.reviewer_role,
        "schema_version": attestation.schema_version,
        "signing_key_id": attestation.signing_key_id,
        "subject_id": attestation.subject_id,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _read_strict_yaml(path: Path) -> dict[str, Any]:
    try:
        encoded = path.read_bytes()
        if len(encoded) > 262_144:
            raise ReleaseReviewAttestationError("Release review metadata exceeds the size limit")
        content = encoded.decode("utf-8")
        syntax_tree = yaml.compose(content, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw = yaml.safe_load(content)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ReleaseReviewAttestationError("Release review metadata is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise ReleaseReviewAttestationError("Release review metadata must be a mapping")
    return raw


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("release review metadata keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("release review metadata contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)


def _decode_base64(value: str, *, expected_length: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ReleaseReviewAttestationError(
            "Release review metadata contains invalid base64"
        ) from exc
    if len(decoded) != expected_length:
        raise ReleaseReviewAttestationError(
            "Release review metadata has an invalid cryptographic length"
        )
    return decoded
