"""Evaluate authenticated consumer coverage for one trust-store checkpoint."""

from datetime import UTC, datetime

from regulated_ai.domain import (
    TrustStoreRolloutFinding,
    TrustStoreRolloutFindingCode,
    TrustStoreRolloutPolicy,
    TrustStoreRolloutReport,
    VerifiedTrustStoreAcknowledgement,
)


class TrustStoreRolloutError(ValueError):
    """Rollout acknowledgements do not form one valid checkpoint lineage."""

    code = "TRUST_STORE_ROLLOUT_INVALID"


class VerifyTrustStoreRollout:
    """Apply target coverage without distributing or mutating trust metadata."""

    def execute(
        self,
        *,
        checkpoint_digest: str,
        store_id: str,
        store_kind: str,
        sequence: int,
        policy: TrustStoreRolloutPolicy,
        acknowledgements: tuple[VerifiedTrustStoreAcknowledgement, ...],
        evaluated_at: datetime,
    ) -> TrustStoreRolloutReport:
        """Return deterministic complete/blocked acknowledgement evidence."""
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
            raise TrustStoreRolloutError("Rollout evaluation time must be timezone-aware UTC")
        if policy.checkpoint_digest != checkpoint_digest:
            raise TrustStoreRolloutError("Rollout policy does not bind the checkpoint")

        acknowledgement_ids: set[str] = set()
        signing_key_ids: set[str] = set()
        target_ids: set[str] = set()
        for item in acknowledgements:
            if item.acknowledgement_id in acknowledgement_ids:
                raise TrustStoreRolloutError("Duplicate rollout acknowledgement id")
            if item.signing_key_id in signing_key_ids:
                raise TrustStoreRolloutError("An acknowledgement key may be used only once")
            if item.target_id in target_ids:
                raise TrustStoreRolloutError("A rollout target may acknowledge only once")
            acknowledgement_ids.add(item.acknowledgement_id)
            signing_key_ids.add(item.signing_key_id)
            target_ids.add(item.target_id)
            if (
                item.checkpoint_digest != checkpoint_digest
                or item.rollout_policy_digest != policy.policy_digest
                or item.store_id != store_id
                or item.store_kind != store_kind
                or item.sequence != sequence
            ):
                raise TrustStoreRolloutError("Acknowledgement does not bind the checkpoint rollout")
            if item.target_id not in policy.allowed_target_ids:
                raise TrustStoreRolloutError("Acknowledgement target is outside the rollout policy")
            if item.accepted_at > evaluated_at:
                raise TrustStoreRolloutError("Acknowledgement is later than the evaluation time")

        findings = [
            TrustStoreRolloutFinding(
                TrustStoreRolloutFindingCode.REQUIRED_TARGET_MISSING,
                target_id,
            )
            for target_id in sorted(set(policy.required_target_ids) - target_ids)
        ]
        if len(acknowledgements) < policy.minimum_acknowledgements:
            findings.append(
                TrustStoreRolloutFinding(
                    TrustStoreRolloutFindingCode.ACKNOWLEDGEMENT_QUORUM_NOT_MET,
                    str(policy.minimum_acknowledgements),
                )
            )
        return TrustStoreRolloutReport(
            checkpoint_digest=checkpoint_digest,
            store_id=store_id,
            store_kind=store_kind,
            sequence=sequence,
            policy=policy,
            evaluated_at=evaluated_at,
            acknowledgements=tuple(
                sorted(acknowledgements, key=lambda item: (item.target_id, item.signing_key_id))
            ),
            findings=tuple(
                sorted(findings, key=lambda item: (item.code.value, item.subject_id or ""))
            ),
        )
