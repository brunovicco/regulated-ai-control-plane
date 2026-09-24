from dataclasses import replace

import pytest

from regulated_ai.adapters.classifier import DeterministicDataClassifier
from regulated_ai.adapters.mock_execution import MockInferenceExecutionAdapter
from regulated_ai.adapters.tokenization import HmacTokenizationAdapter
from regulated_ai.application import (
    EnforceAiOperation,
    EnforcementPersistenceError,
    EvaluateAiOperation,
    ExecutionFailedError,
    TransformationFailedError,
)
from regulated_ai.application.ports import TokenizationPort
from regulated_ai.domain import (
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
) -> tuple[EnforceAiOperation, MemoryEnforcementRepository, MockInferenceExecutionAdapter]:
    evaluator = EvaluateAiOperation(
        policies=MemoryPolicyRepository(policy),
        capabilities=MemoryCapabilityRepository(()),
        evidence=MemoryEvidenceRepository(),
        classifier=DeterministicDataClassifier(),
        clock=lambda: NOW,
    )
    records = enforcement or MemoryEnforcementRepository()
    mock = execution or MockInferenceExecutionAdapter()
    service = EnforceAiOperation(
        evaluator=evaluator,
        tokenizer=tokenizer or HmacTokenizationAdapter(b"t" * 32),
        enforcement=records,
        execution=mock,
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
