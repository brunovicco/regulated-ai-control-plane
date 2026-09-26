#!/usr/bin/env python3
"""Compose verified control-pack analysis and review evidence without promotion."""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from regulated_ai.adapters.policy_review_files import (
    PolicyReviewBoundaryError,
    load_policy_regulatory_review,
)
from regulated_ai.adapters.provider_review_files import (
    ProviderReviewBoundaryError,
    load_provider_capability_review,
)
from regulated_ai.adapters.scenario_files import ScenarioSuiteError, load_scenario_suite_file
from regulated_ai.adapters.signed_packs import (
    SignedPackError,
    VerifiedControlPack,
    verify_control_pack,
)
from regulated_ai.adapters.yaml_files import (
    ConfigurationBoundaryError,
    load_capability_bytes,
    load_policy_bytes,
)
from regulated_ai.application import (
    AnalyzeControlPackDiff,
    AssembleControlPackReleaseEvidence,
    ControlPackDiffError,
    ControlPackScenarioReplayError,
    PolicyUpdateRegulatoryReviewError,
    ProviderCapabilityUpdateReviewError,
    ReleaseEvidenceError,
    ReplayControlPackScenarios,
    ReviewPolicyUpdate,
    ReviewProviderCapabilityUpdate,
)
from regulated_ai.domain import (
    ControlPackChange,
    ControlPackDiffReport,
    ControlPackImpact,
    ControlPackRelease,
    ControlPackReleaseEvidenceReport,
    ControlPackReleaseIdentity,
    ControlPackScenarioReplayReport,
    PolicyDraft,
    PolicyUpdateRegulatoryReviewReport,
    ProviderCapabilityDraft,
    ProviderCapabilityUpdateReport,
    ReleaseCandidateArtifact,
    ReleaseEvidenceFinding,
    ReleaseReviewArtifactKind,
    ReleaseReviewEvidence,
    ScenarioReplayOutcome,
    ScenarioReplayResult,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify and compose deterministic release evidence from bounded local inputs."""
    parser = argparse.ArgumentParser(
        description=(
            "Compose static, replay and human-review evidence for two signed control packs."
        )
    )
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--scenario-suite", type=Path, required=True)
    parser.add_argument(
        "--provider-review-record",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--policy-review-record",
        type=Path,
        action="append",
        default=[],
    )
    args = parser.parse_args(argv)

    try:
        base_pack = verify_control_pack(args.base_manifest, args.trust_store)
        candidate_pack = verify_control_pack(args.candidate_manifest, args.trust_store)
        base = _release_from_pack(base_pack)
        candidate = _release_from_pack(candidate_pack)
        static_analysis = AnalyzeControlPackDiff().execute(base, candidate)
        suite = load_scenario_suite_file(args.scenario_suite)
        scenario_replay = ReplayControlPackScenarios().execute(base, candidate, suite)
        policy_drafts = _policy_drafts(candidate_pack)
        provider_drafts = _provider_drafts(candidate_pack)
        review_evidence = (
            *_policy_review_evidence(base, policy_drafts, tuple(args.policy_review_record)),
            *_provider_review_evidence(
                base,
                provider_drafts,
                tuple(args.provider_review_record),
            ),
        )
        report = AssembleControlPackReleaseEvidence().execute(
            base=base,
            candidate=candidate,
            static_analysis=static_analysis,
            scenario_replay=scenario_replay,
            candidate_artifacts=_candidate_artifacts(policy_drafts, provider_drafts),
            review_evidence=review_evidence,
        )
    except (
        ConfigurationBoundaryError,
        ControlPackDiffError,
        ControlPackScenarioReplayError,
        PolicyReviewBoundaryError,
        PolicyUpdateRegulatoryReviewError,
        ProviderCapabilityUpdateReviewError,
        ProviderReviewBoundaryError,
        ReleaseEvidenceError,
        ScenarioSuiteError,
        SignedPackError,
    ) as exc:
        print(f"Control-pack release evidence failed: {exc}", file=sys.stderr)
        return 1

    payload = _report_payload(report)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if report.complete else 2


def _release_from_pack(pack: VerifiedControlPack) -> ControlPackRelease:
    identity = pack.identity
    return ControlPackRelease(
        identity=ControlPackReleaseIdentity(
            pack_id=identity.pack_id,
            pack_version=identity.pack_version,
            signing_key_id=identity.signing_key_id,
            payload_digest=identity.payload_digest,
        ),
        policy_sets=tuple(load_policy_bytes(item.content, item.path) for item in pack.policy_files),
        provider_records=tuple(
            load_capability_bytes(item.content, item.path) for item in pack.capability_files
        ),
    )


def _policy_drafts(pack: VerifiedControlPack) -> dict[str, PolicyDraft]:
    drafts: dict[str, PolicyDraft] = {}
    for item in pack.policy_files:
        policy = load_policy_bytes(item.content, item.path)
        if policy.id in drafts:
            raise ReleaseEvidenceError("Candidate policy-set ids must be unique")
        drafts[policy.id] = PolicyDraft(policy, _content_digest(item.content))
    return drafts


def _provider_drafts(pack: VerifiedControlPack) -> dict[str, ProviderCapabilityDraft]:
    drafts: dict[str, ProviderCapabilityDraft] = {}
    for item in pack.capability_files:
        record = load_capability_bytes(item.content, item.path)
        identifier = record.target.identifier
        if identifier in drafts:
            raise ReleaseEvidenceError("Candidate provider targets must be unique")
        drafts[identifier] = ProviderCapabilityDraft(record, _content_digest(item.content))
    return drafts


def _candidate_artifacts(
    policies: dict[str, PolicyDraft],
    providers: dict[str, ProviderCapabilityDraft],
) -> tuple[ReleaseCandidateArtifact, ...]:
    return (
        *(
            ReleaseCandidateArtifact(
                ReleaseReviewArtifactKind.POLICY_SET,
                subject_id,
                draft.content_digest,
            )
            for subject_id, draft in sorted(policies.items())
        ),
        *(
            ReleaseCandidateArtifact(
                ReleaseReviewArtifactKind.PROVIDER_TARGET,
                subject_id,
                draft.content_digest,
            )
            for subject_id, draft in sorted(providers.items())
        ),
    )


def _policy_review_evidence(
    base: ControlPackRelease,
    drafts: dict[str, PolicyDraft],
    paths: tuple[Path, ...],
) -> tuple[ReleaseReviewEvidence, ...]:
    evidence = []
    for path in paths:
        review = load_policy_regulatory_review(path)
        draft = drafts.get(review.policy_set_id)
        if draft is None:
            raise ReleaseEvidenceError("Policy review target is absent from the candidate pack")
        report = ReviewPolicyUpdate().execute(base, draft, review)
        evidence.append(_policy_review_result(report))
    return tuple(evidence)


def _provider_review_evidence(
    base: ControlPackRelease,
    drafts: dict[str, ProviderCapabilityDraft],
    paths: tuple[Path, ...],
) -> tuple[ReleaseReviewEvidence, ...]:
    evidence = []
    for path in paths:
        review = load_provider_capability_review(path)
        draft = drafts.get(review.target.identifier)
        if draft is None:
            raise ReleaseEvidenceError("Provider review target is absent from the candidate pack")
        report = ReviewProviderCapabilityUpdate().execute(base, draft, review)
        evidence.append(_provider_review_result(report))
    return tuple(evidence)


def _policy_review_result(
    report: PolicyUpdateRegulatoryReviewReport,
) -> ReleaseReviewEvidence:
    return ReleaseReviewEvidence(
        kind=ReleaseReviewArtifactKind.POLICY_SET,
        subject_id=report.policy_set_id,
        base_pack_payload_digest=report.base.payload_digest,
        candidate_content_digest=report.candidate_policy_digest,
        review_id=report.review_id,
        review_digest=report.review_digest,
        approved=report.approved,
    )


def _provider_review_result(report: ProviderCapabilityUpdateReport) -> ReleaseReviewEvidence:
    return ReleaseReviewEvidence(
        kind=ReleaseReviewArtifactKind.PROVIDER_TARGET,
        subject_id=report.target.identifier,
        base_pack_payload_digest=report.base.payload_digest,
        candidate_content_digest=report.candidate_record_digest,
        review_id=report.review_id,
        review_digest=report.review_digest,
        approved=report.approved,
    )


def _content_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _report_payload(report: ControlPackReleaseEvidenceReport) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": "1",
        "status": "EVIDENCE_COMPLETE" if report.complete else "EVIDENCE_INCOMPLETE",
        "base_pack": _identity_payload(report.static_analysis.base),
        "candidate_pack": _identity_payload(report.static_analysis.candidate),
        "static_analysis": _static_analysis_payload(report.static_analysis),
        "scenario_replay": _scenario_replay_payload(report.scenario_replay),
        "review_evidence": [
            {
                "kind": item.kind.value,
                "subject_id": item.subject_id,
                "candidate_content_digest": item.candidate_content_digest,
                "review_id": item.review_id,
                "review_digest": item.review_digest,
                "approved": item.approved,
            }
            for item in report.review_evidence
        ],
        "findings": [_finding_payload(item) for item in report.findings],
        "summary": {
            "potential_changes": len(report.static_analysis.changes),
            "replayed_scenarios": len(report.scenario_replay.results),
            "review_artifacts": len(report.review_evidence),
            "findings": len(report.findings),
        },
        "evidence_scope": (
            "Verified static, finite replay and digest-bound review evidence; completeness does "
            "not authenticate reviewers, approve impacts, sign or promote a release, or assert "
            "legal, regulatory, provider or compliance correctness."
        ),
    }
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {**core, "bundle_digest": f"sha256:{hashlib.sha256(canonical).hexdigest()}"}


def _identity_payload(identity: ControlPackReleaseIdentity) -> dict[str, str]:
    return {
        "id": identity.pack_id,
        "version": identity.pack_version,
        "signing_key_id": identity.signing_key_id,
        "payload_digest": identity.payload_digest,
    }


def _static_analysis_payload(report: ControlPackDiffReport) -> dict[str, object]:
    counts = {
        impact.value: sum(item.impact is impact for item in report.changes)
        for impact in ControlPackImpact
    }
    return {
        "status": "CHANGES_DETECTED" if report.changes else "NO_SEMANTIC_CHANGE",
        "highest_impact": None if report.highest_impact is None else report.highest_impact.value,
        "version_reused": report.version_reused,
        "signing_key_changed": report.signing_key_changed,
        "summary": {"total_changes": len(report.changes), "by_impact": counts},
        "changes": [_change_payload(item) for item in report.changes],
    }


def _change_payload(change: ControlPackChange) -> dict[str, object]:
    return {
        "kind": change.kind.value,
        "change_type": change.change_type.value,
        "identifier": change.identifier,
        "impact": change.impact.value,
        "changed_fields": list(change.changed_fields),
        "dependent_policy_rule_ids": list(change.dependent_policy_rule_ids),
    }


def _scenario_replay_payload(report: ControlPackScenarioReplayReport) -> dict[str, object]:
    changed = tuple(item for item in report.results if item.impact is not None)
    decision_count = sum(item.impact is ControlPackImpact.DECISION for item in report.results)
    evidence_count = sum(item.impact is ControlPackImpact.EVIDENCE for item in report.results)
    status = "NO_OBSERVED_CHANGE"
    if decision_count:
        status = "DECISION_CHANGES_OBSERVED"
    elif evidence_count:
        status = "EVIDENCE_CHANGES_OBSERVED"
    return {
        "status": status,
        "suite": {
            "id": report.suite_id,
            "version": report.suite_version,
            "digest": report.suite_digest,
            "evaluated_at": report.evaluated_at.isoformat(),
        },
        "summary": {
            "total_scenarios": len(report.results),
            "changed_scenarios": len(changed),
            "by_impact": {"DECISION": decision_count, "EVIDENCE": evidence_count},
        },
        "results": [_result_payload(item) for item in report.results],
    }


def _result_payload(result: ScenarioReplayResult) -> dict[str, object]:
    return {
        "scenario_id": result.scenario_id,
        "impact": None if result.impact is None else result.impact.value,
        "changed_fields": list(result.changed_fields),
        "base": _outcome_payload(result.base),
        "candidate": _outcome_payload(result.candidate),
    }


def _outcome_payload(outcome: ScenarioReplayOutcome) -> dict[str, object]:
    return {
        "status": outcome.status.value,
        "decision": None if outcome.decision is None else outcome.decision.value,
        "obligation_types": [item.value for item in outcome.obligation_types],
        "obligations_digest": outcome.obligations_digest,
        "matched_policy_ids": list(outcome.matched_policy_ids),
        "provider_capability_ids": list(outcome.provider_capability_ids),
        "reason_codes": list(outcome.reason_codes),
        "policy_set_version": outcome.policy_set_version,
        "provider_registry_version": outcome.provider_registry_version,
        "output_digest": outcome.output_digest,
        "error_code": outcome.error_code,
    }


def _finding_payload(finding: ReleaseEvidenceFinding) -> dict[str, str]:
    return {"code": finding.code.value, "subject_id": finding.subject_id}


if __name__ == "__main__":
    raise SystemExit(main())
