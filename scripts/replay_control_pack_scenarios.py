#!/usr/bin/env python3
"""Replay metadata-only scenarios across two verified control packs."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from regulated_ai.adapters.scenario_files import ScenarioSuiteError, load_scenario_suite_file
from regulated_ai.adapters.signed_packs import SignedPackError, verify_control_pack
from regulated_ai.adapters.yaml_files import (
    ConfigurationBoundaryError,
    load_capability_bytes,
    load_policy_bytes,
)
from regulated_ai.application import ControlPackScenarioReplayError, ReplayControlPackScenarios
from regulated_ai.domain import (
    ControlPackImpact,
    ControlPackRelease,
    ControlPackReleaseIdentity,
    ControlPackScenarioReplayReport,
    ScenarioReplayOutcome,
    ScenarioReplayResult,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify releases, replay a bounded suite and print deterministic JSON."""
    parser = argparse.ArgumentParser(
        description=(
            "Replay metadata-only scenarios against two signed policy/provider control packs."
        )
    )
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--scenario-suite", type=Path, required=True)
    parser.add_argument(
        "--fail-on-decision-impact",
        action="store_true",
        help="Return exit code 2 when replay observes decision or obligation impact.",
    )
    args = parser.parse_args(argv)

    try:
        base = _load_release(args.base_manifest, args.trust_store)
        candidate = _load_release(args.candidate_manifest, args.trust_store)
        suite = load_scenario_suite_file(args.scenario_suite)
        report = ReplayControlPackScenarios().execute(base, candidate, suite)
    except (
        ConfigurationBoundaryError,
        ControlPackScenarioReplayError,
        ScenarioSuiteError,
        SignedPackError,
    ) as exc:
        print(f"Control-pack scenario replay failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_report_payload(report), sort_keys=True, separators=(",", ":")))
    if args.fail_on_decision_impact and report.has_decision_impact:
        return 2
    return 0


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


def _report_payload(report: ControlPackScenarioReplayReport) -> dict[str, object]:
    changed = tuple(item for item in report.results if item.impact is not None)
    decision_count = sum(item.impact is ControlPackImpact.DECISION for item in report.results)
    evidence_count = sum(item.impact is ControlPackImpact.EVIDENCE for item in report.results)
    status = "NO_OBSERVED_CHANGE"
    if decision_count:
        status = "DECISION_CHANGES_OBSERVED"
    elif evidence_count:
        status = "EVIDENCE_CHANGES_OBSERVED"
    return {
        "schema_version": "1",
        "status": status,
        "base_pack": _identity_payload(report.base),
        "candidate_pack": _identity_payload(report.candidate),
        "suite": {
            "id": report.suite_id,
            "version": report.suite_version,
            "digest": report.suite_digest,
            "evaluated_at": report.evaluated_at.isoformat(),
        },
        "summary": {
            "total_scenarios": len(report.results),
            "changed_scenarios": len(changed),
            "by_impact": {
                "DECISION": decision_count,
                "EVIDENCE": evidence_count,
            },
        },
        "results": [_result_payload(item) for item in report.results],
        "analysis_scope": (
            "Finite metadata-only scenario replay; unchanged results do not prove semantic, legal, "
            "regulatory, provider or compliance equivalence."
        ),
    }


def _identity_payload(identity: ControlPackReleaseIdentity) -> dict[str, str]:
    return {
        "id": identity.pack_id,
        "version": identity.pack_version,
        "signing_key_id": identity.signing_key_id,
        "payload_digest": identity.payload_digest,
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


if __name__ == "__main__":
    raise SystemExit(main())
