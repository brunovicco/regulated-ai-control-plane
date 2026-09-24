# ADR-0009: Bind tool execution to exact arguments and separate action approval

## Status

Accepted.

## Date

2026-09-24.

## Context

Phase 4b records model-produced tool calls as metadata-only proposals. The earlier Phase 4a
approval is issued before inference and is bound to the deterministic decision, so it cannot
authorize arguments produced later by a model. Executing a proposal with that approval would let
model output cross an authority boundary without exact human authorization.

Raw proposal arguments are intentionally not persisted or returned. An execution request must
therefore resubmit them ephemerally and prove that they match the stored proposal digest.

## Decision

Add a separate `ExecuteToolAction` use case and `ToolExecutionPort`. The use case loads an executed
enforcement and its proposal, verifies that the current catalog/evidence identity and schema still
match, validates the resubmitted arguments against the closed catalog schema, and recomputes the
proposal argument digest.

It derives an action digest binding enforcement, evaluation, call, catalog/tool definition,
schema, exact arguments, downstream workload identity and a digest of the idempotency key. Every
tool effect requires a new action-specific assertion. The assertion uses a domain-separated `ra2`
format and a dedicated key; a Phase 4a `ra1` decision approval cannot authorize an action.

The action is persisted before I/O, atomically claimed as `DISPATCHED`, and its approval is
consumed exactly once before calling the port. An ambiguous execution failure becomes terminal
`RECONCILIATION_REQUIRED` and is never retried automatically. One enforcement proposal can have
only one action binding, preventing a new idempotency key from executing the same proposal again.

Phase 4c provides only a network-silent mock tool adapter. Live enterprise-system connectors and
returning tool results to a model remain deferred.

## Alternatives considered

- Reuse Phase 4a approval: rejected because it predates and does not bind model-produced arguments.
- Persist raw proposal arguments: rejected because it expands sensitive-data retention and breach
  impact.
- Automatically execute catalog `read_only` tools: rejected for this slice because read access is
  still an external effect with identity, privacy and authorization consequences.
- Retry timeouts: rejected because the downstream effect may have occurred even when no response
  was observed.

## Consequences

Clients use a two-step action flow: first submit exact arguments to obtain a stable action digest
and `WAITING_APPROVAL`; then resubmit the same request with externally issued `ra2` authority.
Argument and idempotency values remain ephemeral. SQLite retains only identities, statuses,
digests, approval metadata and the metadata-only execution receipt.

## Security and privacy impact

Catalog/schema drift, unknown proposals, invalid arguments, digest mismatch, wrong/expired/replayed
authority and competing execution claims fail closed. The service does not mint approvals, retain
assertions, persist raw arguments or expose raw tool output.

## Follow-up

- Implement reviewed enterprise-system adapters with explicit network allowlists and timeouts.
- Define tool-result validation, classification and minimization before any result reaches a model.
- Add operational reconciliation for ambiguous downstream outcomes.
- Replace symmetric verification with an asymmetric or workload-identity-backed authority adapter.
