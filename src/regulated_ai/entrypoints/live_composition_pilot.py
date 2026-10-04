"""Run one fixed synthetic request through the opt-in governed gateway path."""

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from regulated_ai.adapters.pilot_profile import FinancialPilotProfile, load_pilot_profile
from regulated_ai.domain import (
    AssuranceLevel,
    DataClassification,
    DataItem,
    DecisionOutcome,
    EnforcementStatus,
    EvaluationContext,
    Jurisdiction,
    ObligationType,
    Purpose,
    Sector,
)
from regulated_ai.entrypoints.api import Runtime, build_runtime
from regulated_ai.entrypoints.logging import configure_logging

_SAFE_CORRELATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SAFE_ENVIRONMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SYNTHETIC_DOCUMENT = "synthetic-customer-document"
_SYNTHETIC_QUESTION = "synthetic support availability question"


class LiveCompositionPilotError(ValueError):
    """The live composition proof failed closed."""


def run_live_composition_pilot(
    runtime: Runtime,
    *,
    correlation_id: str,
    profile: FinancialPilotProfile | None = None,
) -> dict[str, object]:
    """Execute one fixed synthetic inference and return metadata-only proof."""
    if _SAFE_CORRELATION_ID.fullmatch(correlation_id) is None:
        raise LiveCompositionPilotError("Pilot correlation ID is invalid")
    if runtime.mock_execution is not None:
        raise LiveCompositionPilotError("Pilot requires gateway execution mode")

    selected = profile or _demo_profile()
    result = runtime.enforcer.execute(_pilot_context(correlation_id, selected))
    metadata = result.provider_call_metadata
    if (
        result.decision is not DecisionOutcome.ALLOW_WITH_TRANSFORMATION
        or result.status is not EnforcementStatus.EXECUTED
        or result.output_digest is None
        or result.provider_execution_id is None
        or not result.provider_execution_id.startswith("gw_")
        or metadata is None
        or metadata.provider != selected.gateway_provider
        or metadata.cached
        or (selected.gateway_model is not None and metadata.model != selected.gateway_model)
        or (
            selected.gateway_deployment is not None
            and metadata.deployment != selected.gateway_deployment
        )
        or result.tool_proposals
        or len(result.transformation_receipts) != 1
        or result.transformation_receipts[0].target != "customer_document"
        or result.transformation_receipts[0].type is not ObligationType.TOKENIZE
    ):
        raise LiveCompositionPilotError("Pilot enforcement result is inconsistent")

    timeline = runtime.operator_timeline.execute(result.enforcement_id)
    if (
        timeline.enforcement_id != result.enforcement_id
        or timeline.evidence_id != result.evaluation_evidence_id
        or timeline.correlation_id != correlation_id
        or timeline.provider_target != selected.target.identifier
        or not timeline.provider_context_complete
        or not timeline.history_complete
        or timeline.attention_codes
        or timeline.actions_truncated
        or timeline.events_truncated
        or tuple(stage.status for stage in timeline.stages)
        != (DecisionOutcome.ALLOW_WITH_TRANSFORMATION.value, EnforcementStatus.EXECUTED.value)
    ):
        raise LiveCompositionPilotError("Pilot operator timeline is inconsistent")

    core: dict[str, object] = {
        "schema_version": "2",
        "status": "LIVE_COMPOSITION_VERIFIED",
        "observed_at": datetime.now(UTC).isoformat(),
        "profile_digest": selected.digest,
        "provider_profile": selected.provider,
        "policy_set_version": selected.policy_set_version,
        "correlation_id": correlation_id,
        "control_pack": {
            "id": runtime.control_pack.pack_id,
            "version": runtime.control_pack.pack_version,
            "signing_key_id": runtime.control_pack.signing_key_id,
            "payload_digest": runtime.control_pack.payload_digest,
        },
        "enforcement": {
            "enforcement_id": result.enforcement_id,
            "evaluation_id": result.evaluation_id,
            "evidence_id": result.evaluation_evidence_id,
            "decision": result.decision.value,
            "status": result.status.value,
            "output_digest": result.output_digest,
            "provider_execution_id": result.provider_execution_id,
            "transformed_fields": [receipt.target for receipt in result.transformation_receipts],
            "transformation_types": [
                receipt.type.value for receipt in result.transformation_receipts
            ],
        },
        "gateway": {
            "gateway_request_id": metadata.gateway_request_id,
            "routing_decision_id": metadata.routing_decision_id,
            "policy_id": metadata.policy_id,
            "policy_version": metadata.policy_version,
            "provider": metadata.provider,
            "model": metadata.model,
            "deployment": metadata.deployment,
            "latency_ms": metadata.latency_ms,
            "attempt_number": metadata.attempt_number,
            "fallback_index": metadata.fallback_index,
            "cached": metadata.cached,
        },
        "operator_timeline": {
            "history_complete": timeline.history_complete,
            "provider_context_complete": timeline.provider_context_complete,
            "stage_statuses": [stage.status for stage in timeline.stages],
            "lifecycle_event_count": len(timeline.lifecycle_events),
            "attention_codes": [item.value for item in timeline.attention_codes],
        },
        "data_handling": {
            "input_profile": "FIXED_SYNTHETIC",
            "request_content_persisted": False,
            "model_output_persisted": False,
            "model_output_returned": False,
            "tool_execution_enabled": False,
        },
        "scope": (
            "One opt-in non-production gateway/provider composition proof using fixed synthetic "
            "input; this report does not establish provider compliance, production readiness or "
            "live enterprise-tool authority."
        ),
    }
    encoded = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {**core, "report_digest": f"sha256:{hashlib.sha256(encoded).hexdigest()}"}


def main(argv: Sequence[str] | None = None) -> int:
    """Build the configured runtime and print one metadata-only pilot report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--correlation-prefix", default="pilot")
    parser.add_argument("--profile", type=Path, help="Reviewed non-secret financial pilot JSON")
    args = parser.parse_args(argv)

    if os.environ.get("REGULAAI_EXECUTION_MODE", "mock").strip().casefold() != "gateway":
        print("Live composition pilot failed: gateway execution mode is required", file=sys.stderr)
        return 1
    environment = os.environ.get("REGULAAI_ENVIRONMENT", "").strip().casefold()
    if _SAFE_ENVIRONMENT.fullmatch(environment) is None or environment in {"prod", "production"}:
        print(
            "Live composition pilot failed: an explicit non-production environment is required",
            file=sys.stderr,
        )
        return 1
    if not any(
        os.environ.get(name, "").strip()
        for name in ("REGULAAI_EVIDENCE_DB", "REGULAAI_DATABASE_URL")
    ):
        print(
            "Live composition pilot failed: a dedicated evidence database is required",
            file=sys.stderr,
        )
        return 1

    runtime: Runtime | None = None
    try:
        profile = load_pilot_profile(args.profile) if args.profile is not None else _demo_profile()
        if args.profile is not None and (
            os.environ.get("REGULAAI_GATEWAY_ALLOWED_TARGET") != profile.target.identifier
            or os.environ.get("REGULAAI_GATEWAY_EXPECTED_PROVIDER") != profile.gateway_provider
            or profile.gateway_model is None
            or profile.gateway_deployment is None
        ):
            raise LiveCompositionPilotError("Pilot and gateway bindings differ")
        configure_logging(
            service="regulaai-live-composition-pilot",
            environment=environment,
            version="0.1.0",
            stream=sys.stderr,
        )
        runtime = build_runtime()
        correlation_id = f"{args.correlation_prefix}-{uuid4().hex}"
        report = run_live_composition_pilot(runtime, correlation_id=correlation_id, profile=profile)
    except Exception as exc:
        print(f"Live composition pilot failed closed ({type(exc).__name__})", file=sys.stderr)
        return 1
    finally:
        if runtime is not None and runtime.telemetry is not None:
            runtime.telemetry.force_flush(timeout_seconds=2.0)
            runtime.telemetry.shutdown(timeout_seconds=2.0)

    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


def _demo_profile() -> FinancialPilotProfile:
    return FinancialPilotProfile(
        profile_id="legacy-openai-demo",
        provider="openai",
        gateway_provider="openai",
        policy_set_version="br-financial-demo@1.0.0",
        organization_assertions={
            "eligible_organization_required": True,
            "endpoint_or_feature_must_be_zdr_eligible": True,
        },
    )


def _pilot_context(correlation_id: str, profile: FinancialPilotProfile) -> EvaluationContext:
    return EvaluationContext(
        correlation_id=correlation_id,
        jurisdiction=Jurisdiction("BR"),
        sector=Sector("financial_services"),
        purpose=Purpose("customer_support"),
        operation_kind="external_inference",
        assurance_level=AssuranceLevel.HIGH,
        provider=profile.target,
        data_items=(
            DataItem(
                field="customer_document",
                value=_SYNTHETIC_DOCUMENT,
                supplied_labels=(DataClassification.PERSONAL_DIRECT_IDENTIFIER,),
            ),
            DataItem(field="question", value=_SYNTHETIC_QUESTION),
        ),
        tools=(),
        policy_set_version=profile.policy_set_version,
        organization_assertions=tuple(sorted(profile.organization_assertions.items())),
        fallback_providers=(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
