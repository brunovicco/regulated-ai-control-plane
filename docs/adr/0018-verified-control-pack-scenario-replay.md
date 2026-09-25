# ADR-0018: Replay fixed metadata scenarios across verified control packs

## Status

Accepted.

## Date

2026-09-25.

## Context

Phase 6b conservatively classifies semantic configuration changes after verifying an approved base
and candidate through the same trust store. Static analysis intentionally does not execute policy,
so it can identify potential impact without showing whether a curated customer-relevant context
actually changes. Raw historical request replay would introduce personal data, retention and
authorization risks, while a moving evaluation clock would make provider-freshness outcomes
non-reproducible.

A finite scenario corpus also cannot establish semantic equivalence. It can only add observed
behavior evidence for the contexts the organization deliberately selected.

## Decision

Add an offline scenario replay workflow after Phase 6a verification. Require both releases to pass
one explicit trust store and share a pack id. Load a separately governed, bounded YAML suite with a
stable id/version, an exact SHA-256 digest and a mandatory timezone-aware evaluation timestamp.

The suite accepts normalized jurisdiction, sector, purpose, operation, assurance, provider,
fallback, boolean organization assertions, field identifiers and classification labels. It has no
field-value, prompt, response, tool or free-form description field. Each logical policy-set id is
resolved independently in the base and candidate so versioned releases can be compared.

Reuse the existing deterministic evaluator with exact parsed release records, a pass-through
classifier, no tools, no observer and an ephemeral evidence repository. Compare status, decision
and an exact digest of obligations as `DECISION` impact. Compare matched policy ids, provider
capability ids, reason codes, policy/registry versions and output digest as `EVIDENCE` impact. A
missing or ambiguous policy fails closed as a per-scenario outcome. Emit deterministic,
metadata-only JSON and optionally return exit code 2 when decision impact is observed.

## Alternatives considered

- Replay historical production requests: rejected because it expands data processing and retention
  scope and is unnecessary for deterministic control regression.
- Generate arbitrary contexts automatically: deferred because generated coverage is difficult to
  govern and may imply completeness that does not exist.
- Use the current wall clock: rejected because freshness decisions would change without either pack
  or suite changing.
- Include tool requests with an unsigned catalog: rejected because risk resolution would occur
  outside the authenticated policy/provider release boundary.
- Treat unchanged replay as automatic promotion approval: rejected because a finite corpus cannot
  establish equivalence or grant release authority.

## Consequences

Reviewers and CI gain concrete observed behavior evidence alongside the Phase 6b potential-impact
report. Scenario results are reproducible for the same signed releases and exact suite bytes. The
suite must be maintained as a reviewed organization artifact, and its bounded coverage must be
understood explicitly.

## Security and privacy impact

Scenario schemas structurally exclude raw values, prompts, responses, tool arguments and customer
data. Reports contain release/suite identities, decisions, obligation types and digests,
control/capability identifiers, reason codes and output digests. Evaluation evidence exists only in
memory for the duration of the process.

Field names, classification labels and control identifiers remain organization metadata. Access,
retention and review controls still apply. The scenario digest detects which corpus was used but
does not authenticate who approved it. Trust-store or signing-key compromise remains outside the
workflow's guarantee.

## Operational impact

The CLI performs local bounded parsing and evaluation with no network, database, approval,
enforcement, provider, tool or promotion mutation. Exit code 0 means a valid report, 1 means invalid
verification/configuration/suite input, and 2 means observed decision impact when the CI flag is
enabled. Pipelines may archive the report under organization-defined metadata retention.

## Follow-up

- Bring trusted tool catalogs into a signed release boundary before adding tool scenarios.
- Define scenario ownership, review quorum and promotion attestations.
- Add source-retrieval and provider-freshness review before candidate signing.
- Version the replay-report schema before external consumers depend on it.
- Expand curated coverage using synthetic-safe sector scenarios without claiming completeness.
