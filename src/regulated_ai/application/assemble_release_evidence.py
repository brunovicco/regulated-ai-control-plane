"""Compose verified release analysis and review evidence without promotion authority."""

from collections.abc import Callable, Iterable

from regulated_ai.domain import (
    ControlPackDiffReport,
    ControlPackRelease,
    ControlPackReleaseEvidenceReport,
    ControlPackScenarioReplayReport,
    PolicySet,
    ProviderCapabilityRecord,
    ReleaseCandidateArtifact,
    ReleaseEvidenceFinding,
    ReleaseEvidenceFindingCode,
    ReleaseReviewArtifactKind,
    ReleaseReviewEvidence,
)


class ReleaseEvidenceError(ValueError):
    """Release evidence cannot be composed safely from the supplied lineage."""

    code = "CONTROL_PACK_RELEASE_EVIDENCE_INVALID"


class AssembleControlPackReleaseEvidence:
    """Bind static, replay and human-review evidence for one release pair."""

    def execute(
        self,
        base: ControlPackRelease,
        candidate: ControlPackRelease,
        static_analysis: ControlPackDiffReport,
        scenario_replay: ControlPackScenarioReplayReport,
        candidate_artifacts: tuple[ReleaseCandidateArtifact, ...],
        review_evidence: tuple[ReleaseReviewEvidence, ...],
    ) -> ControlPackReleaseEvidenceReport:
        """Return deterministic evidence completeness without approving promotion."""
        if static_analysis.base != base.identity or static_analysis.candidate != candidate.identity:
            raise ReleaseEvidenceError("Static analysis does not bind the release pair")
        if scenario_replay.base != base.identity or scenario_replay.candidate != candidate.identity:
            raise ReleaseEvidenceError("Scenario replay does not bind the release pair")

        base_policies = _unique_index(base.policy_sets, lambda item: item.id, "base policy set")
        candidate_policies = _unique_index(
            candidate.policy_sets, lambda item: item.id, "candidate policy set"
        )
        base_providers = _unique_index(
            base.provider_records,
            lambda item: item.target.identifier,
            "base provider target",
        )
        candidate_providers = _unique_index(
            candidate.provider_records,
            lambda item: item.target.identifier,
            "candidate provider target",
        )

        expected_artifacts = {
            *(
                (ReleaseReviewArtifactKind.POLICY_SET, identifier)
                for identifier in candidate_policies
            ),
            *(
                (ReleaseReviewArtifactKind.PROVIDER_TARGET, identifier)
                for identifier in candidate_providers
            ),
        }
        artifacts = _evidence_index(
            candidate_artifacts,
            lambda item: (item.kind, item.subject_id),
            "candidate artifact",
        )
        if set(artifacts) != expected_artifacts:
            raise ReleaseEvidenceError(
                "Candidate artifact digests do not match the verified release composition"
            )

        reviews = _evidence_index(
            review_evidence,
            lambda item: (item.kind, item.subject_id),
            "review evidence",
        )
        for key, review in reviews.items():
            artifact = artifacts.get(key)
            if artifact is None:
                raise ReleaseEvidenceError("Review evidence is outside the candidate release")
            if review.base_pack_payload_digest != base.identity.payload_digest:
                raise ReleaseEvidenceError("Review evidence does not bind the approved base")
            if review.candidate_content_digest != artifact.content_digest:
                raise ReleaseEvidenceError("Review evidence does not bind candidate content")

        findings: list[ReleaseEvidenceFinding] = []
        required: set[tuple[ReleaseReviewArtifactKind, str]] = set()
        _collect_changes(
            base_policies,
            candidate_policies,
            ReleaseReviewArtifactKind.POLICY_SET,
            ReleaseEvidenceFindingCode.POLICY_SET_ADDITION_UNSUPPORTED,
            ReleaseEvidenceFindingCode.POLICY_SET_REMOVAL_UNSUPPORTED,
            required,
            findings,
        )
        _collect_changes(
            base_providers,
            candidate_providers,
            ReleaseReviewArtifactKind.PROVIDER_TARGET,
            ReleaseEvidenceFindingCode.PROVIDER_TARGET_ADDITION_UNSUPPORTED,
            ReleaseEvidenceFindingCode.PROVIDER_TARGET_REMOVAL_UNSUPPORTED,
            required,
            findings,
        )
        if not set(reviews).issubset(required):
            raise ReleaseEvidenceError("Review evidence is outside the changed release lineage")

        for kind, subject_id in sorted(required, key=lambda item: (item[0].value, item[1])):
            resolved_review = reviews.get((kind, subject_id))
            if resolved_review is None:
                findings.append(_review_finding(kind, subject_id, blocked=False))
            elif not resolved_review.approved:
                findings.append(_review_finding(kind, subject_id, blocked=True))

        return ControlPackReleaseEvidenceReport(
            static_analysis=static_analysis,
            scenario_replay=scenario_replay,
            review_evidence=tuple(
                sorted(review_evidence, key=lambda item: (item.kind.value, item.subject_id))
            ),
            findings=tuple(sorted(findings, key=lambda item: (item.code.value, item.subject_id))),
        )


def _collect_changes[Item: (PolicySet, ProviderCapabilityRecord)](
    base: dict[str, Item],
    candidate: dict[str, Item],
    kind: ReleaseReviewArtifactKind,
    addition_code: ReleaseEvidenceFindingCode,
    removal_code: ReleaseEvidenceFindingCode,
    required: set[tuple[ReleaseReviewArtifactKind, str]],
    findings: list[ReleaseEvidenceFinding],
) -> None:
    for subject_id in sorted(candidate.keys() - base.keys()):
        findings.append(ReleaseEvidenceFinding(addition_code, subject_id))
    for subject_id in sorted(base.keys() - candidate.keys()):
        findings.append(ReleaseEvidenceFinding(removal_code, subject_id))
    required.update(
        (kind, subject_id)
        for subject_id in base.keys() & candidate.keys()
        if base[subject_id] != candidate[subject_id]
    )


def _review_finding(
    kind: ReleaseReviewArtifactKind,
    subject_id: str,
    *,
    blocked: bool,
) -> ReleaseEvidenceFinding:
    codes = {
        (ReleaseReviewArtifactKind.POLICY_SET, False): (
            ReleaseEvidenceFindingCode.POLICY_REVIEW_MISSING
        ),
        (ReleaseReviewArtifactKind.POLICY_SET, True): (
            ReleaseEvidenceFindingCode.POLICY_REVIEW_BLOCKED
        ),
        (ReleaseReviewArtifactKind.PROVIDER_TARGET, False): (
            ReleaseEvidenceFindingCode.PROVIDER_REVIEW_MISSING
        ),
        (ReleaseReviewArtifactKind.PROVIDER_TARGET, True): (
            ReleaseEvidenceFindingCode.PROVIDER_REVIEW_BLOCKED
        ),
    }
    return ReleaseEvidenceFinding(codes[(kind, blocked)], subject_id)


def _unique_index[Item](
    items: Iterable[Item], key: Callable[[Item], str], label: str
) -> dict[str, Item]:
    indexed: dict[str, Item] = {}
    for item in items:
        identifier = key(item)
        if identifier in indexed:
            raise ReleaseEvidenceError(f"Duplicate {label} identifier")
        indexed[identifier] = item
    return indexed


def _evidence_index[Item](
    items: Iterable[Item],
    key: Callable[[Item], tuple[ReleaseReviewArtifactKind, str]],
    label: str,
) -> dict[tuple[ReleaseReviewArtifactKind, str], Item]:
    indexed: dict[tuple[ReleaseReviewArtifactKind, str], Item] = {}
    for item in items:
        identifier = key(item)
        if identifier in indexed:
            raise ReleaseEvidenceError(f"Duplicate {label} identifier")
        indexed[identifier] = item
    return indexed
