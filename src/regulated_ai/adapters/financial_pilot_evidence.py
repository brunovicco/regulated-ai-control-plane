"""Strict JSON and domain-separated public-key verification for pilot acceptance."""

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from regulated_ai.adapters.trust_key_lifecycle import TrustKeyLifecycleModel
from regulated_ai.domain.financial_pilot import (
    FinancialPilotScope,
    PilotCheck,
    PilotEvidence,
    VerifiedPilotReview,
)

_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ScopeModel(_StrictModel):
    schema_version: Literal["1"]
    pilot_id: str = Field(pattern=_ID)
    environment: Literal["pilot", "sandbox", "test"]
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    image_digest: str = Field(pattern=_DIGEST)
    control_pack_digest: str = Field(pattern=_DIGEST)
    policy_set_version: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9._-]+$"
    )
    openai_profile_digest: str = Field(pattern=_DIGEST)
    bedrock_profile_digest: str = Field(pattern=_DIGEST)
    ready: bool = Field(strict=True)


class _EvidenceModel(_StrictModel):
    schema_version: Literal["1"]
    check: PilotCheck
    scope_digest: str = Field(pattern=_DIGEST)
    artifact_digest: str = Field(pattern=_DIGEST)
    observed_at: datetime
    passed: bool = Field(strict=True)
    execution_mode: Literal["CI_REAL_POSTGRES", "SANDBOX_LIVE", "HUMAN_REVIEW", "SIMULATED"]


class _ReviewModel(_StrictModel):
    schema_version: Literal["1"]
    domain: Literal["regulaai.financial-pilot.review.v1"]
    bundle_digest: str = Field(pattern=_DIGEST)
    role: Literal["OPERATIONS", "POLICY_OWNER"]
    key_id: str = Field(pattern=_ID)
    approved: bool = Field(strict=True)
    issued_at: datetime
    expires_at: datetime
    signature: str = Field(min_length=88, max_length=88)


class _KeyModel(TrustKeyLifecycleModel):
    algorithm: Literal["ed25519"]
    public_key: str = Field(min_length=44, max_length=44)
    role: Literal["OPERATIONS", "POLICY_OWNER"]


class _TrustModel(_StrictModel):
    schema_version: Literal["1"]
    keys: dict[str, _KeyModel] = Field(min_length=2, max_length=16)


def load_pilot_scope(path: Path) -> FinancialPilotScope:
    """Parse non-secret deployment artifacts with no inferred approvals."""
    model = _ScopeModel.model_validate(_read_json(path))
    return FinancialPilotScope(**model.model_dump(exclude={"schema_version"}))


def load_pilot_evidence(path: Path) -> PilotEvidence:
    """Read an organization-owned observation referencing retained evidence by digest."""
    model = _EvidenceModel.model_validate(_read_json(path))
    return PilotEvidence(**model.model_dump(exclude={"schema_version"}))


def verify_pilot_reviews(
    paths: tuple[Path, ...],
    trust_store: Path,
    *,
    evaluated_at: datetime,
) -> tuple[VerifiedPilotReview, ...]:
    """Verify distinct, role-bound public keys active at issuance and evaluation."""
    trust = _TrustModel.model_validate(_read_json(trust_store))
    public_keys = [base64.b64decode(key.public_key, validate=True) for key in trust.keys.values()]
    if any(len(key) != 32 for key in public_keys) or len(set(public_keys)) != len(public_keys):
        raise ValueError("Pilot reviewer keys must be distinct")
    result: list[VerifiedPilotReview] = []
    for path in paths:
        model = _ReviewModel.model_validate(_read_json(path))
        key = trust.keys.get(model.key_id)
        if (
            key is None
            or key.role != model.role
            or not key.active_at(model.issued_at)
            or not key.active_at(evaluated_at)
        ):
            raise ValueError("Pilot review authority is invalid")
        payload = model.model_dump(mode="json", exclude={"signature"})
        payload["issued_at"] = model.issued_at.isoformat()
        payload["expires_at"] = model.expires_at.isoformat()
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        try:
            public = base64.b64decode(key.public_key, validate=True)
            signature = base64.b64decode(model.signature, validate=True)
            Ed25519PublicKey.from_public_bytes(public).verify(signature, canonical)
        except (InvalidSignature, ValueError):
            raise ValueError("Pilot review signature is invalid") from None
        result.append(
            VerifiedPilotReview(
                bundle_digest=model.bundle_digest,
                role=model.role,
                key_id=model.key_id,
                approved=model.approved,
                issued_at=model.issued_at,
                expires_at=model.expires_at,
            )
        )
    return tuple(result)


def _read_json(path: Path) -> object:
    try:
        with path.open("rb") as stream:
            encoded = stream.read(65_537)
        if len(encoded) > 65_536:
            raise ValueError("Pilot metadata exceeds the size limit")
        return json.loads(
            encoded, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (OSError, ValueError, RecursionError):
        raise ValueError("Pilot metadata document is invalid") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate pilot metadata field")
        value[key] = item
    return value


def _reject_constant(value: str) -> object:
    raise ValueError("Non-JSON pilot metadata constant")
