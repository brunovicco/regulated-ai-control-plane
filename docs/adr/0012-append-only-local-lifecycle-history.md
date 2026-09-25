# ADR-0012: Record lifecycle transitions in an append-only local ledger

## Status

Accepted.

## Date

2026-09-24.

## Context

Phase 5a composes a bounded operator timeline from the current evidence, enforcement and
tool-action records. Those records preserve only the latest state, so the view cannot show which
intermediate states were actually persisted or when a transition was observed.

Reconstructing history from current state would be misleading. Writing history separately in the
application would also allow the state write to succeed while its event fails, or vice versa.
Existing installations already contain records created before lifecycle tracking.

## Decision

Add a shared `operator_lifecycle_event` SQLite table. Database triggers append metadata-only events
in the same transaction as:

- immutable evidence insertion;
- enforcement insertion and status change;
- tool-action insertion and status change.

Each event stores only an integer sequence, UTC observation time, source, entity kind/id, optional
enforcement id and status. A unique entity/status constraint prevents duplicate replay events.
`BEFORE UPDATE` and `BEFORE DELETE` triggers reject mutation of event rows.

During repository initialization, existing records with no event receive one
`MIGRATION_BASELINE`. This is an observation of current state at upgrade time, not reconstructed
history. The operator timeline returns at most 256 events, reports truncation explicitly and sets
`history_complete` only when every event came from a transition, neither events nor current actions
were truncated, and the recorded events cover the current evaluation, enforcement and returned
action states.

## Alternatives considered

- Reconstruct transitions from the latest status: rejected because it would claim events that may
  never have been persisted.
- Write events from application use cases: rejected because separate repository calls are not
  atomic with lifecycle state changes.
- Add a message broker/event store: deferred because the local SQLite profile can prove the
  contract without another operational dependency.
- Backfill inferred historical transitions: rejected because neither their occurrence nor timing
  can be proven.
- Call the table tamper-evident: rejected because a database owner can alter schema/triggers; local
  append-only enforcement is not cryptographic integrity.

## Consequences

New transitions have an ordered local history and replaying an unchanged terminal state does not
add duplicate events. Legacy records remain queryable with an explicit incomplete-history signal.
The current-state stages remain available separately from the lifecycle event list.

## Security and privacy impact

Events contain no prompts, values, arguments, assertions, outputs, credentials, error details or
actor data. Schema triggers prevent accidental application-level mutation/deletion. The ledger is
not resistant to a privileged database owner and must not be described as signed, immutable or
externally anchored evidence.

## Operational impact

Repositories create the table, indexes, baselines and triggers automatically. No background job is
required. Database-retention procedures must rotate or remove the database as an approved unit;
ordinary row deletion is intentionally blocked. Event truncation requires direct investigation.

## Follow-up

- Add signed digest chaining or external anchoring if tamper evidence becomes required.
- Define approved retention/rotation tooling that respects lifecycle-event immutability.
- Add tenant/operator authorization before global event discovery.
- Evaluate an external append-only store for multi-instance production deployments.
