#!/usr/bin/env python3
"""Evaluate a digest-bound regulatory review before policy-pack signing."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from regulated_ai.adapters.policy_review_files import (
    PolicyReviewBoundaryError,
    load_policy_draft,
    load_policy_regulatory_review,
)
from regulated_ai.adapters.signed_packs import SignedPackError, verify_control_pack
from regulated_ai.adapters.yaml_files import (
    ConfigurationBoundaryError,
    load_capability_bytes,
    load_policy_bytes,
)
from regulated_ai.application import PolicyUpdateRegulatoryReviewError, ReviewPolicyUpdate
from regulated_ai.domain import (
    ControlPackRelease,
    ControlPackReleaseIdentity,
    PolicyUpdateRegulatoryReviewReport,
    RegulatoryReviewFinding,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify the base, validate review bindings and print a stable gate report."""
    parser = argparse.ArgumentParser(
        description="Review one policy draft against an authenticated base before signing."
    )
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--candidate-policy", type=Path, required=True)
    parser.add_argument("--review-record", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        base = _load_release(args.base_manifest, args.trust_store)
        draft = load_policy_draft(args.candidate_policy)
        review = load_policy_regulatory_review(args.review_record)
        report = ReviewPolicyUpdate().execute(base, draft, review)
    except (
        ConfigurationBoundaryError,
        PolicyReviewBoundaryError,
        PolicyUpdateRegulatoryReviewError,
        SignedPackError,
    ) as exc:
        print(f"Policy regulatory review failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_report_payload(report), sort_keys=True, separators=(",", ":")))
    return 0 if report.approved else 2


def _load_release(manifest_path: Path, trust_store_path: Path) -> ControlPackRelease:
    pack = verify_control_pack(manifest_path, trust_store_path)
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


def _report_payload(report: PolicyUpdateRegulatoryReviewReport) -> dict[str, object]:
    return {
        "schema_version": "1",
        "status": "REGULATORY_REVIEW_PASSED" if report.approved else "REGULATORY_REVIEW_BLOCKED",
        "base_pack": {
            "id": report.base.pack_id,
            "version": report.base.pack_version,
            "signing_key_id": report.base.signing_key_id,
            "payload_digest": report.base.payload_digest,
        },
        "candidate_policy": {
            "policy_set_id": report.policy_set_id,
            "version": report.candidate_policy_version,
            "content_digest": report.candidate_policy_digest,
        },
        "review": {
            "id": report.review_id,
            "reviewer_role": report.reviewer_role,
            "reviewed_at": report.reviewed_at.isoformat(),
            "digest": report.review_digest,
        },
        "summary": {
            "required_policy_set_fields": len(report.required_policy_set_fields),
            "required_rule_reviews": len(report.required_rule_ids),
            "findings": len(report.findings),
        },
        "required_policy_set_fields": list(report.required_policy_set_fields),
        "required_rule_ids": list(report.required_rule_ids),
        "findings": [_finding_payload(item) for item in report.findings],
        "review_scope": (
            "Offline consistency and coverage gate for human-recorded regulatory mappings; "
            "passing does not authenticate a reviewer, retrieve or interpret source text, sign "
            "or promote a release, or assert legal, regulatory or compliance correctness."
        ),
    }


def _finding_payload(finding: RegulatoryReviewFinding) -> dict[str, str | None]:
    return {
        "code": finding.code.value,
        "rule_id": finding.rule_id,
        "policy_set_field": finding.policy_set_field,
    }


if __name__ == "__main__":
    raise SystemExit(main())
