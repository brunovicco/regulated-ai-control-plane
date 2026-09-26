from dataclasses import replace
from datetime import date

import pytest

from regulated_ai.application import PolicyUpdateRegulatoryReviewError, ReviewPolicyUpdate
from regulated_ai.domain import (
    ControlPackChangeType,
    ControlPackRelease,
    ControlPackReleaseIdentity,
    DecisionOutcome,
    PolicyDraft,
    PolicyMatch,
    PolicyRule,
    PolicyRuleRegulatoryReview,
    PolicySet,
    PolicyUpdateRegulatoryReview,
    RegulatoryReviewConclusion,
    RegulatoryReviewFindingCode,
)


def _rule(
    *,
    rule_id: str = "regulated.rule",
    version: str = "1.0.0",
    objectives: tuple[str, ...] = ("BR.PRIV.MINIMIZE_EXTERNAL_DATA",),
    support: tuple[str, ...] = ("ANPD-R19-A9",),
    decision: DecisionOutcome = DecisionOutcome.ALLOW,
) -> PolicyRule:
    return PolicyRule(
        id=rule_id,
        version=version,
        match=PolicyMatch(operation_kind="external_inference"),
        decision=decision,
        obligations=(),
        required_capabilities=(),
        control_objective_ids=objectives,
        regulatory_support_refs=support,
    )


def _policy(*, version: str, rules: tuple[PolicyRule, ...]) -> PolicySet:
    return PolicySet(
        id="test-policy",
        version=version,
        jurisdiction="BR",
        sector="financial_services",
        status="approved",
        rules=rules,
    )


def _base(rule: PolicyRule | None = None) -> ControlPackRelease:
    return ControlPackRelease(
        identity=ControlPackReleaseIdentity("test-pack", "1", "test-key", "sha256:base"),
        policy_sets=(_policy(version="1.0.0", rules=(rule or _rule(),)),),
        provider_records=(),
    )


def _draft(rule: PolicyRule | None = None) -> PolicyDraft:
    return PolicyDraft(
        policy_set=_policy(
            version="1.1.0",
            rules=(
                rule
                or _rule(
                    version="1.1.0",
                    objectives=(
                        "BR.PRIV.DEMONSTRABLE_CONTROLS",
                        "BR.PRIV.MINIMIZE_EXTERNAL_DATA",
                    ),
                ),
            ),
        ),
        content_digest="sha256:candidate",
    )


def _review(
    *,
    conclusion: RegulatoryReviewConclusion = RegulatoryReviewConclusion.APPROVED,
    rule_reviews: tuple[PolicyRuleRegulatoryReview, ...] | None = None,
) -> PolicyUpdateRegulatoryReview:
    reviews = (
        (
            PolicyRuleRegulatoryReview(
                rule_id="regulated.rule",
                change_type=ControlPackChangeType.MODIFIED,
                control_objective_ids=(
                    "BR.PRIV.DEMONSTRABLE_CONTROLS",
                    "BR.PRIV.MINIMIZE_EXTERNAL_DATA",
                ),
                regulatory_support_refs=("ANPD-R19-A9",),
                conclusion=conclusion,
            ),
        )
        if rule_reviews is None
        else rule_reviews
    )
    return PolicyUpdateRegulatoryReview(
        review_id="review-1",
        reviewer_role="regulatory-governance",
        reviewed_at=date(2026, 9, 26),
        base_pack_payload_digest="sha256:base",
        candidate_policy_digest="sha256:candidate",
        policy_set_id="test-policy",
        reviewed_policy_set_fields=("version",),
        policy_set_conclusion=RegulatoryReviewConclusion.APPROVED,
        rule_reviews=reviews,
        review_digest="sha256:review",
    )


def test_complete_regulatory_review_passes_gate() -> None:
    report = ReviewPolicyUpdate().execute(_base(), _draft(), _review())

    assert report.approved is True
    assert report.findings == ()
    assert report.required_policy_set_fields == ("version",)
    assert report.required_rule_ids == ("regulated.rule",)
    assert report.candidate_policy_version == "1.1.0"


@pytest.mark.parametrize(
    ("conclusion", "code"),
    [
        (RegulatoryReviewConclusion.REJECTED, RegulatoryReviewFindingCode.RULE_REJECTED),
        (
            RegulatoryReviewConclusion.NEEDS_REVISION,
            RegulatoryReviewFindingCode.RULE_NEEDS_REVISION,
        ),
        (
            RegulatoryReviewConclusion.NOT_APPLICABLE,
            RegulatoryReviewFindingCode.REGULATORY_MAPPING_NOT_APPLICABLE,
        ),
    ],
)
def test_non_approved_regulatory_mapping_blocks_gate(
    conclusion: RegulatoryReviewConclusion,
    code: RegulatoryReviewFindingCode,
) -> None:
    report = ReviewPolicyUpdate().execute(
        _base(),
        _draft(),
        _review(conclusion=conclusion),
    )

    assert {item.code for item in report.findings} == {code}


def test_enterprise_rule_requires_explicit_not_applicable_conclusion() -> None:
    base_rule = _rule(
        rule_id="org.rule",
        objectives=("ORG.AGENT.HIGH_IMPACT_APPROVAL",),
        support=(),
    )
    candidate_rule = replace(base_rule, version="1.1.0", decision=DecisionOutcome.DENY)
    draft = _draft(candidate_rule)
    review_item = PolicyRuleRegulatoryReview(
        rule_id="org.rule",
        change_type=ControlPackChangeType.MODIFIED,
        control_objective_ids=("ORG.AGENT.HIGH_IMPACT_APPROVAL",),
        regulatory_support_refs=(),
        conclusion=RegulatoryReviewConclusion.APPROVED,
    )

    blocked = ReviewPolicyUpdate().execute(
        _base(base_rule),
        draft,
        _review(rule_reviews=(review_item,)),
    )
    passed = ReviewPolicyUpdate().execute(
        _base(base_rule),
        draft,
        _review(
            rule_reviews=(
                replace(review_item, conclusion=RegulatoryReviewConclusion.NOT_APPLICABLE),
            )
        ),
    )

    assert blocked.findings[0].code is (
        RegulatoryReviewFindingCode.ENTERPRISE_RULE_CONCLUSION_INVALID
    )
    assert passed.approved is True


def test_missing_review_and_version_bump_fail_closed() -> None:
    candidate_rule = _rule(
        version="1.0.0",
        objectives=(),
        support=(),
        decision=DecisionOutcome.DENY,
    )
    draft = PolicyDraft(
        policy_set=_policy(version="1.0.0", rules=(candidate_rule,)),
        content_digest="sha256:candidate",
    )
    review = replace(
        _review(rule_reviews=()),
        reviewed_policy_set_fields=(),
        policy_set_conclusion=RegulatoryReviewConclusion.NOT_APPLICABLE,
    )

    report = ReviewPolicyUpdate().execute(_base(), draft, review)

    assert {item.code for item in report.findings} == {
        RegulatoryReviewFindingCode.POLICY_SET_VERSION_UNCHANGED,
        RegulatoryReviewFindingCode.RULE_REVIEW_MISSING,
    }


def test_changed_candidate_rule_without_control_objective_is_blocked() -> None:
    candidate_rule = _rule(
        version="1.1.0",
        objectives=(),
        support=(),
        decision=DecisionOutcome.DENY,
    )
    review_item = PolicyRuleRegulatoryReview(
        rule_id="regulated.rule",
        change_type=ControlPackChangeType.MODIFIED,
        control_objective_ids=(),
        regulatory_support_refs=(),
        conclusion=RegulatoryReviewConclusion.NOT_APPLICABLE,
    )

    report = ReviewPolicyUpdate().execute(
        _base(),
        _draft(candidate_rule),
        _review(rule_reviews=(review_item,)),
    )

    assert {item.code for item in report.findings} == {
        RegulatoryReviewFindingCode.CONTROL_OBJECTIVE_MISSING
    }


def test_added_and_removed_rules_bind_candidate_and_base_mappings() -> None:
    removed = _rule(rule_id="removed.rule")
    added = _rule(
        rule_id="added.rule",
        version="1.0.0",
        objectives=("BR.FIN.TRACEABILITY",),
        support=("BCB-CMN-4893",),
    )
    draft = _draft(added)
    reviews = (
        PolicyRuleRegulatoryReview(
            rule_id="added.rule",
            change_type=ControlPackChangeType.ADDED,
            control_objective_ids=("BR.FIN.TRACEABILITY",),
            regulatory_support_refs=("BCB-CMN-4893",),
            conclusion=RegulatoryReviewConclusion.APPROVED,
        ),
        PolicyRuleRegulatoryReview(
            rule_id="removed.rule",
            change_type=ControlPackChangeType.REMOVED,
            control_objective_ids=("BR.PRIV.MINIMIZE_EXTERNAL_DATA",),
            regulatory_support_refs=("ANPD-R19-A9",),
            conclusion=RegulatoryReviewConclusion.APPROVED,
        ),
    )

    report = ReviewPolicyUpdate().execute(
        _base(removed),
        draft,
        _review(rule_reviews=reviews),
    )

    assert report.approved is True
    assert report.required_rule_ids == ("added.rule", "removed.rule")


def test_unreviewed_policy_metadata_and_revision_conclusion_block_gate() -> None:
    draft = _draft()
    draft = replace(draft, policy_set=replace(draft.policy_set, status="reviewed"))
    review = replace(
        _review(),
        policy_set_conclusion=RegulatoryReviewConclusion.NEEDS_REVISION,
    )

    report = ReviewPolicyUpdate().execute(_base(), draft, review)

    assert {item.code for item in report.findings} == {
        RegulatoryReviewFindingCode.POLICY_SET_FIELD_UNREVIEWED,
        RegulatoryReviewFindingCode.POLICY_SET_NEEDS_REVISION,
    }


def test_modified_rule_must_advance_its_version() -> None:
    candidate_rule = replace(_rule(), decision=DecisionOutcome.DENY)
    draft = _draft(candidate_rule)
    review_item = PolicyRuleRegulatoryReview(
        rule_id="regulated.rule",
        change_type=ControlPackChangeType.MODIFIED,
        control_objective_ids=("BR.PRIV.MINIMIZE_EXTERNAL_DATA",),
        regulatory_support_refs=("ANPD-R19-A9",),
        conclusion=RegulatoryReviewConclusion.APPROVED,
    )

    report = ReviewPolicyUpdate().execute(
        _base(),
        draft,
        _review(rule_reviews=(review_item,)),
    )

    assert {item.code for item in report.findings} == {
        RegulatoryReviewFindingCode.RULE_VERSION_UNCHANGED
    }


@pytest.mark.parametrize(
    "review",
    [
        replace(_review(), base_pack_payload_digest="sha256:other"),
        replace(_review(), candidate_policy_digest="sha256:other"),
        replace(_review(), policy_set_id="other-policy"),
    ],
)
def test_digest_and_policy_binding_mismatches_are_rejected(
    review: PolicyUpdateRegulatoryReview,
) -> None:
    with pytest.raises(PolicyUpdateRegulatoryReviewError):
        ReviewPolicyUpdate().execute(_base(), _draft(), review)


def test_review_mappings_and_rules_outside_changed_lineage_are_rejected() -> None:
    wrong_mapping = replace(
        _review(),
        rule_reviews=(
            replace(
                _review().rule_reviews[0],
                control_objective_ids=("BR.OTHER",),
            ),
        ),
    )
    unchanged_rule = replace(
        _review(),
        rule_reviews=(replace(_review().rule_reviews[0], rule_id="unchanged.rule"),),
    )

    with pytest.raises(PolicyUpdateRegulatoryReviewError, match="mappings"):
        ReviewPolicyUpdate().execute(_base(), _draft(), wrong_mapping)
    with pytest.raises(PolicyUpdateRegulatoryReviewError, match="outside"):
        ReviewPolicyUpdate().execute(_base(), _draft(), unchanged_rule)
