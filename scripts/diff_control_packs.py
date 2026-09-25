#!/usr/bin/env python3
"""Compare two verified policy/provider packs and emit metadata-only JSON."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

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
from regulated_ai.application import AnalyzeControlPackDiff, ControlPackDiffError
from regulated_ai.domain import (
    ControlPackChange,
    ControlPackDiffReport,
    ControlPackImpact,
    ControlPackRelease,
    ControlPackReleaseIdentity,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify two releases, analyze semantic impact and print stable JSON."""
    parser = argparse.ArgumentParser(
        description="Compare two signed policy/provider control packs without executing policy."
    )
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument(
        "--fail-on-decision-impact",
        action="store_true",
        help="Return exit code 2 when static analysis finds potential decision impact.",
    )
    args = parser.parse_args(argv)

    try:
        base = _load_release(args.base_manifest, args.trust_store)
        candidate = _load_release(args.candidate_manifest, args.trust_store)
        report = AnalyzeControlPackDiff().execute(base, candidate)
    except (ConfigurationBoundaryError, ControlPackDiffError, SignedPackError) as exc:
        print(f"Control-pack diff failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_report_payload(report), sort_keys=True, separators=(",", ":")))
    if args.fail_on_decision_impact and report.has_decision_impact:
        return 2
    return 0


def _load_release(manifest_path: Path, trust_store_path: Path) -> ControlPackRelease:
    pack = verify_control_pack(manifest_path, trust_store_path)
    return _release_from_verified_pack(pack)


def _release_from_verified_pack(pack: VerifiedControlPack) -> ControlPackRelease:
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


def _report_payload(report: ControlPackDiffReport) -> dict[str, object]:
    impact_counts = {
        impact.value: sum(change.impact is impact for change in report.changes)
        for impact in ControlPackImpact
    }
    return {
        "schema_version": "1",
        "status": "CHANGES_DETECTED" if report.changes else "NO_SEMANTIC_CHANGE",
        "base_pack": _identity_payload(report.base),
        "candidate_pack": _identity_payload(report.candidate),
        "release_metadata_changed": report.base.payload_digest != report.candidate.payload_digest,
        "version_reused": report.version_reused,
        "signing_key_changed": report.signing_key_changed,
        "highest_impact": None if report.highest_impact is None else report.highest_impact.value,
        "summary": {"total_changes": len(report.changes), "by_impact": impact_counts},
        "changes": [_change_payload(change) for change in report.changes],
        "analysis_scope": (
            "Static potential-impact analysis; this report does not simulate every runtime "
            "context or assert legal, regulatory, provider or compliance correctness."
        ),
    }


def _identity_payload(identity: ControlPackReleaseIdentity) -> dict[str, str]:
    return {
        "id": identity.pack_id,
        "version": identity.pack_version,
        "signing_key_id": identity.signing_key_id,
        "payload_digest": identity.payload_digest,
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


if __name__ == "__main__":
    raise SystemExit(main())
