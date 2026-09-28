# ADR-0038: Authenticate terminal tool-action reconciliation

## Status

Accepted.

## Date

2026-09-28.

## Context

Tool execution authority is consumed before crossing the downstream boundary. A timeout or
transport failure can therefore leave an action in `RECONCILIATION_REQUIRED`: retrying may duplicate
an effect, while silently treating the call as failed may hide a completed operation. Phase 7b
introduces one live read-only sandbox connector, making an explicit recovery operation necessary.

The read-only operator timeline intentionally cannot mutate state, and `ra1` decision or `ra2`
action approval does not authorize an operator to declare a downstream outcome.

## Decision

Add a separate `rr1` HMAC-authenticated reconciliation authority with a dedicated key, strict
canonical schema, bounded lifetime, pseudonymous actor identity, exact action-digest binding and a
unique reconciliation identifier. The signed outcome is closed to `EXECUTED` or `NOT_EXECUTED`;
the former requires a bounded downstream execution identifier and the latter forbids one.

Only `RECONCILIATION_REQUIRED` may advance, atomically and irreversibly, to
`RECONCILED_EXECUTED` or `RECONCILED_NOT_EXECUTED`. Persist the metadata-only consumed receipt and
append the lifecycle transition. Exact replay is idempotent. The use case has no execution-port
dependency and cannot retry the tool.

## Alternatives considered

- Retry automatically after timeout: rejected because downstream completion may already have
  occurred.
- Reuse `ra2` action approval: rejected because permission to execute is not authority to attest a
  subsequently investigated outcome.
- Accept outcome fields directly from an authenticated HTTP session: rejected because the current
  service has no organization identity/role boundary and the mutation needs portable,
  action-specific evidence.
- Restore `EXECUTED` with invented result metadata: rejected because output was not safely observed
  or validated.
- Permit free-form notes or evidence URLs: rejected to keep storage metadata-only and prevent
  sensitive content, injection and unbounded retention.

## Consequences

Operators can close a known ambiguous action without causing another downstream request. The two
terminal states distinguish confirmed execution from confirmed non-execution without claiming
that a result was validated. Existing output and safe-result fields remain empty.

Issuance, investigation quality and downstream evidence remain organization responsibilities. An
action stays unresolved when evidence is insufficient.

## Security and privacy impact

Decision, action-approval and reconciliation assertions have separate prefixes, schemas and keys.
Assertions are action-digest bound, short-lived and consumed into an idempotent exact-binding
ledger. Raw assertions are ephemeral. Persisted reconciliation data is limited to bounded IDs,
closed outcome and UTC timestamps; it contains no arguments, output, notes, URLs or credentials.

The symmetric verifier can sign assertions if compromised. Deployments must isolate key access and
add their operator authentication/network perimeter. A future asymmetric or workload-identity
adapter should remove signing capability from this service.

## Operational impact

Deployments must configure a dedicated reconciliation key, retain the consumption ledger and
define an external investigation/issuance procedure. SQLite remains appropriate only for the
single-instance reference. Conflicting or wrong-state operations fail closed, and an issuer must
not conclude `NOT_EXECUTED` from transport failure alone.

## Follow-up

- Design production persistence and atomic multi-replica reconciliation.
- Add asymmetric or enterprise-identity-backed reconciliation authority.
- Collect sandbox evidence for timeout, late-success and duplicate cases.
- Require another ADR before introducing any deliberate retry or state-changing connector.
