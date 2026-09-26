"""Authorize an offline release handoff from authenticated promotion attestations."""

from datetime import UTC, datetime

from regulated_ai.domain import (
    ControlPackPromotionReport,
    PromotionAttestationDecision,
    PromotionFinding,
    PromotionFindingCode,
    PromotionPolicy,
    ReleaseEvidenceBundleIdentity,
    VerifiedPromotionAttestation,
)


class ReleasePromotionError(ValueError):
    """Promotion authorization inputs do not form one safe decision lineage."""

    code = "CONTROL_PACK_PROMOTION_INVALID"


class AuthorizeControlPackPromotion:
    """Apply a quorum policy without signing, promoting or deploying a release."""

    def execute(
        self,
        evidence: ReleaseEvidenceBundleIdentity,
        policy: PromotionPolicy,
        attestations: tuple[VerifiedPromotionAttestation, ...],
        evaluated_at: datetime,
    ) -> ControlPackPromotionReport:
        """Return a deterministic authorization result for one exact evidence bundle."""
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
            raise ReleasePromotionError("Promotion evaluation time must be timezone-aware UTC")
        if not policy.required_roles:
            raise ReleasePromotionError("Promotion policy must require at least one role")
        if len(set(policy.required_roles)) != len(policy.required_roles):
            raise ReleasePromotionError("Promotion policy contains duplicate required roles")
        if policy.minimum_approvals < len(policy.required_roles):
            raise ReleasePromotionError(
                "Promotion quorum cannot be lower than the number of required roles"
            )

        attestation_ids: set[str] = set()
        key_ids: set[str] = set()
        findings: list[PromotionFinding] = []
        active_approvals: list[VerifiedPromotionAttestation] = []
        for attestation in attestations:
            if attestation.attestation_id in attestation_ids:
                raise ReleasePromotionError("Duplicate promotion attestation id")
            if attestation.key_id in key_ids:
                raise ReleasePromotionError("A promotion key may submit only one attestation")
            attestation_ids.add(attestation.attestation_id)
            key_ids.add(attestation.key_id)
            if attestation.bundle_digest != evidence.bundle_digest:
                raise ReleasePromotionError(
                    "Promotion attestation does not bind the evidence bundle"
                )
            if attestation.candidate_pack_payload_digest != evidence.candidate.payload_digest:
                raise ReleasePromotionError(
                    "Promotion attestation does not bind the candidate pack"
                )
            if attestation.promotion_policy_digest != policy.policy_digest:
                raise ReleasePromotionError(
                    "Promotion attestation does not bind the promotion policy"
                )
            if attestation.role not in policy.required_roles:
                raise ReleasePromotionError(
                    "Promotion attestation role is outside the promotion policy"
                )

            if evaluated_at < attestation.issued_at:
                findings.append(
                    PromotionFinding(
                        PromotionFindingCode.ATTESTATION_NOT_YET_VALID,
                        attestation.attestation_id,
                    )
                )
                continue
            if evaluated_at >= attestation.expires_at:
                findings.append(
                    PromotionFinding(
                        PromotionFindingCode.ATTESTATION_EXPIRED,
                        attestation.attestation_id,
                    )
                )
                continue
            if attestation.decision is PromotionAttestationDecision.REJECT:
                findings.append(
                    PromotionFinding(
                        PromotionFindingCode.ACTIVE_REJECTION,
                        attestation.attestation_id,
                    )
                )
                continue
            active_approvals.append(attestation)

        approved_roles = {item.role for item in active_approvals}
        for role in sorted(set(policy.required_roles) - approved_roles):
            findings.append(PromotionFinding(PromotionFindingCode.REQUIRED_ROLE_MISSING, role))
        if len(active_approvals) < policy.minimum_approvals:
            findings.append(
                PromotionFinding(
                    PromotionFindingCode.APPROVAL_QUORUM_NOT_MET,
                    str(policy.minimum_approvals),
                )
            )

        return ControlPackPromotionReport(
            evidence=evidence,
            policy=policy,
            evaluated_at=evaluated_at,
            attestations=tuple(
                sorted(attestations, key=lambda item: (item.role, item.key_id, item.attestation_id))
            ),
            findings=tuple(
                sorted(findings, key=lambda item: (item.code.value, item.subject_id or ""))
            ),
        )
