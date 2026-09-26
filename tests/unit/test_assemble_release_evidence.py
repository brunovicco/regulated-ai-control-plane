from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from regulated_ai.application import (
    AnalyzeControlPackDiff,
    AssembleControlPackReleaseEvidence,
    ReleaseEvidenceError,
)
from regulated_ai.domain import (
    CapabilityState,
    ControlPackRelease,
    ControlPackReleaseEvidenceReport,
    ControlPackReleaseIdentity,
    ControlPackScenarioReplayReport,
    DecisionOutcome,
    PolicyMatch,
    PolicyRule,
    PolicySet,
    ProviderCapability,
    ProviderCapabilityRecord,
    ProviderTarget,
    ReleaseCandidateArtifact,
    ReleaseEvidenceFindingCode,
    ReleaseReviewArtifactKind,
    ReleaseReviewEvidence,
)


def _identity(version: str, digest: str) -> ControlPackReleaseIdentity:
    return ControlPackReleaseIdentity("test-pack", version, "test-key", digest)


def _policy(
    *,
    policy_id: str = "test-policy",
    version: str = "1.0.0",
    decision: DecisionOutcome = DecisionOutcome.ALLOW,
) -> PolicySet:
    rule = PolicyRule(
        id="test.rule",
        version=version,
        match=PolicyMatch(operation_kind="external_inference"),
        decision=decision,
        obligations=(),
        required_capabilities=(),
        control_objective_ids=("BR.PRIV.MINIMIZE_EXTERNAL_DATA",),
        regulatory_support_refs=("ANPD-R19-A9",),
    )
    return PolicySet(policy_id, version, "BR", "financial_services", "approved", (rule,))


def _provider(
    *,
    provider: str = "test-provider",
    registry_version: str = "registry@1",
    record_version: str = "1",
    state: CapabilityState = CapabilityState.SUPPORTED,
) -> ProviderCapabilityRecord:
    target = ProviderTarget(provider, "test-service", "test-region")
    capability = ProviderCapability(
        provider=provider,
        service=target.service,
        region=target.region,
        key="required-control",
        state=state,
        conditions=(),
        notes=(),
        source_urls=("https://provider.invalid/docs",),
        verified_at=date(2026, 9, 26),
        record_version=record_version,
        registry_version=registry_version,
    )
    return ProviderCapabilityRecord(
        target,
        registry_version,
        record_version,
        date(2026, 9, 26),
        ("https://provider.invalid/docs",),
        (capability,),
    )


def _release(
    identity: ControlPackReleaseIdentity,
    *,
    policy: PolicySet | None = None,
    provider: ProviderCapabilityRecord | None = None,
) -> ControlPackRelease:
    return ControlPackRelease(identity, (policy or _policy(),), (provider or _provider(),))


def _replay(
    base: ControlPackReleaseIdentity,
    candidate: ControlPackReleaseIdentity,
) -> ControlPackScenarioReplayReport:
    return ControlPackScenarioReplayReport(
        base=base,
        candidate=candidate,
        suite_id="test-suite",
        suite_version="1",
        suite_digest="sha256:suite",
        evaluated_at=datetime(2026, 9, 26, tzinfo=UTC),
        results=(),
    )


def _artifacts(
    policy_id: str = "test-policy",
    provider_id: str = "test-provider.test-service.test-region",
) -> tuple[ReleaseCandidateArtifact, ...]:
    return (
        ReleaseCandidateArtifact(
            ReleaseReviewArtifactKind.POLICY_SET,
            policy_id,
            "sha256:policy",
        ),
        ReleaseCandidateArtifact(
            ReleaseReviewArtifactKind.PROVIDER_TARGET,
            provider_id,
            "sha256:provider",
        ),
    )


def _review(
    kind: ReleaseReviewArtifactKind,
    *,
    approved: bool = True,
    candidate_digest: str | None = None,
) -> ReleaseReviewEvidence:
    subject_id = (
        "test-policy"
        if kind is ReleaseReviewArtifactKind.POLICY_SET
        else "test-provider.test-service.test-region"
    )
    digest = candidate_digest or (
        "sha256:policy" if kind is ReleaseReviewArtifactKind.POLICY_SET else "sha256:provider"
    )
    return ReleaseReviewEvidence(
        kind=kind,
        subject_id=subject_id,
        base_pack_payload_digest="sha256:base",
        candidate_content_digest=digest,
        review_id=f"review-{kind.value.lower()}",
        review_digest=f"sha256:review-{kind.value.lower()}",
        approved=approved,
    )


def _execute(
    base: ControlPackRelease,
    candidate: ControlPackRelease,
    *,
    artifacts: tuple[ReleaseCandidateArtifact, ...] | None = None,
    reviews: tuple[ReleaseReviewEvidence, ...] = (),
) -> ControlPackReleaseEvidenceReport:
    return AssembleControlPackReleaseEvidence().execute(
        base,
        candidate,
        AnalyzeControlPackDiff().execute(base, candidate),
        _replay(base.identity, candidate.identity),
        artifacts or _artifacts(),
        reviews,
    )


def test_unchanged_verified_releases_need_no_human_review() -> None:
    base = _release(_identity("1", "sha256:base"))
    candidate = replace(base, identity=_identity("2", "sha256:candidate"))

    report = _execute(base, candidate)

    assert report.complete is True
    assert report.review_evidence == ()
    assert report.findings == ()


def test_changed_policy_and_provider_require_review_evidence() -> None:
    base = _release(_identity("1", "sha256:base"))
    candidate = _release(
        _identity("2", "sha256:candidate"),
        policy=_policy(version="2.0.0", decision=DecisionOutcome.DENY),
        provider=_provider(
            registry_version="registry@2",
            record_version="2",
            state=CapabilityState.CONDITIONAL,
        ),
    )

    report = _execute(base, candidate)

    assert report.complete is False
    assert {item.code for item in report.findings} == {
        ReleaseEvidenceFindingCode.POLICY_REVIEW_MISSING,
        ReleaseEvidenceFindingCode.PROVIDER_REVIEW_MISSING,
    }


def test_passing_exact_reviews_complete_changed_release_evidence() -> None:
    base = _release(_identity("1", "sha256:base"))
    candidate = _release(
        _identity("2", "sha256:candidate"),
        policy=_policy(version="2.0.0"),
        provider=_provider(registry_version="registry@2", record_version="2"),
    )
    reviews = (
        _review(ReleaseReviewArtifactKind.POLICY_SET),
        _review(ReleaseReviewArtifactKind.PROVIDER_TARGET),
    )

    report = _execute(base, candidate, reviews=reviews)

    assert report.complete is True
    assert report.findings == ()
    assert report.review_evidence == reviews


def test_blocked_reviews_remain_visible_and_incomplete() -> None:
    base = _release(_identity("1", "sha256:base"))
    candidate = _release(
        _identity("2", "sha256:candidate"),
        policy=_policy(version="2.0.0"),
        provider=_provider(registry_version="registry@2", record_version="2"),
    )
    reviews = (
        _review(ReleaseReviewArtifactKind.POLICY_SET, approved=False),
        _review(ReleaseReviewArtifactKind.PROVIDER_TARGET, approved=False),
    )

    report = _execute(base, candidate, reviews=reviews)

    assert {item.code for item in report.findings} == {
        ReleaseEvidenceFindingCode.POLICY_REVIEW_BLOCKED,
        ReleaseEvidenceFindingCode.PROVIDER_REVIEW_BLOCKED,
    }


def test_added_and_removed_entities_are_explicitly_unsupported() -> None:
    base = _release(_identity("1", "sha256:base"))
    candidate = _release(
        _identity("2", "sha256:candidate"),
        policy=_policy(policy_id="new-policy"),
        provider=_provider(provider="new-provider"),
    )

    report = _execute(
        base,
        candidate,
        artifacts=_artifacts(
            policy_id="new-policy",
            provider_id="new-provider.test-service.test-region",
        ),
    )

    assert {item.code for item in report.findings} == {
        ReleaseEvidenceFindingCode.POLICY_SET_ADDITION_UNSUPPORTED,
        ReleaseEvidenceFindingCode.POLICY_SET_REMOVAL_UNSUPPORTED,
        ReleaseEvidenceFindingCode.PROVIDER_TARGET_ADDITION_UNSUPPORTED,
        ReleaseEvidenceFindingCode.PROVIDER_TARGET_REMOVAL_UNSUPPORTED,
    }


def test_mismatched_artifacts_and_reviews_are_rejected() -> None:
    base = _release(_identity("1", "sha256:base"))
    candidate = _release(
        _identity("2", "sha256:candidate"),
        policy=_policy(version="2.0.0"),
    )

    with pytest.raises(ReleaseEvidenceError, match="artifact digests"):
        _execute(base, candidate, artifacts=(_artifacts()[0],))
    with pytest.raises(ReleaseEvidenceError, match="candidate content"):
        _execute(
            base,
            candidate,
            reviews=(
                _review(
                    ReleaseReviewArtifactKind.POLICY_SET,
                    candidate_digest="sha256:other",
                ),
            ),
        )
    with pytest.raises(ReleaseEvidenceError, match="approved base"):
        _execute(
            base,
            candidate,
            reviews=(
                replace(
                    _review(ReleaseReviewArtifactKind.POLICY_SET),
                    base_pack_payload_digest="sha256:other",
                ),
            ),
        )


def test_analysis_and_review_lineage_mismatches_are_rejected() -> None:
    base = _release(_identity("1", "sha256:base"))
    candidate = _release(_identity("2", "sha256:candidate"), policy=_policy(version="2.0.0"))
    analysis = AnalyzeControlPackDiff().execute(base, candidate)
    assembler = AssembleControlPackReleaseEvidence()

    with pytest.raises(ReleaseEvidenceError, match="Static analysis"):
        assembler.execute(
            base,
            candidate,
            replace(analysis, candidate=base.identity),
            _replay(base.identity, candidate.identity),
            _artifacts(),
            (),
        )
    with pytest.raises(ReleaseEvidenceError, match="Scenario replay"):
        assembler.execute(
            base,
            candidate,
            analysis,
            _replay(base.identity, base.identity),
            _artifacts(),
            (),
        )
    with pytest.raises(ReleaseEvidenceError, match="changed release lineage"):
        _execute(
            base,
            replace(candidate, policy_sets=base.policy_sets),
            reviews=(_review(ReleaseReviewArtifactKind.POLICY_SET),),
        )


def test_duplicate_candidate_and_review_evidence_are_rejected() -> None:
    base = _release(_identity("1", "sha256:base"))
    candidate = _release(_identity("2", "sha256:candidate"), policy=_policy(version="2.0.0"))
    artifacts = _artifacts()
    review = _review(ReleaseReviewArtifactKind.POLICY_SET)

    with pytest.raises(ReleaseEvidenceError, match="Duplicate candidate artifact"):
        _execute(base, candidate, artifacts=(*artifacts, artifacts[0]))
    with pytest.raises(ReleaseEvidenceError, match="Duplicate review evidence"):
        _execute(base, candidate, reviews=(review, review))
