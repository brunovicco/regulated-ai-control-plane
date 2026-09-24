# ADR-0011: Compose a bounded metadata-only operator timeline

## Status

Accepted.

## Date

2026-09-24.

## Context

RegulaAI persists evaluation evidence, enforcement state and tool-action state separately. An
operator investigating pending approval, ambiguous execution or a rejected tool result otherwise
has to correlate several exact identifiers and understand the lifecycle model. Phase 5 needs an
operator-facing read model, but the current tables store current state rather than an append-only
transition history.

A broad listing/search endpoint would also create a new metadata-discovery surface before product
authentication and tenant isolation exist.

## Decision

Add a read-only application query and
`GET /v1/operator/enforcements/{enforcement_id}/timeline`. The caller must provide one exact,
bounded enforcement identifier. The query correlates the enforcement with its immutable evidence
and a deterministic, enforcement-scoped list of tool actions.

The response orders `EVALUATION`, `ENFORCEMENT` and `TOOL_ACTION` stages by architectural sequence
and action creation metadata. It reports current statuses and stable attention codes for approval,
failure, reconciliation and result rejection. It does not claim that these stages form a complete
historical event ledger or invent missing transition timestamps.

The action query reads at most 129 rows, returns at most 128 stages and explicitly reports
`ACTION_LIST_TRUNCATED` when the bound is exceeded. The endpoint cannot approve, retry, reconcile
or mutate any record.

## Alternatives considered

- Build an append-only event ledger now: deferred because existing writes do not carry every
  transition timestamp and adding transactional history changes all lifecycle repositories.
- Add global recent-activity search: rejected for this slice because it increases discovery and
  authorization risk before tenant/product identity controls exist.
- Compose the view in the HTTP handler: rejected because correlation, integrity checks, bounds and
  attention semantics are application policy rather than transport formatting.
- Add reconciliation mutations with the read model: rejected because operational authority and
  downstream-effect proof require a separate design.

## Consequences

Operators get one bounded current-state view and stable attention reasons without new persistence.
The view cannot answer when every transition occurred or show superseded states. A future event
ledger may coexist with or replace its stage source while preserving the public attention contract.

## Security and privacy impact

The response contains only existing allowlisted metadata, version identifiers, labels and digests;
it does not recover prompts, field values, tool arguments, assertions or tool results. Exact-ID
lookup avoids global discovery, but deployments must still protect the operator route with their
existing network and access-control boundary until product authentication is implemented.

## Operational impact

No schema migration or background job is required. SQLite adds one bounded indexed lookup using
the existing enforcement identifier. `actions_truncated=true` and `ACTION_LIST_TRUNCATED` mean the
operator view is incomplete and requires direct investigation.

## Follow-up

- Add organization identity, tenant isolation and explicit operator authorization before global
  listing or search.
- Design an append-only transition ledger if complete historical timing becomes a product need.
- Define separately authorized reconciliation and retry workflows.
- Build a visual dashboard on the stable read-only contract.
