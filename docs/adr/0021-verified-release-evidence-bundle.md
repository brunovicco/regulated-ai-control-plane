# ADR-0021: Compose verified release evidence without promotion authority

## Status

Accepted.

## Date

2026-09-26.

## Context

Phases 6b and 6c produce static and observed change evidence for a signed candidate. Phases 6d and
6e gate exact provider and policy drafts before signing. Running these workflows independently does
not prove that the reviewed draft bytes are the bytes that entered the signed candidate, and a
pipeline can accidentally compare different release pairs or omit a required review artifact.

A release coordinator needs one deterministic artifact that verifies those relationships without
turning analysis completeness into approval. Automatically promoting a candidate because tests or
reviews passed would collapse evidence, risk acceptance, signing authority and deployment authority
into one unsafe boundary.

## Decision

Add an offline release-evidence composer for one signed base, one signed candidate and one exact
metadata-only scenario suite. Verify both packs through the same trust store, run the existing
static diff and scenario replay use cases, and re-run supplied Phase 6d/6e review records against
the exact authenticated candidate file bytes.

Compare policy sets by stable policy-set id and provider records by stable target id. Every modified
existing entity requires one passing review artifact. Missing and blocked reviews make evidence
incomplete. New or removed whole policy sets/provider targets also make evidence incomplete because
their onboarding/removal governance is not defined by the existing update-only review gates.

Emit the full metadata-only static/replay results, bounded review identities, stable findings and a
SHA-256 digest over the canonical bundle payload. Potential or observed impact remains visible but
does not itself determine evidence completeness. `EVIDENCE_COMPLETE` means the configured evidence
set is internally bound and present; it does not authorize promotion.

## Alternatives considered

- Trust previously emitted JSON reports: rejected because unsigned report files could be edited or
  accidentally mixed across release pairs.
- Reimplement diff, replay or review policy inside the composer: rejected because the existing
  application use cases remain the authoritative behavior.
- Automatically promote when the bundle is complete: rejected because impact acceptance, key use,
  release approval and deployment are separate organization-owned authority boundaries.
- Treat additions/removals as ordinary updates: rejected because no authenticated same-entity
  lineage exists for the current review gates.
- Include raw policy/provider YAML or source text in the bundle: rejected because exact digests and
  allowlisted semantic metadata are sufficient.

## Consequences

CI and release tooling can archive one reproducible artifact that binds verified releases, the
scenario corpus and exact review records. A review of bytes that differ from the signed candidate
fails closed. Missing review coverage is distinct from invalid input.

The bundle can be large because it contains per-change and per-scenario metadata. Its schema and
canonical digest become compatibility contracts. Organizations still need an external decision
record for accepting intended impacts.

## Security and privacy impact

The workflow reads bounded local signed-pack files, scenario metadata and review metadata. It makes
no network call and includes no prompts, responses, field values, source text, customer data,
credentials, private keys or personal reviewer identity. It exposes configuration identifiers,
public signing-key ids, digests, decisions, classifications, findings and non-personal roles already
allowed by the component reports.

Review records remain unauthenticated human assertions. A compromised trust store/signing key,
malicious reviewer assertion or incomplete scenario corpus remains outside the guarantee. The
bundle digest provides integrity identification, not a signature or external timestamp.

## Operational impact

The CLI returns 0 for complete evidence, 1 for invalid verification/schema/binding input and 2 for
valid but incomplete evidence. It does not mutate packs, access signing keys, persist state, deploy
or call providers/tools. Re-running with the same exact inputs produces the same JSON and bundle
digest.

## Follow-up

- Add organization-owned signed reviewer and promotion attestations with quorum.
- Define onboarding/removal review contracts for whole policy sets and provider targets.
- Add signed tool catalogs to the control-pack and replay boundary.
- Define retention, external timestamping and distribution for evidence bundles.
- Version the bundle schema before external consumers depend on it.
