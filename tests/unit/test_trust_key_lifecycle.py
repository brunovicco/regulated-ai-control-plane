from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from regulated_ai.adapters.trust_key_lifecycle import TrustKeyLifecycleModel


def test_active_key_uses_half_open_utc_validity_window() -> None:
    lifecycle = TrustKeyLifecycleModel(
        status="ACTIVE",
        valid_from=datetime(2026, 9, 1, tzinfo=UTC),
        valid_until=datetime(2026, 10, 1, tzinfo=UTC),
    )

    assert lifecycle.active_at(datetime(2026, 9, 1, tzinfo=UTC)) is True
    assert lifecycle.active_at(datetime(2026, 10, 1, tzinfo=UTC)) is False


@pytest.mark.parametrize("status", ["RETIRED", "REVOKED"])
def test_inactive_status_never_grants_authority(status: str) -> None:
    lifecycle = TrustKeyLifecycleModel(
        status=status,
        valid_from=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert lifecycle.active_at(datetime(2026, 9, 26, tzinfo=UTC)) is False


def test_rejects_naive_or_decreasing_lifecycle_times() -> None:
    with pytest.raises(ValidationError, match="valid_from"):
        TrustKeyLifecycleModel(status="ACTIVE", valid_from=datetime(2026, 9, 1))

    with pytest.raises(ValidationError, match="valid_until"):
        TrustKeyLifecycleModel(
            status="ACTIVE",
            valid_from=datetime(2026, 9, 1, tzinfo=UTC),
            valid_until=datetime(2026, 8, 1, tzinfo=UTC),
        )


def test_rejects_naive_evaluation_time() -> None:
    lifecycle = TrustKeyLifecycleModel(
        status="ACTIVE",
        valid_from=datetime(2026, 9, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="evaluation time"):
        lifecycle.active_at(datetime(2026, 9, 26))
