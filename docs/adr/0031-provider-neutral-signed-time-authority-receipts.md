# ADR-0031: Verify provider-neutral signed time-authority receipts

## Status

Accepted.

## Date

2026-09-27.

## Context

Local artifact times and repository history do not establish that an independent authority observed
specific evidence bytes at a claimed time. Selecting and integrating a timestamp provider is an
organization decision, but the control plane can define a strict verification boundary now.

## Decision

Verify a minimal Ed25519 receipt that binds an allowlisted subject kind, exact SHA-256 artifact
digest, UTC issue time, external authority id and lifecycle-aware key id. Require an explicit UTC
evaluation time, reject future receipts and optionally enforce a caller-pinned minimum issue time.
Emit metadata-only verification evidence without acquiring receipts or contacting services.

## Alternatives considered

- Trust filesystem or archive timestamps: rejected because they are locally mutable metadata.
- Implement RFC 3161 immediately: deferred until interoperability requirements and a provider are
  selected; this phase must not imply standards compatibility it does not provide.
- Accept a receipt-provided freshness floor: rejected because an untrusted package cannot establish
  its own trust floor.

## Consequences

Organizations can attach and verify independently signed time assertions for bounded release and
trust artifacts. Authority key distribution and receipt acquisition remain external.

## Security and privacy impact

Receipts contain bounded artifact/authority/key ids, UTC time and cryptographic digests/signatures.
They exclude artifact content, credentials, private keys, people and customer data. A compromised
authority key or dishonest authority can assert false time.

## Operational impact

Verification is deterministic, offline and read-only. This custom provider-neutral format is not an
RFC 3161 implementation, timestamp service, immutable ledger or certification claim.

## Follow-up

- Select an approved external time or transparency provider.
- Add a standards-specific adapter when interoperability requirements are known.
- Define availability, retention, rotation, revocation and incident procedures for authority keys.
