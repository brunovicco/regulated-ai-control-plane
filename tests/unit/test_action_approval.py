from pathlib import Path

import pytest

from regulated_ai.adapters import (
    ActionApprovalAssertionError,
    ApprovalAssertionError,
    HmacActionApprovalAdapter,
    HmacApprovalAdapter,
)

from ..helpers import NOW, action_approval_assertion, approval_assertion

KEY = b"q" * 32
ACTION_DIGEST = f"sha256:{'a' * 64}"


def test_action_assertion_is_domain_separated_bound_and_consumed_once(tmp_path: Path) -> None:
    adapter = HmacActionApprovalAdapter(tmp_path / "approval.sqlite3", KEY)
    assertion = action_approval_assertion(KEY, ACTION_DIGEST)

    grant = adapter.inspect(assertion, action_digest=ACTION_DIGEST, now=NOW)
    receipt = adapter.consume(grant, action_id="act_test", now=NOW)

    assert receipt.action_digest == ACTION_DIGEST
    assert adapter.get(receipt.approval_id) == receipt
    with pytest.raises(ActionApprovalAssertionError):
        adapter.consume(grant, action_id="act_other", now=NOW)
    assert assertion not in (tmp_path / "approval.sqlite3").read_bytes().decode(errors="ignore")


def test_decision_approval_cannot_authorize_a_tool_action(tmp_path: Path) -> None:
    action_adapter = HmacActionApprovalAdapter(tmp_path / "approval.sqlite3", KEY)
    decision_assertion = approval_assertion(KEY, ACTION_DIGEST)

    with pytest.raises(ActionApprovalAssertionError):
        action_adapter.inspect(decision_assertion, action_digest=ACTION_DIGEST, now=NOW)

    decision_adapter = HmacApprovalAdapter(tmp_path / "approval.sqlite3", KEY)
    action_assertion = action_approval_assertion(KEY, ACTION_DIGEST)
    with pytest.raises(ApprovalAssertionError):
        decision_adapter.inspect(action_assertion, decision_digest=ACTION_DIGEST, now=NOW)


def test_action_assertion_rejects_a_different_action_digest(tmp_path: Path) -> None:
    adapter = HmacActionApprovalAdapter(tmp_path / "approval.sqlite3", KEY)
    assertion = action_approval_assertion(KEY, ACTION_DIGEST)

    with pytest.raises(ActionApprovalAssertionError):
        adapter.inspect(assertion, action_digest=f"sha256:{'b' * 64}", now=NOW)
