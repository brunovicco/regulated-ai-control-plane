#!/usr/bin/env python3
"""Create or verify a deterministic OCI image layout for release evidence."""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters import ReleaseCustodyArtifactKind
from regulated_ai.adapters.oci_evidence import (
    OciEvidenceError,
    OciEvidenceIdentity,
    create_oci_evidence_layout,
    verify_oci_evidence_layout,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Create or verify an OCI evidence layout and emit its stable identity."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--package-ref", required=True)
    create.add_argument("--created-at", required=True)
    create.add_argument("--artifact", action="append", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--layout", type=Path, required=True)
    verify.add_argument("--package-ref")
    args = parser.parse_args(argv)

    try:
        if args.command == "create":
            identity = create_oci_evidence_layout(
                args.output,
                package_ref=args.package_ref,
                created_at=_parse_utc(args.created_at),
                artifacts=tuple(_parse_artifact(item) for item in args.artifact),
            )
        else:
            identity = verify_oci_evidence_layout(
                args.layout, expected_package_ref=args.package_ref
            )
    except (OciEvidenceError, ValueError) as exc:
        print(f"OCI evidence operation failed: {exc}", file=sys.stderr)
        return 1
    print(_identity_json(identity))
    return 0


def _parse_artifact(value: str) -> tuple[ReleaseCustodyArtifactKind, Path]:
    try:
        raw_kind, raw_path = value.split("=", 1)
        return ReleaseCustodyArtifactKind(raw_kind), Path(raw_path)
    except ValueError as exc:
        raise ValueError("OCI artifact must use KIND=PATH with an allowlisted kind") from exc


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("OCI evidence creation time is not valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("OCI evidence creation time must be timezone-aware UTC")
    return parsed


def _identity_json(identity: OciEvidenceIdentity) -> str:
    return json.dumps(
        {
            "schema_version": "1",
            "status": "OCI_EVIDENCE_VERIFIED",
            "package_ref": identity.package_ref,
            "created_at": identity.created_at.isoformat(),
            "manifest_digest": identity.manifest_digest,
            "config_digest": identity.config_digest,
            "artifact_count": identity.artifact_count,
            "distribution_scope": (
                "Verified local OCI image layout for metadata-only evidence; registry push, pull, "
                "authentication, authorization, retention and availability remain external."
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
