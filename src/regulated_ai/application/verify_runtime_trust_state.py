"""Evaluate fresh signed runtime state for one public trust-store checkpoint."""

from datetime import UTC, datetime, timedelta

from regulated_ai.domain import (
    RuntimeTrustStateFinding,
    RuntimeTrustStateFindingCode,
    RuntimeTrustStatePolicy,
    RuntimeTrustStateReport,
    VerifiedRuntimeTrustStateAttestation,
)


class RuntimeTrustStateVerificationError(ValueError):
    """Runtime attestations do not form one valid checkpoint state."""

    code = "RUNTIME_TRUST_STATE_VERIFICATION_INVALID"


class VerifyRuntimeTrustState:
    """Apply freshness and target coverage without probing runtime processes."""

    def execute(
        self,
        *,
        checkpoint_digest: str,
        checkpoint_issued_at: datetime,
        trust_store_digest: str,
        store_id: str,
        store_kind: str,
        sequence: int,
        policy: RuntimeTrustStatePolicy,
        attestations: tuple[VerifiedRuntimeTrustStateAttestation, ...],
        evaluated_at: datetime,
    ) -> RuntimeTrustStateReport:
        """Return deterministic current/blocked runtime trust-state evidence."""
        if (
            evaluated_at.tzinfo is None
            or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at)
            or checkpoint_issued_at.tzinfo is None
            or checkpoint_issued_at.utcoffset() != UTC.utcoffset(checkpoint_issued_at)
        ):
            raise RuntimeTrustStateVerificationError(
                "Runtime trust-state times must be timezone-aware UTC"
            )
        if policy.checkpoint_digest != checkpoint_digest:
            raise RuntimeTrustStateVerificationError(
                "Runtime trust-state policy does not bind the checkpoint"
            )

        attestation_ids: set[str] = set()
        signing_key_ids: set[str] = set()
        target_ids: set[str] = set()
        fresh_target_ids: set[str] = set()
        findings: list[RuntimeTrustStateFinding] = []
        maximum_age = timedelta(seconds=policy.maximum_age_seconds)
        for item in attestations:
            if item.attestation_id in attestation_ids:
                raise RuntimeTrustStateVerificationError("Duplicate runtime attestation id")
            if item.signing_key_id in signing_key_ids:
                raise RuntimeTrustStateVerificationError(
                    "A runtime attestation key may be used only once"
                )
            if item.target_id in target_ids:
                raise RuntimeTrustStateVerificationError("A runtime target may attest only once")
            attestation_ids.add(item.attestation_id)
            signing_key_ids.add(item.signing_key_id)
            target_ids.add(item.target_id)
            if (
                item.checkpoint_digest != checkpoint_digest
                or item.runtime_policy_digest != policy.policy_digest
                or item.store_id != store_id
                or item.store_kind != store_kind
                or item.sequence != sequence
                or item.loaded_trust_store_digest != trust_store_digest
            ):
                raise RuntimeTrustStateVerificationError(
                    "Runtime attestation does not bind the loaded checkpoint"
                )
            if item.target_id not in policy.allowed_target_ids:
                raise RuntimeTrustStateVerificationError(
                    "Runtime target is outside the state policy"
                )
            if item.observed_at > evaluated_at:
                raise RuntimeTrustStateVerificationError(
                    "Runtime observation is later than the evaluation time"
                )
            if item.observed_at < checkpoint_issued_at:
                raise RuntimeTrustStateVerificationError(
                    "Runtime observation predates the checkpoint"
                )
            if evaluated_at - item.observed_at > maximum_age:
                findings.append(
                    RuntimeTrustStateFinding(
                        RuntimeTrustStateFindingCode.ATTESTATION_STALE,
                        item.target_id,
                    )
                )
            else:
                fresh_target_ids.add(item.target_id)

        findings.extend(
            RuntimeTrustStateFinding(
                RuntimeTrustStateFindingCode.REQUIRED_TARGET_MISSING,
                target_id,
            )
            for target_id in sorted(set(policy.required_target_ids) - fresh_target_ids)
        )
        if len(fresh_target_ids) < policy.minimum_attestations:
            findings.append(
                RuntimeTrustStateFinding(
                    RuntimeTrustStateFindingCode.ATTESTATION_QUORUM_NOT_MET,
                    str(policy.minimum_attestations),
                )
            )
        return RuntimeTrustStateReport(
            checkpoint_digest=checkpoint_digest,
            trust_store_digest=trust_store_digest,
            store_id=store_id,
            store_kind=store_kind,
            sequence=sequence,
            policy=policy,
            evaluated_at=evaluated_at,
            attestations=tuple(
                sorted(attestations, key=lambda item: (item.target_id, item.signing_key_id))
            ),
            findings=tuple(
                sorted(findings, key=lambda item: (item.code.value, item.subject_id or ""))
            ),
        )
