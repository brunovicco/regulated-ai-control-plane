from dataclasses import replace
from datetime import date

import pytest

from regulated_ai.application import (
    ProviderCapabilityUpdateReviewError,
    ReviewProviderCapabilityUpdate,
)
from regulated_ai.domain import (
    CapabilityState,
    ControlPackRelease,
    ControlPackReleaseIdentity,
    ProviderCapability,
    ProviderCapabilityDraft,
    ProviderCapabilityRecord,
    ProviderCapabilityReviewFindingCode,
    ProviderCapabilityUpdateReview,
    ProviderReviewConclusion,
    ProviderSourceReview,
    ProviderTarget,
)

SOURCE = "https://provider.invalid/documentation"
SECOND_SOURCE = "https://provider.invalid/security"
TARGET = ProviderTarget("test-provider", "test-service", "test-region")


def _record(
    *,
    registry_version: str,
    record_version: str,
    verified_at: date,
    state: CapabilityState = CapabilityState.SUPPORTED,
    sources: tuple[str, ...] = (SOURCE,),
) -> ProviderCapabilityRecord:
    fact = ProviderCapability(
        provider=TARGET.provider,
        service=TARGET.service,
        region=TARGET.region,
        key="required_control",
        state=state,
        conditions=(),
        notes=(),
        source_urls=sources,
        verified_at=verified_at,
        record_version=record_version,
        registry_version=registry_version,
    )
    return ProviderCapabilityRecord(
        target=TARGET,
        registry_version=registry_version,
        record_version=record_version,
        verified_at=verified_at,
        source_urls=sources,
        capabilities=(fact,),
    )


def _base() -> ControlPackRelease:
    return ControlPackRelease(
        identity=ControlPackReleaseIdentity("test-pack", "1.0.0", "test-key", "sha256:base"),
        policy_sets=(),
        provider_records=(
            _record(
                registry_version="registry@1",
                record_version="1",
                verified_at=date(2026, 9, 20),
            ),
        ),
    )


def _draft(
    *,
    registry_version: str = "registry@2",
    record_version: str = "2",
    verified_at: date = date(2026, 9, 26),
    state: CapabilityState = CapabilityState.CONDITIONAL,
    sources: tuple[str, ...] = (SOURCE,),
) -> ProviderCapabilityDraft:
    return ProviderCapabilityDraft(
        record=_record(
            registry_version=registry_version,
            record_version=record_version,
            verified_at=verified_at,
            state=state,
            sources=sources,
        ),
        content_digest="sha256:candidate",
    )


def _review(
    *,
    conclusion: ProviderReviewConclusion = ProviderReviewConclusion.CORROBORATED,
    source_reviews: tuple[ProviderSourceReview, ...] | None = None,
    reviewed_at: date = date(2026, 9, 26),
) -> ProviderCapabilityUpdateReview:
    reviews = source_reviews or (ProviderSourceReview(SOURCE, ("required_control",), conclusion),)
    return ProviderCapabilityUpdateReview(
        review_id="review-1",
        reviewer_role="provider-reviewer",
        reviewed_at=reviewed_at,
        base_pack_payload_digest="sha256:base",
        candidate_record_digest="sha256:candidate",
        target=TARGET,
        source_reviews=reviews,
        review_digest="sha256:review",
    )


def test_complete_corroborated_review_passes_gate() -> None:
    report = ReviewProviderCapabilityUpdate().execute(_base(), _draft(), _review())

    assert report.approved is True
    assert report.findings == ()
    assert report.required_capability_keys == ("required_control",)
    assert report.candidate_registry_version == "registry@2"
    assert report.candidate_record_version == "2"


def test_contradicted_or_inconclusive_capability_blocks_gate() -> None:
    contradicted = ReviewProviderCapabilityUpdate().execute(
        _base(),
        _draft(),
        _review(conclusion=ProviderReviewConclusion.CONTRADICTED),
    )
    inconclusive = ReviewProviderCapabilityUpdate().execute(
        _base(),
        _draft(),
        _review(conclusion=ProviderReviewConclusion.INCONCLUSIVE),
    )

    assert contradicted.findings[0].code is (
        ProviderCapabilityReviewFindingCode.CAPABILITY_CONTRADICTED
    )
    assert inconclusive.findings[0].code is (
        ProviderCapabilityReviewFindingCode.CAPABILITY_INCONCLUSIVE
    )


def test_unversioned_stale_and_incomplete_review_is_blocked() -> None:
    report = ReviewProviderCapabilityUpdate().execute(
        _base(),
        _draft(
            registry_version="registry@1",
            record_version="1",
            verified_at=date(2026, 9, 19),
            sources=(SOURCE, SECOND_SOURCE),
        ),
        _review(
            source_reviews=(
                ProviderSourceReview(
                    SOURCE, ("required_control",), ProviderReviewConclusion.CORROBORATED
                ),
            )
        ),
    )

    codes = {item.code for item in report.findings}
    assert codes == {
        ProviderCapabilityReviewFindingCode.CANDIDATE_SOURCE_UNREVIEWED,
        ProviderCapabilityReviewFindingCode.RECORD_VERSION_UNCHANGED,
        ProviderCapabilityReviewFindingCode.REGISTRY_VERSION_UNCHANGED,
        ProviderCapabilityReviewFindingCode.VERIFIED_AT_REGRESSION,
        ProviderCapabilityReviewFindingCode.VERIFIED_AT_REVIEW_MISMATCH,
    }
    source_finding = next(
        item
        for item in report.findings
        if item.code is ProviderCapabilityReviewFindingCode.CANDIDATE_SOURCE_UNREVIEWED
    )
    assert source_finding.source_digest is not None
    assert SECOND_SOURCE not in repr(report)


@pytest.mark.parametrize(
    "review",
    [
        replace(_review(), base_pack_payload_digest="sha256:other"),
        replace(_review(), candidate_record_digest="sha256:other"),
        replace(_review(), target=ProviderTarget("other", "service", None)),
    ],
)
def test_digest_and_target_binding_mismatches_are_rejected(
    review: ProviderCapabilityUpdateReview,
) -> None:
    with pytest.raises(ProviderCapabilityUpdateReviewError):
        ReviewProviderCapabilityUpdate().execute(_base(), _draft(), review)


def test_sources_and_capabilities_outside_record_lineage_are_rejected() -> None:
    unknown_source = _review(
        source_reviews=(
            ProviderSourceReview(
                "https://unbound.invalid/source",
                ("required_control",),
                ProviderReviewConclusion.CORROBORATED,
            ),
        )
    )
    unknown_capability = _review(
        source_reviews=(
            ProviderSourceReview(
                SOURCE,
                ("unknown_control",),
                ProviderReviewConclusion.CORROBORATED,
            ),
        )
    )

    with pytest.raises(ProviderCapabilityUpdateReviewError, match="source outside"):
        ReviewProviderCapabilityUpdate().execute(_base(), _draft(), unknown_source)
    with pytest.raises(ProviderCapabilityUpdateReviewError, match="capability outside"):
        ReviewProviderCapabilityUpdate().execute(_base(), _draft(), unknown_capability)
