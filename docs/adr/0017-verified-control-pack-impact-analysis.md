# ADR-0017: Analyze semantic impact only after same-trust pack verification

## Status

Accepted.

## Date

2026-09-25.

## Context

Phase 6a authenticates the exact policy and provider records in one control-pack release. That
prevents untrusted content from entering runtime composition, but it does not help reviewers see
which control semantics changed between an approved base and a promotion candidate. Raw YAML diffs
also overemphasize formatting while failing to correlate provider capability changes with policies
that depend on them.

Impact analysis must not weaken the Phase 6a trust boundary. Comparing a trusted base with a
candidate accepted by an unrelated trust store would make the report appear authoritative across
different approval domains. Conversely, exhaustive behavioral equivalence would require an
unbounded set of runtime contexts and is not a credible guarantee for this phase.

## Decision

Add an offline control-pack diff workflow. Both manifests must pass the Phase 6a verifier against
one explicitly selected trust store and must carry the same pack id. Parse the exact authenticated
bytes into existing domain policy/provider records, then pass only those records and non-secret
release identities into a framework-free application use case.

Compare:

- policy sets by versioned identity and rules by versioned identity;
- provider targets by provider/service/region and capabilities by key;
- only explicit allowlisted fields from immutable domain models.

Classify additions, removals and changes conservatively:

- `DECISION`: policy/rule availability or executable rule fields; provider capability availability,
  state, conditions or freshness;
- `EVIDENCE`: reason/control mappings and provider provenance/version fields bound to evidence;
- `GOVERNANCE`: non-executable policy metadata, regulatory-support mappings and provider notes.

For provider changes, include rules from either release that require the capability key and whose
provider/service/region match can apply to the target. Emit stable metadata-only JSON including
base/candidate identity, counts, highest impact, same-version/different-payload reuse and signing-key
change. An optional flag returns exit code 2 for decision impact; successful analysis otherwise
returns 0 and invalid verification/parsing/comparison returns 1.

## Alternatives considered

- Diff raw YAML text: rejected because formatting noise obscures semantic fields and does not map
  capabilities to dependent policy.
- Compare manifests without verifying signatures: rejected because untrusted input could produce a
  misleading governance artifact.
- Allow separate trust stores for base and candidate: rejected because the report should stay
  within one explicit approval domain; key rotation is represented by multiple keys in that store.
- Run every historical request against both packs: deferred because it requires sensitive datasets,
  retention decisions and a bounded evaluation corpus; it still would not prove equivalence.
- Automatically approve low-impact releases: rejected because impact classification supports human
  review and does not grant promotion authority.

## Consequences

Reviewers and CI can identify potential runtime impact before promotion without network access or
policy execution. Semantically identical releases can differ in signed release metadata without
producing semantic changes, while version reuse and key changes remain visible.

The impact taxonomy and JSON schema become compatibility contracts. Conservative classification may
produce false positives, especially for additions or removals that no current caller selects. That
is preferred to silently understating impact.

## Security and privacy impact

The report includes only pack ids/versions/digests, public signing-key ids, configuration
identifiers, changed field names, impact classes and dependent policy identifiers. It excludes YAML
values, notes, source contents, private keys, runtime payloads, customer data and stored evidence.

The workflow cannot authorize a release. Its guarantees depend on trust-store integrity and the
Phase 6a verifier. A compromised trusted key can still produce a valid malicious candidate.

## Operational impact

The CLI performs bounded local verification and parsing and emits one compact JSON document to
stdout. It makes no network call and mutates neither pack. Pipelines may use
`--fail-on-decision-impact` to require explicit handling while archiving the JSON as review evidence
under organization-defined retention.

## Follow-up

- Define reviewer ownership, approval quorum and promotion attestations.
- Add curated scenario replay as evidence alongside static analysis without claiming completeness.
- Add source-retrieval and freshness-review workflow before candidate signing.
- Version the report schema if external systems begin consuming it.
- Decide whether signed tool catalogs participate in the same analysis.
