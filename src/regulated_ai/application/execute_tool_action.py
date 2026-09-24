"""Action-specific approval and bounded execution for exact tool proposals."""

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime

from regulated_ai.application.evaluate_operation import EvaluationError
from regulated_ai.application.ports import (
    ActionApprovalPort,
    EnforcementRepository,
    EvaluationObserver,
    EvidenceRepository,
    ToolActionRepository,
    ToolCatalogRepository,
    ToolExecutionPort,
)
from regulated_ai.domain import (
    ActionApprovalGrant,
    ActionApprovalReceipt,
    AuthorizedTool,
    EnforcementStatus,
    ToolActionPlan,
    ToolActionRecord,
    ToolActionResult,
    ToolActionStatus,
    ToolExecutionReceipt,
    ToolProposal,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ToolActionNotFoundError(EvaluationError):
    """The enforcement or proposal does not exist at the trusted boundary."""

    code = "TOOL_ACTION_NOT_FOUND"


class InvalidToolActionError(EvaluationError):
    """The proposed action does not match its trusted schema or digest."""

    code = "INVALID_TOOL_ACTION"


class ActionApprovalFailedError(EvaluationError):
    """Action-specific approval was unavailable, invalid or not consumable."""

    code = "ACTION_APPROVAL_FAILED"


class ToolActionConflictError(EvaluationError):
    """A different binding already exists for the same proposed call."""

    code = "TOOL_ACTION_CONFLICT"


class ToolActionExecutionFailedError(EvaluationError):
    """Tool execution has an ambiguous outcome requiring reconciliation."""

    code = "TOOL_ACTION_EXECUTION_FAILED"


class ToolActionPersistenceError(EvaluationError):
    """Tool-action metadata could not be persisted."""

    code = "TOOL_ACTION_PERSISTENCE_FAILED"


class ExecuteToolAction:
    """Validate, authorize, claim and execute one exact tool proposal."""

    def __init__(
        self,
        *,
        enforcement: EnforcementRepository,
        evidence: EvidenceRepository,
        tools: ToolCatalogRepository,
        actions: ToolActionRepository,
        execution: ToolExecutionPort,
        approval: ActionApprovalPort | None = None,
        observer: EvaluationObserver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind trusted proposal, catalog, authority and execution boundaries."""
        self._enforcement = enforcement
        self._evidence = evidence
        self._tools = tools
        self._actions = actions
        self._execution = execution
        self._approval = approval
        self._observer = observer
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        *,
        enforcement_id: str,
        call_id: str,
        arguments: Mapping[str, object],
        workload_identity: str,
        idempotency_key: str,
        approval_assertion: str | None = None,
    ) -> ToolActionResult:
        """Execute only the exact schema-valid proposal authorized after inference."""
        _validate_identifiers(enforcement_id, call_id, workload_identity, idempotency_key)
        enforcement = self._enforcement.get(enforcement_id)
        if enforcement is None or enforcement.status is not EnforcementStatus.EXECUTED:
            raise ToolActionNotFoundError("Executed enforcement was not found")
        proposal = next(
            (item for item in enforcement.tool_proposals if item.call_id == call_id),
            None,
        )
        if proposal is None:
            raise ToolActionNotFoundError("Tool proposal was not found")
        evidence = self._evidence.get(enforcement.evaluation_evidence_id)
        if evidence is None:
            raise InvalidToolActionError("Tool proposal evidence is unavailable")
        tool = self._tools.get(proposal.tool_name)
        if (
            tool is None
            or tool.catalog_version != evidence.tool_catalog_version
            or tool.identifier not in evidence.authorized_tool_ids
            or tool.schema_version != proposal.tool_schema_version
            or tool.input_schema_digest != proposal.tool_schema_digest
        ):
            raise InvalidToolActionError("Trusted tool definition no longer matches the proposal")
        canonical_arguments, argument_pairs = _validated_arguments(arguments, tool)
        arguments_digest = _arguments_digest(canonical_arguments, tool)
        if arguments_digest != proposal.arguments_digest:
            raise InvalidToolActionError("Tool arguments do not match the proposal")

        idempotency_key_digest = _digest(idempotency_key)
        action_digest = _action_digest(
            enforcement_id=enforcement_id,
            evaluation_id=enforcement.evaluation_id,
            proposal=proposal,
            tool=tool,
            workload_identity=workload_identity,
            idempotency_key_digest=idempotency_key_digest,
        )
        action_id = _action_id(enforcement_id, call_id)
        candidate = ToolActionRecord(
            action_id=action_id,
            created_at=self._clock(),
            enforcement_id=enforcement_id,
            evaluation_id=enforcement.evaluation_id,
            call_id=call_id,
            tool_name=tool.name,
            tool_schema_version=tool.schema_version,
            tool_schema_digest=tool.input_schema_digest,
            arguments_digest=arguments_digest,
            workload_identity=workload_identity,
            idempotency_key_digest=idempotency_key_digest,
            action_digest=action_digest,
            status=ToolActionStatus.WAITING_APPROVAL,
        )
        stored = self._save(candidate)
        _require_same_binding(stored, candidate)
        self._emit("tool_action.started", action_id=action_id)
        if stored.status not in {
            ToolActionStatus.WAITING_APPROVAL,
            ToolActionStatus.PREPARED,
        }:
            return _to_result(stored)
        if approval_assertion is None:
            self._emit("tool_action.waiting_approval", action_id=action_id)
            return _to_result(stored)
        if self._approval is None:
            raise ActionApprovalFailedError("Action approval verification failed closed")

        approval_grant = self._inspect_approval(approval_assertion, action_digest)
        prepared = replace(candidate, status=ToolActionStatus.PREPARED)
        stored_prepared = (
            self._save(prepared) if stored.status is ToolActionStatus.WAITING_APPROVAL else stored
        )
        _require_same_binding(stored_prepared, candidate)
        if stored_prepared.status is not ToolActionStatus.PREPARED:
            return _to_result(stored_prepared)
        dispatched, claimed = self._claim(replace(prepared, status=ToolActionStatus.DISPATCHED))
        if not claimed:
            return _to_result(dispatched)

        approval_receipt = self._consume_approval(approval_grant, action_id)
        active_record = replace(dispatched, approval_receipt=approval_receipt)
        plan = ToolActionPlan(
            action_id=action_id,
            action_digest=action_digest,
            enforcement_id=enforcement_id,
            call_id=call_id,
            tool=tool,
            workload_identity=workload_identity,
            idempotency_key=idempotency_key,
            arguments=argument_pairs,
            approval_receipt=approval_receipt,
        )
        try:
            receipt = self._execution.execute(plan)
            _validate_execution_receipt(receipt, plan)
        except Exception as exc:
            failed = replace(active_record, status=ToolActionStatus.RECONCILIATION_REQUIRED)
            self._save(failed)
            self._emit("tool_action.failed", action_id=action_id)
            raise ToolActionExecutionFailedError(
                "Tool execution outcome requires reconciliation"
            ) from exc
        completed = replace(
            active_record,
            status=ToolActionStatus.EXECUTED,
            tool_execution_id=receipt.execution_id,
            output_digest=receipt.output_digest,
        )
        stored_completed = self._save(completed)
        self._emit("tool_action.completed", action_id=action_id)
        return _to_result(stored_completed)

    def _inspect_approval(self, assertion: str, action_digest: str) -> ActionApprovalGrant:
        try:
            if self._approval is None:
                raise ValueError("Action approval verifier is unavailable")
            now = self._clock()
            grant = self._approval.inspect(assertion, action_digest=action_digest, now=now)
            _validate_approval_grant(grant, action_digest=action_digest, now=now)
        except Exception as exc:
            self._emit("tool_action.failed", error_type=type(exc).__name__)
            raise ActionApprovalFailedError("Action approval verification failed closed") from exc
        self._emit("tool_action.approval_validated", approval_id=grant.approval_id)
        return grant

    def _consume_approval(
        self, grant: ActionApprovalGrant, action_id: str
    ) -> ActionApprovalReceipt:
        try:
            if self._approval is None:
                raise ValueError("Action approval verifier is unavailable")
            now = self._clock()
            receipt = self._approval.consume(grant, action_id=action_id, now=now)
            _validate_approval_receipt(receipt, grant=grant, action_id=action_id, now=now)
        except Exception as exc:
            current = self._actions.get(action_id)
            if current is not None:
                self._save(replace(current, status=ToolActionStatus.APPROVAL_FAILED))
            self._emit("tool_action.failed", error_type=type(exc).__name__)
            raise ActionApprovalFailedError("Action approval consumption failed closed") from exc
        self._emit("tool_action.approval_consumed", approval_id=receipt.approval_id)
        return receipt

    def _save(self, record: ToolActionRecord) -> ToolActionRecord:
        try:
            return self._actions.save(record)
        except Exception as exc:
            raise ToolActionPersistenceError("Tool-action metadata could not be persisted") from exc

    def _claim(self, record: ToolActionRecord) -> tuple[ToolActionRecord, bool]:
        try:
            return self._actions.claim_execution(record)
        except Exception as exc:
            raise ToolActionPersistenceError("Tool-action claim could not be persisted") from exc

    def _emit(self, event: str, **metadata: str) -> None:
        if self._observer is None:
            return
        try:
            self._observer.emit(event, metadata)
        except Exception:
            return


def _validated_arguments(
    arguments: Mapping[str, object], tool: AuthorizedTool
) -> tuple[str, tuple[tuple[str, str], ...]]:
    if len(arguments) > 128 or any(not isinstance(key, str) for key in arguments):
        raise InvalidToolActionError("Tool arguments are invalid")
    try:
        parsed_schema: object = json.loads(tool.input_schema_json)
    except json.JSONDecodeError as exc:
        raise InvalidToolActionError("Trusted tool schema is invalid") from exc
    if not isinstance(parsed_schema, dict):
        raise InvalidToolActionError("Trusted tool schema is invalid")
    properties = parsed_schema.get("properties")
    required = parsed_schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise InvalidToolActionError("Trusted tool schema is invalid")
    if set(arguments) - set(properties) or not set(required).issubset(arguments):
        raise InvalidToolActionError("Tool arguments do not satisfy the trusted schema")
    normalized: dict[str, str] = {}
    for key, value in arguments.items():
        constraints = properties.get(key)
        if not isinstance(value, str) or not isinstance(constraints, dict):
            raise InvalidToolActionError("Tool arguments do not satisfy the trusted schema")
        _validate_string(value, constraints)
        normalized[key] = value
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(canonical.encode()) > 32_768:
        raise InvalidToolActionError("Tool arguments exceed the execution limit")
    return canonical, tuple(sorted(normalized.items()))


def _validate_string(value: str, constraints: Mapping[object, object]) -> None:
    minimum = constraints.get("minLength")
    maximum = constraints.get("maxLength")
    pattern = constraints.get("pattern")
    choices = constraints.get("enum")
    if (
        (minimum is not None and (not isinstance(minimum, int) or len(value) < minimum))
        or (maximum is not None and (not isinstance(maximum, int) or len(value) > maximum))
        or (choices is not None and (not isinstance(choices, list) or value not in choices))
    ):
        raise InvalidToolActionError("Tool arguments do not satisfy the trusted schema")
    if pattern is not None:
        if not isinstance(pattern, str):
            raise InvalidToolActionError("Trusted tool schema is invalid")
        try:
            matched = re.search(pattern, value) is not None
        except re.error as exc:
            raise InvalidToolActionError("Trusted tool schema is invalid") from exc
        if not matched:
            raise InvalidToolActionError("Tool arguments do not satisfy the trusted schema")


def _arguments_digest(canonical_arguments: str, tool: AuthorizedTool) -> str:
    binding = json.dumps(
        {
            "arguments": json.loads(canonical_arguments),
            "schema_digest": tool.input_schema_digest,
            "tool": tool.name,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return f"sha256:{hashlib.sha256(binding).hexdigest()}"


def _action_digest(
    *,
    enforcement_id: str,
    evaluation_id: str,
    proposal: ToolProposal,
    tool: AuthorizedTool,
    workload_identity: str,
    idempotency_key_digest: str,
) -> str:
    canonical = json.dumps(
        {
            "arguments_digest": proposal.arguments_digest,
            "call_id": proposal.call_id,
            "catalog_version": tool.catalog_version,
            "enforcement_id": enforcement_id,
            "evaluation_id": evaluation_id,
            "idempotency_key_digest": idempotency_key_digest,
            "schema_version": "1",
            "tool_definition_digest": tool.definition_digest,
            "tool_name": tool.name,
            "tool_schema_digest": tool.input_schema_digest,
            "tool_schema_version": tool.schema_version,
            "workload_identity": workload_identity,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _action_id(enforcement_id: str, call_id: str) -> str:
    digest = hashlib.sha256(f"{enforcement_id}:{call_id}".encode()).hexdigest()
    return f"act_{digest[:24]}"


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _validate_identifiers(
    enforcement_id: str, call_id: str, workload_identity: str, idempotency_key: str
) -> None:
    if (
        _SAFE_ID.fullmatch(enforcement_id) is None
        or _SAFE_ID.fullmatch(call_id) is None
        or _SAFE_ID.fullmatch(workload_identity) is None
        or not idempotency_key
        or len(idempotency_key.encode()) > 256
    ):
        raise InvalidToolActionError("Tool action identifiers are invalid")


def _require_same_binding(stored: ToolActionRecord, candidate: ToolActionRecord) -> None:
    fields = (
        "enforcement_id",
        "evaluation_id",
        "call_id",
        "tool_name",
        "tool_schema_version",
        "tool_schema_digest",
        "arguments_digest",
        "workload_identity",
        "idempotency_key_digest",
        "action_digest",
    )
    if any(getattr(stored, field) != getattr(candidate, field) for field in fields):
        raise ToolActionConflictError("A different action binding already exists for this proposal")


def _validate_approval_grant(
    grant: ActionApprovalGrant, *, action_digest: str, now: datetime
) -> None:
    if (
        _SAFE_ID.fullmatch(grant.approval_id) is None
        or _SAFE_ID.fullmatch(grant.actor_id) is None
        or grant.action_digest != action_digest
        or _DIGEST.fullmatch(grant.action_digest) is None
        or grant.issued_at.tzinfo is None
        or grant.expires_at.tzinfo is None
        or grant.issued_at > now
        or grant.expires_at <= now
    ):
        raise ValueError("Action approval adapter returned an invalid grant")


def _validate_approval_receipt(
    receipt: ActionApprovalReceipt,
    *,
    grant: ActionApprovalGrant,
    action_id: str,
    now: datetime,
) -> None:
    if (
        receipt.approval_id != grant.approval_id
        or receipt.actor_id != grant.actor_id
        or receipt.action_digest != grant.action_digest
        or receipt.action_id != action_id
        or receipt.issued_at != grant.issued_at
        or receipt.expires_at != grant.expires_at
        or receipt.consumed_at > now
        or receipt.consumed_at < receipt.issued_at
        or receipt.consumed_at >= receipt.expires_at
    ):
        raise ValueError("Action approval adapter returned an invalid receipt")


def _validate_execution_receipt(receipt: ToolExecutionReceipt, plan: ToolActionPlan) -> None:
    if (
        receipt.action_id != plan.action_id
        or _SAFE_ID.fullmatch(receipt.execution_id) is None
        or _DIGEST.fullmatch(receipt.output_digest) is None
    ):
        raise ValueError("Tool execution adapter returned an invalid receipt")


def _to_result(record: ToolActionRecord) -> ToolActionResult:
    return ToolActionResult(
        action_id=record.action_id,
        enforcement_id=record.enforcement_id,
        call_id=record.call_id,
        tool_name=record.tool_name,
        workload_identity=record.workload_identity,
        action_digest=record.action_digest,
        status=record.status,
        approval_receipt=record.approval_receipt,
        tool_execution_id=record.tool_execution_id,
        output_digest=record.output_digest,
    )
