"""Evaluate bounded PoC evidence and authenticated self-attestation."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from regulated_ai.domain.financial_pilot import (
    FinancialPilotAcceptance,
    FinancialPilotScope,
    PilotCheck,
    PilotEvidence,
    VerifiedPilotReview,
)


def pilot_scope_digest(scope: FinancialPilotScope) -> str:
    """Bind image, source, policy pack and both provider profiles."""
    return _digest(asdict(scope))


def pilot_bundle_digest(scope: FinancialPilotScope, evidence: tuple[PilotEvidence, ...]) -> str:
    """Bind all evidence references and observations before the author signs."""
    return _digest(
        {
            "domain": "regulaai.financial-poc.bundle.v1",
            "scope": asdict(scope),
            "evidence": [
                {**asdict(item), "observed_at": item.observed_at.isoformat()}
                for item in sorted(evidence, key=lambda item: item.check.value)
            ],
        }
    )


class AcceptFinancialPilot:
    """Fail closed on missing, stale, simulated or differently bound evidence."""

    def execute(
        self,
        *,
        scope: FinancialPilotScope,
        evidence: tuple[PilotEvidence, ...],
        reviews: tuple[VerifiedPilotReview, ...],
        evaluated_at: datetime,
    ) -> FinancialPilotAcceptance:
        """Require all checks and two distinct role-bound self-attestation keys."""
        _require_utc(evaluated_at)
        scope_digest = pilot_scope_digest(scope)
        bundle_digest = pilot_bundle_digest(scope, evidence)
        findings: set[str] = set()
        if not scope.ready:
            findings.add("SCOPE_NOT_READY")
        if scope.environment not in {"pilot", "sandbox", "test"}:
            findings.add("NON_PRODUCTION_SCOPE_REQUIRED")
        if not scope.policy_set_version.startswith("poc-financial@"):
            findings.add("POC_POLICY_REVIEW_REQUIRED")
        if scope.attestation_mode != "SELF_ATTESTED_POC":
            findings.add("SELF_ATTESTATION_REQUIRED")
        if scope.source_revision == "0" * 40 or any(
            value == f"sha256:{'0' * 64}"
            for value in (
                scope.image_digest,
                scope.control_pack_digest,
                scope.openai_profile_digest,
                scope.bedrock_profile_digest,
            )
        ):
            findings.add("SCOPE_PLACEHOLDER")
        kinds = [item.check for item in evidence]
        if len(kinds) != len(set(kinds)):
            findings.add("DUPLICATE_EVIDENCE")
        for check in PilotCheck:
            if check not in kinds:
                findings.add(f"MISSING_{check.value}")
        for item in evidence:
            _require_utc(item.observed_at)
            mode = (
                "CI_REAL_POSTGRES"
                if item.check is PilotCheck.POSTGRES_CONCURRENCY
                else "HUMAN_REVIEW"
                if item.check is PilotCheck.POLICY_REVIEW
                else "SANDBOX_LIVE"
            )
            if item.scope_digest != scope_digest:
                findings.add(f"SCOPE_MISMATCH_{item.check.value}")
            if not item.passed or item.execution_mode != mode:
                findings.add(f"UNPROVEN_{item.check.value}")
            if not evaluated_at - timedelta(days=7) <= item.observed_at <= evaluated_at:
                findings.add(f"STALE_{item.check.value}")
            if item.artifact_digest == f"sha256:{'0' * 64}":
                findings.add(f"PLACEHOLDER_{item.check.value}")
        required_roles = {"POC_OPERATOR", "POC_POLICY_REVIEWER"}
        roles: set[str] = set()
        keys: set[str] = set()
        for review in reviews:
            _require_utc(review.issued_at)
            _require_utc(review.expires_at)
            if (
                not review.approved
                or review.bundle_digest != bundle_digest
                or review.role not in required_roles
                or not review.issued_at <= evaluated_at < review.expires_at
                or review.expires_at - review.issued_at > timedelta(days=7)
                or any(item.observed_at > review.issued_at for item in evidence)
            ):
                findings.add("REVIEW_INVALID")
            elif review.role in roles or review.key_id in keys:
                findings.add("DISTINCT_ATTESTATION_KEYS_REQUIRED")
            else:
                roles.add(review.role)
                keys.add(review.key_id)
        if roles != required_roles:
            findings.add("POC_SELF_ATTESTATION_REQUIRED")
        return FinancialPilotAcceptance(
            scope_digest, bundle_digest, not findings, tuple(sorted(findings))
        )


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("Pilot evidence requires timezone-aware UTC")
