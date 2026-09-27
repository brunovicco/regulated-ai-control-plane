from dataclasses import replace
from datetime import UTC, datetime

import pytest

from regulated_ai.application import (
    RuntimeTrustStateVerificationError,
    VerifyRuntimeTrustState,
)
from regulated_ai.domain import (
    RuntimeTrustStateFindingCode,
    RuntimeTrustStatePolicy,
    RuntimeTrustStateReport,
    VerifiedRuntimeTrustStateAttestation,
)


def _policy() -> RuntimeTrustStatePolicy:
    return RuntimeTrustStatePolicy(
        policy_id="production-runtime-state",
        policy_version="1",
        checkpoint_digest="sha256:checkpoint",
        allowed_target_ids=("node-a", "node-b", "node-c"),
        required_target_ids=("node-a",),
        minimum_attestations=2,
        maximum_age_seconds=300,
        policy_digest="sha256:policy",
    )


def _attestation(
    target_id: str, key_id: str, *, observed_at: datetime | None = None
) -> VerifiedRuntimeTrustStateAttestation:
    return VerifiedRuntimeTrustStateAttestation(
        attestation_id=f"state-{target_id}",
        checkpoint_digest="sha256:checkpoint",
        runtime_policy_digest="sha256:policy",
        store_id="production-control-pack",
        store_kind="CONTROL_PACK",
        sequence=2,
        loaded_trust_store_digest="sha256:store",
        target_id=target_id,
        observed_at=observed_at or datetime(2026, 9, 27, 14, 58, tzinfo=UTC),
        signing_key_id=key_id,
        attestation_digest=f"sha256:state-{target_id}",
        signature_digest=f"sha256:signature-{target_id}",
    )


def _execute(
    attestations: tuple[VerifiedRuntimeTrustStateAttestation, ...],
) -> RuntimeTrustStateReport:
    return VerifyRuntimeTrustState().execute(
        checkpoint_digest="sha256:checkpoint",
        checkpoint_issued_at=datetime(2026, 9, 27, 14, tzinfo=UTC),
        trust_store_digest="sha256:store",
        store_id="production-control-pack",
        store_kind="CONTROL_PACK",
        sequence=2,
        policy=_policy(),
        attestations=attestations,
        evaluated_at=datetime(2026, 9, 27, 15, tzinfo=UTC),
    )


def test_fresh_required_target_and_quorum_establish_current_state() -> None:
    report = _execute((_attestation("node-a", "key-a"), _attestation("node-b", "key-b")))

    assert report.current is True
    assert report.findings == ()


def test_stale_and_missing_state_block_required_target_and_quorum() -> None:
    report = _execute(
        (
            _attestation(
                "node-a",
                "key-a",
                observed_at=datetime(2026, 9, 27, 14, 50, tzinfo=UTC),
            ),
        )
    )

    assert report.current is False
    assert {item.code for item in report.findings} == {
        RuntimeTrustStateFindingCode.ATTESTATION_STALE,
        RuntimeTrustStateFindingCode.REQUIRED_TARGET_MISSING,
        RuntimeTrustStateFindingCode.ATTESTATION_QUORUM_NOT_MET,
    }


@pytest.mark.parametrize(
    "attestations",
    [
        (_attestation("node-a", "key-a"), _attestation("node-a", "key-b")),
        (
            _attestation("node-a", "key-a"),
            replace(_attestation("node-b", "key-b"), signing_key_id="key-a"),
        ),
        (replace(_attestation("node-a", "key-a"), checkpoint_digest="sha256:other"),),
        (replace(_attestation("node-a", "key-a"), loaded_trust_store_digest="sha256:other"),),
        (replace(_attestation("node-a", "key-a"), target_id="unknown-node"),),
        (
            _attestation(
                "node-a",
                "key-a",
                observed_at=datetime(2026, 9, 27, 15, 1, tzinfo=UTC),
            ),
        ),
        (
            _attestation(
                "node-a",
                "key-a",
                observed_at=datetime(2026, 9, 27, 13, 59, tzinfo=UTC),
            ),
        ),
    ],
)
def test_invalid_bindings_duplicates_and_times_fail_closed(
    attestations: tuple[VerifiedRuntimeTrustStateAttestation, ...],
) -> None:
    with pytest.raises(RuntimeTrustStateVerificationError):
        _execute(attestations)
