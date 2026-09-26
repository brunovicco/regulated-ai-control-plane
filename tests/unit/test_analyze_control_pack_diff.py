from dataclasses import replace
from datetime import date

import pytest

from regulated_ai.application import AnalyzeControlPackDiff, ControlPackDiffError
from regulated_ai.domain import (
    AuthorizedTool,
    CapabilityRequirement,
    CapabilityState,
    ControlPackChangeKind,
    ControlPackChangeType,
    ControlPackImpact,
    ControlPackRelease,
    ControlPackReleaseIdentity,
    DecisionOutcome,
    PolicyMatch,
    PolicyRule,
    PolicySet,
    ProviderCapability,
    ProviderCapabilityRecord,
    ProviderTarget,
)


def _tool(*, risk_class: str = "read_only") -> AuthorizedTool:
    return AuthorizedTool(
        name="cards.read",
        description="Read synthetic status.",
        risk_class=risk_class,
        schema_version="1",
        input_schema_json="{}",
        input_schema_digest="sha256:input",
        output_schema_json="{}",
        output_schema_digest="sha256:output",
        definition_digest=f"sha256:{risk_class}",
        catalog_version="tools@1",
    )


def _rule() -> PolicyRule:
    return PolicyRule(
        id="org.provider.require-zdr",
        version="1.0.0",
        match=PolicyMatch(provider="openai", service="responses_api", region="global"),
        decision=DecisionOutcome.ALLOW,
        obligations=(),
        required_capabilities=(
            CapabilityRequirement(
                key="zero_data_retention",
                accepted_states=(CapabilityState.SUPPORTED, CapabilityState.CONDITIONAL),
            ),
        ),
        control_objective_ids=("BR.PRIV.DEMONSTRABLE_CONTROLS",),
        regulatory_support_refs=("ANPD-R19-A9",),
        reason_code="PROVIDER_REVIEWED",
    )


def _policy(rule: PolicyRule | None = None) -> PolicySet:
    return PolicySet(
        id="br-financial-demo",
        version="1.0.0",
        jurisdiction="BR",
        sector="financial_services",
        status="approved",
        rules=(rule or _rule(),),
    )


def _record(fact: ProviderCapability | None = None) -> ProviderCapabilityRecord:
    target = ProviderTarget("openai", "responses_api", "global")
    capability = fact or ProviderCapability(
        provider=target.provider,
        service=target.service,
        region=target.region,
        key="zero_data_retention",
        state=CapabilityState.CONDITIONAL,
        conditions=("eligible_organization_required",),
        notes=("Reviewed synthetic note.",),
        source_urls=("https://example.test/provider",),
        verified_at=date(2026, 9, 25),
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
    digest: str = "sha256:base",
    pack_id: str = "br-financial-runtime",
    policy: PolicySet | None = None,
    record: ProviderCapabilityRecord | None = None,
    signing_key_id: str = "key-a",
    pack_version: str = "1.0.0",
    tool: AuthorizedTool | None = None,
) -> ControlPackRelease:
    return ControlPackRelease(
        identity=ControlPackReleaseIdentity(
            pack_id=pack_id,
            pack_version=pack_version,
            signing_key_id=signing_key_id,
            payload_digest=digest,
        ),
        policy_sets=(policy or _policy(),),
        provider_records=(record or _record(),),
        tool_catalog_version="tools@1" if tool is not None else None,
        tools=() if tool is None else (tool,),
    )


def test_identical_releases_have_no_semantic_impact() -> None:
    release = _release()

    report = AnalyzeControlPackDiff().execute(release, release)

    assert report.changes == ()
    assert report.highest_impact is None
    assert report.has_decision_impact is False
    assert report.version_reused is False
    assert report.signing_key_changed is False


def test_policy_decision_change_is_decision_impact_and_detects_version_reuse() -> None:
    candidate_rule = replace(_rule(), decision=DecisionOutcome.DENY)

    report = AnalyzeControlPackDiff().execute(
        _release(),
        _release(digest="sha256:candidate", policy=_policy(candidate_rule)),
    )

    assert report.version_reused is True
    assert report.highest_impact is ControlPackImpact.DECISION
    assert len(report.changes) == 1
    change = report.changes[0]
    assert change.kind is ControlPackChangeKind.POLICY_RULE
    assert change.change_type is ControlPackChangeType.MODIFIED
    assert change.impact is ControlPackImpact.DECISION
    assert change.changed_fields == ("decision",)


def test_policy_regulatory_mapping_change_is_governance_only() -> None:
    candidate_rule = replace(_rule(), regulatory_support_refs=("ANPD-R19-A10",))

    report = AnalyzeControlPackDiff().execute(
        _release(),
        _release(digest="sha256:candidate", policy=_policy(candidate_rule)),
    )

    assert report.highest_impact is ControlPackImpact.GOVERNANCE
    assert report.changes[0].changed_fields == ("regulatory_support_refs",)


def test_release_metadata_can_change_without_semantic_changes() -> None:
    report = AnalyzeControlPackDiff().execute(
        _release(),
        _release(
            digest="sha256:candidate",
            pack_version="2.0.0",
            signing_key_id="key-b",
        ),
    )

    assert report.changes == ()
    assert report.highest_impact is None
    assert report.version_reused is False
    assert report.signing_key_changed is True


def test_tool_risk_change_is_decision_impact() -> None:
    report = AnalyzeControlPackDiff().execute(
        _release(tool=_tool()),
        _release(digest="sha256:candidate", tool=_tool(risk_class="high_impact_state_change")),
    )

    change = next(
        item for item in report.changes if item.kind is ControlPackChangeKind.TOOL_DEFINITION
    )
    assert change.impact is ControlPackImpact.DECISION
    assert change.changed_fields == ("risk_class",)


def test_capability_state_change_names_dependent_policy_rules() -> None:
    candidate_fact = replace(
        _record().capabilities[0],
        state=CapabilityState.UNSUPPORTED,
    )

    report = AnalyzeControlPackDiff().execute(
        _release(),
        _release(digest="sha256:candidate", record=_record(candidate_fact)),
    )

    change = report.changes[0]
    assert change.kind is ControlPackChangeKind.PROVIDER_CAPABILITY
    assert change.impact is ControlPackImpact.DECISION
    assert change.changed_fields == ("state",)
    assert change.dependent_policy_rule_ids == (
        "br-financial-demo@1.0.0:org.provider.require-zdr@1.0.0",
    )


def test_capability_source_change_is_evidence_impact() -> None:
    candidate_fact = replace(
        _record().capabilities[0],
        source_urls=("https://example.test/new-source",),
    )

    report = AnalyzeControlPackDiff().execute(
        _release(),
        _release(digest="sha256:candidate", record=_record(candidate_fact)),
    )

    assert report.highest_impact is ControlPackImpact.EVIDENCE
    assert report.changes[0].changed_fields == ("source_urls",)


def test_capability_dependency_excludes_rules_for_other_provider() -> None:
    other_provider_rule = replace(
        _rule(),
        id="org.provider.aws-zdr",
        match=PolicyMatch(provider="aws", service="bedrock_runtime"),
    )
    policy = replace(_policy(), rules=(_rule(), other_provider_rule))
    candidate_fact = replace(
        _record().capabilities[0],
        state=CapabilityState.UNSUPPORTED,
    )

    report = AnalyzeControlPackDiff().execute(
        _release(policy=policy),
        _release(
            digest="sha256:candidate",
            policy=policy,
            record=_record(candidate_fact),
        ),
    )

    assert report.changes[0].dependent_policy_rule_ids == (
        "br-financial-demo@1.0.0:org.provider.require-zdr@1.0.0",
    )


def test_pack_lineages_must_match() -> None:
    with pytest.raises(ControlPackDiffError, match="identifiers must match"):
        AnalyzeControlPackDiff().execute(_release(), _release(pack_id="other-pack"))
