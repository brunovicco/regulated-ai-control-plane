#!/usr/bin/env python3
"""Verify signed runtime-loaded trust-store state for one checkpoint."""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters import (
    RuntimeTrustStateError,
    TrustStoreLineageError,
    load_runtime_trust_state_policy,
    verify_runtime_trust_state_attestations,
    verify_trust_store_checkpoint,
)
from regulated_ai.application import (
    RuntimeTrustStateVerificationError,
    VerifyRuntimeTrustState,
)
from regulated_ai.domain import RuntimeTrustStateReport


def main(argv: Sequence[str] | None = None) -> int:
    """Verify one signed checkpoint and fresh runtime-state coverage."""
    parser = argparse.ArgumentParser(
        description="Verify signed runtime trust-state coverage for a checkpoint."
    )
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-public-key", type=Path, required=True)
    parser.add_argument("--checkpoint-signing-key-id", required=True)
    parser.add_argument("--minimum-sequence", type=int)
    parser.add_argument("--expected-checkpoint-digest")
    parser.add_argument("--previous-checkpoint", type=Path)
    parser.add_argument("--runtime-policy", type=Path, required=True)
    parser.add_argument("--attestation-trust-store", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, action="append", default=[])
    parser.add_argument("--attestation-directory", type=Path, action="append", default=[])
    evaluation_time = parser.add_mutually_exclusive_group(required=True)
    evaluation_time.add_argument("--evaluated-at")
    evaluation_time.add_argument("--evaluated-at-now", action="store_true")
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
        policy = load_runtime_trust_state_policy(args.runtime_policy)
        attestation_paths = tuple(args.attestation) + tuple(
            path
            for directory in args.attestation_directory
            for path in _attestation_paths(directory)
        )
        attestations = verify_runtime_trust_state_attestations(
            attestation_paths, args.attestation_trust_store
        )
        report = VerifyRuntimeTrustState().execute(
            checkpoint_digest=checkpoint.checkpoint_digest,
            checkpoint_issued_at=checkpoint.issued_at,
            trust_store_digest=checkpoint.trust_store_digest,
            store_id=checkpoint.store_id,
            store_kind=checkpoint.store_kind.value,
            sequence=checkpoint.sequence,
            policy=policy,
            attestations=attestations,
            evaluated_at=datetime.now(UTC)
            if args.evaluated_at_now
            else _parse_utc(args.evaluated_at),
        )
    except (
        RuntimeTrustStateError,
        RuntimeTrustStateVerificationError,
        TrustStoreLineageError,
        ValueError,
    ) as exc:
        print(f"Runtime trust-state verification failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_report_payload(report), sort_keys=True, separators=(",", ":")))
    return 0 if report.current else 2


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Runtime evaluation time is not valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("Runtime evaluation time must be timezone-aware UTC")
    return parsed


def _attestation_paths(directory: Path) -> tuple[Path, ...]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Runtime attestation directory is not allowed")
    entries = tuple(sorted(directory.iterdir(), key=lambda item: item.name))
    if any(
        item.is_symlink() or not item.is_file() or item.suffix.lower() not in {".yaml", ".yml"}
        for item in entries
    ):
        raise ValueError("Runtime attestation directory contains an invalid entry")
    return entries


def _report_payload(report: RuntimeTrustStateReport) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": "1",
        "status": "RUNTIME_TRUST_STATE_CURRENT"
        if report.current
        else "RUNTIME_TRUST_STATE_BLOCKED",
        "checkpoint": {
            "digest": report.checkpoint_digest,
            "trust_store_digest": report.trust_store_digest,
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
            "minimum_attestations": report.policy.minimum_attestations,
            "maximum_age_seconds": report.policy.maximum_age_seconds,
        },
        "evaluated_at": report.evaluated_at.isoformat(),
        "attestations": [
            {
                "attestation_id": item.attestation_id,
                "target_id": item.target_id,
                "observed_at": item.observed_at.isoformat(),
                "signing_key_id": item.signing_key_id,
                "attestation_digest": item.attestation_digest,
                "signature_digest": item.signature_digest,
            }
            for item in report.attestations
        ],
        "findings": [
            {"code": item.code.value, "subject_id": item.subject_id} for item in report.findings
        ],
        "runtime_state_scope": (
            "Authenticated target assertions for one exact loaded trust-store digest; this report "
            "does not probe processes, prove continuous enforcement or mutate any target."
        ),
    }
    encoded = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {**core, "report_digest": f"sha256:{hashlib.sha256(encoded).hexdigest()}"}


if __name__ == "__main__":
    raise SystemExit(main())
