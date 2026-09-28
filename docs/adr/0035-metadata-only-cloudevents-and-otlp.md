# ADR-0035: Emit metadata-only CloudEvents and opt-in OTLP traces

## Status

Accepted.

## Date

2026-09-27.

## Context

Control lifecycle metadata must integrate with enterprise event and observability systems without
turning prompts, responses, data values or authority payloads into telemetry. A collector or broker
is an external availability boundary and cannot be allowed to control deterministic policy results.

## Decision

Convert only existing allowlisted lifecycle events and metadata into CloudEvents 1.0 structured
envelopes with generated id, fixed source/type, UTC time and JSON data. Log the envelope locally.
Map the same event to one bounded OpenTelemetry span and initialize the OTLP HTTP/protobuf exporter
only when an endpoint is explicitly configured. Configure structured logging before composition and
bound telemetry flush/shutdown. Suppress sink/exporter failures from business execution.

## Alternatives considered

- Export full application request/response bodies: rejected because content can contain regulated,
  personal, credential or tool data and is unnecessary for control telemetry.
- Make broker/collector delivery synchronous and mandatory: rejected because observability outage
  must not weaken or block deterministic enforcement.
- Implement a broker-specific producer: rejected because identity, protocol, tenancy and delivery
  semantics are enterprise integration decisions.
- Propagate OpenTelemetry baggage: rejected because arbitrary caller metadata could cross trust
  boundaries outside the allowlist.

## Consequences

Log processors can route portable CloudEvent envelopes, and approved collectors can receive
correlated OTLP spans. Delivery is at-most the behavior of the configured log/export pipeline; this
phase does not provide queue durability, ordering or an audit ledger.

## Security and privacy impact

Unsafe event names and metadata fields are dropped. Span resources/attributes remain bounded;
exception message/stack, status description and baggage are excluded. Allowed identifiers are still
organization metadata and require access, residency, retention and deletion controls.

## Operational impact

Without an endpoint the runtime imports no optional OTLP SDK, creates no exporter and remains
network-silent. A configured endpoint requires the observability extra; the deployment image ships
it but provides neither endpoint nor egress. Setup, emit, flush and shutdown failures are isolated,
so operators need independent collector/export health monitoring.

## Follow-up

- Select a collector/broker only with explicit workload identity, TLS, tenancy and residency policy.
- Define sampling, delivery SLO, retention and deletion for each environment.
- Add durable broker delivery only if audit/event requirements justify a separate availability and
  replay design.
