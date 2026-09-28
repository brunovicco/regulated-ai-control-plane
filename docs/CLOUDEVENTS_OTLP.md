# CloudEvents and OTLP

Phase 6t turns the existing metadata-only lifecycle callbacks into portable CloudEvents and optional
OTLP spans. It does not add a broker client or make telemetry part of authorization.

## CloudEvent envelope

Structured logs use `control.lifecycle` with a nested `cloudevent` object:

```json
{
  "specversion": "1.0",
  "id": "7cfd65ec3dc94b698d8364b12f7ad87e",
  "source": "urn:regulaai:control-plane",
  "type": "com.regulaai.control.decision.produced",
  "time": "2026-09-27T18:00:00+00:00",
  "datacontenttype": "application/json",
  "data": {"correlation_id": "corr-1", "decision": "DENY"}
}
```

Only known lifecycle names and bounded identifier/outcome fields can enter `data`. Unknown,
oversized, nested or content-bearing fields are discarded. The canonical encoder is available for
an approved external log processor, but this service does not deliver to an event broker.

## Enable OTLP traces

Install `uv sync --extra observability` outside the deployment image, then set exactly the approved
OTLP HTTP endpoint configuration:

```text
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://collector.example/v1/traces
OTEL_SERVICE_NAME=regulaai-control-plane
REGULAAI_ENVIRONMENT=production
REGULAAI_SERVICE_VERSION=2026.09.27
```

Use environment-injected collector credentials supported by the approved collector/exporter; never
commit them. Validate TLS, workload identity, tenancy, residency, sampling, retention, deletion and
bounded timeout behavior. The Kubernetes reference needs a narrow DNS/HTTPS egress overlay because
its default NetworkPolicy denies all egress.

`OTEL_SDK_DISABLED=true` always disables exporter construction. With no trace/base endpoint, the
optional SDK is not imported. Startup fails clearly when an endpoint is configured without the
observability extra rather than silently claiming export.

## Data and failure boundary

Spans include only CloudEvent id/source/version/type, operation and optional outcome plus the three
approved service resource attributes. Trace context uses W3C `traceparent`/`tracestate`; baggage is
not accepted. Prompt/response/data values, tool arguments/results, arbitrary URLs, credentials,
exception messages/stacks and status descriptions are prohibited.

CloudEvent sink and OTLP exporter failures do not alter evaluation, enforcement or tool-action
results. Monitor exporter queues, rejected spans, log delivery and collector availability through a
separate operational path. Neither log emission nor successful OTLP export is durable audit proof.
