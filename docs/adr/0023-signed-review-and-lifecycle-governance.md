# ADR-0023: Authenticate release reviews and whole-entity lifecycle changes

## Status

Accepted.

## Date

2026-09-26.

## Context

Phases 6d and 6e validate detailed provider-source and policy-mapping review records, but those
records contain an asserted role rather than cryptographic reviewer authority. Phase 6f also marks
whole policy-set or provider-target additions and removals incomplete because an update-only review
has no authenticated same-entity lineage. Phase 6g authenticates promotion acceptance, but a
promotion signer should not be the only evidence that a claimed technical or regulatory reviewer
actually approved an exact review or lifecycle transition.

The review boundary must not grant control-pack signing or promotion authority, and onboarding must
not allow new content to bypass exact digest binding.

## Decision

Define a strict Ed25519 release-review attestation. Its canonical payload binds an attestation id,
artifact kind, stable subject id, `ADDED`, `MODIFIED` or `REMOVED` change type, exact base and
candidate pack payload digests, reviewed content digest, bounded non-personal reviewer role,
conclusion, UTC attestation time and signing-key id.

A separate deployment-controlled public-key trust store authorizes every key by role, artifact kind
and change type. Modified entities additionally require the exact detailed Phase 6d/6e review id
and digest. The composer re-runs that review and refuses a signed approval when the detailed gate is
blocked. Additions omit the update-review binding and sign the exact candidate entity bytes;
removals sign the exact approved-base entity bytes being retired.

One authenticated review is required per changed entity. Duplicate entity targets and attestation
ids fail closed. The composed evidence format advances to schema version 2 and records only
attestation/signature digests, key/role ids, change metadata and conclusions. Phase 6g accepts both
bundle schemas 1 and 2 during migration.

## Alternatives considered

- Treat the Phase 6g promotion quorum as reviewer authentication: rejected because impact
  acceptance and subject-matter review are different authority boundaries.
- Add a signature field directly to each Phase 6d/6e record: rejected because lifecycle changes do
  not have those update-only schemas and a common envelope keeps cryptography consistent.
- Let a signed approval override a blocked detailed review: rejected because authentication cannot
  replace semantic coverage and conclusion checks.
- Continue rejecting every addition/removal: rejected because it prevents governed expansion and
  retirement of the control plane.
- Count several review signatures here: deferred because organizational impact acceptance already
  has explicit role/quorum enforcement in Phase 6g; this phase authenticates the accountable
  subject-matter review.

## Consequences

Release evidence can distinguish an authenticated review from an asserted role and can cover whole
entity onboarding/removal without weakening update validation. Pipelines must provision a separate
review trust store and obtain one attestation for each change. Existing unsigned update reviews no
longer complete a changed release bundle by themselves.

Bundle schema version 2 is an external compatibility change. The Phase 6g parser accepts version 1
and 2, while new composition always emits version 2.

## Security and privacy impact

Only public reviewer keys enter the workflow. Private keys remain in organization-controlled
external signers. Role, key, entity, review and attestation ids must be non-personal. Reports contain
timestamps, conclusions and cryptographic digests but no source text, policy/provider YAML,
credentials, personal identity or customer data. Raw signature bytes are not emitted.

A compromised reviewer key or trust-store authorization can approve malicious content. Whole-entity
approval authenticates acceptance of exact bytes; it does not prove source truth, legal correctness,
applicability, safety or compliance.

## Operational impact

The workflow remains local and network-silent. Changed releases require a review trust-store path
and attestation paths in addition to any detailed update-review records. Missing/rejected evidence
returns bundle exit code 2; invalid cryptography, authority, schema or binding returns 1. There is no
database, HTTP API, dependency or runtime-startup change.

## Follow-up

- Define hardware-backed reviewer-key issuance, revocation, rotation and emergency recovery.
- Add trusted timestamping and durable attestation/bundle retention.
- Bind signed tool catalogs into the same release, diff and replay boundary.
- Define organization-specific multi-review requirements if Phase 6g promotion quorum is
  insufficient for a regulated workflow.
