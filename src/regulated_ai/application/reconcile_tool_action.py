"""Authenticated terminal reconciliation for ambiguous tool executions."""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from regulated_ai.application.evaluate_operation import EvaluationError
from regulated_ai.application.ports import (
    EvaluationObserver,
    ToolActionReconciliationPort,
    ToolActionRepository,
)
from regulated_ai.domain import (
    ToolActionReconciliationGrant,
    ToolActionReconciliationOutcome,
    ToolActionReconciliationReceipt,
    ToolActionRecord,
    ToolActionResult,
    ToolActionStatus,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TERMINAL_RECONCILIATION_STATUSES = {
    ToolActionStatus.RECONCILED_EXECUTED,
    ToolActionStatus.RECONCILED_NOT_EXECUTED,
}


class ToolActionReconciliationNotFoundError(EvaluationError):
    """The exact action does not exist."""

    code = "TOOL_ACTION_NOT_FOUND"


class ToolActionReconciliationAuthorizationError(EvaluationError):
    """Separate reconciliation authority is unavailable or invalid."""

    code = "TOOL_ACTION_RECONCILIATION_AUTHORIZATION_FAILED"


class ToolActionReconciliationConflictError(EvaluationError):
    """The action cannot accept the requested terminal outcome."""

    code = "TOOL_ACTION_RECONCILIATION_CONFLICT"


class ToolActionReconciliationPersistenceError(EvaluationError):
    """Reconciliation metadata could not be read or persisted."""

    code = "TOOL_ACTION_RECONCILIATION_PERSISTENCE_FAILED"


class ReconcileToolAction:
    """Resolve ambiguity using separate authority without tool re-execution."""

    def __init__(
        self,
        *,
        actions: ToolActionRepository,
        authority: ToolActionReconciliationPort | None,
        observer: EvaluationObserver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind metadata persistence and reconciliation authority boundaries."""
        self._actions = actions
        self._authority = authority
        self._observer = observer
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(self, *, action_id: str, assertion: str) -> ToolActionResult:
        """Apply one signed terminal outcome and never invoke a tool adapter."""
        if _SAFE_ID.fullmatch(action_id) is None:
            raise ToolActionReconciliationNotFoundError("Tool action was not found")
        try:
            record = self._actions.get(action_id)
        except Exception as exc:
            raise ToolActionReconciliationPersistenceError(
                "Tool-action reconciliation metadata could not be read"
            ) from exc
        if record is None:
            raise ToolActionReconciliationNotFoundError("Tool action was not found")
        if record.status not in {
            ToolActionStatus.RECONCILIATION_REQUIRED,
            *_TERMINAL_RECONCILIATION_STATUSES,
        }:
            raise ToolActionReconciliationConflictError(
                "Tool action does not require reconciliation"
            )
        grant = self._inspect(assertion, record)
        if record.status in _TERMINAL_RECONCILIATION_STATUSES:
            _require_existing_binding(record, grant)
            receipt = self._consume(grant, action_id)
            _validate_receipt(receipt, grant=grant, action_id=action_id, now=self._clock())
            if record.reconciliation_receipt != receipt:
                raise ToolActionReconciliationConflictError(
                    "Stored reconciliation receipt is inconsistent"
                )
            return _to_result(record)

        receipt = self._consume(grant, action_id)
        target_status = (
            ToolActionStatus.RECONCILED_EXECUTED
            if grant.outcome is ToolActionReconciliationOutcome.EXECUTED
            else ToolActionStatus.RECONCILED_NOT_EXECUTED
        )
        candidate = replace(
            record,
            status=target_status,
            tool_execution_id=grant.tool_execution_id,
            reconciliation_receipt=receipt,
        )
        try:
            stored = self._actions.save(candidate)
        except Exception as exc:
            raise ToolActionReconciliationPersistenceError(
                "Tool-action reconciliation metadata could not be persisted"
            ) from exc
        if (
            stored.status is not target_status
            or stored.reconciliation_receipt != receipt
            or stored.tool_execution_id != grant.tool_execution_id
        ):
            raise ToolActionReconciliationConflictError(
                "Tool action was reconciled with a different outcome"
            )
        self._emit(
            "tool_action.reconciled",
            action_id=action_id,
            outcome=grant.outcome.value,
            reconciliation_id=grant.reconciliation_id,
        )
        return _to_result(stored)

    def _inspect(self, assertion: str, record: ToolActionRecord) -> ToolActionReconciliationGrant:
        try:
            if self._authority is None:
                raise ValueError("Reconciliation authority verifier is unavailable")
            now = self._clock()
            grant = self._authority.inspect(
                assertion,
                action_digest=record.action_digest,
                now=now,
            )
            _validate_grant(grant, action_digest=record.action_digest, now=now)
        except Exception as exc:
            self._emit("tool_action.reconciliation_failed", error_type=type(exc).__name__)
            raise ToolActionReconciliationAuthorizationError(
                "Tool-action reconciliation authorization failed closed"
            ) from exc
        return grant

    def _consume(
        self, grant: ToolActionReconciliationGrant, action_id: str
    ) -> ToolActionReconciliationReceipt:
        try:
            if self._authority is None:
                raise ValueError("Reconciliation authority verifier is unavailable")
            now = self._clock()
            receipt = self._authority.consume(grant, action_id=action_id, now=now)
            _validate_receipt(receipt, grant=grant, action_id=action_id, now=now)
        except Exception as exc:
            self._emit("tool_action.reconciliation_failed", error_type=type(exc).__name__)
            raise ToolActionReconciliationAuthorizationError(
                "Tool-action reconciliation authorization failed closed"
            ) from exc
        return receipt

    def _emit(self, event: str, **metadata: str) -> None:
        if self._observer is None:
            return
        try:
            self._observer.emit(event, metadata)
        except Exception:
            return


def _validate_grant(
    grant: ToolActionReconciliationGrant,
    *,
    action_digest: str,
    now: datetime,
) -> None:
    if (
        _SAFE_ID.fullmatch(grant.reconciliation_id) is None
        or _SAFE_ID.fullmatch(grant.actor_id) is None
        or _DIGEST.fullmatch(grant.action_digest) is None
        or grant.action_digest != action_digest
        or grant.issued_at.tzinfo is None
        or grant.expires_at.tzinfo is None
        or grant.issued_at > now
        or grant.expires_at <= now
        or not _valid_outcome_binding(grant.outcome, grant.tool_execution_id)
    ):
        raise ValueError("Reconciliation grant is invalid")


def _validate_receipt(
    receipt: ToolActionReconciliationReceipt,
    *,
    grant: ToolActionReconciliationGrant,
    action_id: str,
    now: datetime,
) -> None:
    if (
        receipt.reconciliation_id != grant.reconciliation_id
        or receipt.actor_id != grant.actor_id
        or receipt.action_digest != grant.action_digest
        or receipt.action_id != action_id
        or receipt.outcome is not grant.outcome
        or receipt.tool_execution_id != grant.tool_execution_id
        or receipt.issued_at != grant.issued_at
        or receipt.expires_at != grant.expires_at
        or receipt.consumed_at.tzinfo is None
        or receipt.consumed_at < receipt.issued_at
        or receipt.consumed_at > now
    ):
        raise ValueError("Reconciliation receipt is invalid")


def _valid_outcome_binding(
    outcome: ToolActionReconciliationOutcome, tool_execution_id: str | None
) -> bool:
    if outcome is ToolActionReconciliationOutcome.EXECUTED:
        return tool_execution_id is not None and _SAFE_ID.fullmatch(tool_execution_id) is not None
    return outcome is ToolActionReconciliationOutcome.NOT_EXECUTED and tool_execution_id is None


def _require_existing_binding(
    record: ToolActionRecord, grant: ToolActionReconciliationGrant
) -> None:
    receipt = record.reconciliation_receipt
    expected_status = (
        ToolActionStatus.RECONCILED_EXECUTED
        if grant.outcome is ToolActionReconciliationOutcome.EXECUTED
        else ToolActionStatus.RECONCILED_NOT_EXECUTED
    )
    if (
        receipt is None
        or record.status is not expected_status
        or receipt.reconciliation_id != grant.reconciliation_id
        or receipt.actor_id != grant.actor_id
        or receipt.action_digest != grant.action_digest
        or receipt.action_id != record.action_id
        or receipt.outcome is not grant.outcome
        or receipt.tool_execution_id != grant.tool_execution_id
        or receipt.issued_at != grant.issued_at
        or receipt.expires_at != grant.expires_at
    ):
        raise ToolActionReconciliationConflictError(
            "Tool action was reconciled with a different outcome"
        )


def _to_result(record: ToolActionRecord) -> ToolActionResult:
    return ToolActionResult(
        action_id=record.action_id,
        enforcement_id=record.enforcement_id,
        call_id=record.call_id,
        tool_name=record.tool_name,
        workload_identity=record.workload_identity,
        action_digest=record.action_digest,
        status=record.status,
        output_schema_digest=record.output_schema_digest,
        approval_receipt=record.approval_receipt,
        tool_execution_id=record.tool_execution_id,
        output_digest=record.output_digest,
        safe_output_digest=record.safe_output_digest,
        result_classifications=record.result_classifications,
        exposed_result_fields=record.exposed_result_fields,
        reconciliation_receipt=record.reconciliation_receipt,
    )
