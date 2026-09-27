from dataclasses import replace
from datetime import date

import pytest

from regulated_ai.application import ReviewToolCatalogUpdate, ToolCatalogUpdateReviewError
from regulated_ai.domain import (
    AuthorizedTool,
    ControlPackChangeType,
    ControlPackRelease,
    ControlPackReleaseIdentity,
    ToolCatalogDraft,
    ToolCatalogUpdateReview,
    ToolDefinitionReview,
    ToolDefinitionReviewConclusion,
    ToolDefinitionReviewFindingCode,
)


def _tool(*, schema_version: str = "1", input_digest: str = "sha256:input") -> AuthorizedTool:
    return AuthorizedTool(
        name="cards.read",
        description="Read a synthetic card.",
        risk_class="read_only",
        schema_version=schema_version,
        input_schema_json='{"type":"object"}',
        input_schema_digest=input_digest,
        output_schema_json='{"type":"object"}',
        output_schema_digest="sha256:output",
        definition_digest=f"sha256:definition-{schema_version}-{input_digest}",
        catalog_version="catalog@2",
    )


def _base() -> ControlPackRelease:
    return ControlPackRelease(
        identity=ControlPackReleaseIdentity("pack", "1", "key", "sha256:base"),
        policy_sets=(),
        provider_records=(),
        tool_catalog_version="catalog@1",
        tools=(_tool(),),
    )


def _draft(
    *, schema_version: str = "2", input_digest: str = "sha256:new-input"
) -> ToolCatalogDraft:
    return ToolCatalogDraft(
        catalog_version="catalog@2",
        tools=(_tool(schema_version=schema_version, input_digest=input_digest),),
        content_digest="sha256:candidate",
    )


def _review(
    conclusion: ToolDefinitionReviewConclusion = ToolDefinitionReviewConclusion.APPROVED,
) -> ToolCatalogUpdateReview:
    return ToolCatalogUpdateReview(
        review_id="tool-review-1",
        reviewer_role="tool-governance-reviewer",
        reviewed_at=date(2026, 9, 27),
        base_pack_payload_digest="sha256:base",
        candidate_catalog_digest="sha256:candidate",
        tool_reviews=(
            ToolDefinitionReview(
                tool_name="cards.read",
                change_type=ControlPackChangeType.MODIFIED,
                owner_role="payments-platform-owner",
                implementation_refs=("https://engineering.invalid/tools/cards-read",),
                conclusion=conclusion,
            ),
        ),
        review_digest="sha256:review",
    )


def test_complete_owner_and_implementation_review_passes() -> None:
    report = ReviewToolCatalogUpdate().execute(_base(), _draft(), _review())

    assert report.approved is True
    assert report.required_tool_names == ("cards.read",)
    assert report.findings == ()


def test_missing_rejected_and_unversioned_schema_reviews_block() -> None:
    missing = ReviewToolCatalogUpdate().execute(
        _base(), _draft(), replace(_review(), tool_reviews=())
    )
    rejected = ReviewToolCatalogUpdate().execute(
        _base(), _draft(), _review(ToolDefinitionReviewConclusion.REJECTED)
    )
    unversioned = ReviewToolCatalogUpdate().execute(_base(), _draft(schema_version="1"), _review())

    assert missing.findings[0].code is ToolDefinitionReviewFindingCode.TOOL_REVIEW_MISSING
    assert rejected.findings[0].code is ToolDefinitionReviewFindingCode.TOOL_REJECTED
    assert unversioned.findings[0].code is (
        ToolDefinitionReviewFindingCode.TOOL_SCHEMA_VERSION_UNCHANGED
    )


def test_digest_and_lineage_mismatches_are_rejected() -> None:
    with pytest.raises(ToolCatalogUpdateReviewError, match="approved base"):
        ReviewToolCatalogUpdate().execute(
            _base(), _draft(), replace(_review(), base_pack_payload_digest="sha256:other")
        )
    with pytest.raises(ToolCatalogUpdateReviewError, match="outside"):
        ReviewToolCatalogUpdate().execute(
            _base(),
            _draft(),
            replace(
                _review(),
                tool_reviews=(replace(_review().tool_reviews[0], tool_name="unknown.tool"),),
            ),
        )
