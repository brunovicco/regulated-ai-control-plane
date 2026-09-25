# ADR-0013: Expose allowlisted control context in the operator timeline

## Status

Accepted.

## Date

2026-09-25.

## Context

The operator timeline correlates current state and append-only lifecycle events, but it does not
yet show the persisted metadata explaining which policies, control objectives, capabilities,
transformations and approvals shaped the enforcement. Operators would otherwise need several
separate exact-ID reads and knowledge of internal record relationships.

The service does not persist an immutable snapshot of provider source URLs and verification dates
with each decision. Reading those fields from the current registry could incorrectly attribute new
configuration to historical evidence. Approval receipts also contain actor identity that is not
required to understand control state in this endpoint.

## Decision

Extend the exact-enforcement operator timeline with metadata already persisted in evidence and
enforcement records:

- matched policy, control-objective and provider-capability identifiers;
- decision and enforcement reason codes;
- authorized tool identifiers and provider target;
- transformation receipts and the optional previous evidence digest;
- an enforcement approval summary containing approval id and lifecycle timestamps, without actor
  identity;
- an `approval_recorded` boolean on enforcement and tool-action stages.

Before returning this context, validate that evidence and enforcement share the input digest and
that approval receipts remain bound to the expected enforcement/action and digest. Keep the route
bounded, read-only and addressed by one exact enforcement id.

## Alternatives considered

- Join current provider configuration to historical evidence: rejected because equal identifiers
  do not prove that mutable source metadata is the snapshot used by the past decision.
- Return complete approval receipts: rejected because actor identity is unnecessary for this
  operator view and expands metadata exposure.
- Add a global operator queue with the context: deferred until organization identity, tenant
  isolation and explicit operator authorization exist.
- Duplicate the metadata into a new dashboard table: rejected because the existing immutable
  records already contain the selected fields.

## Consequences

One exact-ID response can explain the current control decision and transformations without payload
recovery. The response contract grows additively. Historical provider source/freshness provenance
remains incomplete and is reported as future work rather than reconstructed.

## Security and privacy impact

The new fields are allowlisted identifiers, reason codes, digests, structural transformation
targets and timestamps. Prompts, values, arguments, assertions, tool results, credentials and
approval actor identity remain excluded. Integrity mismatches fail closed with the existing
operator timeline integrity error.

## Operational impact

No schema migration or background process is required. The query uses the same bounded local reads
as Phase 5b. Existing access controls must continue protecting the operator route.

## Follow-up

- Persist immutable provider capability source/freshness snapshots with future evidence.
- Add organization identity, tenant isolation and operator authorization before global discovery.
- Define separately authorized reconciliation workflows.
- Build the visual dashboard on the stable read-only contract.
