"""Metadata-only contracts for a self-attested financial proof of concept."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PilotCheck(StrEnum):
    """Evidence required before the individual PoC may be verified."""

    POSTGRES_CONCURRENCY = "POSTGRES_CONCURRENCY"
    ENTERPRISE_IDENTITY = "ENTERPRISE_IDENTITY"
    OPENAI_GATEWAY = "OPENAI_GATEWAY"
    BEDROCK_GATEWAY = "BEDROCK_GATEWAY"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    TOOL_RECOVERY_EXECUTED = "TOOL_RECOVERY_EXECUTED"
    TOOL_RECOVERY_NOT_EXECUTED = "TOOL_RECOVERY_NOT_EXECUTED"
    POLICY_REVIEW = "POLICY_REVIEW"
    BACKUP_RESTORE = "BACKUP_RESTORE"


@dataclass(frozen=True, slots=True)
class FinancialPilotScope:
    """Exact artifacts and configuration covered by PoC verification."""

    pilot_id: str
    environment: str
    source_revision: str
    image_digest: str
    control_pack_digest: str
    policy_set_version: str
    attestation_mode: str
    openai_profile_digest: str
    bedrock_profile_digest: str
    ready: bool


@dataclass(frozen=True, slots=True)
class PilotEvidence:
    """A bounded observation referencing separately retained metadata evidence."""

    check: PilotCheck
    scope_digest: str
    artifact_digest: str
    observed_at: datetime
    passed: bool
    execution_mode: str


@dataclass(frozen=True, slots=True)
class VerifiedPilotReview:
    """One role-specific self-attestation of the exact PoC bundle."""

    bundle_digest: str
    role: str
    key_id: str
    approved: bool
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class FinancialPilotAcceptance:
    """PoC verification without independent review or compliance claims."""

    scope_digest: str
    bundle_digest: str
    accepted: bool
    findings: tuple[str, ...]
