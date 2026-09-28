"""Metadata-only CloudEvents and OTLP spans for control lifecycle events."""

import json
import re
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, suppress
from datetime import UTC, datetime
from typing import Any, Protocol

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
        "approval.validated",
        "approval.consumed",
        "transformation.applied",
        "enforcement.blocked",
        "execution.completed",
        "enforcement.completed",
        "enforcement.failed",
        "tool_action.started",
        "tool_action.waiting_approval",
        "tool_action.approval_validated",
        "tool_action.approval_consumed",
        "tool_action.completed",
        "tool_action.failed",
        "tool_result.accepted",
        "tool_result.rejected",
    }
)
_METADATA_KEYS = frozenset(
    {
        "capability_key",
        "approval_id",
        "action_id",
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
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SOURCE = "urn:regulaai:control-plane"

type CloudEvent = dict[str, object]
type CloudEventSink = Callable[[Mapping[str, object]], None]


class ControlEventTracer(Protocol):
    """Minimal safe tracing surface needed by the control-event observer."""

    def start_as_current_span(
        self, name: str, *, attributes: Mapping[str, Any] | None = None
    ) -> AbstractContextManager[object]:
        """Start one already-sanitized metadata span."""
        ...


def encode_cloudevent(event: Mapping[str, object]) -> bytes:
    """Encode a sanitized CloudEvent as deterministic structured JSON."""
    _validate_cloudevent(event)
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _validate_cloudevent(event: Mapping[str, object]) -> None:
    expected_keys = {
        "specversion",
        "id",
        "source",
        "type",
        "time",
        "datacontenttype",
        "data",
    }
    event_id = event.get("id")
    event_type = event.get("type")
    event_time = event.get("time")
    data = event.get("data")
    if (
        set(event) != expected_keys
        or event.get("specversion") != "1.0"
        or not isinstance(event_id, str)
        or _EVENT_ID.fullmatch(event_id) is None
        or event.get("source") != _SOURCE
        or not isinstance(event_type, str)
        or not event_type.startswith("com.regulaai.control.")
        or event_type.removeprefix("com.regulaai.control.") not in _EVENTS
        or not isinstance(event_time, str)
        or event.get("datacontenttype") != "application/json"
        or not isinstance(data, dict)
    ):
        raise ValueError("CloudEvent envelope is invalid")
    try:
        parsed_time = datetime.fromisoformat(event_time)
    except ValueError as exc:
        raise ValueError("CloudEvent time is invalid") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() != UTC.utcoffset(parsed_time):
        raise ValueError("CloudEvent time must be timezone-aware UTC")
    if any(
        key not in _METADATA_KEYS or not isinstance(value, str) or not value or len(value) > 128
        for key, value in data.items()
    ):
        raise ValueError("CloudEvent data is not metadata-only")


class StructuredEvaluationObserver:
    """Emit only stable event names and bounded identifier metadata."""

    def __init__(
        self,
        *,
        tracer: ControlEventTracer | None = None,
        sink: CloudEventSink | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Bind optional safe telemetry and a metadata-only CloudEvent sink."""
        self._tracer = tracer
        self._sink = sink or _log_cloudevent
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def emit(self, event: str, metadata: Mapping[str, str]) -> None:
        """Drop unsafe fields and isolate all observability failures from policy."""
        if event not in _EVENTS:
            return
        safe = {
            key: value[:128]
            for key, value in metadata.items()
            if key in _METADATA_KEYS and value and len(value) <= 128
        }
        occurred_at = self._clock()
        event_id = self._id_factory()
        if (
            occurred_at.tzinfo is None
            or occurred_at.utcoffset() != UTC.utcoffset(occurred_at)
            or _EVENT_ID.fullmatch(event_id) is None
        ):
            return
        cloud_event: CloudEvent = {
            "specversion": "1.0",
            "id": event_id,
            "source": _SOURCE,
            "type": f"com.regulaai.control.{event}",
            "time": occurred_at.isoformat(),
            "datacontenttype": "application/json",
            "data": safe,
        }
        with suppress(Exception):
            self._sink(cloud_event)
        self._emit_span(event, event_id, safe)

    def _emit_span(self, event: str, event_id: str, metadata: Mapping[str, str]) -> None:
        tracer = self._tracer
        if tracer is None:
            return
        outcome = metadata.get("outcome") or metadata.get("decision") or metadata.get("status")
        attributes: dict[str, Any] = {
            "app.operation": event,
            "cloudevents.event_id": event_id,
            "cloudevents.event_source": _SOURCE,
            "cloudevents.event_spec_version": "1.0",
            "cloudevents.event_type": f"com.regulaai.control.{event}",
        }
        if outcome is not None:
            attributes["app.outcome"] = outcome
        with (
            suppress(Exception),
            tracer.start_as_current_span("control.lifecycle", attributes=attributes),
        ):
            pass


def _log_cloudevent(event: Mapping[str, object]) -> None:
    structlog.get_logger("regulated_ai.control_events").info(
        "control.lifecycle", cloudevent=dict(event)
    )
