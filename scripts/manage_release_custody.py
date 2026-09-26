#!/usr/bin/env python3
"""Create or verify a content-addressed offline release-custody archive."""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters.release_custody import (
    ReleaseCustodyArtifactKind,
    ReleaseCustodyError,
    ReleaseCustodyIdentity,
    create_release_custody,
    verify_release_custody,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Create a new archive or verify an existing archive without external calls."""
    parser = argparse.ArgumentParser(description="Manage metadata-only release artifact custody.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="Create a new content-addressed archive.")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--archive-id", required=True)
    create.add_argument("--created-at", required=True)
    create.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="KIND=PATH",
        help="Allowlisted artifact kind and local JSON/YAML path; repeat for every artifact.",
    )
    verify = subparsers.add_parser("verify", help="Verify a custody archive recursively.")
    verify.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "create":
            identity = create_release_custody(
                args.output,
                archive_id=args.archive_id,
                created_at=_parse_utc(args.created_at),
                artifacts=tuple(_parse_artifact(value) for value in args.artifact),
            )
        else:
            identity = verify_release_custody(args.archive)
    except (ReleaseCustodyError, ValueError) as exc:
        print(f"Release custody failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_identity_payload(identity), sort_keys=True, separators=(",", ":")))
    return 0


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Custody creation time is not valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("Custody creation time must be timezone-aware UTC")
    return parsed


def _parse_artifact(value: str) -> tuple[ReleaseCustodyArtifactKind, Path]:
    kind_value, separator, path_value = value.partition("=")
    if not separator or not path_value:
        raise ValueError("Custody artifact must use KIND=PATH")
    try:
        kind = ReleaseCustodyArtifactKind(kind_value)
    except ValueError as exc:
        raise ValueError("Custody artifact kind is not supported") from exc
    return kind, Path(path_value)


def _identity_payload(identity: ReleaseCustodyIdentity) -> dict[str, object]:
    return {
        "schema_version": "1",
        "status": "CUSTODY_VERIFIED",
        "archive_id": identity.archive_id,
        "created_at": identity.created_at.isoformat(),
        "evidence_bundle_digest": identity.evidence_bundle_digest,
        "authorization_digest": identity.authorization_digest,
        "manifest_digest": identity.manifest_digest,
        "artifact_count": identity.artifact_count,
        "custody_scope": (
            "Local content-addressed retention and tamper detection for metadata-only release "
            "artifacts; this does not provide remote timestamping, immutable storage or backup."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
