"""Offline pre-signing regulatory review gate for policy-set drafts."""

from collections.abc import Iterable

from regulated_ai.domain import (
    ControlPackChangeType,
    ControlPackRelease,
    PolicyDraft,
    PolicyRule,
    PolicyRuleRegulatoryReview,
    PolicyUpdateRegulatoryReview,
    PolicyUpdateRegulatoryReviewReport,
    RegulatoryReviewConclusion,
    RegulatoryReviewFinding,
    RegulatoryReviewFindingCode,
)


class PolicyUpdateRegulatoryReviewError(ValueError):
    """A regulatory review cannot be bound to the approved policy lineage."""

    code = "POLICY_UPDATE_REGULATORY_REVIEW_INVALID"


class ReviewPolicyUpdate:
    """Check bounded human review coverage without retrieving regulatory text."""

    def execute(
        self,
        base: ControlPackRelease,
        draft: PolicyDraft,
        review: PolicyUpdateRegulatoryReview,
    ) -> PolicyUpdateRegulatoryReviewReport:
        """Return a deterministic pass/block report for one existing policy set."""
        candidate = draft.policy_set
        if review.base_pack_payload_digest != base.identity.payload_digest:
            raise PolicyUpdateRegulatoryReviewError("Review does not bind the approved base pack")
        if review.candidate_policy_digest != draft.content_digest:
            raise PolicyUpdateRegulatoryReviewError("Review does not bind the candidate policy")
        if review.policy_set_id != candidate.id:
            raise PolicyUpdateRegulatoryReviewError(
                "Review policy-set identifier does not match the candidate"
            )

        matches = tuple(item for item in base.policy_sets if item.id == candidate.id)
        if len(matches) != 1:
            raise PolicyUpdateRegulatoryReviewError(
                "Approved base must contain exactly one matching policy set"
            )
        approved = matches[0]
        base_rules = _rule_index(approved.rules, "approved base")
        candidate_rules = _rule_index(candidate.rules, "candidate")
        changes = _rule_changes(base_rules, candidate_rules)
        required_rule_ids = tuple(sorted(changes))

        expected_fields = tuple(
            field
            for field in ("version", "jurisdiction", "sector", "status")
            if getattr(approved, field) != getattr(candidate, field)
        )
        reviewed_fields = set(review.reviewed_policy_set_fields)
        if not reviewed_fields.issubset(expected_fields):
            raise PolicyUpdateRegulatoryReviewError("Review contains an unchanged policy-set field")

        reviews = {item.rule_id: item for item in review.rule_reviews}
        if not set(reviews).issubset(changes):
            raise PolicyUpdateRegulatoryReviewError(
                "Review contains a rule outside the changed policy lineage"
            )
        for rule_id, item in reviews.items():
            change_type, rule = changes[rule_id]
            if item.change_type is not change_type:
                raise PolicyUpdateRegulatoryReviewError(
                    "Review rule change type does not match the policy lineage"
                )
            if item.control_objective_ids != tuple(
                sorted(rule.control_objective_ids)
            ) or item.regulatory_support_refs != tuple(sorted(rule.regulatory_support_refs)):
                raise PolicyUpdateRegulatoryReviewError(
                    "Review rule mappings do not match the policy lineage"
                )

        findings: list[RegulatoryReviewFinding] = []
        if candidate.version == approved.version:
            findings.append(_finding(RegulatoryReviewFindingCode.POLICY_SET_VERSION_UNCHANGED))
        for field in sorted(set(expected_fields) - reviewed_fields):
            findings.append(
                _finding(
                    RegulatoryReviewFindingCode.POLICY_SET_FIELD_UNREVIEWED,
                    policy_set_field=field,
                )
            )
        findings.extend(_policy_set_conclusion_findings(review))

        for rule_id in required_rule_ids:
            change_type, rule = changes[rule_id]
            review_item = reviews.get(rule_id)
            if review_item is None:
                findings.append(
                    _finding(
                        RegulatoryReviewFindingCode.RULE_REVIEW_MISSING,
                        rule_id=rule_id,
                    )
                )
                continue
            if (
                change_type is ControlPackChangeType.MODIFIED
                and candidate_rules[rule_id].version == base_rules[rule_id].version
            ):
                findings.append(
                    _finding(
                        RegulatoryReviewFindingCode.RULE_VERSION_UNCHANGED,
                        rule_id=rule_id,
                    )
                )
            if change_type is not ControlPackChangeType.REMOVED and not rule.control_objective_ids:
                findings.append(
                    _finding(
                        RegulatoryReviewFindingCode.CONTROL_OBJECTIVE_MISSING,
                        rule_id=rule_id,
                    )
                )
            findings.extend(_rule_conclusion_findings(review_item))

        ordered = tuple(
            sorted(
                findings,
                key=lambda item: (
                    item.code.value,
                    item.rule_id or "",
                    item.policy_set_field or "",
                ),
            )
        )
        return PolicyUpdateRegulatoryReviewReport(
            base=base.identity,
            policy_set_id=candidate.id,
            candidate_policy_version=candidate.version,
            candidate_policy_digest=draft.content_digest,
            review_id=review.review_id,
            reviewer_role=review.reviewer_role,
            reviewed_at=review.reviewed_at,
            review_digest=review.review_digest,
            required_policy_set_fields=expected_fields,
            required_rule_ids=required_rule_ids,
            findings=ordered,
        )


def _rule_index(items: Iterable[PolicyRule], label: str) -> dict[str, PolicyRule]:
    indexed: dict[str, PolicyRule] = {}
    for item in items:
        if item.id in indexed:
            raise PolicyUpdateRegulatoryReviewError(f"Duplicate rule id in {label}")
        indexed[item.id] = item
    return indexed


def _rule_changes(
    base: dict[str, PolicyRule], candidate: dict[str, PolicyRule]
) -> dict[str, tuple[ControlPackChangeType, PolicyRule]]:
    changes: dict[str, tuple[ControlPackChangeType, PolicyRule]] = {}
    for rule_id in base.keys() - candidate.keys():
        changes[rule_id] = (ControlPackChangeType.REMOVED, base[rule_id])
    for rule_id in candidate.keys() - base.keys():
        changes[rule_id] = (ControlPackChangeType.ADDED, candidate[rule_id])
    for rule_id in base.keys() & candidate.keys():
        if base[rule_id] != candidate[rule_id]:
            changes[rule_id] = (ControlPackChangeType.MODIFIED, candidate[rule_id])
    return changes


def _policy_set_conclusion_findings(
    review: PolicyUpdateRegulatoryReview,
) -> tuple[RegulatoryReviewFinding, ...]:
    if not review.reviewed_policy_set_fields:
        return ()
    codes = {
        RegulatoryReviewConclusion.REJECTED: RegulatoryReviewFindingCode.POLICY_SET_REJECTED,
        RegulatoryReviewConclusion.NEEDS_REVISION: (
            RegulatoryReviewFindingCode.POLICY_SET_NEEDS_REVISION
        ),
        RegulatoryReviewConclusion.NOT_APPLICABLE: (
            RegulatoryReviewFindingCode.POLICY_SET_NOT_APPLICABLE
        ),
    }
    code = codes.get(review.policy_set_conclusion)
    return () if code is None else (_finding(code),)


def _rule_conclusion_findings(
    review: PolicyRuleRegulatoryReview,
) -> tuple[RegulatoryReviewFinding, ...]:
    if not review.regulatory_support_refs:
        if review.conclusion is RegulatoryReviewConclusion.NOT_APPLICABLE:
            return ()
        return (
            _finding(
                RegulatoryReviewFindingCode.ENTERPRISE_RULE_CONCLUSION_INVALID,
                rule_id=review.rule_id,
            ),
        )
    codes = {
        RegulatoryReviewConclusion.REJECTED: RegulatoryReviewFindingCode.RULE_REJECTED,
        RegulatoryReviewConclusion.NEEDS_REVISION: (
            RegulatoryReviewFindingCode.RULE_NEEDS_REVISION
        ),
        RegulatoryReviewConclusion.NOT_APPLICABLE: (
            RegulatoryReviewFindingCode.REGULATORY_MAPPING_NOT_APPLICABLE
        ),
    }
    code = codes.get(review.conclusion)
    return () if code is None else (_finding(code, rule_id=review.rule_id),)


def _finding(
    code: RegulatoryReviewFindingCode,
    *,
    rule_id: str | None = None,
    policy_set_field: str | None = None,
) -> RegulatoryReviewFinding:
    return RegulatoryReviewFinding(
        code=code,
        rule_id=rule_id,
        policy_set_field=policy_set_field,
    )
