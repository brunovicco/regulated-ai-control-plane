#!/usr/bin/env python3
"""Verify metadata evidence and two-key individual PoC self-attestation; never deploy."""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters.financial_pilot_evidence import (
    load_pilot_evidence,
    load_pilot_scope,
    verify_pilot_reviews,
)
from regulated_ai.application.accept_financial_pilot import AcceptFinancialPilot


def main(argv: Sequence[str] | None = None) -> int:
    """Emit a reproducible acceptance report or explicit blocking findings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--review", type=Path, action="append", default=[])
    parser.add_argument("--trust-store", type=Path)
    parser.add_argument("--evaluated-at", help="UTC clock; omitted uses current UTC")
    args = parser.parse_args(argv)
    try:
        now = (
            datetime.now(UTC)
            if args.evaluated_at is None
            else datetime.fromisoformat(args.evaluated_at)
        )
        if len(args.evidence) > 32 or len(args.review) > 16:
            raise ValueError("Pilot evidence count exceeds limit")
        if args.review and args.trust_store is None:
            raise ValueError("Pilot review requires a deployment-owned trust store")
        scope = load_pilot_scope(args.scope)
        evidence = tuple(load_pilot_evidence(path) for path in args.evidence)
        reviews = (
            ()
            if not args.review
            else verify_pilot_reviews(
                tuple(args.review),
                args.trust_store,
                evaluated_at=now,
            )
        )
        result = AcceptFinancialPilot().execute(
            scope=scope, evidence=evidence, reviews=reviews, evaluated_at=now
        )
    except Exception as exc:
        print(f"Financial pilot acceptance failed closed ({type(exc).__name__})", file=sys.stderr)
        return 1
    report = {
        "schema_version": "1",
        "status": "POC_VERIFIED" if result.accepted else "POC_BLOCKED",
        "evaluated_at": now.isoformat(),
        "scope_digest": result.scope_digest,
        "bundle_digest": result.bundle_digest,
        "findings": result.findings,
        "scope": "Two-key self-attestation by an individual PoC author over referenced "
        "non-production evidence; not independent review, production authorization or compliance.",
    }
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if result.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
