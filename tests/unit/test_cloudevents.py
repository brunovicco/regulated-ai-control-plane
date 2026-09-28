import json
from datetime import UTC, datetime

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from regulated_ai.adapters import (
    StructuredEvaluationObserver,
    encode_cloudevent,
)
from regulated_ai.adapters.observability import TelemetryLifecycle
from regulated_ai.entrypoints.api import _build_telemetry_lifecycle, _runtime_label


def _telemetry(exporter: InMemorySpanExporter) -> TelemetryLifecycle:
    return TelemetryLifecycle(
        service_name="regulaai-control-plane",
        service_version="1.2.3",
        environment="test",
        exporter_factory=lambda: exporter,
    )


def test_emits_cloud_event_and_correlated_metadata_only_otlp_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://collector.invalid/v1/traces")
    exporter = InMemorySpanExporter()
    telemetry = _telemetry(exporter)
    events: list[dict[str, object]] = []
    observer = StructuredEvaluationObserver(
        tracer=telemetry.initialize(),
        sink=lambda event: events.append(dict(event)),
        clock=lambda: datetime(2026, 9, 27, 18, tzinfo=UTC),
        id_factory=lambda: "evt-123",
    )

    observer.emit(
        "decision.produced",
        {
            "correlation_id": "corr-1",
            "decision": "DENY",
            "prompt": "forbidden content",
            "provider_target": "x" * 129,
        },
    )

    assert events == [
        {
            "specversion": "1.0",
            "id": "evt-123",
            "source": "urn:regulaai:control-plane",
            "type": "com.regulaai.control.decision.produced",
            "time": "2026-09-27T18:00:00+00:00",
            "datacontenttype": "application/json",
            "data": {"correlation_id": "corr-1", "decision": "DENY"},
        }
    ]
    encoded = encode_cloudevent(events[0])
    assert json.loads(encoded) == events[0]
    assert b"forbidden" not in encoded
    with pytest.raises(ValueError, match="metadata-only"):
        encode_cloudevent({**events[0], "data": {"prompt": "forbidden content"}})

    assert telemetry.force_flush(timeout_seconds=1)
    span = exporter.get_finished_spans()[0]
    assert span.name == "control.lifecycle"
    assert span.attributes == {
        "app.operation": "decision.produced",
        "app.outcome": "DENY",
        "cloudevents.event_id": "evt-123",
        "cloudevents.event_source": "urn:regulaai:control-plane",
        "cloudevents.event_spec_version": "1.0",
        "cloudevents.event_type": "com.regulaai.control.decision.produced",
    }
    assert telemetry.shutdown(timeout_seconds=1)


def test_unknown_invalid_or_failing_observability_never_changes_business_flow() -> None:
    events: list[dict[str, object]] = []
    observer = StructuredEvaluationObserver(
        sink=lambda event: events.append(dict(event)),
        clock=lambda: datetime(2026, 9, 27, 18, tzinfo=UTC),
        id_factory=lambda: "evt-1",
    )
    observer.emit("unknown.event", {"decision": "ALLOW"})
    assert events == []

    invalid = StructuredEvaluationObserver(
        sink=lambda event: events.append(dict(event)),
        clock=lambda: datetime(2026, 9, 27, 18),
        id_factory=lambda: "evt-2",
    )
    invalid.emit("decision.produced", {"decision": "ALLOW"})
    assert events == []

    def failing_sink(_event: object) -> None:
        raise RuntimeError("collector unavailable with sensitive detail")

    failing = StructuredEvaluationObserver(
        sink=failing_sink,
        clock=lambda: datetime(2026, 9, 27, 18, tzinfo=UTC),
        id_factory=lambda: "evt-3",
    )
    failing.emit("decision.produced", {"decision": "ALLOW"})


def test_runtime_telemetry_is_opt_in_and_runtime_labels_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "OTEL_SDK_DISABLED",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "REGULAAI_ENVIRONMENT",
    ):
        monkeypatch.delenv(name, raising=False)
    assert _build_telemetry_lifecycle(service_version="1.2.3", environment="test") is None

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert _build_telemetry_lifecycle(service_version="1.2.3", environment="test") is None

    monkeypatch.setenv("REGULAAI_ENVIRONMENT", "prod/br")
    with pytest.raises(ValueError, match="bounded identifier"):
        _runtime_label("REGULAAI_ENVIRONMENT", "local")
