from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from regulated_ai.application import AuthorizeControlPackPromotion, ReleasePromotionError
from regulated_ai.domain import (
    ControlPackReleaseIdentity,
    PromotionAttestationDecision,
    PromotionFindingCode,
    PromotionPolicy,
    ReleaseEvidenceBundleIdentity,
    VerifiedPromotionAttestation,
)

NOW = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)


def _identity(version: str, digest_character: str) -> ControlPackReleaseIdentity:
    return ControlPackReleaseIdentity(
        pack_id="test-pack",
        pack_version=version,
        signing_key_id="pack-key",
        payload_digest=f"sha256:{digest_character * 64}",
    )


def _evidence() -> ReleaseEvidenceBundleIdentity:
    return ReleaseEvidenceBundleIdentity(
        bundle_digest=f"sha256:{'c' * 64}",
        base=_identity("1", "a"),
        candidate=_identity("2", "b"),
    )


def _policy() -> PromotionPolicy:
    return PromotionPolicy(
        policy_id="test-promotion",
        policy_version="1",
        required_roles=("CONTROL_OWNER", "RELEASE_MANAGER"),
        minimum_approvals=2,
        policy_digest=f"sha256:{'f' * 64}",
    )


def _attestation(
    attestation_id: str,
    role: str,
    key_id: str,
    *,
    decision: PromotionAttestationDecision = PromotionAttestationDecision.APPROVE,
    issued_at: datetime = NOW - timedelta(hours=1),
    expires_at: datetime = NOW + timedelta(hours=1),
) -> VerifiedPromotionAttestation:
    return VerifiedPromotionAttestation(
        attestation_id=attestation_id,
        bundle_digest=_evidence().bundle_digest,
        candidate_pack_payload_digest=_evidence().candidate.payload_digest,
        promotion_policy_digest=_policy().policy_digest,
        decision=decision,
        role=role,
        key_id=key_id,
        issued_at=issued_at,
        expires_at=expires_at,
        attestation_digest=f"sha256:{'d' * 64}",
        signature_digest=f"sha256:{'e' * 64}",
    )


def test_distinct_active_keys_cover_required_roles_and_quorum() -> None:
    report = AuthorizeControlPackPromotion().execute(
        _evidence(),
        _policy(),
        (
            _attestation("release-manager", "RELEASE_MANAGER", "release-key"),
            _attestation("control-owner", "CONTROL_OWNER", "control-key"),
        ),
        NOW,
    )

    assert report.authorized is True
    assert report.findings == ()
    assert tuple(item.attestation_id for item in report.attestations) == (
        "control-owner",
        "release-manager",
    )


def test_missing_role_and_quorum_block_authorization() -> None:
    report = AuthorizeControlPackPromotion().execute(
        _evidence(),
        _policy(),
        (_attestation("control-owner", "CONTROL_OWNER", "control-key"),),
        NOW,
    )

    assert report.authorized is False
    assert {finding.code for finding in report.findings} == {
        PromotionFindingCode.REQUIRED_ROLE_MISSING,
        PromotionFindingCode.APPROVAL_QUORUM_NOT_MET,
    }


@pytest.mark.parametrize(
    ("attestation", "expected"),
    [
        (
            _attestation(
                "rejected",
                "CONTROL_OWNER",
                "control-key",
                decision=PromotionAttestationDecision.REJECT,
            ),
            PromotionFindingCode.ACTIVE_REJECTION,
        ),
        (
            _attestation(
                "future",
                "CONTROL_OWNER",
                "control-key",
                issued_at=NOW + timedelta(minutes=1),
                expires_at=NOW + timedelta(hours=1),
            ),
            PromotionFindingCode.ATTESTATION_NOT_YET_VALID,
        ),
        (
            _attestation(
                "expired",
                "CONTROL_OWNER",
                "control-key",
                issued_at=NOW - timedelta(hours=2),
                expires_at=NOW,
            ),
            PromotionFindingCode.ATTESTATION_EXPIRED,
        ),
    ],
)
def test_non_approving_attestation_blocks_with_explicit_finding(
    attestation: VerifiedPromotionAttestation,
    expected: PromotionFindingCode,
) -> None:
    report = AuthorizeControlPackPromotion().execute(_evidence(), _policy(), (attestation,), NOW)

    assert expected in {finding.code for finding in report.findings}
    assert report.authorized is False


def test_attestation_must_bind_exact_bundle_and_candidate() -> None:
    attestation = _attestation("control-owner", "CONTROL_OWNER", "control-key")
    wrong_bundle = replace(attestation, bundle_digest=f"sha256:{'f' * 64}")

    with pytest.raises(ReleasePromotionError, match="does not bind the evidence bundle"):
        AuthorizeControlPackPromotion().execute(_evidence(), _policy(), (wrong_bundle,), NOW)


def test_attestation_must_bind_policy_and_use_a_required_role() -> None:
    attestation = _attestation("control-owner", "CONTROL_OWNER", "control-key")

    with pytest.raises(ReleasePromotionError, match="does not bind the promotion policy"):
        AuthorizeControlPackPromotion().execute(
            _evidence(),
            _policy(),
            (replace(attestation, promotion_policy_digest=f"sha256:{'0' * 64}"),),
            NOW,
        )

    with pytest.raises(ReleasePromotionError, match="outside the promotion policy"):
        AuthorizeControlPackPromotion().execute(
            _evidence(),
            _policy(),
            (replace(attestation, role="SECURITY_OBSERVER"),),
            NOW,
        )


def test_one_key_cannot_count_more_than_once() -> None:
    with pytest.raises(ReleasePromotionError, match="only one attestation"):
        AuthorizeControlPackPromotion().execute(
            _evidence(),
            _policy(),
            (
                _attestation("one", "CONTROL_OWNER", "shared-key"),
                _attestation("two", "RELEASE_MANAGER", "shared-key"),
            ),
            NOW,
        )
