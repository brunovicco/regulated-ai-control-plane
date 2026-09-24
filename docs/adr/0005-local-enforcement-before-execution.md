# ADR-0005: Enforce transformations locally before provider execution

## Status

Accepted

## Date

2026-09-23

## Context

Phase 1 returns deterministic decisions and transformation obligations but does not prove that the
obligations run before data reaches a provider boundary. Phase 2 must create an execution-plan
contract that can later support real provider adapters without exposing raw values in logs,
receipts, API responses or persisted evidence. It must also fail closed when transformation,
evidence persistence or execution fails.

## Decision

Add a separate `EnforceAiOperation` use case after deterministic evaluation. It normalizes the
same context, refuses `DENY`, applies required field transformations inside the local trust
boundary, persists a metadata-only `PREPARED` enforcement record and only then calls an
`InferenceExecutionPort`. `REQUIRE_APPROVAL` may create an in-memory transformed plan but never
calls the execution port.

Support `REMOVE_FIELD`, `MASK`, `TOKENIZE` and `PSEUDONYMIZE`. Multiple transformations targeting
the same field are ambiguous and fail closed. Tokenization and pseudonymization use an injected
port; the local adapter derives scoped HMAC-SHA-256 values. The default runtime creates an ephemeral
256-bit key, while a stable key may be injected through `REGULAAI_TOKENIZATION_KEY`. The Phase 2
execution adapter is network-silent and returns metadata only.

Persist enforcement state in a separate SQLite table. Transformation receipts contain field IDs,
transformation types, reason codes and input/output digests, never values. API responses expose the
same metadata allowlist and do not return the execution payload.

## Alternatives considered

- Transform inside `EvaluateAiOperation`: rejected because decision and enforcement have different
  responsibilities and failure lifecycles.
- Let each provider adapter implement transformations: rejected because raw data could cross the
  provider boundary before policy controls are applied and behavior could diverge by provider.
- Apply multiple transformations in an implicit order: rejected because ordering can silently
  change semantics; ambiguous policy fails closed instead.
- Use reversible local token storage in Phase 2: rejected because it creates a new sensitive-data
  repository and is not required to prove the enforcement boundary.
- Return transformed payloads from the HTTP API: rejected because receipts and public responses
  should remain metadata-only.

## Consequences

Tests can prove that the mock execution port observes only transformed data and that `DENY`,
approval-pending, transformation-failure and evidence-failure paths never execute. Evaluation and
enforcement evidence have separate identifiers and lifecycle states. Real provider integration can
reuse the execution-plan port without moving transformation logic into provider adapters.

The HMAC token is not reversible and therefore is not a token vault. An ephemeral default key makes
tokens process-local; stable cross-process pseudonyms require an explicitly managed key.
Completed enforcement IDs are idempotent: `EXECUTED` is terminal, and replaying the same transformed
plan returns the stored result without calling the execution port again.

## Security and privacy impact

Raw values remain in memory only for classification, transformation and the internal execution
plan. They are excluded from logs, errors, receipts, SQLite records and API responses. Enforcement
metadata is persisted before execution, so evidence failure prevents boundary crossing. HMAC key
material is never recorded or returned. Operators must inject production key material through an
approved secret-management boundary and protect the SQLite metadata store.

## Operational impact

The local runtime adds `POST /v1/enforcements` and
`GET /v1/enforcements/{enforcement_id}`. Without a configured key, tokens change after process
restart. A configured key shorter than 32 bytes causes startup failure. The mock adapter performs no
network call and is not a provider simulator; it exists only to verify boundary ordering.

## Follow-up

- Integrate a managed token vault or KMS-backed pseudonymization adapter where reversibility or
  stable cross-service identity is required.
- Bind human approvals to the evaluation/output digest before allowing pending plans to execute.
- Add a real provider or gateway adapter with bounded timeouts in Phase 3.
- Replace local SQLite enforcement evidence with an append-only production backend.
