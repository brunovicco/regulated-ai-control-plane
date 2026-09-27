from pathlib import Path

import pytest

from regulated_ai.adapters import ToolReviewBoundaryError, load_tool_catalog_review
from regulated_ai.domain import ToolDefinitionReviewConclusion


def _document(*, implementation_ref: str = "https://engineering.invalid/tools/cards-read") -> str:
    return f'''schema_version: "1"
review:
  id: "tool-review-1"
  reviewer_role: "tool-governance-reviewer"
  reviewed_at: "2026-09-27"
  base_pack_payload_digest: "sha256:{"a" * 64}"
  candidate_catalog_digest: "sha256:{"b" * 64}"
  tool_reviews:
    - tool_name: "cards.read"
      change_type: "MODIFIED"
      owner_role: "payments-platform-owner"
      implementation_refs: ["{implementation_ref}"]
      conclusion: "APPROVED"
'''


def test_loads_digest_bound_metadata_only_tool_review(tmp_path: Path) -> None:
    path = tmp_path / "review.yaml"
    path.write_text(_document(), encoding="utf-8")

    review = load_tool_catalog_review(path)

    assert review.review_digest.startswith("sha256:")
    assert review.tool_reviews[0].owner_role == "payments-platform-owner"
    assert review.tool_reviews[0].conclusion is ToolDefinitionReviewConclusion.APPROVED


@pytest.mark.parametrize(
    "document",
    [
        _document(implementation_ref="http://engineering.invalid/tools/cards-read"),
        _document().replace(
            '      conclusion: "APPROVED"',
            '      source_content: "secret"\n      conclusion: "APPROVED"',
        ),
        _document().replace('  id: "tool-review-1"', '  id: "tool-review-1"\n  id: "duplicate"'),
    ],
)
def test_rejects_non_https_content_fields_and_duplicate_keys(tmp_path: Path, document: str) -> None:
    path = tmp_path / "review.yaml"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(ToolReviewBoundaryError, match="schema validation"):
        load_tool_catalog_review(path)
