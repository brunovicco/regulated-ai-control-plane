# ADR-0014: Bind provider provenance snapshots to decision evidence

## Status

Accepted.

## Date

2026-09-25.

## Context

Evidence records identify provider capabilities and the registry version used by a decision, but
they do not retain the source URLs, verification date or fact state. The Phase 5c operator view
therefore cannot safely display historical provider provenance. Joining an old decision to the
currently loaded registry could attribute changed metadata to a past evaluation.

Provider facts can also differ by target and region even when their existing capability identifier
is the same. Historical evidence must preserve the exact target that was evaluated.

## Decision

For every provider capability fact resolved during evaluation, capture an immutable metadata-only
snapshot with:

- capability id, key and exact provider target;
- state and documented conditions;
- record version and registry version;
- verification date and reviewed public HTTPS source URLs.

Normalize and order snapshots deterministically. Include them in the canonical decision output and
event payloads so changes affect the output digest, evaluation id and evidence id. Persist snapshots
as strictly parsed JSON in SQLite and expose them through exact-ID evidence and operator responses.

Add `provider_context_complete`. It is true when every recorded capability id has a corresponding
snapshot and false for legacy rows migrated with an empty snapshot list. Never reconstruct missing
history from the active registry.

## Alternatives considered

- Resolve sources from the current registry at read time: rejected because it can misattribute new
  configuration to historical decisions.
- Store only a digest of source metadata: rejected because operators need the reviewed source and
  verification date to understand the evidence.
- Store full provider notes or documentation content: rejected because URLs and structured fact
  metadata are sufficient and minimize retained content.
- Backfill legacy snapshots from current configuration: rejected because the historical mapping
  cannot be proven.

## Consequences

New evaluations are reproducibly bound to the provider provenance they used. Changing a fact or
source without changing the declared registry version still changes the decision/evidence identity,
making silent configuration drift visible. Existing evidence remains readable but explicitly
incomplete.

## Security and privacy impact

Snapshots contain only public-source and technical metadata. They exclude prompts, values,
credentials, provider notes, customer eligibility/configuration and organization assertions.
Malformed, duplicate or registry-inconsistent persisted snapshots fail closed. A snapshot supports
historical attribution; it is not a provider attestation, current-state check or compliance claim.

## Operational impact

SQLite initialization adds one non-null JSON column with an empty-list default. No background
backfill occurs. New evidence rows are larger and decision/evidence identifiers change for
capability-bearing evaluations because provenance is now digest-bound.

## Follow-up

- Include a canonical snapshot digest in external evidence export formats.
- Add signed provider packs if provenance authenticity beyond local configuration is required.
- Define registry-diff impact analysis for capability/source changes.
- Retain old versioned registry packs according to governance policy.
