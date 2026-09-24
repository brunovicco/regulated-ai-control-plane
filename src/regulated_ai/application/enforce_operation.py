"""Local enforcement use case that transforms data before provider execution."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from regulated_ai.application.evaluate_operation import (
    EvaluateAiOperation,
    EvaluationError,
    normalize_evaluation_context,
)
from regulated_ai.application.ports import (
    ApprovalPort,
    EnforcementRepository,
    EvaluationObserver,
    InferenceExecutionPort,
    TokenizationPort,
)
from regulated_ai.domain import (
    ApprovalGrant,
    ApprovalReceipt,
    DataItem,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementResult,
    EnforcementStatus,
    EvaluationContext,
    EvaluationResult,
    ExecutionPlan,
    Obligation,
    ObligationType,
    ProviderCallMetadata,
    ProviderExecutionReceipt,
    TransformationReceipt,
)

_TRANSFORMATIONS = frozenset(
    {
        ObligationType.REMOVE_FIELD,
        ObligationType.MASK,
        ObligationType.TOKENIZE,
        ObligationType.PSEUDONYMIZE,
    }
)


class TransformationFailedError(EvaluationError):
    """A required local transformation failed closed."""

    code = "TRANSFORMATION_FAILED"


class ExecutionFailedError(EvaluationError):
    """The post-transformation execution port failed."""

    code = "EXECUTION_FAILED"


class ApprovalFailedError(EvaluationError):
    """External approval authority was unavailable, invalid or not consumable."""

    code = "APPROVAL_FAILED"


class EnforcementPersistenceError(EvaluationError):
    """Enforcement metadata could not be persisted."""

    code = "ENFORCEMENT_PERSISTENCE_FAILED"


class EnforceAiOperation:
    """Evaluate, transform, persist and optionally execute one AI operation."""

    def __init__(
        self,
        *,
        evaluator: EvaluateAiOperation,
        tokenizer: TokenizationPort,
        enforcement: EnforcementRepository,
        execution: InferenceExecutionPort,
        approval: ApprovalPort | None = None,
        observer: EvaluationObserver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind local enforcement ports and explicit infrastructure inputs."""
        self._evaluator = evaluator
        self._tokenizer = tokenizer
        self._enforcement = enforcement
        self._execution = execution
        self._approval = approval
        self._observer = observer
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        context: EvaluationContext,
        *,
        approval_assertion: str | None = None,
    ) -> EnforcementResult:
        """Apply required controls before allowing the execution port to observe data."""
        normalized = normalize_evaluation_context(context)
        evaluation = self._evaluator.execute(normalized)
        self._emit("enforcement.started", evaluation_id=evaluation.evaluation_id)
        if evaluation.decision is DecisionOutcome.DENY:
            return self._blocked_result(
                evaluation=evaluation,
                context=normalized,
                status=EnforcementStatus.BLOCKED_DENY,
            )

        try:
            transformed, receipts = self._apply_transformations(normalized, evaluation)
        except Exception as exc:
            record = self._record(
                evaluation=evaluation,
                context=normalized,
                status=EnforcementStatus.TRANSFORMATION_FAILED,
                receipts=(),
                output_digest=None,
                provider_execution_id=None,
                extra_reason="TRANSFORMATION_FAILED",
            )
            self._save(record)
            self._emit("enforcement.failed", error_type=type(exc).__name__)
            raise TransformationFailedError("A required transformation failed") from exc

        output_digest = _execution_output_digest(transformed, normalized, evaluation)
        approval_grant: ApprovalGrant | None = None
        if evaluation.decision is DecisionOutcome.REQUIRE_APPROVAL:
            if approval_assertion is None:
                return self._waiting_for_approval(
                    evaluation=evaluation,
                    context=normalized,
                    receipts=receipts,
                    output_digest=output_digest,
                    reason="HUMAN_APPROVAL_REQUIRED",
                )
            if self._approval is None:
                self._waiting_for_approval(
                    evaluation=evaluation,
                    context=normalized,
                    receipts=receipts,
                    output_digest=output_digest,
                    reason="APPROVAL_VERIFIER_UNAVAILABLE",
                )
                raise ApprovalFailedError("Approval verification failed closed")
            verification_time = self._clock()
            try:
                approval_grant = self._approval.inspect(
                    approval_assertion,
                    decision_digest=evaluation.output_digest,
                    now=verification_time,
                )
                _validate_approval_grant(
                    approval_grant,
                    decision_digest=evaluation.output_digest,
                    now=verification_time,
                )
            except Exception as exc:
                self._waiting_for_approval(
                    evaluation=evaluation,
                    context=normalized,
                    receipts=receipts,
                    output_digest=output_digest,
                    reason="APPROVAL_INVALID",
                )
                self._emit("enforcement.failed", error_type=type(exc).__name__)
                raise ApprovalFailedError("Approval verification failed closed") from exc
            self._emit("approval.validated", approval_id=approval_grant.approval_id)

        plan = _execution_plan(evaluation, normalized, transformed, receipts, output_digest)
        prepared = self._record(
            evaluation=evaluation,
            context=normalized,
            status=EnforcementStatus.PREPARED,
            receipts=receipts,
            output_digest=output_digest,
            provider_execution_id=None,
        )
        stored_prepared = self._save(prepared)
        if stored_prepared.status in {
            EnforcementStatus.DISPATCHED,
            EnforcementStatus.EXECUTED,
            EnforcementStatus.EXECUTION_FAILED,
            EnforcementStatus.APPROVAL_FAILED,
        }:
            self._emit("enforcement.completed", status=stored_prepared.status.value)
            return _to_result(stored_prepared)
        dispatched = replace(prepared, status=EnforcementStatus.DISPATCHED)
        stored_dispatched, claimed = self._claim_execution(dispatched)
        if not claimed:
            self._emit("enforcement.completed", status=stored_dispatched.status.value)
            return _to_result(stored_dispatched)
        active_plan = plan
        active_record = dispatched
        if approval_grant is not None:
            consumption_time = self._clock()
            try:
                if self._approval is None:
                    raise ValueError("Approval verifier is unavailable")
                approval_receipt = self._approval.consume(
                    approval_grant,
                    enforcement_id=dispatched.enforcement_id,
                    now=consumption_time,
                )
                _validate_approval_receipt(
                    approval_receipt,
                    grant=approval_grant,
                    enforcement_id=dispatched.enforcement_id,
                    now=consumption_time,
                )
            except Exception as exc:
                failed = replace(
                    dispatched,
                    status=EnforcementStatus.APPROVAL_FAILED,
                    reason_codes=tuple(sorted({*dispatched.reason_codes, "APPROVAL_FAILED"})),
                )
                self._save(failed)
                self._emit("enforcement.failed", error_type=type(exc).__name__)
                raise ApprovalFailedError("Approval consumption failed closed") from exc
            active_plan = replace(plan, approval_receipt=approval_receipt)
            active_record = replace(dispatched, approval_receipt=approval_receipt)
            self._emit("approval.consumed", approval_id=approval_receipt.approval_id)
        try:
            provider_receipt = self._execution.execute(active_plan)
            _validate_provider_receipt(provider_receipt, active_plan)
        except Exception as exc:
            failed = replace(
                active_record,
                status=EnforcementStatus.EXECUTION_FAILED,
                reason_codes=tuple(sorted({*dispatched.reason_codes, "EXECUTION_FAILED"})),
            )
            self._save(failed)
            self._emit("enforcement.failed", error_type=type(exc).__name__)
            raise ExecutionFailedError("The execution port failed") from exc
        completed = replace(
            active_record,
            status=EnforcementStatus.EXECUTED,
            provider_execution_id=provider_receipt.execution_id,
            provider_call_metadata=provider_receipt.call_metadata,
            tool_proposals=provider_receipt.tool_proposals,
        )
        self._emit("execution.completed", provider_execution_id=provider_receipt.execution_id)
        stored = self._save(completed)
        self._emit("enforcement.completed", status=stored.status.value)
        return _to_result(stored)

    def _waiting_for_approval(
        self,
        *,
        evaluation: EvaluationResult,
        context: EvaluationContext,
        receipts: tuple[TransformationReceipt, ...],
        output_digest: str,
        reason: str,
    ) -> EnforcementResult:
        record = self._record(
            evaluation=evaluation,
            context=context,
            status=EnforcementStatus.WAITING_APPROVAL,
            receipts=receipts,
            output_digest=output_digest,
            provider_execution_id=None,
            extra_reason=reason,
        )
        stored = self._save(record)
        self._emit("enforcement.blocked", status=stored.status.value)
        return _to_result(stored)

    def _apply_transformations(
        self,
        context: EvaluationContext,
        evaluation: EvaluationResult,
    ) -> tuple[tuple[DataItem, ...], tuple[TransformationReceipt, ...]]:
        by_target: dict[str, Obligation] = {}
        for obligation in evaluation.obligations:
            if obligation.type not in _TRANSFORMATIONS:
                continue
            if obligation.target is None or obligation.target in by_target:
                raise ValueError("Transformation targeting is ambiguous")
            by_target[obligation.target] = obligation
        if evaluation.decision is DecisionOutcome.ALLOW_WITH_TRANSFORMATION and not by_target:
            raise ValueError("Transformation decision has no executable obligation")
        known_fields = {item.field for item in context.data_items}
        if not set(by_target).issubset(known_fields):
            raise ValueError("Transformation target does not exist")

        transformed: list[DataItem] = []
        receipts: list[TransformationReceipt] = []
        for item in context.data_items:
            selected = by_target.get(item.field)
            if selected is None:
                transformed.append(item)
                continue
            transformed_value = self._transform(item, selected, evaluation.output_digest)
            if transformed_value is not None and (
                not transformed_value
                or len(transformed_value) > 100_000
                or transformed_value == item.value
            ):
                raise ValueError("Transformation did not produce a safe replacement")
            if transformed_value is not None:
                transformed.append(replace(item, value=transformed_value))
            receipt = _transformation_receipt(
                item=item,
                transformed_value=transformed_value,
                obligation=selected,
                decision_digest=evaluation.output_digest,
            )
            receipts.append(receipt)
            self._emit(
                "transformation.applied",
                transformation_type=selected.type.value,
                target_field=item.field,
            )
        return tuple(transformed), tuple(receipts)

    def _transform(
        self, item: DataItem, obligation: Obligation, decision_digest: str
    ) -> str | None:
        if obligation.type is ObligationType.REMOVE_FIELD:
            return None
        if obligation.type is ObligationType.MASK:
            return "***MASKED***"
        if obligation.type is ObligationType.TOKENIZE:
            return self._tokenizer.tokenize(
                item.value, field=item.field, decision_digest=decision_digest
            )
        if obligation.type is ObligationType.PSEUDONYMIZE:
            return self._tokenizer.pseudonymize(
                item.value, field=item.field, decision_digest=decision_digest
            )
        raise ValueError("Unsupported transformation")

    def _blocked_result(
        self,
        *,
        evaluation: EvaluationResult,
        context: EvaluationContext,
        status: EnforcementStatus,
    ) -> EnforcementResult:
        record = self._record(
            evaluation=evaluation,
            context=context,
            status=status,
            receipts=(),
            output_digest=None,
            provider_execution_id=None,
        )
        stored = self._save(record)
        self._emit("enforcement.blocked", status=stored.status.value)
        return _to_result(stored)

    def _record(
        self,
        *,
        evaluation: EvaluationResult,
        context: EvaluationContext,
        status: EnforcementStatus,
        receipts: tuple[TransformationReceipt, ...],
        output_digest: str | None,
        provider_execution_id: str | None,
        extra_reason: str | None = None,
    ) -> EnforcementRecord:
        reason_codes = set(evaluation.reason_codes)
        if extra_reason is not None:
            reason_codes.add(extra_reason)
        identity = _digest(
            {
                "evaluation_id": evaluation.evaluation_id,
                "output_digest": output_digest,
                "status_family": _status_family(status),
            }
        )
        return EnforcementRecord(
            enforcement_id=f"enf_{identity.removeprefix('sha256:')[:24]}",
            created_at=self._clock(),
            evaluation_id=evaluation.evaluation_id,
            evaluation_evidence_id=evaluation.evidence_id,
            decision=evaluation.decision,
            status=status,
            policy_set_version=evaluation.policy_set_version,
            provider_registry_version=evaluation.provider_registry_version,
            provider_target=context.provider.identifier,
            transformation_receipts=receipts,
            reason_codes=tuple(sorted(reason_codes)),
            input_digest=evaluation.input_digest,
            output_digest=output_digest,
            provider_execution_id=provider_execution_id,
        )

    def _save(self, record: EnforcementRecord) -> EnforcementRecord:
        try:
            return self._enforcement.save(record)
        except Exception as exc:
            raise EnforcementPersistenceError(
                "Enforcement metadata could not be persisted"
            ) from exc

    def _claim_execution(self, record: EnforcementRecord) -> tuple[EnforcementRecord, bool]:
        try:
            return self._enforcement.claim_execution(record)
        except Exception as exc:
            raise EnforcementPersistenceError(
                "Enforcement execution claim could not be persisted"
            ) from exc

    def _emit(self, event: str, **metadata: str) -> None:
        if self._observer is None:
            return
        try:
            self._observer.emit(event, metadata)
        except Exception:
            return


def _execution_plan(
    evaluation: EvaluationResult,
    context: EvaluationContext,
    transformed: tuple[DataItem, ...],
    receipts: tuple[TransformationReceipt, ...],
    output_digest: str,
) -> ExecutionPlan:
    plan_key = _digest(
        {
            "evaluation_id": evaluation.evaluation_id,
            "output_digest": output_digest,
            "provider": context.provider.identifier,
        }
    )
    return ExecutionPlan(
        plan_id=f"plan_{plan_key.removeprefix('sha256:')[:24]}",
        evaluation_id=evaluation.evaluation_id,
        decision_digest=evaluation.output_digest,
        operation_kind=context.operation_kind,
        purpose=context.purpose.name,
        assurance_level=context.assurance_level,
        provider=context.provider,
        data_items=transformed,
        tools=evaluation.authorized_tools,
        transformation_receipts=receipts,
        output_digest=output_digest,
    )


def _transformation_receipt(
    *,
    item: DataItem,
    transformed_value: str | None,
    obligation: Obligation,
    decision_digest: str,
) -> TransformationReceipt:
    input_digest = _digest(item.value)
    output_digest = _digest(transformed_value)
    receipt_key = _digest(
        {
            "decision_digest": decision_digest,
            "input_digest": input_digest,
            "output_digest": output_digest,
            "target": item.field,
            "type": obligation.type.value,
        }
    )
    return TransformationReceipt(
        receipt_id=f"tr_{receipt_key.removeprefix('sha256:')[:24]}",
        type=obligation.type,
        target=item.field,
        input_digest=input_digest,
        output_digest=output_digest,
        reason_code=obligation.reason_code,
    )


def _execution_output_digest(
    data_items: tuple[DataItem, ...],
    context: EvaluationContext,
    evaluation: EvaluationResult,
) -> str:
    return _digest(
        {
            "data": [
                {
                    "field": item.field,
                    "labels": [label.value for label in item.labels],
                    "value_digest": _digest(item.value),
                }
                for item in data_items
            ],
            "provider": context.provider.identifier,
            "tools": [
                {
                    "catalog_version": tool.catalog_version,
                    "definition_digest": tool.definition_digest,
                    "name": tool.name,
                    "risk_class": tool.risk_class,
                    "schema_digest": tool.input_schema_digest,
                    "schema_version": tool.schema_version,
                }
                for tool in evaluation.authorized_tools
            ],
        }
    )


def _status_family(status: EnforcementStatus) -> str:
    if status in {
        EnforcementStatus.WAITING_APPROVAL,
        EnforcementStatus.PREPARED,
        EnforcementStatus.DISPATCHED,
        EnforcementStatus.EXECUTED,
        EnforcementStatus.APPROVAL_FAILED,
        EnforcementStatus.EXECUTION_FAILED,
    }:
        return "execution"
    return status.value


def _to_result(record: EnforcementRecord) -> EnforcementResult:
    return EnforcementResult(
        enforcement_id=record.enforcement_id,
        evaluation_id=record.evaluation_id,
        evaluation_evidence_id=record.evaluation_evidence_id,
        decision=record.decision,
        status=record.status,
        transformation_receipts=record.transformation_receipts,
        reason_codes=record.reason_codes,
        output_digest=record.output_digest,
        provider_execution_id=record.provider_execution_id,
        provider_call_metadata=record.provider_call_metadata,
        approval_receipt=record.approval_receipt,
        tool_proposals=record.tool_proposals,
    )


_SAFE_EXECUTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")


def _validate_provider_receipt(receipt: ProviderExecutionReceipt, plan: ExecutionPlan) -> None:
    if (
        len(receipt.execution_id) > 128
        or _SAFE_EXECUTION_ID.fullmatch(receipt.execution_id) is None
        or receipt.provider_target != plan.provider.identifier
        or receipt.plan_id != plan.plan_id
        or receipt.output_digest != plan.output_digest
    ):
        raise ValueError("Execution adapter returned an invalid receipt")
    if receipt.call_metadata is not None:
        _validate_provider_call_metadata(receipt.call_metadata)
    authorized = {tool.name: tool for tool in plan.tools}
    if len(receipt.tool_proposals) != len({item.call_id for item in receipt.tool_proposals}):
        raise ValueError("Execution adapter returned duplicate tool proposals")
    for proposal in receipt.tool_proposals:
        definition = authorized.get(proposal.tool_name)
        if (
            definition is None
            or proposal.tool_schema_version != definition.schema_version
            or proposal.tool_schema_digest != definition.input_schema_digest
            or len(proposal.call_id) > 128
            or _SAFE_EXECUTION_ID.fullmatch(proposal.call_id) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", proposal.arguments_digest) is None
        ):
            raise ValueError("Execution adapter returned an invalid tool proposal")


def _validate_approval_grant(
    grant: ApprovalGrant,
    *,
    decision_digest: str,
    now: datetime,
) -> None:
    if (
        len(grant.approval_id) > 128
        or len(grant.actor_id) > 128
        or _SAFE_EXECUTION_ID.fullmatch(grant.approval_id) is None
        or _SAFE_EXECUTION_ID.fullmatch(grant.actor_id) is None
        or grant.decision_digest != decision_digest
        or grant.issued_at.tzinfo is None
        or grant.issued_at.utcoffset() is None
        or grant.expires_at.tzinfo is None
        or grant.expires_at.utcoffset() is None
        or grant.issued_at > now
        or grant.expires_at <= now
        or grant.expires_at <= grant.issued_at
        or (grant.expires_at - grant.issued_at).total_seconds() > 86_400
    ):
        raise ValueError("Approval adapter returned an invalid grant")


def _validate_approval_receipt(
    receipt: ApprovalReceipt,
    *,
    grant: ApprovalGrant,
    enforcement_id: str,
    now: datetime,
) -> None:
    if (
        receipt.approval_id != grant.approval_id
        or receipt.actor_id != grant.actor_id
        or receipt.decision_digest != grant.decision_digest
        or receipt.enforcement_id != enforcement_id
        or receipt.issued_at != grant.issued_at
        or receipt.expires_at != grant.expires_at
        or receipt.consumed_at.tzinfo is None
        or receipt.consumed_at.utcoffset() is None
        or receipt.consumed_at != now
        or receipt.consumed_at < receipt.issued_at
        or receipt.consumed_at >= receipt.expires_at
    ):
        raise ValueError("Approval adapter returned an invalid receipt")


_SAFE_PROVIDER_METADATA = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]*\Z")


def _validate_provider_call_metadata(metadata: ProviderCallMetadata) -> None:
    values = (
        metadata.gateway_request_id,
        metadata.routing_decision_id,
        metadata.policy_id,
        metadata.policy_version,
        metadata.provider,
        metadata.model,
        metadata.deployment,
    )
    if (
        any(
            len(value) > 256 or _SAFE_PROVIDER_METADATA.fullmatch(value) is None for value in values
        )
        or metadata.latency_ms < 0
        or metadata.attempt_number <= 0
        or metadata.fallback_index < 0
    ):
        raise ValueError("Execution adapter returned invalid provider metadata")


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
