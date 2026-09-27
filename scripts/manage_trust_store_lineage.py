#!/usr/bin/env python3
"""Create and verify rollback-resistant trust-store lineage checkpoints."""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters.trust_store_lineage import (
    TrustStoreCheckpointIdentity,
    TrustStoreKind,
    TrustStoreLineageError,
    create_trust_store_checkpoint,
    verify_trust_store_checkpoint,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Create or verify one checkpoint using explicit trusted lineage inputs."""
    parser = argparse.ArgumentParser(description="Manage public trust-store lineage checkpoints.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--trust-store", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--store-id", required=True)
    create.add_argument("--store-kind", choices=tuple(TrustStoreKind), required=True)
    create.add_argument("--sequence", type=int, required=True)
    create.add_argument("--issued-at", required=True)
    create.add_argument("--signing-key-id", required=True)
    create.add_argument("--private-key", type=Path, required=True)
    create.add_argument("--previous-checkpoint", type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--trust-store", type=Path, required=True)
    verify.add_argument("--checkpoint", type=Path, required=True)
    verify.add_argument("--signing-key-id", required=True)
    verify.add_argument("--public-key", type=Path, required=True)
    verify.add_argument("--previous-checkpoint", type=Path)
    verify.add_argument("--minimum-sequence", type=int)
    verify.add_argument("--expected-checkpoint-digest")
    args = parser.parse_args(argv)

    try:
        if args.command == "create":
            identity = create_trust_store_checkpoint(
                args.trust_store,
                args.output,
                store_id=args.store_id,
                store_kind=TrustStoreKind(args.store_kind),
                sequence=args.sequence,
                issued_at=_parse_utc(args.issued_at),
                signing_key_id=args.signing_key_id,
                private_key_path=args.private_key,
                previous_checkpoint_path=args.previous_checkpoint,
            )
        else:
            identity = verify_trust_store_checkpoint(
                args.trust_store,
                args.checkpoint,
                public_key_path=args.public_key,
                signing_key_id=args.signing_key_id,
                previous_checkpoint_path=args.previous_checkpoint,
                minimum_sequence=args.minimum_sequence,
                expected_checkpoint_digest=args.expected_checkpoint_digest,
            )
    except (TrustStoreLineageError, ValueError) as exc:
        print(f"Trust-store lineage failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(_identity_payload(identity), sort_keys=True, separators=(",", ":")))
    return 0


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Checkpoint issue time is not valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("Checkpoint issue time must be timezone-aware UTC")
    return parsed


def _identity_payload(identity: TrustStoreCheckpointIdentity) -> dict[str, object]:
    return {
        "schema_version": "1",
        "status": "TRUST_STORE_CHECKPOINT_VERIFIED",
        "store_id": identity.store_id,
        "store_kind": identity.store_kind.value,
        "sequence": identity.sequence,
        "issued_at": identity.issued_at.isoformat(),
        "trust_store_digest": identity.trust_store_digest,
        "previous_checkpoint_digest": identity.previous_checkpoint_digest,
        "checkpoint_digest": identity.checkpoint_digest,
        "signing_key_id": identity.signing_key_id,
        "signature_digest": identity.signature_digest,
        "verification_scope": (
            "Exact public trust-store bytes and caller-pinned lineage constraints; this is not "
            "remote distribution, an external timestamp, immutable storage or private-key custody."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
