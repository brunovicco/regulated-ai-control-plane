#!/usr/bin/env python3
"""Verify signed consumer acknowledgements for one trust-store checkpoint."""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters import (
    TrustStoreAcknowledgementError,
    TrustStoreLineageError,
    load_trust_store_rollout_policy,
    verify_trust_store_acknowledgements,
    verify_trust_store_checkpoint,
)
from regulated_ai.application import TrustStoreRolloutError, VerifyTrustStoreRollout
from regulated_ai.domain import TrustStoreRolloutReport


def main(argv: Sequence[str] | None = None) -> int:
    """Verify one signed checkpoint and its consumer acknowledgement coverage."""
    parser = argparse.ArgumentParser(
        description="Verify acknowledgement coverage for a signed trust-store checkpoint."
    )
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-public-key", type=Path, required=True)
    parser.add_argument("--checkpoint-signing-key-id", required=True)
    parser.add_argument("--minimum-sequence", type=int)
    parser.add_argument("--expected-checkpoint-digest")
    parser.add_argument("--previous-checkpoint", type=Path)
    parser.add_argument("--rollout-policy", type=Path, required=True)
    parser.add_argument("--acknowledgement-trust-store", type=Path, required=True)
    parser.add_argument("--acknowledgement", type=Path, action="append", default=[])
    parser.add_argument("--evaluated-at", required=True)
    args = parser.parse_args(argv)

    try:
        checkpoint = verify_trust_store_checkpoint(
            args.trust_store,
            args.checkpoint,
            public_key_path=args.checkpoint_public_key,
            signing_key_id=args.checkpoint_signing_key_id,
            previous_checkpoint_path=args.previous_checkpoint,
            minimum_sequence=args.minimum_sequence,
            expected_checkpoint_digest=args.expected_checkpoint_digest,
        )
        policy = load_trust_store_rollout_policy(args.rollout_policy)
        acknowledgements = verify_trust_store_acknowledgements(
            tuple(args.acknowledgement), args.acknowledgement_trust_store
        )
        report = VerifyTrustStoreRollout().execute(
            checkpoint_digest=checkpoint.checkpoint_digest,
            store_id=checkpoint.store_id,
            store_kind=checkpoint.store_kind.value,
            sequence=checkpoint.sequence,
            policy=policy,
            acknowledgements=acknowledgements,
            evaluated_at=_parse_utc(args.evaluated_at),
        )
    except (
        TrustStoreAcknowledgementError,
        TrustStoreLineageError,
        TrustStoreRolloutError,
        ValueError,
    ) as exc:
        print(f"Trust-store rollout verification failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_report_payload(report), sort_keys=True, separators=(",", ":")))
    return 0 if report.complete else 2


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Rollout evaluation time is not valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("Rollout evaluation time must be timezone-aware UTC")
    return parsed


def _report_payload(report: TrustStoreRolloutReport) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": "1",
        "status": "ROLLOUT_ACKNOWLEDGED" if report.complete else "ROLLOUT_INCOMPLETE",
        "checkpoint": {
            "digest": report.checkpoint_digest,
            "store_id": report.store_id,
            "store_kind": report.store_kind,
            "sequence": report.sequence,
        },
        "policy": {
            "id": report.policy.policy_id,
            "version": report.policy.policy_version,
            "digest": report.policy.policy_digest,
            "allowed_target_ids": list(report.policy.allowed_target_ids),
            "required_target_ids": list(report.policy.required_target_ids),
            "minimum_acknowledgements": report.policy.minimum_acknowledgements,
        },
        "evaluated_at": report.evaluated_at.isoformat(),
        "acknowledgements": [
            {
                "acknowledgement_id": item.acknowledgement_id,
                "target_id": item.target_id,
                "accepted_at": item.accepted_at.isoformat(),
                "signing_key_id": item.signing_key_id,
                "acknowledgement_digest": item.acknowledgement_digest,
                "signature_digest": item.signature_digest,
            }
            for item in report.acknowledgements
        ],
        "findings": [
            {"code": item.code.value, "subject_id": item.subject_id} for item in report.findings
        ],
        "rollout_scope": (
            "Authenticated consumer acceptance of one exact trust-store checkpoint; this report "
            "does not distribute configuration, prove runtime adoption or mutate any target."
        ),
    }
    encoded = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {**core, "report_digest": f"sha256:{hashlib.sha256(encoded).hexdigest()}"}


if __name__ == "__main__":
    raise SystemExit(main())
