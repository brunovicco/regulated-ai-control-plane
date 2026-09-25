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

Phase 4b removes caller control over tool risk. A versioned catalog supplies trusted risk classes
and closed input schemas. The gateway may propose an authorized tool call, but RegulaAI stores only
its metadata/digest and performs no tool side effect.

Phase 4c binds exact proposal arguments and separate approval to an atomic tool execution. Phase
4d then validates the untrusted result against a trusted closed output schema and exposes only an
ephemeral minimized result.

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

The gateway path sends only sanitized text and, in Phase 4b, trusted catalog tool definitions.
Separate transport and provider timeouts are configured, while retry and fallback remain
gateway-owned. The configured
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

## Phase 4b components

- `domain/models.py`: immutable authorized-tool definitions and metadata-only proposals.
- `application/ports.py`: organization-owned tool-catalog contract.
- `adapters/yaml_files.py`: strict versioned tool catalog and canonical schema digests.
- `application/evaluate_operation.py`: fail-closed resolution and policy matching using catalog
  risk classes only.
- `adapters/gateway_execution.py`: trusted schema translation and proposal digesting.
- `adapters/evidence_sqlite.py`: catalog/tool identities and argument digests without arguments.

The sequence is:

```text
caller tool name -> catalog resolution -> deterministic policy -> trusted gateway definition
                 -> model proposal -> metadata/digest only -> no tool execution
```

An approval bound to the evaluation digest does not authorize model-generated arguments. Phase 4c
therefore validates exact arguments and requires new authority bound to the action digest. See
[ADR-0008](adr/0008-trusted-tool-catalog-and-proposal-boundary.md).

## Phase 4c components

- `application/execute_tool_action.py`: exact schema/digest validation, action binding, atomic claim
  and fail-closed reconciliation lifecycle.
- `adapters/action_approval.py`: domain-separated `ra2` HMAC verification and replay ledger.
- `adapters/evidence_sqlite.py`: metadata-only action records and atomic `DISPATCHED` claim.
- `adapters/mock_tool_execution.py`: local, network-silent execution proof.
- `entrypoints/api.py`: two-step action submission and metadata-only inspection endpoints.

```text
stored proposal + resubmitted arguments -> schema/digest validation -> action digest
    -> WAITING_APPROVAL -> inspect ra2 -> PREPARED -> claim DISPATCHED
    -> consume once -> mock tool boundary -> EXECUTED
                              \-> ambiguous failure -> RECONCILIATION_REQUIRED
```

Raw arguments and idempotency keys exist only in the request and ephemeral action plan. Phase 4c
does not return tool output to a model or enable a live enterprise connector. See
[ADR-0009](adr/0009-action-digest-bound-tool-execution.md).

## Phase 4d components

- `adapters/yaml_files.py`: closed output schemas with classifications and handling rules.
- `application/execute_tool_action.py`: untrusted result validation, minimization and digesting.
- `adapters/evidence_sqlite.py`: result metadata and schema migration without result content.
- `entrypoints/api.py`: immediate-only `safe_result` and terminal result-rejection mapping.

```text
tool adapter output (untrusted) -> validate closed schema -> classify each field
    -> RETURN closed enum | MASK value | DROP field -> immediate safe_result
    -> persist digests/classifications/field names only
    \-> invalid/disallowed output -> RESULT_REJECTED (terminal, no retry)
```

Raw and safe values exist only during the successful request. Replays and action inspection cannot
recover them. No result is supplied to a model in this phase. See
[ADR-0010](adr/0010-trusted-tool-result-handling.md).

## Phase 5a components

- `application/get_operator_timeline.py`: exact-ID metadata correlation, integrity validation,
  stable attention codes and bounded stage composition.
- `adapters/evidence_sqlite.py`: deterministic action listing scoped to one enforcement.
- `entrypoints/api.py`: read-only operator timeline endpoint.

```text
exact enforcement id -> enforcement + immutable evidence + bounded actions
    -> integrity checks -> ordered current-state stages -> attention codes
```

This is a current-state control timeline, not an append-only transition ledger. It neither lists
activity globally nor mutates approval, execution or reconciliation state. See
[ADR-0011](adr/0011-metadata-only-operator-timeline.md).

## Phase 5b components

- `adapters/evidence_sqlite.py`: shared lifecycle-event table, transactional triggers, migration
  baselines, append-only guards and bounded event query.
- `application/get_operator_timeline.py`: event integrity validation, completeness and truncation.
- `entrypoints/api.py`: metadata-only lifecycle history within the exact-ID operator response.

```text
state INSERT/UPDATE -> SQLite trigger in the same transaction -> append lifecycle event
legacy record at upgrade -> MIGRATION_BASELINE -> history_complete=false
```

The local ledger prevents ordinary row updates/deletes but is not cryptographically tamper-evident
against a database owner. See
[ADR-0012](adr/0012-append-only-local-lifecycle-history.md).

## Phase 5c components

- `domain/models.py`: sanitized approval summary and expanded operator control context.
- `application/get_operator_timeline.py`: evidence/enforcement and approval-binding validation.
- `entrypoints/api.py`: allowlisted decision, transformation and approval metadata.

```text
exact enforcement id -> validate linked metadata and approval bindings
    -> current state + lifecycle history + control context
```

The operator response deliberately omits actor identity and does not reconstruct provider source
or freshness history from the current registry. See
[ADR-0013](adr/0013-operator-control-context.md).

## Phase 5d components

- `application/evaluate_operation.py`: captures ordered capability snapshots and binds them to
  decision/event digests.
- `adapters/evidence_sqlite.py`: persists and strictly parses snapshot JSON with legacy migration.
- `entrypoints/api.py`: exposes historical source/freshness context and completeness.

```text
resolved capability -> immutable metadata snapshot -> canonical decision digest -> evidence
legacy evidence without snapshot -> provider_context_complete=false
```

Historical snapshots are not refreshed from the current registry and do not assert current
provider behavior or compliance. See
[ADR-0014](adr/0014-immutable-provider-provenance-snapshots.md).

## Phase 5e components

- `entrypoints/operator_dashboard.py`: escaped, no-script HTML rendering and local styling.
- `entrypoints/api.py`: exact-ID dashboard route and defensive browser response headers.
- `application/get_operator_timeline.py`: unchanged source of correlation, integrity and attention
  semantics for both JSON and HTML presentations.

```text
known enforcement id -> bounded timeline use case -> escaped server-rendered HTML
unknown or inconsistent metadata -> generic 404/503 HTML state
```

The dashboard does not introduce listing, search or administrative mutations. See
[ADR-0015](adr/0015-exact-id-server-rendered-operator-dashboard.md).

## Diagrams

Add C4 context/container diagrams and sequence diagrams for critical flows.
