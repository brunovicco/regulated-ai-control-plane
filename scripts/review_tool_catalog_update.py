#!/usr/bin/env python3
"""Evaluate a digest-bound detailed tool-catalog review before pack signing."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from regulated_ai.adapters.signed_packs import SignedPackError, verify_control_pack
from regulated_ai.adapters.tool_review_files import (
    ToolReviewBoundaryError,
    load_tool_catalog_draft,
    load_tool_catalog_review,
)
from regulated_ai.adapters.yaml_files import (
    ConfigurationBoundaryError,
    load_capability_bytes,
    load_policy_bytes,
    load_tool_catalog_bytes,
)
from regulated_ai.application import ReviewToolCatalogUpdate, ToolCatalogUpdateReviewError
from regulated_ai.domain import (
    ControlPackRelease,
    ControlPackReleaseIdentity,
    ToolCatalogUpdateReviewReport,
    ToolDefinitionReviewFinding,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify the base, validate detailed review bindings and print a stable report."""
    parser = argparse.ArgumentParser(
        description="Review one trusted tool-catalog draft against an authenticated base."
    )
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--candidate-catalog", type=Path, required=True)
    parser.add_argument("--review-record", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        base = _load_release(args.base_manifest, args.trust_store)
        draft = load_tool_catalog_draft(args.candidate_catalog)
        review = load_tool_catalog_review(args.review_record)
        report = ReviewToolCatalogUpdate().execute(base, draft, review)
    except (
        ConfigurationBoundaryError,
        SignedPackError,
        ToolCatalogUpdateReviewError,
        ToolReviewBoundaryError,
    ) as exc:
        print(f"Tool-catalog review failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_report_payload(report), sort_keys=True, separators=(",", ":")))
    return 0 if report.approved else 2


def _load_release(manifest_path: Path, trust_store_path: Path) -> ControlPackRelease:
    pack = verify_control_pack(manifest_path, trust_store_path)
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


def _report_payload(report: ToolCatalogUpdateReviewReport) -> dict[str, object]:
    return {
        "schema_version": "1",
        "status": "TOOL_REVIEW_PASSED" if report.approved else "TOOL_REVIEW_BLOCKED",
        "base_pack": {
            "id": report.base.pack_id,
            "version": report.base.pack_version,
            "signing_key_id": report.base.signing_key_id,
            "payload_digest": report.base.payload_digest,
        },
        "candidate_catalog": {
            "version": report.candidate_catalog_version,
            "content_digest": report.candidate_catalog_digest,
        },
        "review": {
            "id": report.review_id,
            "reviewer_role": report.reviewer_role,
            "reviewed_at": report.reviewed_at.isoformat(),
            "digest": report.review_digest,
        },
        "summary": {
            "required_tool_reviews": len(report.required_tool_names),
            "findings": len(report.findings),
        },
        "required_tool_names": list(report.required_tool_names),
        "findings": [_finding_payload(item) for item in report.findings],
        "review_scope": (
            "Offline owner and implementation-reference coverage for changed trusted-tool "
            "definitions; passing does not authenticate the reviewer, execute a tool, validate "
            "the implementation, promote a release, or authorize any side effect."
        ),
    }


def _finding_payload(finding: ToolDefinitionReviewFinding) -> dict[str, str | None]:
    return {"code": finding.code.value, "tool_name": finding.tool_name}


if __name__ == "__main__":
    raise SystemExit(main())
