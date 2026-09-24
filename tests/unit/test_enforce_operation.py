from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from regulated_ai.adapters.classifier import DeterministicDataClassifier
from regulated_ai.adapters.mock_execution import MockInferenceExecutionAdapter
from regulated_ai.adapters.tokenization import HmacTokenizationAdapter
from regulated_ai.application import (
    ApprovalFailedError,
    EnforceAiOperation,
    EnforcementPersistenceError,
    EvaluateAiOperation,
    ExecutionFailedError,
    TransformationFailedError,
)
from regulated_ai.application.ports import ApprovalPort, TokenizationPort
from regulated_ai.domain import (
    ApprovalGrant,
    ApprovalReceipt,
    DataItem,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    ExecutionPlan,
    ObligationType,
    PolicyMatch,
    PolicyObligation,
    PolicyRule,
    PolicySet,
    ProviderExecutionReceipt,
)

from ..helpers import (
    NOW,
    MemoryCapabilityRepository,
    MemoryEnforcementRepository,
    MemoryEvidenceRepository,
    MemoryPolicyRepository,
    MemoryToolCatalogRepository,
    context,
)


def _policy(
    outcome: DecisionOutcome,
    *obligations: PolicyObligation,
) -> PolicySet:
    rule = PolicyRule(
        id="enforcement-rule",
        version="1",
        match=PolicyMatch(),
        decision=outcome,
        obligations=obligations,
        required_capabilities=(),
        control_objective_ids=("CONTROL.TEST",),
        regulatory_support_refs=(),
    )
    return PolicySet("test-policy", "1.0.0", "BR", "financial_services", "approved", (rule,))


def _obligation(type_: ObligationType) -> PolicyObligation:
    return PolicyObligation(type_, "sensitive_field", None, f"{type_.value}_REQUIRED")


def _enforcer(
    policy: PolicySet,
    *,
    enforcement: MemoryEnforcementRepository | None = None,
    execution: MockInferenceExecutionAdapter | None = None,
    tokenizer: TokenizationPort | None = None,
    approval: ApprovalPort | None = None,
) -> tuple[EnforceAiOperation, MemoryEnforcementRepository, MockInferenceExecutionAdapter]:
    evaluator = EvaluateAiOperation(
        policies=MemoryPolicyRepository(policy),
        capabilities=MemoryCapabilityRepository(()),
        evidence=MemoryEvidenceRepository(),
        classifier=DeterministicDataClassifier(),
        tools=MemoryToolCatalogRepository(),
        clock=lambda: NOW,
    )
    records = enforcement or MemoryEnforcementRepository()
    mock = execution or MockInferenceExecutionAdapter()
    service = EnforceAiOperation(
        evaluator=evaluator,
        tokenizer=tokenizer or HmacTokenizationAdapter(b"t" * 32),
        enforcement=records,
        execution=mock,
        approval=approval,
        clock=lambda: NOW,
    )
    return service, records, mock


@pytest.mark.parametrize(
    ("type_", "expected"),
    [
        (ObligationType.MASK, "***MASKED***"),
        (ObligationType.TOKENIZE, "tok_"),
        (ObligationType.PSEUDONYMIZE, "psn_"),
        (ObligationType.REMOVE_FIELD, None),
    ],
)
def test_transformations_are_applied_before_mock_execution(
    type_: ObligationType, expected: str | None
) -> None:
    sentinel = "raw-sensitive-enforcement-sentinel"
    enforcer, records, mock = _enforcer(
        _policy(DecisionOutcome.ALLOW_WITH_TRANSFORMATION, _obligation(type_))
    )

    result = enforcer.execute(context(data_items=(DataItem("sensitive_field", sentinel),)))

    assert result.status is EnforcementStatus.EXECUTED
    assert records.saved_statuses == ["PREPARED", "DISPATCHED", "EXECUTED"]
    assert mock.call_count == 1
    assert mock.last_plan is not None
    values = {item.field: item.value for item in mock.last_plan.data_items}
    if expected is None:
        assert "sensitive_field" not in values
    elif expected.endswith("_"):
        assert values["sensitive_field"].startswith(expected)
    else:
        assert values["sensitive_field"] == expected
    assert sentinel not in repr(result)
    assert sentinel not in repr(records.items)
    assert len(result.transformation_receipts) == 1


def test_deny_never_transforms_or_executes() -> None:
    enforcer, records, mock = _enforcer(
        _policy(DecisionOutcome.DENY, _obligation(ObligationType.TOKENIZE))
    )

    result = enforcer.execute(context(data_items=(DataItem("sensitive_field", "sentinel"),)))

    assert result.status is EnforcementStatus.BLOCKED_DENY
    assert result.transformation_receipts == ()
    assert records.saved_statuses == ["BLOCKED_DENY"]
    assert mock.call_count == 0


def test_approval_transforms_but_never_executes() -> None:
    enforcer, records, mock = _enforcer(
        _policy(DecisionOutcome.REQUIRE_APPROVAL, _obligation(ObligationType.TOKENIZE))
    )

    result = enforcer.execute(context(data_items=(DataItem("sensitive_field", "sentinel"),)))

    assert result.status is EnforcementStatus.WAITING_APPROVAL
    assert len(result.transformation_receipts) == 1
    assert records.saved_statuses == ["WAITING_APPROVAL"]
    assert mock.call_count == 0


class _ApprovalFake:
    def __init__(self, *, fail_consumption: bool = False) -> None:
        self.inspect_count = 0
        self.consume_count = 0
        self.fail_consumption = fail_consumption

    def inspect(
        self,
        assertion: str,
        *,
        decision_digest: str,
        now: datetime,
    ) -> ApprovalGrant:
        del now
        self.inspect_count += 1
        if assertion != "synthetic-approval":
            raise ValueError("synthetic invalid approval")
        return ApprovalGrant(
            approval_id="approval-test",
            actor_id="approver-test",
            decision_digest=decision_digest,
            issued_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=5),
        )

    def consume(
        self,
        grant: ApprovalGrant,
        *,
        enforcement_id: str,
        now: datetime,
    ) -> ApprovalReceipt:
        self.consume_count += 1
        if self.fail_consumption:
            raise ValueError("synthetic replay")
        assert now == NOW
        return ApprovalReceipt(
            approval_id=grant.approval_id,
            actor_id=grant.actor_id,
            decision_digest=grant.decision_digest,
            enforcement_id=enforcement_id,
            issued_at=grant.issued_at,
            expires_at=grant.expires_at,
            consumed_at=NOW,
        )


def test_valid_approval_is_consumed_after_claim_and_sent_as_metadata() -> None:
    approval = _ApprovalFake()
    enforcer, records, mock = _enforcer(
        _policy(DecisionOutcome.REQUIRE_APPROVAL, _obligation(ObligationType.TOKENIZE)),
        approval=approval,
    )

    result = enforcer.execute(
        context(data_items=(DataItem("sensitive_field", "sentinel"),)),
        approval_assertion="synthetic-approval",
    )

    assert result.status is EnforcementStatus.EXECUTED
    assert result.approval_receipt is not None
    assert result.approval_receipt.approval_id == "approval-test"
    assert records.saved_statuses == ["PREPARED", "DISPATCHED", "EXECUTED"]
    assert approval.inspect_count == 1
    assert approval.consume_count == 1
    assert mock.last_plan is not None
    assert mock.last_plan.approval_receipt == result.approval_receipt


def test_invalid_approval_stays_waiting_and_never_claims_execution() -> None:
    approval = _ApprovalFake()
    enforcer, records, mock = _enforcer(
        _policy(DecisionOutcome.REQUIRE_APPROVAL),
        approval=approval,
    )

    with pytest.raises(ApprovalFailedError):
        enforcer.execute(context(), approval_assertion="invalid")

    assert records.saved_statuses == ["WAITING_APPROVAL"]
    assert next(iter(records.items.values())).status is EnforcementStatus.WAITING_APPROVAL
    assert mock.call_count == 0
    assert approval.consume_count == 0


def test_approval_assertion_without_verifier_fails_closed() -> None:
    enforcer, records, mock = _enforcer(_policy(DecisionOutcome.REQUIRE_APPROVAL))

    with pytest.raises(ApprovalFailedError):
        enforcer.execute(context(), approval_assertion="synthetic-approval")

    assert records.saved_statuses == ["WAITING_APPROVAL"]
    assert mock.call_count == 0


def test_approval_consumption_failure_is_terminal_and_prevents_execution() -> None:
    approval = _ApprovalFake(fail_consumption=True)
    enforcer, records, mock = _enforcer(
        _policy(DecisionOutcome.REQUIRE_APPROVAL),
        approval=approval,
    )

    with pytest.raises(ApprovalFailedError):
        enforcer.execute(context(), approval_assertion="synthetic-approval")

    assert records.saved_statuses == ["PREPARED", "DISPATCHED", "APPROVAL_FAILED"]
    assert next(iter(records.items.values())).status is EnforcementStatus.APPROVAL_FAILED
    assert approval.consume_count == 1
    assert mock.call_count == 0


class _MismatchedApprovalReceipt(_ApprovalFake):
    def consume(
        self,
        grant: ApprovalGrant,
        *,
        enforcement_id: str,
        now: datetime,
    ) -> ApprovalReceipt:
        receipt = super().consume(grant, enforcement_id=enforcement_id, now=now)
        return replace(receipt, enforcement_id="enf_wrong")


def test_untrusted_approval_receipt_is_validated_before_execution() -> None:
    enforcer, records, mock = _enforcer(
        _policy(DecisionOutcome.REQUIRE_APPROVAL),
        approval=_MismatchedApprovalReceipt(),
    )

    with pytest.raises(ApprovalFailedError):
        enforcer.execute(context(), approval_assertion="synthetic-approval")

    assert records.saved_statuses == ["PREPARED", "DISPATCHED", "APPROVAL_FAILED"]
    assert mock.call_count == 0


def test_conflicting_transformations_fail_closed() -> None:
    enforcer, records, mock = _enforcer(
        _policy(
            DecisionOutcome.ALLOW_WITH_TRANSFORMATION,
            _obligation(ObligationType.MASK),
            _obligation(ObligationType.TOKENIZE),
        )
    )

    with pytest.raises(TransformationFailedError):
        enforcer.execute(context(data_items=(DataItem("sensitive_field", "sentinel"),)))

    assert records.saved_statuses == ["TRANSFORMATION_FAILED"]
    assert mock.call_count == 0


def test_missing_transformation_target_fails_closed() -> None:
    enforcer, records, mock = _enforcer(
        _policy(DecisionOutcome.ALLOW_WITH_TRANSFORMATION, _obligation(ObligationType.TOKENIZE))
    )

    with pytest.raises(TransformationFailedError):
        enforcer.execute(context(data_items=(DataItem("different_field", "sentinel"),)))

    assert records.saved_statuses == ["TRANSFORMATION_FAILED"]
    assert mock.call_count == 0


def test_transformation_decision_without_obligation_fails_closed() -> None:
    enforcer, records, mock = _enforcer(_policy(DecisionOutcome.ALLOW_WITH_TRANSFORMATION))

    with pytest.raises(TransformationFailedError):
        enforcer.execute(context())

    assert records.saved_statuses == ["TRANSFORMATION_FAILED"]
    assert mock.call_count == 0


class _NoOpTokenizer:
    def tokenize(self, value: str, *, field: str, decision_digest: str) -> str:
        del field, decision_digest
        return value

    def pseudonymize(self, value: str, *, field: str, decision_digest: str) -> str:
        del field, decision_digest
        return value


def test_tokenizer_cannot_return_the_original_value() -> None:
    enforcer, records, mock = _enforcer(
        _policy(
            DecisionOutcome.ALLOW_WITH_TRANSFORMATION,
            _obligation(ObligationType.TOKENIZE),
        ),
        tokenizer=_NoOpTokenizer(),
    )

    with pytest.raises(TransformationFailedError):
        enforcer.execute(context(data_items=(DataItem("sensitive_field", "sentinel"),)))

    assert records.saved_statuses == ["TRANSFORMATION_FAILED"]
    assert mock.call_count == 0


class _BrokenEnforcementRepository(MemoryEnforcementRepository):
    def save(self, record: EnforcementRecord) -> EnforcementRecord:
        del record
        raise OSError("synthetic persistence failure")


def test_persistence_failure_prevents_execution() -> None:
    mock = MockInferenceExecutionAdapter()
    enforcer, _, _ = _enforcer(
        _policy(DecisionOutcome.ALLOW),
        enforcement=_BrokenEnforcementRepository(),
        execution=mock,
    )

    with pytest.raises(EnforcementPersistenceError):
        enforcer.execute(context())

    assert mock.call_count == 0


class _BrokenExecution:
    def __init__(self) -> None:
        self.call_count = 0

    def execute(self, plan: ExecutionPlan) -> ProviderExecutionReceipt:
        del plan
        self.call_count += 1
        raise TimeoutError("synthetic execution timeout")


def test_execution_failure_is_recorded_and_fails_closed() -> None:
    evaluator = EvaluateAiOperation(
        policies=MemoryPolicyRepository(_policy(DecisionOutcome.ALLOW)),
        capabilities=MemoryCapabilityRepository(()),
        evidence=MemoryEvidenceRepository(),
        classifier=DeterministicDataClassifier(),
        tools=MemoryToolCatalogRepository(),
        clock=lambda: NOW,
    )
    records = MemoryEnforcementRepository()
    broken = _BrokenExecution()
    enforcer = EnforceAiOperation(
        evaluator=evaluator,
        tokenizer=HmacTokenizationAdapter(b"t" * 32),
        enforcement=records,
        execution=broken,
        clock=lambda: NOW,
    )

    with pytest.raises(ExecutionFailedError):
        enforcer.execute(context())

    replayed = enforcer.execute(context())

    assert replayed.status is EnforcementStatus.EXECUTION_FAILED
    assert broken.call_count == 1
    assert records.saved_statuses == ["PREPARED", "DISPATCHED", "EXECUTION_FAILED"]


class _MismatchedExecution:
    def execute(self, plan: ExecutionPlan) -> ProviderExecutionReceipt:
        return ProviderExecutionReceipt(
            execution_id="mockexec_mismatch",
            provider_target=plan.provider.identifier,
            plan_id="wrong-plan",
            output_digest=plan.output_digest,
        )


def test_untrusted_execution_receipt_is_validated() -> None:
    evaluator = EvaluateAiOperation(
        policies=MemoryPolicyRepository(_policy(DecisionOutcome.ALLOW)),
        capabilities=MemoryCapabilityRepository(()),
        evidence=MemoryEvidenceRepository(),
        classifier=DeterministicDataClassifier(),
        tools=MemoryToolCatalogRepository(),
        clock=lambda: NOW,
    )
    records = MemoryEnforcementRepository()
    enforcer = EnforceAiOperation(
        evaluator=evaluator,
        tokenizer=HmacTokenizationAdapter(b"t" * 32),
        enforcement=records,
        execution=_MismatchedExecution(),
        clock=lambda: NOW,
    )

    with pytest.raises(ExecutionFailedError):
        enforcer.execute(context())

    assert records.saved_statuses == ["PREPARED", "DISPATCHED", "EXECUTION_FAILED"]


def test_hmac_tokenization_is_scoped_and_rejects_short_keys() -> None:
    tokenizer = HmacTokenizationAdapter(b"k" * 32)
    first = tokenizer.tokenize("value", field="field", decision_digest="decision-a")
    repeated = tokenizer.tokenize("value", field="field", decision_digest="decision-a")
    different = tokenizer.tokenize("value", field="field", decision_digest="decision-b")

    assert first == repeated
    assert first != different
    assert "value" not in first
    with pytest.raises(ValueError):
        HmacTokenizationAdapter(b"short")


def test_completed_enforcement_is_idempotent() -> None:
    enforcer, records, mock = _enforcer(_policy(DecisionOutcome.ALLOW))

    first = enforcer.execute(context())
    second = enforcer.execute(context())

    assert first == second
    assert mock.call_count == 1
    assert records.saved_statuses == ["PREPARED", "DISPATCHED", "EXECUTED"]


class _ContendedExecutionRepository(MemoryEnforcementRepository):
    def claim_execution(self, record: EnforcementRecord) -> tuple[EnforcementRecord, bool]:
        dispatched = replace(record, status=EnforcementStatus.DISPATCHED)
        self.items[record.enforcement_id] = dispatched
        self.saved_statuses.append(dispatched.status.value)
        return dispatched, False


def test_execution_claim_contention_does_not_repeat_external_call() -> None:
    mock = MockInferenceExecutionAdapter()
    enforcer, records, _ = _enforcer(
        _policy(DecisionOutcome.ALLOW),
        enforcement=_ContendedExecutionRepository(),
        execution=mock,
    )

    result = enforcer.execute(context())

    assert result.status is EnforcementStatus.DISPATCHED
    assert mock.call_count == 0
    assert records.saved_statuses == ["PREPARED", "DISPATCHED"]


def test_execution_claim_contention_does_not_consume_approval() -> None:
    approval = _ApprovalFake()
    mock = MockInferenceExecutionAdapter()
    enforcer, records, _ = _enforcer(
        _policy(DecisionOutcome.REQUIRE_APPROVAL),
        enforcement=_ContendedExecutionRepository(),
        execution=mock,
        approval=approval,
    )

    result = enforcer.execute(context(), approval_assertion="synthetic-approval")

    assert result.status is EnforcementStatus.DISPATCHED
    assert approval.inspect_count == 1
    assert approval.consume_count == 0
    assert mock.call_count == 0
    assert records.saved_statuses == ["PREPARED", "DISPATCHED"]
