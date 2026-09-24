"""Metadata-only structured events for policy evaluation."""

from collections.abc import Mapping

import structlog

_EVENTS = frozenset(
    {
        "evaluation.started",
        "policy.matched",
        "capability.resolved",
        "decision.produced",
        "evidence.persisted",
        "evaluation.failed",
        "enforcement.started",
        "transformation.applied",
        "enforcement.blocked",
        "execution.completed",
        "enforcement.completed",
        "enforcement.failed",
    }
)
_METADATA_KEYS = frozenset(
    {
        "capability_key",
        "correlation_id",
        "decision",
        "error_type",
        "evidence_id",
        "evaluation_id",
        "provider_execution_id",
        "outcome",
        "policy_id",
        "provider_target",
        "status",
        "target_field",
        "transformation_type",
    }
)


class StructuredEvaluationObserver:
    """Emit only stable event names and bounded identifier metadata."""

    def emit(self, event: str, metadata: Mapping[str, str]) -> None:
        """Drop unknown event names/fields and truncate identifier values."""
        if event not in _EVENTS:
            return
        safe = {
            key: value[:128]
            for key, value in metadata.items()
            if key in _METADATA_KEYS and len(value) <= 128
        }
        structlog.get_logger("regulated_ai.evaluation").info(event, **safe)
