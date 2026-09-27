# ADR-0028: Bind public trust-store updates into monotonic lineage checkpoints

## Status

Accepted.

## Date

2026-09-27.

## Context

Phase 6j rejects inactive and out-of-window keys in the supplied trust store, but a stale or rolled
back store can restore authority by omitting a later revocation. Phase 6k retains exact snapshots
without defining update order. The repository needs a provider-neutral way for a distribution
boundary to detect stale or forked public trust metadata.

## Decision

Create strict Ed25519-signed canonical JSON checkpoints that bind exact schema-v2 trust-store bytes, stable store
identity, one of the three authority kinds, a monotonic sequence, UTC issue time and the prior
checkpoint digest. Genesis is sequence one. Each successor must increment by exactly one, advance
time and bind changed trust-store bytes.

Verification requires a pinned distribution-authority public key plus a caller-controlled rollback
floor: an expected checkpoint digest, minimum accepted sequence or exact predecessor. Checkpoint creation is fail-if-present. Inputs reject
symlinks, duplicate keys, malformed schemas, oversized data and common private-key PEM markers.
Allow checkpoints to be retained as Phase 6k custody artifacts.

## Alternatives considered

- Rely on filesystem modification times: rejected because they are mutable and not portable
  authority metadata.
- Put sequence fields directly into all three trust-store schemas: deferred because that would not
  prevent rollback unless verifiers still hold an external floor and would couple unrelated
  authority schemas to distribution state.
- Select a remote transparency log or object store: deferred because provider, credentials,
  availability and retention policy are deployment decisions.

## Consequences

Operators must preserve the distribution public key and accepted digest or sequence independently
from a newly distributed package and create checkpoints only for real byte changes. Forks, skipped
sequences, stale packages, invalid signatures and mismatched bytes fail closed.

## Security and privacy impact

Artifacts contain only public trust metadata identities, timestamps, counters and digests. Private
key markers are rejected. The mechanism cannot resist an attacker who can replace the package,
pinned public key and trusted rollback floor together.

## Operational impact

Creation and verification are local, deterministic and network-silent. The offline creation command
reads an external private key only to sign the checkpoint; it never stores or emits that key.
Deployments must persist the public key and accepted floor and invoke verification in their
distribution/startup workflow. No runtime API, database schema or live infrastructure mutation is
introduced.

## Follow-up

- Integrate the verifier with a selected configuration-distribution system.
- Anchor accepted checkpoint digests in an external transparency or trusted-time service.
- Define alerting and recovery for detected forks, gaps and stale nodes.
