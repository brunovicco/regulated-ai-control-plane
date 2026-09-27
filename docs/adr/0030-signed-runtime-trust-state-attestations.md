# ADR-0030: Verify signed runtime trust-state attestations

## Status

Accepted.

## Date

2026-09-27.

## Context

Phase 6n shows which target identities accepted a checkpoint, but acceptance does not show that a
runtime process currently reports the checkpoint trust-store digest as loaded. A bounded freshness
contract is needed before deployment tooling can use target state as release evidence.

## Decision

Define strict Ed25519 runtime-state attestations bound to the exact checkpoint, runtime-policy
digest, store identity/kind, sequence and loaded trust-store digest. Authorize target keys through a
separate lifecycle-aware public trust store. Apply required-target coverage, a minimum distinct
target quorum and a bounded maximum observation age at an explicit UTC evaluation time. Treat
stale or incomplete valid evidence as blocked and invalid bindings as fail-closed input errors.

## Alternatives considered

- Treat Phase 6n acceptance as current runtime state: rejected because loading can fail or later
  regress after acceptance.
- Poll processes directly from this repository: deferred because topology, credentials, protocol
  and process semantics belong to the selected deployment platform.
- Accept unsigned health output: rejected because it cannot establish target identity or prevent
  cross-target substitution.

## Consequences

Runtime integrations must measure the loaded digest and sign one bounded assertion per target.
Offline verification can distinguish invalid, stale/incomplete and current evidence without network
or mutation authority.

## Security and privacy impact

Attestations contain non-personal target/key/store ids, UTC time and cryptographic digests/signatures
only. They exclude hostnames, addresses, process payloads, private keys and customer data. A
compromised target or signing key can falsely report loaded state, and clock integrity remains an
external control.

## Operational impact

The verifier is deterministic, offline and read-only. It does not implement probes, distribute
configuration, restart services or continuously monitor targets.

## Follow-up

- Integrate target-specific probes and receipt collection with the selected deployment platform.
- Add alerting and remediation for stale, missing and conflicting state.
- Add external trusted-time or transparency evidence where organizational requirements demand it.
