from dataclasses import replace
from datetime import date

import pytest

from regulated_ai.adapters.classifier import DeterministicDataClassifier
from regulated_ai.application import (
    EvaluateAiOperation,
    EvidencePersistenceError,
    InvalidEvaluationContextError,
    PolicySetNotFoundError,
    ToolAuthorizationError,
)
from regulated_ai.application.ports import EvaluationObserver, EvidenceRepository
from regulated_ai.domain import (
    CapabilityRequirement,
    CapabilityState,
    DataClassification,
    DataItem,
    DecisionOutcome,
    EvidenceMetadata,
    Jurisdiction,
    ObligationType,
    PolicyMatch,
    PolicyObligation,
    PolicyRule,
    PolicySet,
    ProviderCapabilityRecord,
    ProviderTarget,
    Sector,
    ToolRequest,
    strongest_outcome,
)

from ..helpers import (
    NOW,
    CapturingObserver,
    MemoryCapabilityRepository,
    MemoryEvidenceRepository,
    MemoryPolicyRepository,
    MemoryToolCatalogRepository,
    capability_record,
    context,
    synthetic_cpf,
)


def _policy(*rules: PolicyRule) -> PolicySet:
    return PolicySet("test-policy", "1.0.0", "BR", "financial_services", "approved", rules)


def _evaluator(
    policy: PolicySet,
    *,
    records: tuple[ProviderCapabilityRecord, ...] | None = None,
    evidence: EvidenceRepository | None = None,
    observer: EvaluationObserver | None = None,
) -> EvaluateAiOperation:
    return EvaluateAiOperation(
        policies=MemoryPolicyRepository(policy),
        capabilities=MemoryCapabilityRepository(
            (capability_record(),) if records is None else records
        ),
        evidence=evidence or MemoryEvidenceRepository(),
        classifier=DeterministicDataClassifier(),
        tools=MemoryToolCatalogRepository(),
        observer=observer,
        clock=lambda: NOW,
    )


def _capability_rule(
    *,
    accepted: tuple[CapabilityState, ...] = (CapabilityState.SUPPORTED,),
    assertions: tuple[str, ...] = (),
    max_age_days: int | None = 30,
) -> PolicyRule:
    return PolicyRule(
        id="require-capability",
        version="1",
        match=PolicyMatch(operation_kind="external_inference"),
        decision=None,
        obligations=(),
        required_capabilities=(
            CapabilityRequirement("required_control", accepted, assertions, max_age_days),
        ),
        control_objective_ids=("CONTROL.TEST",),
        regulatory_support_refs=(),
    )


def test_decision_precedence_is_fixed() -> None:
    assert strongest_outcome((DecisionOutcome.ALLOW, DecisionOutcome.DENY)) is DecisionOutcome.DENY
    assert (
        strongest_outcome(
            (DecisionOutcome.ALLOW_WITH_TRANSFORMATION, DecisionOutcome.REQUIRE_APPROVAL)
        )
        is DecisionOutcome.REQUIRE_APPROVAL
    )


def test_repeatable_evaluation_preserves_transform_before_approval_and_metadata_only_evidence() -> (
    None
):
    sentinel = f"raw-{synthetic_cpf()}-must-not-persist"
    transform = PolicyRule(
        id="transform",
        version="1",
        match=PolicyMatch(data_class_any=(DataClassification.PERSONAL_DIRECT_IDENTIFIER,)),
        decision=DecisionOutcome.ALLOW_WITH_TRANSFORMATION,
        obligations=(
            PolicyObligation(
                ObligationType.TOKENIZE,
                None,
                DataClassification.PERSONAL_DIRECT_IDENTIFIER,
                "MINIMIZE",
            ),
        ),
        required_capabilities=(),
        control_objective_ids=("CONTROL.MINIMIZE",),
        regulatory_support_refs=("SOURCE.TEST",),
    )
    approval = PolicyRule(
        id="approval",
        version="1",
        match=PolicyMatch(tool_risk_class_any=("high_impact_state_change",)),
        decision=DecisionOutcome.REQUIRE_APPROVAL,
        obligations=(
            PolicyObligation(
                ObligationType.REQUIRE_HUMAN_APPROVAL,
                "matched_tool",
                None,
                "APPROVAL_REQUIRED",
            ),
        ),
        required_capabilities=(),
        control_objective_ids=("CONTROL.AUTHORITY",),
        regulatory_support_refs=(),
    )
    evidence = MemoryEvidenceRepository()
    observer = CapturingObserver()
    evaluator = _evaluator(_policy(transform, approval), evidence=evidence, observer=observer)
    request = context(
        data_items=(
            DataItem(
                "customer_document",
                sentinel,
                supplied_labels=(DataClassification.PERSONAL_DIRECT_IDENTIFIER,),
            ),
        ),
        tools=(ToolRequest("cards.unblock", "high_impact_state_change"),),
    )

    first = evaluator.execute(request)
    second = evaluator.execute(request)

    assert first.decision is DecisionOutcome.REQUIRE_APPROVAL
    assert first.evaluation_id == second.evaluation_id
    assert first.input_digest == second.input_digest
    assert [item.type for item in first.obligations] == [
        ObligationType.REQUIRE_EVIDENCE,
        ObligationType.REQUIRE_HUMAN_APPROVAL,
        ObligationType.TOKENIZE,
    ]
    assert first.obligations[-1].target == "customer_document"
    assert sentinel not in repr(evidence.items)
    assert evidence.get(first.evidence_id).policy_set_version == "test-policy@1.0.0"  # type: ignore[union-attr]
    assert evidence.get(first.evidence_id).provider_registry_version == "registry@test"  # type: ignore[union-attr]
    assert {event for event, _ in observer.events} >= {
        "evaluation.started",
        "policy.matched",
        "decision.produced",
        "evidence.persisted",
    }


def test_tool_risk_is_resolved_from_catalog_and_bound_to_evidence() -> None:
    approval = PolicyRule(
        id="approval",
        version="1",
        match=PolicyMatch(tool_risk_class_any=("high_impact_state_change",)),
        decision=DecisionOutcome.REQUIRE_APPROVAL,
        obligations=(
            PolicyObligation(
                ObligationType.REQUIRE_HUMAN_APPROVAL,
                "matched_tool",
                None,
                "APPROVAL_REQUIRED",
            ),
        ),
        required_capabilities=(),
        control_objective_ids=("CONTROL.AUTHORITY",),
        regulatory_support_refs=(),
    )
    evidence = MemoryEvidenceRepository()
    evaluator = _evaluator(_policy(approval), evidence=evidence)

    result = evaluator.execute(context(tools=(ToolRequest("cards.unblock"),)))
    stored = evidence.get(result.evidence_id)

    assert result.decision is DecisionOutcome.REQUIRE_APPROVAL
    assert result.authorized_tools[0].risk_class == "high_impact_state_change"
    assert result.tool_catalog_version == "tools@test"
    assert stored is not None
    assert stored.authorized_tool_ids == ("cards.unblock@1.1.0",)


@pytest.mark.parametrize(
    "tool_request",
    [
        ToolRequest("cards.unknown"),
        ToolRequest("cards.unblock", "read_only"),
    ],
)
def test_unknown_tool_or_forged_risk_claim_fails_closed(tool_request: ToolRequest) -> None:
    evaluator = _evaluator(_policy(_capability_rule()))

    with pytest.raises(ToolAuthorizationError):
        evaluator.execute(context(tools=(tool_request,)))


@pytest.mark.parametrize(
    ("records", "expected_reason"),
    [
        ((), "PROVIDER_CAPABILITY_UNKNOWN"),
        (
            (capability_record(state=CapabilityState.UNKNOWN),),
            "PROVIDER_CAPABILITY_UNKNOWN",
        ),
        (
            (capability_record(state=CapabilityState.UNSUPPORTED),),
            "PROVIDER_CAPABILITY_UNSUPPORTED",
        ),
        (
            (capability_record(verified_at=date(2026, 1, 1)),),
            "PROVIDER_CAPABILITY_STALE",
        ),
    ],
)
def test_mandatory_capability_failures_deny(
    records: tuple[ProviderCapabilityRecord, ...], expected_reason: str
) -> None:
    evaluator = _evaluator(_policy(_capability_rule()), records=records)

    result = evaluator.execute(context())

    assert result.decision is DecisionOutcome.DENY
    assert expected_reason in result.reason_codes


def test_conditional_capability_requires_explicit_matching_assertion() -> None:
    records = (
        capability_record(
            state=CapabilityState.CONDITIONAL,
            conditions=("organization_eligible",),
        ),
    )
    rule = _capability_rule(
        accepted=(CapabilityState.CONDITIONAL,), assertions=("organization_eligible",)
    )
    evaluator = _evaluator(_policy(rule), records=records)

    denied = evaluator.execute(context())
    allowed = evaluator.execute(context(assertions=(("organization_eligible", True),)))

    assert denied.decision is DecisionOutcome.DENY
    assert allowed.decision is DecisionOutcome.ALLOW


def test_every_documented_capability_condition_must_be_asserted() -> None:
    records = (
        capability_record(
            state=CapabilityState.CONDITIONAL,
            conditions=("organization_eligible", "endpoint_eligible"),
        ),
    )
    rule = _capability_rule(
        accepted=(CapabilityState.CONDITIONAL,), assertions=("organization_eligible",)
    )
    evaluator = _evaluator(_policy(rule), records=records)

    denied = evaluator.execute(context(assertions=(("organization_eligible", True),)))
    allowed = evaluator.execute(
        context(assertions=(("endpoint_eligible", True), ("organization_eligible", True)))
    )

    assert denied.decision is DecisionOutcome.DENY
    assert allowed.decision is DecisionOutcome.ALLOW


def test_application_normalizes_metadata_and_rejects_content_like_identifiers() -> None:
    rule = PolicyRule(
        id="normalized",
        version="1",
        match=PolicyMatch(
            jurisdiction="BR",
            sector="financial_services",
            operation_kind="external_inference",
            provider="test-provider",
            service="test-service",
        ),
        decision=DecisionOutcome.REQUIRE_APPROVAL,
        obligations=(),
        required_capabilities=(),
        control_objective_ids=(),
        regulatory_support_refs=(),
    )
    evaluator = _evaluator(_policy(rule))
    mixed_case = replace(
        context(),
        jurisdiction=Jurisdiction(" br "),
        sector=Sector(" Financial_Services "),
        operation_kind=" External_Inference ",
        provider=ProviderTarget(" TEST-PROVIDER ", " TEST-SERVICE ", " TEST-REGION "),
    )

    assert evaluator.execute(mixed_case).decision is DecisionOutcome.REQUIRE_APPROVAL
    with pytest.raises(InvalidEvaluationContextError):
        evaluator.execute(replace(context(), correlation_id="raw content is not metadata"))


def test_fallback_cannot_weaken_mandatory_requirements() -> None:
    fallback = ProviderTarget("fallback-provider", "fallback-service", "test-region")
    evaluator = _evaluator(_policy(_capability_rule()))

    result = evaluator.execute(context(fallback_providers=(fallback,)))

    assert result.decision is DecisionOutcome.DENY
    assert "PROVIDER_CAPABILITY_UNKNOWN" in result.reason_codes


def test_deny_has_precedence_over_approval_and_transformation() -> None:
    rules = tuple(
        PolicyRule(
            id=outcome.value,
            version="1",
            match=PolicyMatch(),
            decision=outcome,
            obligations=(),
            required_capabilities=(),
            control_objective_ids=(),
            regulatory_support_refs=(),
        )
        for outcome in (
            DecisionOutcome.ALLOW_WITH_TRANSFORMATION,
            DecisionOutcome.REQUIRE_APPROVAL,
            DecisionOutcome.DENY,
        )
    )

    assert _evaluator(_policy(*rules)).execute(context()).decision is DecisionOutcome.DENY


def test_policy_not_found_and_evidence_failure_use_stable_errors() -> None:
    evaluator = _evaluator(_policy())
    missing = replace(context(), policy_set_version="missing@1")
    with pytest.raises(PolicySetNotFoundError):
        evaluator.execute(missing)

    class BrokenEvidence(MemoryEvidenceRepository):
        def save(self, evidence: EvidenceMetadata) -> EvidenceMetadata:
            del evidence
            raise OSError("synthetic persistence failure")

    with pytest.raises(EvidencePersistenceError):
        _evaluator(_policy(_capability_rule()), evidence=BrokenEvidence()).execute(context())
