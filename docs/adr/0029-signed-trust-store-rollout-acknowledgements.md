# ADR-0029: Require signed consumer acknowledgements for trust-store rollout coverage

## Status

Accepted.

## Date

2026-09-27.

## Context

Phase 6m authenticates and orders trust-store packages but cannot show which intended consumers
accepted a checkpoint. Declaring a rollout complete from delivery logs alone can hide stale nodes
that still authorize revoked keys.

## Decision

Define strict Ed25519 consumer acknowledgements bound to one exact checkpoint and rollout-policy
digest. Authorize each consumer key for explicit non-personal target ids in a separate
lifecycle-aware public trust store. Apply an organization policy containing allowed targets,
required targets and a minimum distinct-target quorum. Reject duplicate target, key or receipt
identities and any mismatch in store identity, kind, sequence, checkpoint, policy or time.

## Alternatives considered

- Treat distribution success as adoption: rejected because transport completion does not prove a
  consumer accepted the expected bytes.
- Require every allowed target: rejected because organizations need explicit required nodes plus a
  bounded quorum for larger interchangeable groups.
- Poll live nodes from this repository: deferred because network topology, credentials and health
  semantics belong to the selected deployment system.

## Consequences

Consumers need dedicated signing identities and must emit one bounded receipt after accepting a
checkpoint. Rollout systems can block completion when required targets or quorum are missing.

## Security and privacy impact

Receipts contain non-personal target/key ids, timestamps and cryptographic digests/signatures only.
They exclude configuration content, credentials, private keys, people and customer data. Compromised
consumer keys can falsely acknowledge their authorized targets.

## Operational impact

Verification is offline, deterministic and read-only. It does not distribute configuration, contact
nodes, restart services or mutate infrastructure. Consumer key rotation and receipt collection are
deployment operations.

## Follow-up

- Connect receipt generation/collection to the selected distribution platform.
- Add runtime-loaded digest health probes where supported.
- Define alerts and remediation for missing, late or conflicting target state.
