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
from regulated_ai.adapters.release_review_attestations import (
    ReleaseReviewAttestationError,
    verify_release_review_attestations,
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
    load_tool_catalog_bytes,
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
    ControlPackChangeType,
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
    ReleaseReviewConclusion,
    ReleaseReviewEvidence,
    ScenarioReplayOutcome,
    ScenarioReplayResult,
    VerifiedReleaseReviewAttestation,
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
    parser.add_argument("--review-trust-store", type=Path)
    parser.add_argument(
        "--review-attestation",
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
        base_policy_drafts = _policy_drafts(base_pack)
        candidate_policy_drafts = _policy_drafts(candidate_pack)
        base_provider_drafts = _provider_drafts(base_pack)
        candidate_provider_drafts = _provider_drafts(candidate_pack)
        policy_reports = _policy_review_reports(
            base,
            candidate_policy_drafts,
            tuple(args.policy_review_record),
        )
        provider_reports = _provider_review_reports(
            base,
            candidate_provider_drafts,
            tuple(args.provider_review_record),
        )
        attestations: tuple[VerifiedReleaseReviewAttestation, ...] = ()
        if args.review_attestation:
            if args.review_trust_store is None:
                raise ReleaseEvidenceError(
                    "Review trust store is required when attestations are supplied"
                )
            attestations = verify_release_review_attestations(
                tuple(args.review_attestation), args.review_trust_store
            )
        review_evidence = _authenticated_review_evidence(
            base=base,
            candidate=candidate,
            policy_reports=policy_reports,
            provider_reports=provider_reports,
            attestations=attestations,
        )
        report = AssembleControlPackReleaseEvidence().execute(
            base=base,
            candidate=candidate,
            static_analysis=static_analysis,
            scenario_replay=scenario_replay,
            candidate_artifacts=_release_artifacts(
                candidate_policy_drafts,
                candidate_provider_drafts,
                candidate_pack,
            ),
            review_evidence=review_evidence,
            base_artifacts=_release_artifacts(
                base_policy_drafts,
                base_provider_drafts,
                base_pack,
            ),
        )
    except (
        ConfigurationBoundaryError,
        ControlPackDiffError,
        ControlPackScenarioReplayError,
        PolicyReviewBoundaryError,
        PolicyUpdateRegulatoryReviewError,
        ProviderCapabilityUpdateReviewError,
        ProviderReviewBoundaryError,
        ReleaseReviewAttestationError,
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
    catalog_version, tools = load_tool_catalog_bytes(
        pack.tool_files[0].content, pack.tool_files[0].path
    )
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
        tool_catalog_version=catalog_version,
        tools=tools,
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


def _release_artifacts(
    policies: dict[str, PolicyDraft],
    providers: dict[str, ProviderCapabilityDraft],
    pack: VerifiedControlPack,
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
        ReleaseCandidateArtifact(
            ReleaseReviewArtifactKind.TOOL_CATALOG,
            "trusted-tool-catalog",
            _content_digest(pack.tool_files[0].content),
        ),
    )


def _policy_review_reports(
    base: ControlPackRelease,
    drafts: dict[str, PolicyDraft],
    paths: tuple[Path, ...],
) -> dict[str, PolicyUpdateRegulatoryReviewReport]:
    reports: dict[str, PolicyUpdateRegulatoryReviewReport] = {}
    for path in paths:
        review = load_policy_regulatory_review(path)
        draft = drafts.get(review.policy_set_id)
        if draft is None:
            raise ReleaseEvidenceError("Policy review target is absent from the candidate pack")
        report = ReviewPolicyUpdate().execute(base, draft, review)
        if report.policy_set_id in reports:
            raise ReleaseEvidenceError("Duplicate policy review target")
        reports[report.policy_set_id] = report
    return reports


def _provider_review_reports(
    base: ControlPackRelease,
    drafts: dict[str, ProviderCapabilityDraft],
    paths: tuple[Path, ...],
) -> dict[str, ProviderCapabilityUpdateReport]:
    reports: dict[str, ProviderCapabilityUpdateReport] = {}
    for path in paths:
        review = load_provider_capability_review(path)
        draft = drafts.get(review.target.identifier)
        if draft is None:
            raise ReleaseEvidenceError("Provider review target is absent from the candidate pack")
        report = ReviewProviderCapabilityUpdate().execute(base, draft, review)
        subject_id = report.target.identifier
        if subject_id in reports:
            raise ReleaseEvidenceError("Duplicate provider review target")
        reports[subject_id] = report
    return reports


def _authenticated_review_evidence(
    *,
    base: ControlPackRelease,
    candidate: ControlPackRelease,
    policy_reports: dict[str, PolicyUpdateRegulatoryReviewReport],
    provider_reports: dict[str, ProviderCapabilityUpdateReport],
    attestations: tuple[VerifiedReleaseReviewAttestation, ...],
) -> tuple[ReleaseReviewEvidence, ...]:
    evidence = []
    seen: set[tuple[ReleaseReviewArtifactKind, str]] = set()
    attestation_ids: set[str] = set()
    for attestation in attestations:
        key = (attestation.kind, attestation.subject_id)
        if key in seen:
            raise ReleaseEvidenceError("Duplicate authenticated review target")
        if attestation.attestation_id in attestation_ids:
            raise ReleaseEvidenceError("Duplicate review attestation id")
        seen.add(key)
        attestation_ids.add(attestation.attestation_id)
        if attestation.base_pack_payload_digest != base.identity.payload_digest:
            raise ReleaseEvidenceError("Review attestation does not bind the approved base")
        if attestation.candidate_pack_payload_digest != candidate.identity.payload_digest:
            raise ReleaseEvidenceError("Review attestation does not bind the candidate pack")

        approved = attestation.conclusion is ReleaseReviewConclusion.APPROVE
        review_id = attestation.attestation_id
        review_digest = attestation.attestation_digest
        if (
            attestation.change_type is ControlPackChangeType.MODIFIED
            and attestation.kind is not ReleaseReviewArtifactKind.TOOL_CATALOG
        ):
            report = _detailed_report(attestation, policy_reports, provider_reports)
            if (
                attestation.review_id != report["review_id"]
                or attestation.review_digest != report["review_digest"]
                or attestation.reviewer_role != report["reviewer_role"]
                or attestation.reviewed_content_digest != report["content_digest"]
            ):
                raise ReleaseEvidenceError(
                    "Review attestation does not bind the detailed review result"
                )
            if approved and not report["approved"]:
                raise ReleaseEvidenceError("Review attestation cannot approve a blocked review")
            approved = approved and bool(report["approved"])
            review_id = str(report["review_id"])
            review_digest = str(report["review_digest"])

        evidence.append(
            ReleaseReviewEvidence(
                kind=attestation.kind,
                subject_id=attestation.subject_id,
                change_type=attestation.change_type,
                base_pack_payload_digest=attestation.base_pack_payload_digest,
                candidate_pack_payload_digest=attestation.candidate_pack_payload_digest,
                reviewed_content_digest=attestation.reviewed_content_digest,
                review_id=review_id,
                review_digest=review_digest,
                reviewer_role=attestation.reviewer_role,
                attested_at=attestation.attested_at,
                attestation_id=attestation.attestation_id,
                signing_key_id=attestation.signing_key_id,
                attestation_digest=attestation.attestation_digest,
                signature_digest=attestation.signature_digest,
                approved=approved,
            )
        )
    return tuple(evidence)


def _detailed_report(
    attestation: VerifiedReleaseReviewAttestation,
    policy_reports: dict[str, PolicyUpdateRegulatoryReviewReport],
    provider_reports: dict[str, ProviderCapabilityUpdateReport],
) -> dict[str, object]:
    if attestation.kind is ReleaseReviewArtifactKind.POLICY_SET:
        report = policy_reports.get(attestation.subject_id)
        if report is None:
            raise ReleaseEvidenceError(
                "Modified policy attestation requires its detailed review record"
            )
        return {
            "review_id": report.review_id,
            "review_digest": report.review_digest,
            "reviewer_role": report.reviewer_role,
            "content_digest": report.candidate_policy_digest,
            "approved": report.approved,
        }
    provider_report = provider_reports.get(attestation.subject_id)
    if provider_report is None:
        raise ReleaseEvidenceError(
            "Modified provider attestation requires its detailed review record"
        )
    return {
        "review_id": provider_report.review_id,
        "review_digest": provider_report.review_digest,
        "reviewer_role": provider_report.reviewer_role,
        "content_digest": provider_report.candidate_record_digest,
        "approved": provider_report.approved,
    }


def _content_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _report_payload(report: ControlPackReleaseEvidenceReport) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": "2",
        "status": "EVIDENCE_COMPLETE" if report.complete else "EVIDENCE_INCOMPLETE",
        "base_pack": _identity_payload(report.static_analysis.base),
        "candidate_pack": _identity_payload(report.static_analysis.candidate),
        "static_analysis": _static_analysis_payload(report.static_analysis),
        "scenario_replay": _scenario_replay_payload(report.scenario_replay),
        "review_evidence": [
            {
                "kind": item.kind.value,
                "subject_id": item.subject_id,
                "change_type": item.change_type.value,
                "reviewed_content_digest": item.reviewed_content_digest,
                "review_id": item.review_id,
                "review_digest": item.review_digest,
                "reviewer_role": item.reviewer_role,
                "attested_at": item.attested_at.isoformat(),
                "attestation_id": item.attestation_id,
                "signing_key_id": item.signing_key_id,
                "attestation_digest": item.attestation_digest,
                "signature_digest": item.signature_digest,
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
            "Verified static, finite replay and authenticated exact-change review evidence; "
            "completeness does not approve impacts, sign or promote a release, or assert legal, "
            "regulatory, provider or compliance correctness."
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
        "tool_catalog_version": outcome.tool_catalog_version,
        "authorized_tool_ids": list(outcome.authorized_tool_ids),
        "output_digest": outcome.output_digest,
        "error_code": outcome.error_code,
    }


def _finding_payload(finding: ReleaseEvidenceFinding) -> dict[str, str]:
    return {"code": finding.code.value, "subject_id": finding.subject_id}


if __name__ == "__main__":
    raise SystemExit(main())
