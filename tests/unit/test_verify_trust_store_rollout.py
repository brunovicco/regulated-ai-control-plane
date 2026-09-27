from dataclasses import replace
from datetime import UTC, datetime

import pytest

from regulated_ai.application import TrustStoreRolloutError, VerifyTrustStoreRollout
from regulated_ai.domain import (
    TrustStoreRolloutFindingCode,
    TrustStoreRolloutPolicy,
    TrustStoreRolloutReport,
    VerifiedTrustStoreAcknowledgement,
)


def _policy() -> TrustStoreRolloutPolicy:
    return TrustStoreRolloutPolicy(
        policy_id="production-rollout",
        policy_version="1",
        checkpoint_digest="sha256:checkpoint",
        allowed_target_ids=("node-a", "node-b", "node-c"),
        required_target_ids=("node-a",),
        minimum_acknowledgements=2,
        policy_digest="sha256:policy",
    )


def _ack(target_id: str, key_id: str) -> VerifiedTrustStoreAcknowledgement:
    return VerifiedTrustStoreAcknowledgement(
        acknowledgement_id=f"ack-{target_id}",
        checkpoint_digest="sha256:checkpoint",
        rollout_policy_digest="sha256:policy",
        store_id="production-control-pack",
        store_kind="CONTROL_PACK",
        sequence=2,
        target_id=target_id,
        accepted_at=datetime(2026, 9, 27, 14, tzinfo=UTC),
        signing_key_id=key_id,
        acknowledgement_digest=f"sha256:ack-{target_id}",
        signature_digest=f"sha256:signature-{target_id}",
    )


def _execute(
    acknowledgements: tuple[VerifiedTrustStoreAcknowledgement, ...],
) -> TrustStoreRolloutReport:
    return VerifyTrustStoreRollout().execute(
        checkpoint_digest="sha256:checkpoint",
        store_id="production-control-pack",
        store_kind="CONTROL_PACK",
        sequence=2,
        policy=_policy(),
        acknowledgements=acknowledgements,
        evaluated_at=datetime(2026, 9, 27, 15, tzinfo=UTC),
    )


def test_required_target_and_quorum_complete_rollout() -> None:
    report = _execute((_ack("node-a", "key-a"), _ack("node-b", "key-b")))

    assert report.complete is True
    assert report.findings == ()


def test_missing_required_target_and_quorum_are_reported() -> None:
    report = _execute((_ack("node-b", "key-b"),))

    assert report.complete is False
    assert {item.code for item in report.findings} == {
        TrustStoreRolloutFindingCode.REQUIRED_TARGET_MISSING,
        TrustStoreRolloutFindingCode.ACKNOWLEDGEMENT_QUORUM_NOT_MET,
    }


@pytest.mark.parametrize(
    "acknowledgements",
    [
        (_ack("node-a", "key-a"), _ack("node-a", "key-b")),
        (_ack("node-a", "key-a"), replace(_ack("node-b", "key-b"), signing_key_id="key-a")),
        (replace(_ack("node-a", "key-a"), checkpoint_digest="sha256:other"),),
        (replace(_ack("node-a", "key-a"), target_id="unknown-node"),),
        (
            replace(
                _ack("node-a", "key-a"),
                accepted_at=datetime(2026, 9, 27, 16, tzinfo=UTC),
            ),
        ),
    ],
)
def test_invalid_bindings_duplicates_and_future_acknowledgements_fail_closed(
    acknowledgements: tuple[VerifiedTrustStoreAcknowledgement, ...],
) -> None:
    with pytest.raises(TrustStoreRolloutError):
        _execute(acknowledgements)
