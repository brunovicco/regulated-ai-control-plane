# Architecture

## Context

RegulaAI owns deterministic evaluation at the AI execution boundary. It accepts normalized
business context, combines caller labels with narrow deterministic classification, evaluates an
immutable organization policy set, verifies curated provider capability facts and returns an
execution plan plus metadata-only evidence. Phase 1 does not call an AI provider.

## Layers

```text
src/regulated_ai/
├── domain/
├── application/
├── adapters/
└── entrypoints/
```

### Domain

Pure business concepts, invariants, Value Objects, domain services, events, and domain errors.

### Application

Use cases, commands, queries, ports, authorization decisions, and transaction coordination.

### Adapters

Implementations of application ports for databases, messaging, HTTP, cache, storage, identity, and external SDKs.

### Entrypoints

HTTP, CLI, jobs, events, and serverless handlers. Entrypoints validate and translate transport data but do not own business rules.

## Dependency rule

```text
entrypoints -> application -> domain
adapters    -> application/domain
domain      -> no outer layer
```

## Cross-cutting decisions

- Configuration: environment variables validated at startup.
- Logging: structured events to stdout/stderr.
- Tracing: the service-only OpenTelemetry adapter exports trace data over OTLP HTTP/protobuf only
  when an endpoint is configured. It propagates W3C Trace Context, but not baggage, and keeps the
  SDK lifecycle at the composition-root boundary. The separate Langfuse LLM observer remains an
  opt-in adapter with its existing contract.
- Errors: infrastructure errors translated at adapters; external errors mapped at entrypoints.
- Time: UTC internally with timezone-aware values.
- Money: `Decimal` wrapped in a domain Value Object.
- Idempotency: required for externally visible side effects.
- Packaging: containerized via the repo `Dockerfile` (multi-stage, uv-based); the runtime `CMD` is defined per project.

## Phase 1 components

- `domain/models.py`: immutable value objects and decision precedence; no outer-layer imports.
- `application/evaluate_operation.py`: the `EvaluateAiOperation` orchestration use case.
- `application/ports.py`: policy, capability, classifier, evidence, observability and future
  approval/execution contracts.
- `adapters/yaml_files.py`: strict versioned policy/provider registry boundary.
- `adapters/classifier.py`: CPF/CNPJ checksum, labeled account-field and secret-field detection.
- `adapters/evidence_sqlite.py`: metadata-only local evidence persistence.
- `adapters/evaluation_observability.py`: stable, allowlisted structured lifecycle events.
- `entrypoints/api.py`: HTTP validation, error mapping, composition root and Phase 1 endpoints.

Transform obligations are returned before any future execution port can be called. Capability
requirements selected for the primary target are also applied to every explicit fallback target.
High-assurance freshness is policy data (`max_age_days`), not a global domain constant.

See [ADR-0004](adr/0004-versioned-yaml-and-sqlite-phase-1-adapters.md) for the local adapter
decision and [the demo](DEMO.md) for the end-to-end flow.

## Diagrams

Add C4 context/container diagrams and sequence diagrams for critical flows.
