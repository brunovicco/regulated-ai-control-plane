from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from regulated_ai.application import (
    ControlPackScenarioReplayError,
    ReplayControlPackScenarios,
)
from regulated_ai.domain import (
    AssuranceLevel,
    CapabilityRequirement,
    CapabilityState,
    ControlPackImpact,
    ControlPackRelease,
    ControlPackReleaseIdentity,
    ControlPackScenario,
    ControlPackScenarioSuite,
    DataItem,
    DecisionOutcome,
    Jurisdiction,
    PolicyMatch,
    PolicyRule,
    PolicySet,
    ProviderCapability,
    ProviderCapabilityRecord,
    ProviderTarget,
    Purpose,
    ScenarioReplayStatus,
    Sector,
)


def _rule(*, version: str = "1.0.0") -> PolicyRule:
    return PolicyRule(
        id="org.provider.require-control",
        version=version,
        match=PolicyMatch(operation_kind="external_inference"),
        decision=DecisionOutcome.ALLOW,
        obligations=(),
        required_capabilities=(
            CapabilityRequirement(
                key="required_control",
                accepted_states=(CapabilityState.SUPPORTED,),
                max_age_days=30,
            ),
        ),
        control_objective_ids=("CONTROL.TEST",),
        regulatory_support_refs=(),
        reason_code="PROVIDER_REVIEWED",
    )


def _policy(*, version: str = "1.0.0", rule_version: str = "1.0.0") -> PolicySet:
    return PolicySet(
        id="test-policy",
        version=version,
        jurisdiction="BR",
        sector="financial_services",
        status="approved",
        rules=(_rule(version=rule_version),),
    )


def _record(*, state: CapabilityState = CapabilityState.SUPPORTED) -> ProviderCapabilityRecord:
    target = ProviderTarget("test-provider", "test-service", "test-region")
    capability = ProviderCapability(
        provider=target.provider,
        service=target.service,
        region=target.region,
        key="required_control",
        state=state,
        conditions=(),
        notes=(),
        source_urls=("https://provider.invalid/documentation",),
        verified_at=date(2026, 9, 20),
        record_version="1",
        registry_version="registry@1",
    )
    return ProviderCapabilityRecord(
        target=target,
        registry_version=capability.registry_version,
        record_version=capability.record_version,
        verified_at=capability.verified_at,
        source_urls=capability.source_urls,
        capabilities=(capability,),
    )


def _release(
    *,
    pack_id: str = "test-pack",
    digest: str = "sha256:base",
    policy: PolicySet | None = None,
    record: ProviderCapabilityRecord | None = None,
) -> ControlPackRelease:
    return ControlPackRelease(
        identity=ControlPackReleaseIdentity(pack_id, "1.0.0", "test-key", digest),
        policy_sets=(policy or _policy(),),
        provider_records=(record or _record(),),
    )


def _suite(*, scenario: ControlPackScenario | None = None) -> ControlPackScenarioSuite:
    selected = scenario or ControlPackScenario(
        id="provider-control",
        policy_set_id="test-policy",
        jurisdiction=Jurisdiction("BR"),
        sector=Sector("financial_services"),
        purpose=Purpose("customer_support"),
        operation_kind="external_inference",
        assurance_level=AssuranceLevel.HIGH,
        provider=ProviderTarget("test-provider", "test-service", "test-region"),
        data_items=(),
    )
    return ControlPackScenarioSuite(
        id="test-suite",
        version="1.0.0",
        suite_digest="sha256:suite",
        evaluated_at=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
        scenarios=(selected,),
    )


def test_identical_releases_have_no_observed_scenario_change() -> None:
    release = _release()

    report = ReplayControlPackScenarios().execute(release, release, _suite())

    assert report.has_decision_impact is False
    assert report.results[0].changed_fields == ()
    assert report.results[0].impact is None
    assert report.results[0].base.status is ScenarioReplayStatus.EVALUATED
    assert report.results[0].base.decision is DecisionOutcome.ALLOW
    assert report.results[0].base == report.results[0].candidate


def test_capability_regression_is_observed_as_decision_impact() -> None:
    report = ReplayControlPackScenarios().execute(
        _release(),
        _release(
            digest="sha256:candidate",
            record=_record(state=CapabilityState.UNSUPPORTED),
        ),
        _suite(),
    )

    result = report.results[0]
    assert report.has_decision_impact is True
    assert result.impact is ControlPackImpact.DECISION
    assert "decision" in result.changed_fields
    assert result.base.decision is DecisionOutcome.ALLOW
    assert result.candidate.decision is DecisionOutcome.DENY
    assert "PROVIDER_CAPABILITY_UNSUPPORTED" in result.candidate.reason_codes


def test_version_only_result_change_is_evidence_impact() -> None:
    candidate_policy = _policy(version="2.0.0", rule_version="1.0.0")

    report = ReplayControlPackScenarios().execute(
        _release(),
        _release(digest="sha256:candidate", policy=candidate_policy),
        _suite(),
    )

    result = report.results[0]
    assert result.impact is ControlPackImpact.EVIDENCE
    assert result.base.decision is result.candidate.decision
    assert result.base.obligations_digest == result.candidate.obligations_digest
    assert "policy_set_version" in result.changed_fields
    assert "output_digest" in result.changed_fields


def test_missing_candidate_policy_fails_closed_and_is_decision_impact() -> None:
    other_policy = replace(_policy(), id="other-policy")

    report = ReplayControlPackScenarios().execute(
        _release(),
        _release(digest="sha256:candidate", policy=other_policy),
        _suite(),
    )

    candidate = report.results[0].candidate
    assert report.results[0].impact is ControlPackImpact.DECISION
    assert candidate.status is ScenarioReplayStatus.FAILED_CLOSED
    assert candidate.error_code == "POLICY_SET_NOT_FOUND"


def test_ambiguous_candidate_policy_version_fails_closed() -> None:
    candidate = replace(
        _release(digest="sha256:candidate"),
        policy_sets=(_policy(version="1.0.0"), _policy(version="2.0.0")),
    )

    report = ReplayControlPackScenarios().execute(_release(), candidate, _suite())

    assert report.results[0].candidate.error_code == "POLICY_SET_AMBIGUOUS"
    assert report.results[0].impact is ControlPackImpact.DECISION


def test_pack_mismatch_and_raw_scenario_value_are_rejected() -> None:
    with pytest.raises(ControlPackScenarioReplayError, match="identifiers must match"):
        ReplayControlPackScenarios().execute(
            _release(),
            _release(pack_id="other-pack"),
            _suite(),
        )

    scenario = replace(
        _suite().scenarios[0],
        data_items=(),
    )
    unsafe_item = replace(
        scenario,
        data_items=(
            # A direct constructor must still be rejected even if it bypasses the YAML adapter.
            DataItem("unsafe", "raw-value"),
        ),
    )
    with pytest.raises(ControlPackScenarioReplayError, match="values are not allowed"):
        ReplayControlPackScenarios().execute(_release(), _release(), _suite(scenario=unsafe_item))


def test_naive_clock_and_invalid_approved_base_are_rejected() -> None:
    naive_suite = replace(_suite(), evaluated_at=datetime(2026, 9, 25, 12, 0))
    with pytest.raises(ControlPackScenarioReplayError, match="timezone-aware"):
        ReplayControlPackScenarios().execute(_release(), _release(), naive_suite)

    missing_policy = replace(_release(), policy_sets=(replace(_policy(), id="other-policy"),))
    with pytest.raises(ControlPackScenarioReplayError, match="Approved base failed"):
        ReplayControlPackScenarios().execute(missing_policy, missing_policy, _suite())
