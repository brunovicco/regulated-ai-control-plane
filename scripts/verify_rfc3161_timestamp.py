#!/usr/bin/env python3
"""Verify one RFC 3161 request/response pair against exact artifact bytes."""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters import (
    Rfc3161TimestampError,
    TimestampSubjectKind,
    verify_rfc3161_timestamp,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify offline timestamp evidence and emit a metadata-only report."""
    parser = argparse.ArgumentParser(
        description="Verify an RFC 3161 timestamp for one exact artifact."
    )
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--ca-bundle", type=Path, required=True)
    parser.add_argument("--untrusted-certificates", type=Path)
    parser.add_argument("--subject-kind", choices=tuple(TimestampSubjectKind), required=True)
    parser.add_argument("--policy-oid", action="append", required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--minimum-generated-at")
    args = parser.parse_args(argv)

    try:
        identity = verify_rfc3161_timestamp(
            args.artifact,
            args.request,
            args.response,
            args.ca_bundle,
            subject_kind=TimestampSubjectKind(args.subject_kind),
            allowed_policy_oids=tuple(args.policy_oid),
            evaluated_at=_parse_utc(args.evaluated_at),
            minimum_generated_at=(
                _parse_utc(args.minimum_generated_at) if args.minimum_generated_at else None
            ),
            untrusted_certificates_path=args.untrusted_certificates,
        )
    except (Rfc3161TimestampError, ValueError) as exc:
        print(f"RFC 3161 timestamp verification failed: {exc}", file=sys.stderr)
        return 1

    core: dict[str, object] = {
        "schema_version": "1",
        "status": "RFC3161_TIMESTAMP_VERIFIED",
        "subject_kind": identity.subject_kind.value,
        "subject_digest": identity.subject_digest,
        "hash_algorithm": identity.hash_algorithm,
        "policy_oid": identity.policy_oid,
        "serial_number": identity.serial_number,
        "generated_at": identity.generated_at.isoformat(),
        "request_digest": identity.request_digest,
        "response_digest": identity.response_digest,
        "signer_certificate_digest": identity.signer_certificate_digest,
        "signature_digest": identity.signature_digest,
        "timestamp_scope": (
            "Offline RFC 3161 request, response, message-imprint, nonce, policy and PKIX "
            "verification for exact artifact bytes; this report does not acquire timestamps, "
            "perform online revocation checks or select a provider."
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
        raise ValueError("RFC 3161 time boundary is not valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("RFC 3161 time boundary must be timezone-aware UTC")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
