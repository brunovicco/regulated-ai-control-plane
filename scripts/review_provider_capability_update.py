#!/usr/bin/env python3
"""Evaluate a digest-bound provider capability review before pack signing."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from regulated_ai.adapters.provider_review_files import (
    ProviderReviewBoundaryError,
    load_provider_capability_draft,
    load_provider_capability_review,
)
from regulated_ai.adapters.signed_packs import SignedPackError, verify_control_pack
from regulated_ai.adapters.yaml_files import (
    ConfigurationBoundaryError,
    load_capability_bytes,
    load_policy_bytes,
)
from regulated_ai.application import (
    ProviderCapabilityUpdateReviewError,
    ReviewProviderCapabilityUpdate,
)
from regulated_ai.domain import (
    ControlPackRelease,
    ControlPackReleaseIdentity,
    ProviderCapabilityReviewFinding,
    ProviderCapabilityUpdateReport,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify the base, validate review bindings and print a stable gate report."""
    parser = argparse.ArgumentParser(
        description=(
            "Review one provider capability draft against an authenticated base before signing."
        )
    )
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--candidate-record", type=Path, required=True)
    parser.add_argument("--review-record", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        base = _load_release(args.base_manifest, args.trust_store)
        draft = load_provider_capability_draft(args.candidate_record)
        review = load_provider_capability_review(args.review_record)
        report = ReviewProviderCapabilityUpdate().execute(base, draft, review)
    except (
        ConfigurationBoundaryError,
        ProviderCapabilityUpdateReviewError,
        ProviderReviewBoundaryError,
        SignedPackError,
    ) as exc:
        print(f"Provider capability review failed: {exc}", file=sys.stderr)
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


def _report_payload(report: ProviderCapabilityUpdateReport) -> dict[str, object]:
    return {
        "schema_version": "1",
        "status": "REVIEW_GATE_PASSED" if report.approved else "REVIEW_GATE_BLOCKED",
        "base_pack": {
            "id": report.base.pack_id,
            "version": report.base.pack_version,
            "signing_key_id": report.base.signing_key_id,
            "payload_digest": report.base.payload_digest,
        },
        "candidate_record": {
            "target": report.target.identifier,
            "registry_version": report.candidate_registry_version,
            "record_version": report.candidate_record_version,
            "content_digest": report.candidate_record_digest,
        },
        "review": {
            "id": report.review_id,
            "reviewer_role": report.reviewer_role,
            "reviewed_at": report.reviewed_at.isoformat(),
            "digest": report.review_digest,
        },
        "summary": {
            "required_capabilities": len(report.required_capability_keys),
            "findings": len(report.findings),
        },
        "required_capability_keys": list(report.required_capability_keys),
        "findings": [_finding_payload(item) for item in report.findings],
        "review_scope": (
            "Offline consistency and coverage gate for human-recorded source review; passing does "
            "not authenticate a reviewer, sign or promote a release, verify provider behavior, or "
            "assert legal, regulatory or compliance correctness."
        ),
    }


def _finding_payload(finding: ProviderCapabilityReviewFinding) -> dict[str, str | None]:
    return {
        "code": finding.code.value,
        "capability_key": finding.capability_key,
        "source_digest": finding.source_digest,
    }


if __name__ == "__main__":
    raise SystemExit(main())
