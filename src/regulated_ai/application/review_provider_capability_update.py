"""Offline pre-signing review gate for provider capability record drafts."""

import hashlib

from regulated_ai.domain import (
    ControlPackRelease,
    ProviderCapabilityDraft,
    ProviderCapabilityReviewFinding,
    ProviderCapabilityReviewFindingCode,
    ProviderCapabilityUpdateReport,
    ProviderCapabilityUpdateReview,
    ProviderReviewConclusion,
)


class ProviderCapabilityUpdateReviewError(ValueError):
    """A provider review cannot be bound to the approved record lineage."""

    code = "PROVIDER_CAPABILITY_UPDATE_REVIEW_INVALID"


class ReviewProviderCapabilityUpdate:
    """Check bounded review coverage without retrieving sources or signing releases."""

    def execute(
        self,
        base: ControlPackRelease,
        draft: ProviderCapabilityDraft,
        review: ProviderCapabilityUpdateReview,
    ) -> ProviderCapabilityUpdateReport:
        """Return a deterministic pass/block report for one existing provider target."""
        candidate = draft.record
        if review.base_pack_payload_digest != base.identity.payload_digest:
            raise ProviderCapabilityUpdateReviewError("Review does not bind the approved base pack")
        if review.candidate_record_digest != draft.content_digest:
            raise ProviderCapabilityUpdateReviewError("Review does not bind the candidate record")
        if review.target != candidate.target:
            raise ProviderCapabilityUpdateReviewError(
                "Review target does not match candidate target"
            )

        matches = tuple(item for item in base.provider_records if item.target == candidate.target)
        if len(matches) != 1:
            raise ProviderCapabilityUpdateReviewError(
                "Approved base must contain exactly one matching provider target"
            )
        approved = matches[0]
        required_keys = tuple(
            sorted(
                {item.key for item in approved.capabilities}
                | {item.key for item in candidate.capabilities}
            )
        )
        if not required_keys:
            raise ProviderCapabilityUpdateReviewError("Provider record lineage has no capabilities")

        allowed_sources = set(approved.source_urls) | set(candidate.source_urls)
        reviewed_sources = {item.source_url for item in review.source_reviews}
        reviewed_keys = {
            key for source_review in review.source_reviews for key in source_review.capability_keys
        }
        if not reviewed_sources.issubset(allowed_sources):
            raise ProviderCapabilityUpdateReviewError(
                "Review contains a source outside the provider record lineage"
            )
        if not reviewed_keys.issubset(required_keys):
            raise ProviderCapabilityUpdateReviewError(
                "Review contains a capability outside the provider record lineage"
            )

        findings: list[ProviderCapabilityReviewFinding] = []
        if candidate.registry_version == approved.registry_version:
            findings.append(
                _finding(ProviderCapabilityReviewFindingCode.REGISTRY_VERSION_UNCHANGED)
            )
        if candidate.record_version == approved.record_version:
            findings.append(_finding(ProviderCapabilityReviewFindingCode.RECORD_VERSION_UNCHANGED))
        if candidate.verified_at < approved.verified_at:
            findings.append(_finding(ProviderCapabilityReviewFindingCode.VERIFIED_AT_REGRESSION))
        if candidate.verified_at != review.reviewed_at:
            findings.append(
                _finding(ProviderCapabilityReviewFindingCode.VERIFIED_AT_REVIEW_MISMATCH)
            )

        for source_url in sorted(set(candidate.source_urls) - reviewed_sources):
            findings.append(
                _finding(
                    ProviderCapabilityReviewFindingCode.CANDIDATE_SOURCE_UNREVIEWED,
                    source_digest=_digest_text(source_url),
                )
            )

        for key in required_keys:
            conclusions = tuple(
                item.conclusion for item in review.source_reviews if key in item.capability_keys
            )
            if not conclusions:
                findings.append(
                    _finding(
                        ProviderCapabilityReviewFindingCode.CAPABILITY_UNREVIEWED,
                        capability_key=key,
                    )
                )
            elif ProviderReviewConclusion.CONTRADICTED in conclusions:
                findings.append(
                    _finding(
                        ProviderCapabilityReviewFindingCode.CAPABILITY_CONTRADICTED,
                        capability_key=key,
                    )
                )
            elif ProviderReviewConclusion.INCONCLUSIVE in conclusions:
                findings.append(
                    _finding(
                        ProviderCapabilityReviewFindingCode.CAPABILITY_INCONCLUSIVE,
                        capability_key=key,
                    )
                )
            elif ProviderReviewConclusion.CORROBORATED not in conclusions:
                findings.append(
                    _finding(
                        ProviderCapabilityReviewFindingCode.CAPABILITY_UNREVIEWED,
                        capability_key=key,
                    )
                )

        ordered = tuple(
            sorted(
                findings,
                key=lambda item: (
                    item.code.value,
                    item.capability_key or "",
                    item.source_digest or "",
                ),
            )
        )
        return ProviderCapabilityUpdateReport(
            base=base.identity,
            target=candidate.target,
            candidate_registry_version=candidate.registry_version,
            candidate_record_version=candidate.record_version,
            candidate_record_digest=draft.content_digest,
            review_id=review.review_id,
            reviewer_role=review.reviewer_role,
            reviewed_at=review.reviewed_at,
            review_digest=review.review_digest,
            required_capability_keys=required_keys,
            findings=ordered,
        )


def _finding(
    code: ProviderCapabilityReviewFindingCode,
    *,
    capability_key: str | None = None,
    source_digest: str | None = None,
) -> ProviderCapabilityReviewFinding:
    return ProviderCapabilityReviewFinding(
        code=code,
        capability_key=capability_key,
        source_digest=source_digest,
    )


def _digest_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"
