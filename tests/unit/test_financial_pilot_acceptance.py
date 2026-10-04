from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from regulated_ai.application.accept_financial_pilot import (
    AcceptFinancialPilot,
    pilot_bundle_digest,
    pilot_scope_digest,
)
from regulated_ai.domain.financial_pilot import (
    FinancialPilotScope,
    PilotCheck,
    PilotEvidence,
    VerifiedPilotReview,
)

from ..helpers import NOW


def scope() -> FinancialPilotScope:
    return FinancialPilotScope(
        "pilot-test",
        "pilot",
        "1" * 40,
        f"sha256:{'2' * 64}",
        f"sha256:{'3' * 64}",
        "org-financial-pilot@1.0.0",
        f"sha256:{'4' * 64}",
        f"sha256:{'5' * 64}",
        True,
    )


def observations() -> tuple[PilotEvidence, ...]:
    return tuple(
        PilotEvidence(
            check,
            pilot_scope_digest(scope()),
            f"sha256:{index:064x}",
            NOW - timedelta(hours=1),
            True,
            "CI_REAL_POSTGRES"
            if check is PilotCheck.POSTGRES_CONCURRENCY
            else "HUMAN_REVIEW"
            if check is PilotCheck.POLICY_REVIEW
            else "SANDBOX_LIVE",
        )
        for index, check in enumerate(PilotCheck, start=1)
    )


def reviews(evidence: tuple[PilotEvidence, ...]) -> tuple[VerifiedPilotReview, ...]:
    return tuple(
        VerifiedPilotReview(
            pilot_bundle_digest(scope(), evidence),
            role,
            f"key-{role}",
            True,
            NOW - timedelta(minutes=10),
            NOW + timedelta(days=1),
        )
        for role in ("OPERATIONS", "POLICY_OWNER")
    )


def test_complete_exact_bundle_requires_both_organization_roles() -> None:
    evidence = observations()
    report = AcceptFinancialPilot().execute(
        scope=scope(), evidence=evidence, reviews=reviews(evidence), evaluated_at=NOW
    )
    assert report.accepted and not report.findings
    unsigned = AcceptFinancialPilot().execute(
        scope=scope(), evidence=evidence, reviews=(), evaluated_at=NOW
    )
    assert not unsigned.accepted
    assert unsigned.bundle_digest == report.bundle_digest
    assert "ORGANIZATION_REVIEW_REQUIRED" in unsigned.findings


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("execution_mode", "SIMULATED", "UNPROVEN_POSTGRES_CONCURRENCY"),
        ("passed", False, "UNPROVEN_POSTGRES_CONCURRENCY"),
        ("observed_at", NOW - timedelta(days=8), "STALE_POSTGRES_CONCURRENCY"),
        ("observed_at", NOW + timedelta(seconds=1), "STALE_POSTGRES_CONCURRENCY"),
        (
            "scope_digest",
            f"sha256:{'9' * 64}",
            "SCOPE_MISMATCH_POSTGRES_CONCURRENCY",
        ),
        (
            "artifact_digest",
            f"sha256:{'0' * 64}",
            "PLACEHOLDER_POSTGRES_CONCURRENCY",
        ),
    ],
)
def test_invalid_evidence_cannot_be_overridden_by_signatures(
    field: str, value: object, expected: str
) -> None:
    original = observations()[0]
    if field == "execution_mode":
        changed = replace(original, execution_mode=str(value))
    elif field == "passed":
        changed = replace(original, passed=bool(value))
    elif field == "observed_at":
        assert isinstance(value, datetime)
        changed = replace(original, observed_at=value)
    elif field == "scope_digest":
        changed = replace(original, scope_digest=str(value))
    else:
        assert field == "artifact_digest"
        changed = replace(original, artifact_digest=str(value))
    evidence = (changed, *observations()[1:])
    report = AcceptFinancialPilot().execute(
        scope=scope(), evidence=evidence, reviews=reviews(evidence), evaluated_at=NOW
    )
    assert not report.accepted and expected in report.findings


def test_changed_artifact_invalidates_prior_review_and_missing_checks_block() -> None:
    evidence = observations()
    changed = (replace(evidence[0], artifact_digest=f"sha256:{'a' * 64}"), *evidence[1:-1])
    report = AcceptFinancialPilot().execute(
        scope=scope(), evidence=changed, reviews=reviews(evidence), evaluated_at=NOW
    )
    assert "REVIEW_INVALID" in report.findings
    assert "MISSING_BACKUP_RESTORE" in report.findings


def test_expired_review_same_key_and_demo_scope_cannot_authorize_acceptance() -> None:
    evidence = observations()
    approvals = reviews(evidence)
    duplicate = (approvals[0], replace(approvals[1], key_id=approvals[0].key_id))
    result = AcceptFinancialPilot().execute(
        scope=scope(), evidence=evidence, reviews=duplicate, evaluated_at=NOW
    )
    assert "DISTINCT_REVIEWERS_REQUIRED" in result.findings
    expired = (replace(approvals[0], expires_at=NOW), approvals[1])
    assert (
        not AcceptFinancialPilot()
        .execute(scope=scope(), evidence=evidence, reviews=expired, evaluated_at=NOW)
        .accepted
    )
    draft = replace(scope(), ready=False, policy_set_version="br-financial-demo@1.0.0")
    result = AcceptFinancialPilot().execute(scope=draft, evidence=(), reviews=(), evaluated_at=NOW)
    assert {"ORGANIZATION_POLICY_REQUIRED", "SCOPE_NOT_READY"}.issubset(result.findings)


def test_evidence_order_does_not_change_bundle_but_duplicates_block() -> None:
    evidence = observations()
    assert pilot_bundle_digest(scope(), evidence) == pilot_bundle_digest(
        scope(), tuple(reversed(evidence))
    )
    result = AcceptFinancialPilot().execute(
        scope=scope(), evidence=(*evidence, evidence[0]), reviews=(), evaluated_at=NOW
    )
    assert "DUPLICATE_EVIDENCE" in result.findings
