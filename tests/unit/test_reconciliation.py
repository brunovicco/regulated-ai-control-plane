from datetime import timedelta
from pathlib import Path

import pytest

from regulated_ai.adapters import (
    ActionApprovalAssertionError,
    HmacActionApprovalAdapter,
    HmacToolActionReconciliationAdapter,
    ToolActionReconciliationAssertionError,
)
from regulated_ai.domain import ToolActionReconciliationOutcome

from ..helpers import NOW, action_approval_assertion, reconciliation_assertion

KEY = b"z" * 32
ACTION_DIGEST = f"sha256:{'a' * 64}"


def test_reconciliation_assertion_is_bound_and_exact_replay_is_idempotent(tmp_path: Path) -> None:
    adapter = HmacToolActionReconciliationAdapter(tmp_path / "reconciliation.sqlite3", KEY)
    assertion = reconciliation_assertion(KEY, ACTION_DIGEST)

    grant = adapter.inspect(assertion, action_digest=ACTION_DIGEST, now=NOW)
    receipt = adapter.consume(grant, action_id="act_test", now=NOW)
    replayed = adapter.consume(grant, action_id="act_test", now=NOW)

    assert grant.outcome is ToolActionReconciliationOutcome.EXECUTED
    assert receipt == replayed
    assert adapter.get(receipt.reconciliation_id) == receipt
    assert assertion not in (tmp_path / "reconciliation.sqlite3").read_bytes().decode(
        errors="ignore"
    )
    with pytest.raises(ToolActionReconciliationAssertionError):
        adapter.consume(grant, action_id="act_other", now=NOW)


def test_reconciliation_authority_is_domain_separated_from_action_approval(tmp_path: Path) -> None:
    reconciliation = HmacToolActionReconciliationAdapter(tmp_path / "reconciliation.sqlite3", KEY)
    action_approval = HmacActionApprovalAdapter(tmp_path / "reconciliation.sqlite3", KEY)

    with pytest.raises(ToolActionReconciliationAssertionError):
        reconciliation.inspect(
            action_approval_assertion(KEY, ACTION_DIGEST),
            action_digest=ACTION_DIGEST,
            now=NOW,
        )
    with pytest.raises(ActionApprovalAssertionError):
        action_approval.inspect(
            reconciliation_assertion(KEY, ACTION_DIGEST),
            action_digest=ACTION_DIGEST,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("outcome", "tool_execution_id"),
    [
        ("EXECUTED", None),
        ("NOT_EXECUTED", "unexpected-execution"),
        ("UNKNOWN", None),
    ],
)
def test_reconciliation_assertion_rejects_invalid_outcome_binding(
    tmp_path: Path, outcome: str, tool_execution_id: str | None
) -> None:
    adapter = HmacToolActionReconciliationAdapter(tmp_path / "reconciliation.sqlite3", KEY)

    with pytest.raises(ToolActionReconciliationAssertionError):
        adapter.inspect(
            reconciliation_assertion(
                KEY,
                ACTION_DIGEST,
                outcome=outcome,
                tool_execution_id=tool_execution_id,
            ),
            action_digest=ACTION_DIGEST,
            now=NOW,
        )


def test_reconciliation_assertion_rejects_different_action_digest(tmp_path: Path) -> None:
    adapter = HmacToolActionReconciliationAdapter(tmp_path / "reconciliation.sqlite3", KEY)

    with pytest.raises(ToolActionReconciliationAssertionError):
        adapter.inspect(
            reconciliation_assertion(KEY, ACTION_DIGEST),
            action_digest=f"sha256:{'b' * 64}",
            now=NOW,
        )


def test_reconciliation_ledger_allows_only_one_authority_per_action(tmp_path: Path) -> None:
    adapter = HmacToolActionReconciliationAdapter(tmp_path / "reconciliation.sqlite3", KEY)
    first = adapter.inspect(
        reconciliation_assertion(KEY, ACTION_DIGEST),
        action_digest=ACTION_DIGEST,
        now=NOW,
    )
    second = adapter.inspect(
        reconciliation_assertion(
            KEY,
            ACTION_DIGEST,
            reconciliation_id="reconciliation-test-2",
        ),
        action_digest=ACTION_DIGEST,
        now=NOW,
    )
    adapter.consume(first, action_id="act_test", now=NOW)

    with pytest.raises(ToolActionReconciliationAssertionError):
        adapter.consume(second, action_id="act_test", now=NOW)


def test_exact_consumed_assertion_can_recover_after_expiration(tmp_path: Path) -> None:
    adapter = HmacToolActionReconciliationAdapter(tmp_path / "reconciliation.sqlite3", KEY)
    assertion = reconciliation_assertion(KEY, ACTION_DIGEST)
    grant = adapter.inspect(assertion, action_digest=ACTION_DIGEST, now=NOW)
    receipt = adapter.consume(grant, action_id="act_test", now=NOW)
    later = NOW + timedelta(hours=1)

    recovered_grant = adapter.inspect(assertion, action_digest=ACTION_DIGEST, now=later)
    recovered_receipt = adapter.consume(recovered_grant, action_id="act_test", now=later)

    assert recovered_receipt == receipt
