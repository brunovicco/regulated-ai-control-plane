#!/usr/bin/env python3
"""Verify signed quorum attestations without promoting or deploying a release."""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters.promotion_attestations import (
    PromotionAttestationBoundaryError,
    load_promotion_policy,
    load_release_evidence_bundle,
    verify_promotion_attestations,
)
from regulated_ai.application import AuthorizeControlPackPromotion, ReleasePromotionError
from regulated_ai.domain import ControlPackPromotionReport, ControlPackReleaseIdentity


def main(argv: Sequence[str] | None = None) -> int:
    """Evaluate authenticated promotion authority for one exact release bundle."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify signed release-promotion attestations against an explicit quorum policy."
        )
    )
    parser.add_argument("--evidence-bundle", type=Path, required=True)
    parser.add_argument("--promotion-policy", type=Path, required=True)
    parser.add_argument("--attestation-trust-store", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, action="append", default=[])
    parser.add_argument(
        "--evaluated-at",
        required=True,
        help="Fixed timezone-aware UTC timestamp used for deterministic validity checks.",
    )
    args = parser.parse_args(argv)

    try:
        evaluated_at = _parse_utc(args.evaluated_at)
        evidence = load_release_evidence_bundle(args.evidence_bundle)
        policy = load_promotion_policy(args.promotion_policy)
        attestations = verify_promotion_attestations(
            tuple(args.attestation), args.attestation_trust_store
        )
        report = AuthorizeControlPackPromotion().execute(
            evidence=evidence,
            policy=policy,
            attestations=attestations,
            evaluated_at=evaluated_at,
        )
    except (PromotionAttestationBoundaryError, ReleasePromotionError, ValueError) as exc:
        print(f"Control-pack promotion authorization failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_report_payload(report), sort_keys=True, separators=(",", ":")))
    return 0 if report.authorized else 2


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Promotion evaluation time is not valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("Promotion evaluation time must be timezone-aware UTC")
    return parsed


def _report_payload(report: ControlPackPromotionReport) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": "1",
        "status": "PROMOTION_AUTHORIZED" if report.authorized else "PROMOTION_BLOCKED",
        "bundle_digest": report.evidence.bundle_digest,
        "base_pack": _identity_payload(report.evidence.base),
        "candidate_pack": _identity_payload(report.evidence.candidate),
        "policy": {
            "id": report.policy.policy_id,
            "version": report.policy.policy_version,
            "required_roles": list(report.policy.required_roles),
            "minimum_approvals": report.policy.minimum_approvals,
            "digest": report.policy.policy_digest,
        },
        "evaluated_at": report.evaluated_at.isoformat(),
        "attestations": [
            {
                "attestation_id": item.attestation_id,
                "decision": item.decision.value,
                "role": item.role,
                "signing_key_id": item.key_id,
                "issued_at": item.issued_at.isoformat(),
                "expires_at": item.expires_at.isoformat(),
                "attestation_digest": item.attestation_digest,
                "signature_digest": item.signature_digest,
            }
            for item in report.attestations
        ],
        "findings": [
            {"code": item.code.value, "subject_id": item.subject_id} for item in report.findings
        ],
        "authorization_scope": (
            "Authenticated offline approval quorum for one exact complete evidence bundle; this "
            "report does not sign, promote, distribute, deploy or assert compliance or safety."
        ),
    }
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {
        **core,
        "authorization_digest": f"sha256:{hashlib.sha256(canonical).hexdigest()}",
    }


def _identity_payload(identity: ControlPackReleaseIdentity) -> dict[str, str]:
    return {
        "id": identity.pack_id,
        "version": identity.pack_version,
        "signing_key_id": identity.signing_key_id,
        "payload_digest": identity.payload_digest,
    }


if __name__ == "__main__":
    raise SystemExit(main())
