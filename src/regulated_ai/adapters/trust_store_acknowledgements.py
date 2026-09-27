"""Strict verification for trust-store rollout policies and acknowledgements."""

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

from regulated_ai.adapters.trust_key_lifecycle import TrustKeyLifecycleModel
from regulated_ai.domain import TrustStoreRolloutPolicy, VerifiedTrustStoreAcknowledgement

_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"


class TrustStoreAcknowledgementError(ValueError):
    """Rollout policy or acknowledgement failed strict verification."""

    code = "TRUST_STORE_ACKNOWLEDGEMENT_INVALID"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _PolicyModel(_StrictModel):
    schema_version: Literal["1"]
    policy_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    policy_version: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    checkpoint_digest: str = Field(pattern=_DIGEST)
    allowed_target_ids: tuple[str, ...] = Field(min_length=1, max_length=256)
    required_target_ids: tuple[str, ...] = Field(default=(), max_length=256)
    minimum_acknowledgements: int = Field(ge=1, le=256)

    @model_validator(mode="after")
    def valid_targets(self) -> "_PolicyModel":
        allowed = set(self.allowed_target_ids)
        if (
            len(allowed) != len(self.allowed_target_ids)
            or any(re.fullmatch(_IDENTIFIER, item) is None for item in allowed)
            or len(set(self.required_target_ids)) != len(self.required_target_ids)
            or not set(self.required_target_ids).issubset(allowed)
            or self.minimum_acknowledgements < len(self.required_target_ids)
            or self.minimum_acknowledgements > len(allowed)
        ):
            raise ValueError("rollout policy target coverage is invalid")
        return self


class _AcknowledgementKeyModel(TrustKeyLifecycleModel):
    algorithm: Literal["ed25519"]
    public_key: str = Field(min_length=1, max_length=128)
    target_ids: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def valid_targets(self) -> "_AcknowledgementKeyModel":
        if len(set(self.target_ids)) != len(self.target_ids) or any(
            re.fullmatch(_IDENTIFIER, item) is None for item in self.target_ids
        ):
            raise ValueError("acknowledgement key target ids are invalid")
        return self


class _AcknowledgementTrustStoreModel(_StrictModel):
    schema_version: Literal["2"]
    keys: dict[str, _AcknowledgementKeyModel] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def valid_key_ids(self) -> "_AcknowledgementTrustStoreModel":
        if any(re.fullmatch(_IDENTIFIER, item) is None for item in self.keys):
            raise ValueError("acknowledgement trust-store key id is invalid")
        return self


class _AcknowledgementModel(_StrictModel):
    schema_version: Literal["1"]
    acknowledgement_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    checkpoint_digest: str = Field(pattern=_DIGEST)
    rollout_policy_digest: str = Field(pattern=_DIGEST)
    store_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    store_kind: Literal["CONTROL_PACK", "RELEASE_REVIEW", "RELEASE_PROMOTION"]
    sequence: int = Field(ge=1, le=2_147_483_647)
    target_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    accepted_at: datetime
    signing_key_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    signature: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def utc_time(self) -> "_AcknowledgementModel":
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() != UTC.utcoffset(
            self.accepted_at
        ):
            raise ValueError("rollout acknowledgement time must be timezone-aware UTC")
        return self


def load_trust_store_rollout_policy(path: Path) -> TrustStoreRolloutPolicy:
    """Load one strict checkpoint-bound target coverage policy."""
    try:
        model = _PolicyModel.model_validate(_read_strict_yaml(path))
    except ValidationError as exc:
        raise TrustStoreAcknowledgementError(
            "Trust-store rollout policy failed schema validation"
        ) from exc
    canonical = {
        "allowed_target_ids": sorted(model.allowed_target_ids),
        "checkpoint_digest": model.checkpoint_digest,
        "minimum_acknowledgements": model.minimum_acknowledgements,
        "policy_id": model.policy_id,
        "policy_version": model.policy_version,
        "required_target_ids": sorted(model.required_target_ids),
        "schema_version": model.schema_version,
    }
    return TrustStoreRolloutPolicy(
        policy_id=model.policy_id,
        policy_version=model.policy_version,
        checkpoint_digest=model.checkpoint_digest,
        allowed_target_ids=tuple(sorted(model.allowed_target_ids)),
        required_target_ids=tuple(sorted(model.required_target_ids)),
        minimum_acknowledgements=model.minimum_acknowledgements,
        policy_digest=_digest(_canonical_json(canonical)),
    )


def verify_trust_store_acknowledgements(
    paths: tuple[Path, ...], trust_store_path: Path
) -> tuple[VerifiedTrustStoreAcknowledgement, ...]:
    """Verify consumer acknowledgements against lifecycle-aware public keys."""
    try:
        trust_store = _AcknowledgementTrustStoreModel.model_validate(
            _read_strict_yaml(trust_store_path)
        )
    except ValidationError as exc:
        raise TrustStoreAcknowledgementError(
            "Acknowledgement trust store failed schema validation"
        ) from exc

    verified = []
    for path in paths:
        try:
            model = _AcknowledgementModel.model_validate(_read_strict_yaml(path))
        except ValidationError as exc:
            raise TrustStoreAcknowledgementError(
                "Trust-store acknowledgement failed schema validation"
            ) from exc
        key = trust_store.keys.get(model.signing_key_id)
        if key is None:
            raise TrustStoreAcknowledgementError("Acknowledgement key is not trusted")
        if not key.active_at(model.accepted_at):
            raise TrustStoreAcknowledgementError("Acknowledgement key is not active")
        if model.target_id not in key.target_ids:
            raise TrustStoreAcknowledgementError(
                "Acknowledgement target is not authorized for its key"
            )
        payload = _acknowledgement_payload(model)
        signature = _decode_base64(model.signature, expected_length=64)
        public_key = _decode_base64(key.public_key, expected_length=32)
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
        except (InvalidSignature, ValueError) as exc:
            raise TrustStoreAcknowledgementError(
                "Trust-store acknowledgement signature is invalid"
            ) from exc
        verified.append(
            VerifiedTrustStoreAcknowledgement(
                acknowledgement_id=model.acknowledgement_id,
                checkpoint_digest=model.checkpoint_digest,
                rollout_policy_digest=model.rollout_policy_digest,
                store_id=model.store_id,
                store_kind=model.store_kind,
                sequence=model.sequence,
                target_id=model.target_id,
                accepted_at=model.accepted_at,
                signing_key_id=model.signing_key_id,
                acknowledgement_digest=_digest(payload),
                signature_digest=_digest(signature),
            )
        )
    return tuple(verified)


def _acknowledgement_payload(model: _AcknowledgementModel) -> bytes:
    return _canonical_json(
        {
            "accepted_at": model.accepted_at.isoformat(),
            "acknowledgement_id": model.acknowledgement_id,
            "checkpoint_digest": model.checkpoint_digest,
            "rollout_policy_digest": model.rollout_policy_digest,
            "schema_version": model.schema_version,
            "sequence": model.sequence,
            "signing_key_id": model.signing_key_id,
            "store_id": model.store_id,
            "store_kind": model.store_kind,
            "target_id": model.target_id,
        }
    )


def _read_strict_yaml(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TrustStoreAcknowledgementError("Rollout metadata path is not allowed")
    try:
        encoded = path.read_bytes()
        if not encoded or len(encoded) > 262_144:
            raise TrustStoreAcknowledgementError("Rollout metadata has an invalid size")
        text = encoded.decode("utf-8")
        syntax_tree = yaml.compose(text, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw: Any = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise TrustStoreAcknowledgementError("Rollout metadata is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise TrustStoreAcknowledgementError("Rollout metadata must be a mapping")
    return raw


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("rollout metadata keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("rollout metadata contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)


def _decode_base64(value: str, *, expected_length: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TrustStoreAcknowledgementError("Rollout metadata contains invalid base64") from exc
    if len(decoded) != expected_length:
        raise TrustStoreAcknowledgementError("Rollout metadata cryptographic length is invalid")
    return decoded


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
