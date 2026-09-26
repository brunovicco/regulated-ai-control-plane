# ADR-0019: Gate provider capability drafts with digest-bound source review

## Status

Accepted.

## Date

2026-09-26.

## Context

Provider capability records drive fail-closed runtime decisions and carry record-wide freshness
metadata. Phase 6a authenticates a completed release, Phase 6b analyzes semantic impact and Phase 6c
replays curated contexts. None of those phases structures the human source review that should occur
before a candidate record reaches the separate signing boundary.

Automatically scraping provider documentation would add network, prompt-injection, source-retention
and availability risks without resolving human interpretation. Merely advancing `verified_at`
without explicit claim coverage could make stale or unsupported facts appear reviewed.

## Decision

Add an offline pre-signing review gate for updates to one existing provider target. Verify the
approved base pack through its trust store, parse one candidate provider record from exact bounded
bytes, and require a strict review document bound to both the base pack payload digest and candidate
record digest.

The review records a stable review id, non-personal reviewer role, calendar date, exact target and
scoped conclusions for reviewed public HTTPS sources. Each source entry lists disjoint capability
keys it covers and uses `CORROBORATED`, `CONTRADICTED` or `INCONCLUSIVE`; the same URL may appear
again for a different capability scope. `CORROBORATED` means that the human reviewer found the
source consistent with the state represented in the candidate, including `unknown`; it is not proof
of provider behavior.

Because `verified_at` applies to the record, require coverage for the union of base and candidate
capability keys and every candidate source. Block unchanged registry/record versions, freshness
regression, review-date mismatch, missing coverage, contradiction and inconclusion. Reject digest,
target, source-lineage and capability-lineage mismatches as invalid input. Emit deterministic,
metadata-only JSON. A passed gate does not call the signer or authorize promotion.

## Alternatives considered

- Automatically retrieve and classify provider pages: rejected because source interpretation stays
  human-governed and online content is untrusted and mutable.
- Store copied source text or reviewer notes: rejected because it expands retention, copyright and
  prompt-injection exposure without being necessary for the gate.
- Accept only a reviewer identity and approval boolean: rejected because it does not show which
  sources and capability claims were reviewed.
- Infer version ordering: rejected because registry and record versions are opaque
  organization-defined identifiers; the gate only requires them to change.
- Sign immediately when the gate passes: rejected because key authorization, quorum and promotion
  are separate organization-owned authority boundaries.
- Onboard new provider targets through the same workflow: deferred because no authenticated record
  lineage exists for comparison.

## Consequences

Provider updates now have a reproducible, machine-checkable review artifact before signing. CI can
distinguish invalid inputs from a valid but blocked review. Review records and report schemas become
governance contracts that require controlled evolution.

The gate is deliberately conservative: a single contradictory or inconclusive conclusion blocks a
capability even if another source corroborates it. Reviewers must update all record-wide capability
coverage whenever freshness advances.

## Security and privacy impact

Review files contain public HTTPS URLs, capability identifiers, dates, digests and a reviewer role,
not reviewer identity. They contain no source text, quotes, prompts, customer data, credentials or
private keys. Blocked reports hash uncovered source URLs instead of emitting them.

Digest binding detects substitution of the base or draft but does not authenticate who authored the
review. A malicious or mistaken human assertion, mutable source URL, compromised trust store or
authorized signing-key compromise remains outside the guarantee.

## Operational impact

The CLI performs bounded local reads, signature verification, strict parsing and deterministic
comparison. It makes no network call and no mutation. Exit code 0 means the review gate passed, 1
means invalid verification/schema/binding/lineage input, and 2 means a valid review was blocked.

Organizations may run the gate before allowing access to an external signing job. That integration
must preserve separate key authorization and should archive only the metadata under an approved
retention policy.

## Follow-up

- Add signed reviewer attestations, ownership and quorum without placing private keys in runtime.
- Define controlled onboarding for new provider targets.
- Add optional immutable source timestamp/transparency evidence with explicit availability rules.
- Integrate complete-pack diff and scenario evidence into an external promotion workflow.
- Version the review/report schemas before external systems depend on them.
