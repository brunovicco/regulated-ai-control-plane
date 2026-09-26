# ADR-0022: Authenticate release-promotion attestations with role-bound quorum

## Status

Accepted.

## Date

2026-09-26.

## Context

Phase 6f creates one deterministic bundle that binds verified releases, static analysis, scenario
replay and exact-byte review evidence. Its digest detects changes but authenticates no promotion
actor and deliberately grants no authority. A release system needs a bounded way to prove that
organization-controlled roles accepted the exact candidate and evidence bundle without moving
private keys into RegulaAI or allowing the evidence composer to promote its own output.

Counting unsigned files or free-form reviewer names would permit forgery and duplicate voting.
Using the control-pack signing key for every authority would collapse release composition,
impact acceptance and deployment into one credential.

## Decision

Add an offline Phase 6g verifier. It strictly parses a Phase 6f JSON bundle, recomputes the canonical
bundle digest and requires `EVIDENCE_COMPLETE` with no findings. A separate organization-owned YAML
policy declares normalized required roles and a minimum number of distinct approving keys.

Each promotion attestation is strict YAML signed with Ed25519. Its canonical signed payload binds
the schema, attestation id, exact bundle digest, candidate pack payload digest, canonical promotion
policy digest, `APPROVE` or `REJECT` decision, non-personal role, UTC issue/expiry interval and
signing-key id. A separate public-key trust store maps each key to allowed roles. Roles outside the
bound policy fail closed.

One key may provide only one attestation. At an explicit UTC evaluation time, authorization
requires every mandatory role, the configured distinct-key quorum and no active rejection.
Not-yet-valid and expired attestations are explicit blocking findings. The deterministic report
contains identities and attestation/signature digests, not raw signatures, and has its own canonical
authorization digest.

`PROMOTION_AUTHORIZED` is a handoff assertion only. The workflow never signs or edits a control
pack, invokes a release API, changes repository state, publishes, distributes, promotes or deploys.

## Alternatives considered

- Treat `EVIDENCE_COMPLETE` as automatic approval: rejected because evidence completeness is not
  organizational impact acceptance or release authority.
- Use unsigned approval records: rejected because neither actor authority nor exact-byte binding
  could be authenticated.
- Count attestation files rather than keys: rejected because one credential could satisfy quorum by
  duplicating its vote.
- Reuse the control-pack signing trust store: rejected because signing release composition and
  accepting its impact are distinct authority boundaries with different role policies.
- Use current wall-clock time implicitly: rejected because validity results and evidence would not
  be reproducible.
- Trigger deployment when quorum passes: rejected because target selection, distribution,
  environment authorization, rollback and deployment evidence are separate contracts.

## Consequences

Release automation can require authenticated, role-aware approval for the exact candidate and
complete evidence reviewed by people or external systems. Tampering, untrusted keys, role misuse,
double voting, stale votes, candidate substitution and active rejection fail closed.

Organizations must provision and protect promotion keys, author the trust/policy files and supply
attestations. The report schema, canonical payload and key ids become operational compatibility
contracts. Authorization remains only as strong as the evidence, signers and key governance.

## Security and privacy impact

Only public Ed25519 keys enter the verifier. Private keys, credentials and signing workflows remain
external. Inputs and outputs contain release/bundle/key/role identifiers, decisions, UTC timestamps
and cryptographic digests. They contain no prompts, responses, policy YAML, source text, customer
data or personal approver identity. Role and key ids must remain non-personal pseudonymous labels.

A compromised private key, trust store or promotion policy can authorize a malicious release.
SHA-256 authorization digests are integrity identifiers, not signatures or trusted timestamps.

## Operational impact

The CLI is local, deterministic and network-silent. It returns 0 when authorized, 1 for invalid
schema/cryptography/binding input and 2 for a valid but blocked decision. The evaluation timestamp
is mandatory UTC input. There is no database, API, dependency or runtime-startup change.

## Follow-up

- Define organization procedures for key issuance, hardware custody, revocation and rotation.
- Add externally trusted timestamping and durable evidence retention/distribution.
- Define onboarding/removal review contracts for whole policy sets and provider targets.
- Bind signed tool catalogs into the control-pack and replay boundary.
- Define a separate promotion/deployment adapter with target, rollback and deployed-artifact proof.
