from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from regulated_ai.application import (
    AnalyzeControlPackDiff,
    AssembleControlPackReleaseEvidence,
    ReleaseEvidenceError,
)
from regulated_ai.domain import (
    AuthorizedTool,
    CapabilityState,
    ControlPackChangeType,
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


def _tool(*, risk_class: str = "read_only") -> AuthorizedTool:
    return AuthorizedTool(
        "cards.read",
        "Read synthetic status.",
        risk_class,
        "1",
        "{}",
        "sha256:input",
        "{}",
        "sha256:output",
        f"sha256:{risk_class}",
        "tools@1",
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
    tool: AuthorizedTool | None = None,
) -> ControlPackRelease:
    return ControlPackRelease(
        identity,
        (policy or _policy(),),
        (provider or _provider(),),
        "tools@1" if tool is not None else None,
        () if tool is None else (tool,),
    )


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
    include_tools: bool = False,
) -> tuple[ReleaseCandidateArtifact, ...]:
    artifacts = (
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
    if include_tools:
        return (
            *artifacts,
            ReleaseCandidateArtifact(
                ReleaseReviewArtifactKind.TOOL_CATALOG,
                "trusted-tool-catalog",
                "sha256:tools",
            ),
        )
    return artifacts


def _review(
    kind: ReleaseReviewArtifactKind,
    *,
    approved: bool = True,
    reviewed_digest: str | None = None,
    subject_id: str | None = None,
    change_type: ControlPackChangeType = ControlPackChangeType.MODIFIED,
) -> ReleaseReviewEvidence:
    default_subjects = {
        ReleaseReviewArtifactKind.POLICY_SET: "test-policy",
        ReleaseReviewArtifactKind.PROVIDER_TARGET: "test-provider.test-service.test-region",
        ReleaseReviewArtifactKind.TOOL_CATALOG: "trusted-tool-catalog",
    }
    default_digests = {
        ReleaseReviewArtifactKind.POLICY_SET: "sha256:policy",
        ReleaseReviewArtifactKind.PROVIDER_TARGET: "sha256:provider",
        ReleaseReviewArtifactKind.TOOL_CATALOG: "sha256:tools",
    }
    resolved_subject_id = subject_id or default_subjects[kind]
    digest = reviewed_digest or default_digests[kind]
    return ReleaseReviewEvidence(
        kind=kind,
        subject_id=resolved_subject_id,
        change_type=change_type,
        base_pack_payload_digest="sha256:base",
        candidate_pack_payload_digest="sha256:candidate",
        reviewed_content_digest=digest,
        review_id=f"review-{kind.value.lower()}",
        review_digest=f"sha256:review-{kind.value.lower()}",
        reviewer_role="test-reviewer",
        attested_at=datetime(2026, 9, 26, tzinfo=UTC),
        attestation_id=(
            f"attestation-{kind.value.lower()}-{change_type.value.lower()}-{resolved_subject_id}"
        ),
        signing_key_id="review-key",
        attestation_digest=f"sha256:attestation-{kind.value.lower()}",
        signature_digest=f"sha256:signature-{kind.value.lower()}",
        approved=approved,
    )


def _execute(
    base: ControlPackRelease,
    candidate: ControlPackRelease,
    *,
    artifacts: tuple[ReleaseCandidateArtifact, ...] | None = None,
    base_artifacts: tuple[ReleaseCandidateArtifact, ...] | None = None,
    reviews: tuple[ReleaseReviewEvidence, ...] = (),
) -> ControlPackReleaseEvidenceReport:
    return AssembleControlPackReleaseEvidence().execute(
        base,
        candidate,
        AnalyzeControlPackDiff().execute(base, candidate),
        _replay(base.identity, candidate.identity),
        artifacts or _artifacts(),
        reviews,
        base_artifacts or _artifacts(),
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


def test_changed_tool_catalog_requires_exact_authenticated_review() -> None:
    base = _release(_identity("1", "sha256:base"), tool=_tool())
    candidate = _release(
        _identity("2", "sha256:candidate"),
        tool=_tool(risk_class="high_impact_state_change"),
    )
    artifacts = _artifacts(include_tools=True)

    incomplete = _execute(
        base,
        candidate,
        artifacts=artifacts,
        base_artifacts=artifacts,
    )
    complete = _execute(
        base,
        candidate,
        artifacts=artifacts,
        base_artifacts=artifacts,
        reviews=(_review(ReleaseReviewArtifactKind.TOOL_CATALOG),),
    )

    assert incomplete.findings[0].code is ReleaseEvidenceFindingCode.TOOL_CATALOG_REVIEW_MISSING
    assert complete.complete is True


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


def test_added_and_removed_entities_require_lifecycle_review() -> None:
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
        ReleaseEvidenceFindingCode.POLICY_LIFECYCLE_REVIEW_MISSING,
        ReleaseEvidenceFindingCode.PROVIDER_LIFECYCLE_REVIEW_MISSING,
    }


def test_authenticated_lifecycle_reviews_cover_additions_and_removals() -> None:
    base = _release(_identity("1", "sha256:base"))
    candidate = _release(
        _identity("2", "sha256:candidate"),
        policy=_policy(policy_id="new-policy"),
        provider=_provider(provider="new-provider"),
    )
    candidate_artifacts = _artifacts(
        policy_id="new-policy",
        provider_id="new-provider.test-service.test-region",
    )
    reviews = (
        _review(
            ReleaseReviewArtifactKind.POLICY_SET,
            subject_id="new-policy",
            change_type=ControlPackChangeType.ADDED,
        ),
        _review(
            ReleaseReviewArtifactKind.PROVIDER_TARGET,
            subject_id="new-provider.test-service.test-region",
            change_type=ControlPackChangeType.ADDED,
        ),
        _review(
            ReleaseReviewArtifactKind.POLICY_SET,
            subject_id="test-policy",
            change_type=ControlPackChangeType.REMOVED,
        ),
        _review(
            ReleaseReviewArtifactKind.PROVIDER_TARGET,
            subject_id="test-provider.test-service.test-region",
            change_type=ControlPackChangeType.REMOVED,
        ),
    )

    report = _execute(base, candidate, artifacts=candidate_artifacts, reviews=reviews)

    assert report.complete is True
    assert report.findings == ()


def test_mismatched_artifacts_and_reviews_are_rejected() -> None:
    base = _release(_identity("1", "sha256:base"))
    candidate = _release(
        _identity("2", "sha256:candidate"),
        policy=_policy(version="2.0.0"),
    )

    with pytest.raises(ReleaseEvidenceError, match="artifact digests"):
        _execute(base, candidate, artifacts=(_artifacts()[0],))
    with pytest.raises(ReleaseEvidenceError, match="reviewed content"):
        _execute(
            base,
            candidate,
            reviews=(
                _review(
                    ReleaseReviewArtifactKind.POLICY_SET,
                    reviewed_digest="sha256:other",
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
            _artifacts(),
        )
    with pytest.raises(ReleaseEvidenceError, match="Scenario replay"):
        assembler.execute(
            base,
            candidate,
            analysis,
            _replay(base.identity, base.identity),
            _artifacts(),
            (),
            _artifacts(),
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
