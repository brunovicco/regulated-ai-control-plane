from pathlib import Path

import pytest

from regulated_ai.adapters import (
    PolicyReviewBoundaryError,
    load_policy_draft,
    load_policy_regulatory_review,
)
from regulated_ai.domain import RegulatoryReviewConclusion


def _review_document(*, extra: str = "", conclusion: str = "APPROVED") -> str:
    return f'''schema_version: "1"
review:
  id: "test-review"
  reviewer_role: "regulatory-governance"
  reviewed_at: "2026-09-26"
  base_pack_payload_digest: "sha256:{"a" * 64}"
  candidate_policy_digest: "sha256:{"b" * 64}"
  policy_set_id: "test-policy"
  policy_set_review:
    changed_fields: ["version"]
    conclusion: "APPROVED"
  rule_reviews:
    - rule_id: "regulated.rule"
      change_type: "MODIFIED"
      control_objective_ids: ["BR.PRIV.MINIMIZE_EXTERNAL_DATA"]
      regulatory_support_refs: ["ANPD-R19-A9"]
      conclusion: "{conclusion}"
{extra}'''


def test_loads_example_draft_and_digest_bound_review() -> None:
    root = Path(__file__).resolve().parents[2]
    draft = load_policy_draft(
        root / "examples" / "policy-updates" / "br-financial-external-inference-candidate.yaml"
    )
    review = load_policy_regulatory_review(
        root / "examples" / "regulatory-reviews" / "br-financial-external-inference-2026-09-26.yaml"
    )

    assert draft.content_digest == review.candidate_policy_digest
    assert review.review_digest.startswith("sha256:")
    assert review.rule_reviews[0].conclusion is RegulatoryReviewConclusion.APPROVED
    assert review.rule_reviews[0].control_objective_ids == tuple(
        sorted(review.rule_reviews[0].control_objective_ids)
    )


@pytest.mark.parametrize(
    "document",
    [
        _review_document(extra='  source_content: "not allowed"\n'),
        _review_document().replace('id: "test-review"', 'id: "test-review"\n  id: "duplicate"'),
        _review_document().replace(
            'rule_reviews:\n    - rule_id: "regulated.rule"',
            'rule_reviews:\n    - rule_id: "regulated.rule"\n      unexpected: "field"',
        ),
    ],
)
def test_rejects_content_fields_unknown_fields_and_duplicate_keys(
    tmp_path: Path, document: str
) -> None:
    path = tmp_path / "review.yaml"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(PolicyReviewBoundaryError, match="schema validation"):
        load_policy_regulatory_review(path)
