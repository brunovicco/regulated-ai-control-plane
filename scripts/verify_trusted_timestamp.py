#!/usr/bin/env python3
"""Verify one provider-neutral signed time-authority receipt."""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters import (
    TimestampSubjectKind,
    TrustedTimestampError,
    verify_trusted_timestamp,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify exact artifact bytes and emit metadata-only timestamp evidence."""
    parser = argparse.ArgumentParser(
        description="Verify a signed external time-authority receipt for one artifact."
    )
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--subject-kind", choices=tuple(TimestampSubjectKind), required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--minimum-issued-at")
    args = parser.parse_args(argv)

    try:
        identity = verify_trusted_timestamp(
            args.artifact,
            args.receipt,
            args.trust_store,
            expected_subject_kind=TimestampSubjectKind(args.subject_kind),
            evaluated_at=_parse_utc(args.evaluated_at),
            minimum_issued_at=(
                _parse_utc(args.minimum_issued_at) if args.minimum_issued_at else None
            ),
        )
    except (TrustedTimestampError, ValueError) as exc:
        print(f"Trusted timestamp verification failed: {exc}", file=sys.stderr)
        return 1

    core: dict[str, object] = {
        "schema_version": "1",
        "status": "TRUSTED_TIMESTAMP_VERIFIED",
        "receipt_id": identity.receipt_id,
        "subject_kind": identity.subject_kind.value,
        "subject_digest": identity.subject_digest,
        "issued_at": identity.issued_at.isoformat(),
        "authority_id": identity.authority_id,
        "signing_key_id": identity.signing_key_id,
        "receipt_digest": identity.receipt_digest,
        "signature_digest": identity.signature_digest,
        "timestamp_scope": (
            "Authenticated external authority assertion for one exact artifact digest; this report "
            "does not contact an authority, prove service availability or establish immutable "
            "retention."
        ),
    }
    encoded = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    print(
        json.dumps(
            {**core, "report_digest": f"sha256:{hashlib.sha256(encoded).hexdigest()}"},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Timestamp boundary is not valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("Timestamp boundary must be timezone-aware UTC")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
