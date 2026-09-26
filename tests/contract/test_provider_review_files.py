from pathlib import Path

import pytest

from regulated_ai.adapters import (
    ProviderReviewBoundaryError,
    load_provider_capability_draft,
    load_provider_capability_review,
)
from regulated_ai.domain import ProviderReviewConclusion


def _review_document(*, extra: str = "", source_url: str = "https://provider.invalid/docs") -> str:
    return f'''schema_version: "1"
review:
  id: "test-review"
  reviewer_role: "provider-reviewer"
  reviewed_at: "2026-09-26"
  base_pack_payload_digest: "sha256:{"a" * 64}"
  candidate_record_digest: "sha256:{"b" * 64}"
  target:
    provider: "test-provider"
    service: "test-service"
    region: "test-region"
  source_reviews:
    - source_url: "{source_url}"
      capability_keys: ["required_control"]
      conclusion: "CORROBORATED"
{extra}'''


def test_loads_example_draft_and_digest_bound_review() -> None:
    root = Path(__file__).resolve().parents[2]
    draft = load_provider_capability_draft(
        root / "examples" / "provider-capability-updates" / "openai-responses-candidate.yaml"
    )
    review = load_provider_capability_review(
        root / "examples" / "provider-capability-reviews" / "openai-responses-2026-09-26.yaml"
    )

    assert draft.content_digest == review.candidate_record_digest
    assert review.review_digest.startswith("sha256:")
    assert review.source_reviews[0].conclusion is ProviderReviewConclusion.CORROBORATED
    assert review.source_reviews[0].capability_keys == tuple(
        sorted(review.source_reviews[0].capability_keys)
    )


def test_allows_one_source_to_have_distinct_capability_conclusions(tmp_path: Path) -> None:
    document = _review_document().replace(
        '      capability_keys: ["required_control"]\n      conclusion: "CORROBORATED"',
        '      capability_keys: ["required_control"]\n'
        '      conclusion: "CORROBORATED"\n'
        '    - source_url: "https://provider.invalid/docs"\n'
        '      capability_keys: ["second_control"]\n'
        '      conclusion: "INCONCLUSIVE"',
    )
    path = tmp_path / "review.yaml"
    path.write_text(document, encoding="utf-8")

    review = load_provider_capability_review(path)

    assert [item.conclusion for item in review.source_reviews] == [
        ProviderReviewConclusion.CORROBORATED,
        ProviderReviewConclusion.INCONCLUSIVE,
    ]


@pytest.mark.parametrize(
    "document",
    [
        _review_document(source_url="http://provider.invalid/docs"),
        _review_document(extra='  source_content: "not allowed"\n'),
        _review_document().replace('id: "test-review"', 'id: "test-review"\n  id: "duplicate"'),
    ],
)
def test_rejects_non_https_content_fields_and_duplicate_keys(tmp_path: Path, document: str) -> None:
    path = tmp_path / "review.yaml"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(ProviderReviewBoundaryError, match="schema validation"):
        load_provider_capability_review(path)
