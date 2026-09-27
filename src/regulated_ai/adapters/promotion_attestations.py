"""Strict local verification for release bundles and promotion attestations."""

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
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from regulated_ai.domain import (
    ControlPackReleaseIdentity,
    PromotionAttestationDecision,
    PromotionPolicy,
    ReleaseEvidenceBundleIdentity,
    VerifiedPromotionAttestation,
)

_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
_ROLE = r"^[A-Z][A-Z0-9_]*$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"


class PromotionAttestationBoundaryError(ValueError):
    """Promotion metadata failed strict local parsing or cryptographic verification."""

    code = "PROMOTION_ATTESTATION_BOUNDARY_INVALID"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ReleaseIdentityModel(_StrictModel):
    id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    version: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    signing_key_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    payload_digest: str = Field(pattern=_DIGEST)


class _ReleaseEvidenceBundleModel(_StrictModel):
    schema_version: Literal["1", "2"]
    status: Literal["EVIDENCE_COMPLETE", "EVIDENCE_INCOMPLETE"]
    base_pack: _ReleaseIdentityModel
    candidate_pack: _ReleaseIdentityModel
    static_analysis: dict[str, JsonValue]
    scenario_replay: dict[str, JsonValue]
    review_evidence: tuple[dict[str, JsonValue], ...] = Field(max_length=512)
    findings: tuple[dict[str, JsonValue], ...] = Field(max_length=512)
    summary: dict[str, JsonValue]
    evidence_scope: str = Field(min_length=1, max_length=2048)
    bundle_digest: str = Field(pattern=_DIGEST)


class _PromotionPolicyModel(_StrictModel):
    schema_version: Literal["1"]
    policy_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    policy_version: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    required_roles: tuple[str, ...] = Field(min_length=1, max_length=16)
    minimum_approvals: int = Field(ge=1, le=16)

    @model_validator(mode="after")
    def valid_quorum(self) -> "_PromotionPolicyModel":
        """Require normalized unique roles and a quorum able to cover them."""
        if any(re.fullmatch(_ROLE, role) is None or len(role) > 64 for role in self.required_roles):
            raise ValueError("promotion policy contains an invalid required role")
        if len(set(self.required_roles)) != len(self.required_roles):
            raise ValueError("promotion policy contains duplicate required roles")
        if self.minimum_approvals < len(self.required_roles):
            raise ValueError("promotion quorum is lower than the required role count")
        return self


class _PromotionKeyModel(_StrictModel):
    algorithm: Literal["ed25519"]
    public_key: str = Field(min_length=1, max_length=128)
    roles: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def valid_roles(self) -> "_PromotionKeyModel":
        """Require normalized unique roles for one public key."""
        if any(re.fullmatch(_ROLE, role) is None or len(role) > 64 for role in self.roles):
            raise ValueError("promotion trust key contains an invalid role")
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("promotion trust key contains duplicate roles")
        return self


class _PromotionTrustStoreModel(_StrictModel):
    schema_version: Literal["1"]
    keys: dict[str, _PromotionKeyModel] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def valid_key_ids(self) -> "_PromotionTrustStoreModel":
        """Require bounded safe identifiers for every trusted key."""
        if any(
            re.fullmatch(_IDENTIFIER, key_id) is None or len(key_id) > 128 for key_id in self.keys
        ):
            raise ValueError("promotion trust store contains an invalid key id")
        return self


class _PromotionAttestationModel(_StrictModel):
    schema_version: Literal["1"]
    attestation_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    bundle_digest: str = Field(pattern=_DIGEST)
    candidate_pack_payload_digest: str = Field(pattern=_DIGEST)
    promotion_policy_digest: str = Field(pattern=_DIGEST)
    decision: PromotionAttestationDecision
    role: str = Field(min_length=1, max_length=64, pattern=_ROLE)
    issued_at: datetime
    expires_at: datetime
    signing_key_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    signature: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def valid_window(self) -> "_PromotionAttestationModel":
        """Require one bounded UTC validity interval."""
        if (
            self.issued_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or self.issued_at.utcoffset() != UTC.utcoffset(self.issued_at)
            or self.expires_at.utcoffset() != UTC.utcoffset(self.expires_at)
            or self.expires_at <= self.issued_at
        ):
            raise ValueError("promotion attestation validity must be an increasing UTC interval")
        return self


def load_release_evidence_bundle(path: Path) -> ReleaseEvidenceBundleIdentity:
    """Validate a complete bundle and recompute its canonical Phase 6f digest."""
    raw = _read_strict_json(path, maximum_bytes=8_388_608)
    try:
        bundle = _ReleaseEvidenceBundleModel.model_validate(raw)
    except ValidationError as exc:
        raise PromotionAttestationBoundaryError(
            "Release evidence bundle failed schema validation"
        ) from exc
    canonical_payload = dict(raw)
    supplied_digest = canonical_payload.pop("bundle_digest", None)
    encoded = json.dumps(
        canonical_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    actual_digest = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    if supplied_digest != actual_digest:
        raise PromotionAttestationBoundaryError("Release evidence bundle digest does not match")
    if bundle.status != "EVIDENCE_COMPLETE" or bundle.findings:
        raise PromotionAttestationBoundaryError("Release evidence bundle is not complete")
    return ReleaseEvidenceBundleIdentity(
        bundle_digest=actual_digest,
        base=_release_identity(bundle.base_pack),
        candidate=_release_identity(bundle.candidate_pack),
    )


def load_promotion_policy(path: Path) -> PromotionPolicy:
    """Load a strict organization-owned promotion quorum policy."""
    try:
        policy = _PromotionPolicyModel.model_validate(_read_strict_yaml(path))
    except ValidationError as exc:
        raise PromotionAttestationBoundaryError(
            "Promotion policy failed schema validation"
        ) from exc
    canonical = {
        "minimum_approvals": policy.minimum_approvals,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "required_roles": sorted(policy.required_roles),
        "schema_version": policy.schema_version,
    }
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return PromotionPolicy(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        required_roles=tuple(sorted(policy.required_roles)),
        minimum_approvals=policy.minimum_approvals,
        policy_digest=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
    )


def verify_promotion_attestations(
    paths: tuple[Path, ...], trust_store_path: Path
) -> tuple[VerifiedPromotionAttestation, ...]:
    """Verify exact local attestation bytes against the promotion trust store."""
    try:
        trust_store = _PromotionTrustStoreModel.model_validate(_read_strict_yaml(trust_store_path))
    except ValidationError as exc:
        raise PromotionAttestationBoundaryError(
            "Promotion trust store failed schema validation"
        ) from exc

    verified = []
    for path in paths:
        try:
            attestation = _PromotionAttestationModel.model_validate(_read_strict_yaml(path))
        except ValidationError as exc:
            raise PromotionAttestationBoundaryError(
                "Promotion attestation failed schema validation"
            ) from exc
        key = trust_store.keys.get(attestation.signing_key_id)
        if key is None:
            raise PromotionAttestationBoundaryError("Promotion attestation key is not trusted")
        if attestation.role not in key.roles:
            raise PromotionAttestationBoundaryError(
                "Promotion attestation role is not authorized for its key"
            )
        payload = _canonical_attestation_payload(attestation)
        signature = _decode_base64(attestation.signature, expected_length=64)
        public_key = _decode_base64(key.public_key, expected_length=32)
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
        except (InvalidSignature, ValueError) as exc:
            raise PromotionAttestationBoundaryError(
                "Promotion attestation signature is invalid"
            ) from exc
        verified.append(
            VerifiedPromotionAttestation(
                attestation_id=attestation.attestation_id,
                bundle_digest=attestation.bundle_digest,
                candidate_pack_payload_digest=attestation.candidate_pack_payload_digest,
                promotion_policy_digest=attestation.promotion_policy_digest,
                decision=attestation.decision,
                role=attestation.role,
                key_id=attestation.signing_key_id,
                issued_at=attestation.issued_at,
                expires_at=attestation.expires_at,
                attestation_digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
                signature_digest=f"sha256:{hashlib.sha256(signature).hexdigest()}",
            )
        )
    return tuple(verified)


def _release_identity(model: _ReleaseIdentityModel) -> ControlPackReleaseIdentity:
    return ControlPackReleaseIdentity(
        pack_id=model.id,
        pack_version=model.version,
        signing_key_id=model.signing_key_id,
        payload_digest=model.payload_digest,
    )


def _canonical_attestation_payload(attestation: _PromotionAttestationModel) -> bytes:
    payload = {
        "attestation_id": attestation.attestation_id,
        "bundle_digest": attestation.bundle_digest,
        "candidate_pack_payload_digest": attestation.candidate_pack_payload_digest,
        "decision": attestation.decision.value,
        "expires_at": attestation.expires_at.isoformat(),
        "issued_at": attestation.issued_at.isoformat(),
        "promotion_policy_digest": attestation.promotion_policy_digest,
        "role": attestation.role,
        "schema_version": attestation.schema_version,
        "signing_key_id": attestation.signing_key_id,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _read_strict_json(path: Path, *, maximum_bytes: int) -> dict[str, JsonValue]:
    try:
        encoded = path.read_bytes()
        if len(encoded) > maximum_bytes:
            raise PromotionAttestationBoundaryError("Promotion input exceeds the size limit")
        parsed = json.loads(encoded.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionAttestationBoundaryError(
            "Release evidence bundle is not valid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise PromotionAttestationBoundaryError("Release evidence bundle must be a mapping")
    return parsed


def _unique_json_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise PromotionAttestationBoundaryError(
                "Release evidence bundle contains a duplicate key"
            )
        result[key] = value
    return result


def _read_strict_yaml(path: Path) -> dict[str, Any]:
    try:
        encoded = path.read_bytes()
        if len(encoded) > 262_144:
            raise PromotionAttestationBoundaryError("Promotion metadata exceeds the size limit")
        content = encoded.decode("utf-8")
        syntax_tree = yaml.compose(content, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw = yaml.safe_load(content)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PromotionAttestationBoundaryError("Promotion metadata is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise PromotionAttestationBoundaryError("Promotion metadata must be a mapping")
    return raw


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("promotion metadata keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("promotion metadata contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)


def _decode_base64(value: str, *, expected_length: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PromotionAttestationBoundaryError(
            "Promotion metadata contains invalid base64"
        ) from exc
    if len(decoded) != expected_length:
        raise PromotionAttestationBoundaryError(
            "Promotion metadata has an invalid cryptographic length"
        )
    return decoded
