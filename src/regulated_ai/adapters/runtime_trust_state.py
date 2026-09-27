"""Strict verification for signed runtime trust-state assertions."""

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
from regulated_ai.domain import RuntimeTrustStatePolicy, VerifiedRuntimeTrustStateAttestation

_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"


class RuntimeTrustStateError(ValueError):
    """Runtime trust-state policy or attestation failed strict verification."""

    code = "RUNTIME_TRUST_STATE_INVALID"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _PolicyModel(_StrictModel):
    schema_version: Literal["1"]
    policy_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    policy_version: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    checkpoint_digest: str = Field(pattern=_DIGEST)
    allowed_target_ids: tuple[str, ...] = Field(min_length=1, max_length=256)
    required_target_ids: tuple[str, ...] = Field(default=(), max_length=256)
    minimum_attestations: int = Field(ge=1, le=256)
    maximum_age_seconds: int = Field(ge=1, le=86_400)

    @model_validator(mode="after")
    def valid_targets(self) -> "_PolicyModel":
        allowed = set(self.allowed_target_ids)
        if (
            len(allowed) != len(self.allowed_target_ids)
            or any(re.fullmatch(_IDENTIFIER, item) is None for item in allowed)
            or len(set(self.required_target_ids)) != len(self.required_target_ids)
            or not set(self.required_target_ids).issubset(allowed)
            or self.minimum_attestations < len(self.required_target_ids)
            or self.minimum_attestations > len(allowed)
        ):
            raise ValueError("runtime trust-state target coverage is invalid")
        return self


class _AttestationKeyModel(TrustKeyLifecycleModel):
    algorithm: Literal["ed25519"]
    public_key: str = Field(min_length=1, max_length=128)
    target_ids: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def valid_targets(self) -> "_AttestationKeyModel":
        if len(set(self.target_ids)) != len(self.target_ids) or any(
            re.fullmatch(_IDENTIFIER, item) is None for item in self.target_ids
        ):
            raise ValueError("runtime trust-state key target ids are invalid")
        return self


class _AttestationTrustStoreModel(_StrictModel):
    schema_version: Literal["2"]
    keys: dict[str, _AttestationKeyModel] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def valid_key_ids(self) -> "_AttestationTrustStoreModel":
        if any(re.fullmatch(_IDENTIFIER, item) is None for item in self.keys):
            raise ValueError("runtime trust-state key id is invalid")
        return self


class _AttestationModel(_StrictModel):
    schema_version: Literal["1"]
    attestation_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    checkpoint_digest: str = Field(pattern=_DIGEST)
    runtime_policy_digest: str = Field(pattern=_DIGEST)
    store_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    store_kind: Literal["CONTROL_PACK", "RELEASE_REVIEW", "RELEASE_PROMOTION"]
    sequence: int = Field(ge=1, le=2_147_483_647)
    loaded_trust_store_digest: str = Field(pattern=_DIGEST)
    target_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    observed_at: datetime
    signing_key_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    signature: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def utc_time(self) -> "_AttestationModel":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() != UTC.utcoffset(
            self.observed_at
        ):
            raise ValueError("runtime trust-state observation time must be timezone-aware UTC")
        return self


def load_runtime_trust_state_policy(path: Path) -> RuntimeTrustStatePolicy:
    """Load one strict checkpoint-bound runtime-state policy."""
    try:
        model = _PolicyModel.model_validate(_read_strict_yaml(path))
    except ValidationError as exc:
        raise RuntimeTrustStateError("Runtime trust-state policy failed schema validation") from exc
    canonical = {
        "allowed_target_ids": sorted(model.allowed_target_ids),
        "checkpoint_digest": model.checkpoint_digest,
        "maximum_age_seconds": model.maximum_age_seconds,
        "minimum_attestations": model.minimum_attestations,
        "policy_id": model.policy_id,
        "policy_version": model.policy_version,
        "required_target_ids": sorted(model.required_target_ids),
        "schema_version": model.schema_version,
    }
    return RuntimeTrustStatePolicy(
        policy_id=model.policy_id,
        policy_version=model.policy_version,
        checkpoint_digest=model.checkpoint_digest,
        allowed_target_ids=tuple(sorted(model.allowed_target_ids)),
        required_target_ids=tuple(sorted(model.required_target_ids)),
        minimum_attestations=model.minimum_attestations,
        maximum_age_seconds=model.maximum_age_seconds,
        policy_digest=_digest(_canonical_json(canonical)),
    )


def verify_runtime_trust_state_attestations(
    paths: tuple[Path, ...], trust_store_path: Path
) -> tuple[VerifiedRuntimeTrustStateAttestation, ...]:
    """Verify target runtime-state assertions against lifecycle-aware public keys."""
    try:
        trust_store = _AttestationTrustStoreModel.model_validate(
            _read_strict_yaml(trust_store_path)
        )
    except ValidationError as exc:
        raise RuntimeTrustStateError(
            "Runtime trust-state trust store failed schema validation"
        ) from exc

    verified = []
    for path in paths:
        try:
            model = _AttestationModel.model_validate(_read_strict_yaml(path))
        except ValidationError as exc:
            raise RuntimeTrustStateError(
                "Runtime trust-state attestation failed schema validation"
            ) from exc
        key = trust_store.keys.get(model.signing_key_id)
        if key is None:
            raise RuntimeTrustStateError("Runtime trust-state key is not trusted")
        if not key.active_at(model.observed_at):
            raise RuntimeTrustStateError("Runtime trust-state key is not active")
        if model.target_id not in key.target_ids:
            raise RuntimeTrustStateError("Runtime target is not authorized for its key")
        payload = _attestation_payload(model)
        signature = _decode_base64(model.signature, expected_length=64)
        public_key = _decode_base64(key.public_key, expected_length=32)
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
        except (InvalidSignature, ValueError) as exc:
            raise RuntimeTrustStateError("Runtime trust-state signature is invalid") from exc
        verified.append(
            VerifiedRuntimeTrustStateAttestation(
                attestation_id=model.attestation_id,
                checkpoint_digest=model.checkpoint_digest,
                runtime_policy_digest=model.runtime_policy_digest,
                store_id=model.store_id,
                store_kind=model.store_kind,
                sequence=model.sequence,
                loaded_trust_store_digest=model.loaded_trust_store_digest,
                target_id=model.target_id,
                observed_at=model.observed_at,
                signing_key_id=model.signing_key_id,
                attestation_digest=_digest(payload),
                signature_digest=_digest(signature),
            )
        )
    return tuple(verified)


def _attestation_payload(model: _AttestationModel) -> bytes:
    return _canonical_json(
        {
            "attestation_id": model.attestation_id,
            "checkpoint_digest": model.checkpoint_digest,
            "loaded_trust_store_digest": model.loaded_trust_store_digest,
            "observed_at": model.observed_at.isoformat(),
            "runtime_policy_digest": model.runtime_policy_digest,
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
        raise RuntimeTrustStateError("Runtime trust-state metadata path is not allowed")
    try:
        encoded = path.read_bytes()
        if not encoded or len(encoded) > 262_144:
            raise RuntimeTrustStateError("Runtime trust-state metadata has an invalid size")
        text = encoded.decode("utf-8")
        syntax_tree = yaml.compose(text, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw: Any = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RuntimeTrustStateError("Runtime trust-state metadata is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise RuntimeTrustStateError("Runtime trust-state metadata must be a mapping")
    return raw


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("runtime trust-state metadata keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("runtime trust-state metadata contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)


def _decode_base64(value: str, *, expected_length: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeTrustStateError(
            "Runtime trust-state metadata contains invalid base64"
        ) from exc
    if len(decoded) != expected_length:
        raise RuntimeTrustStateError("Runtime trust-state cryptographic length is invalid")
    return decoded


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
