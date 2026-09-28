from dataclasses import replace
from pathlib import Path

import pytest

from regulated_ai.adapters import (
    HmacToolActionReconciliationAdapter,
    SqliteToolActionRepository,
)
from regulated_ai.application import (
    ReconcileToolAction,
    ToolActionReconciliationAuthorizationError,
    ToolActionReconciliationConflictError,
)
from regulated_ai.domain import ToolActionRecord, ToolActionStatus

from ..helpers import NOW, reconciliation_assertion

KEY = b"y" * 32
ACTION_DIGEST = f"sha256:{'a' * 64}"


def _record(
    status: ToolActionStatus = ToolActionStatus.RECONCILIATION_REQUIRED,
) -> ToolActionRecord:
    return ToolActionRecord(
        action_id="act_reconciliation_test",
        created_at=NOW,
        enforcement_id="enf_reconciliation_test",
        evaluation_id="eval_reconciliation_test",
        call_id="call_reconciliation_test",
        tool_name="cards.read",
        tool_schema_version="1",
        tool_schema_digest=f"sha256:{'b' * 64}",
        arguments_digest=f"sha256:{'c' * 64}",
        workload_identity="workload.cards-sandbox",
        idempotency_key_digest=f"sha256:{'d' * 64}",
        action_digest=ACTION_DIGEST,
        status=status,
        output_schema_digest=f"sha256:{'e' * 64}",
    )


def _service(tmp_path: Path, record: ToolActionRecord) -> ReconcileToolAction:
    path = tmp_path / "reconciliation.sqlite3"
    repository = SqliteToolActionRepository(path)
    repository.save(record)
    return ReconcileToolAction(
        actions=repository,
        authority=HmacToolActionReconciliationAdapter(path, KEY),
        clock=lambda: NOW,
    )


def test_reconcile_confirms_execution_without_reexecuting_or_inventing_output(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, _record())
    assertion = reconciliation_assertion(KEY, ACTION_DIGEST)

    reconciled = service.execute(
        action_id="act_reconciliation_test",
        assertion=assertion,
    )
    replayed = service.execute(
        action_id="act_reconciliation_test",
        assertion=assertion,
    )

    assert reconciled.status is ToolActionStatus.RECONCILED_EXECUTED
    assert reconciled.tool_execution_id == "sandbox-execution-test-1"
    assert reconciled.output_digest is None
    assert reconciled.safe_output is None
    assert reconciled.reconciliation_receipt is not None
    assert replayed == reconciled


def test_reconcile_confirms_not_executed_as_terminal_without_retry(tmp_path: Path) -> None:
    service = _service(tmp_path, _record())

    reconciled = service.execute(
        action_id="act_reconciliation_test",
        assertion=reconciliation_assertion(
            KEY,
            ACTION_DIGEST,
            outcome="NOT_EXECUTED",
            tool_execution_id=None,
        ),
    )

    assert reconciled.status is ToolActionStatus.RECONCILED_NOT_EXECUTED
    assert reconciled.tool_execution_id is None
    assert reconciled.reconciliation_receipt is not None
    assert reconciled.reconciliation_receipt.tool_execution_id is None


def test_reconcile_rejects_wrong_state_before_consuming_authority(tmp_path: Path) -> None:
    record = _record(ToolActionStatus.WAITING_APPROVAL)
    service = _service(tmp_path, record)

    with pytest.raises(ToolActionReconciliationConflictError, match="does not require"):
        service.execute(
            action_id=record.action_id,
            assertion=reconciliation_assertion(KEY, ACTION_DIGEST),
        )

    authority = HmacToolActionReconciliationAdapter(tmp_path / "reconciliation.sqlite3", KEY)
    assert authority.get("reconciliation-test-1") is None


def test_reconcile_rejects_missing_or_wrong_authority(tmp_path: Path) -> None:
    path = tmp_path / "reconciliation.sqlite3"
    repository = SqliteToolActionRepository(path)
    record = repository.save(_record())
    unavailable = ReconcileToolAction(actions=repository, authority=None, clock=lambda: NOW)

    with pytest.raises(ToolActionReconciliationAuthorizationError):
        unavailable.execute(action_id=record.action_id, assertion="untrusted")

    configured = ReconcileToolAction(
        actions=repository,
        authority=HmacToolActionReconciliationAdapter(path, KEY),
        clock=lambda: NOW,
    )
    with pytest.raises(ToolActionReconciliationAuthorizationError):
        configured.execute(
            action_id=record.action_id,
            assertion=reconciliation_assertion(b"x" * 32, ACTION_DIGEST),
        )


def test_reconcile_rejects_a_different_terminal_binding(tmp_path: Path) -> None:
    service = _service(tmp_path, _record())
    first = reconciliation_assertion(KEY, ACTION_DIGEST)
    service.execute(action_id="act_reconciliation_test", assertion=first)

    with pytest.raises(ToolActionReconciliationConflictError, match="different outcome"):
        service.execute(
            action_id="act_reconciliation_test",
            assertion=reconciliation_assertion(
                KEY,
                ACTION_DIGEST,
                reconciliation_id="reconciliation-test-2",
            ),
        )


def test_repository_refuses_to_reopen_reconciled_action(tmp_path: Path) -> None:
    path = tmp_path / "reconciliation.sqlite3"
    repository = SqliteToolActionRepository(path)
    record = repository.save(_record())
    service = ReconcileToolAction(
        actions=repository,
        authority=HmacToolActionReconciliationAdapter(path, KEY),
        clock=lambda: NOW,
    )
    service.execute(
        action_id=record.action_id,
        assertion=reconciliation_assertion(KEY, ACTION_DIGEST),
    )

    stored = repository.save(replace(record, status=ToolActionStatus.RECONCILIATION_REQUIRED))

    assert stored.status is ToolActionStatus.RECONCILED_EXECUTED
