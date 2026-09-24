# Architecture

## Context

RegulaAI owns deterministic evaluation at the AI execution boundary. It accepts normalized
business context, combines caller labels with narrow deterministic classification, evaluates an
immutable organization policy set, verifies curated provider capability facts and returns an
execution plan plus metadata-only evidence. Phase 1 does not call an AI provider.

Phase 2 adds local enforcement. It applies field transformations, persists a metadata-only
`PREPARED` record and then calls a network-silent mock execution port. No real provider SDK or
external inference is present in the default runtime.

Phase 3a adds an opt-in adapter for `governed-llm-gateway`. It sends only the sanitized in-memory
execution plan, delegates provider routing/retry/fallback to the gateway and persists allowlisted
provider-call metadata. The public enforcement response remains content-free.

Phase 4a adds verification and one-time consumption of externally issued approval assertions.
Approval remains outside model authority and is bound to the deterministic evaluation digest.

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

Transform obligations are returned before any configured execution port can be called. Capability
requirements selected for the primary target are also applied to every explicit fallback target.
High-assurance freshness is policy data (`max_age_days`), not a global domain constant.

See [ADR-0004](adr/0004-versioned-yaml-and-sqlite-phase-1-adapters.md) for the local adapter
decision and [the demo](DEMO.md) for the end-to-end flow.

## Phase 2 components

- `application/enforce_operation.py`: evaluation-to-transformation-to-execution orchestration.
- `adapters/tokenization.py`: injected HMAC tokenization/pseudonymization boundary.
- `adapters/mock_execution.py`: network-silent execution port used to prove boundary ordering.
- `adapters/evidence_sqlite.py`: separate metadata-only enforcement lifecycle records.
- `entrypoints/api.py`: metadata-only enforcement endpoints; transformed payloads remain internal.

The enforcement sequence is:

```text
evaluate -> transform locally -> persist PREPARED -> claim DISPATCHED -> execute -> persist EXECUTED
```

`DENY`, missing approval, conflicting transformations, transformation failure and evidence failure
all stop before execution. See
[ADR-0005](adr/0005-local-enforcement-before-execution.md).

## Phase 3a components

- `adapters/gateway_execution.py`: bounded provider-neutral request translation and terminal
  provenance validation.
- `entrypoints/api.py`: explicit mock/gateway composition selected at startup.
- `adapters/evidence_sqlite.py`: optional provider-call metadata stored with enforcement state.

The gateway path is text-only and rejects tools before network access. Separate transport and
provider timeouts are configured, while retry and fallback remain gateway-owned. The configured
gateway workload must be constrained to the provider already evaluated by RegulaAI; terminal
provider mismatch fails closed. An atomic `PREPARED -> DISPATCHED` claim prevents concurrent or
post-crash replay from issuing a second external request; interrupted `DISPATCHED` records require
operational reconciliation. See
[ADR-0006](adr/0006-governed-gateway-execution-adapter.md).

## Phase 4a components

- `application/ports.py`: inspect-and-consume approval authority contract.
- `adapters/approval.py`: strict HMAC assertion verification and SQLite replay ledger.
- `application/enforce_operation.py`: approval validation before preparation and atomic consumption
  after the execution claim but before execution.
- `entrypoints/api.py`: ephemeral secret assertion input and metadata-only approval receipt output.

The approval sequence is:

```text
evaluate -> transform -> inspect digest-bound assertion -> persist PREPARED
         -> claim DISPATCHED -> consume approval once -> execute -> persist EXECUTED
```

Missing assertions remain `WAITING_APPROVAL`. Invalid assertions never reach an execution claim;
consumption failure after a claim becomes terminal `APPROVAL_FAILED`. The raw assertion is never
stored. See [ADR-0007](adr/0007-digest-bound-external-approval.md).

## Diagrams

Add C4 context/container diagrams and sequence diagrams for critical flows.
