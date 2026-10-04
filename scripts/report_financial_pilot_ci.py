#!/usr/bin/env python3
"""Reduce pytest results to metadata evidence without retaining failure output."""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

_REQUIRED = {
    "test_enforcement_claim_has_one_winner_across_connections": 1,
    "test_action_claim_has_one_winner_across_connections": 1,
    "test_decision_approval_consumption_and_claim_are_atomic": 1,
    "test_signed_action_approval_is_consumed_by_one_concurrent_claim": 1,
    "test_signed_reconciliation_is_atomic_idempotent_and_rejects_conflicting_outcome": 2,
    "test_financial_pilot_identity_gateway_approval_and_recovery": 6,
}


def report_results(path: Path, source_revision: str) -> dict[str, object]:
    """Require the complete PostgreSQL pilot suite with no skips or failures."""
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("CI source revision is invalid")
    with path.open("rb") as stream:
        encoded = stream.read(8 * 1024 * 1024 + 1)
    text = encoded.decode("utf-8", errors="strict")
    if len(encoded) > 8 * 1024 * 1024 or "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("CI result document is invalid")
    root = ElementTree.fromstring(text)  # noqa: S314 - bounded local pytest XML, no DTD/entities
    counts: Counter[str] = Counter()
    blocked = False
    seen: set[str] = set()
    for case in root.iter("testcase"):
        if not case.get("classname", "").startswith("tests.integration."):
            continue
        name = case.get("name", "").partition("[")[0]
        if name in _REQUIRED:
            full_name = case.get("name", "")
            blocked |= full_name in seen
            seen.add(full_name)
            counts[name] += 1
            blocked |= any(case.find(tag) is not None for tag in ("skipped", "failure", "error"))
    passed = not blocked and all(counts[name] == count for name, count in _REQUIRED.items())
    core: dict[str, object] = {
        "schema_version": "1",
        "status": "POSTGRES_CI_VERIFIED" if passed else "POSTGRES_CI_BLOCKED",
        "observed_at": datetime.now(UTC).isoformat(),
        "source_revision": source_revision,
        "postgresql": "17",
        "execution_mode": "CI_REAL_POSTGRES",
        "expected_cases": sum(_REQUIRED.values()),
        "observed_cases": sum(counts.values()),
        "external_provider_mode": "SIMULATED",
        "enterprise_issuer_mode": "SYNTHETIC",
    }
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    return {**core, "report_digest": f"sha256:{hashlib.sha256(canonical).hexdigest()}"}


def main(argv: Sequence[str] | None = None) -> int:
    """Emit only counts, provenance and status, including when tests failed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args(argv)
    try:
        result = report_results(args.junit, args.source_revision)
    except Exception as exc:
        print(f"Pilot CI evidence failed closed ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "POSTGRES_CI_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
