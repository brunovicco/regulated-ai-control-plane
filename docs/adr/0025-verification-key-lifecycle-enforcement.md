# ADR-0025: Enforce verification-key lifecycle in every release trust boundary

## Status

Accepted.

## Date

2026-09-26.

## Context

Control-pack, release-review and promotion verifiers selected public keys by identifier and scope,
but any listed key remained trusted indefinitely. Removing a key was the only way to end authority,
which did not distinguish planned rollover from emergency revocation or enforce activation/expiry
windows. A valid signature from stale trust metadata could therefore retain authority.

## Decision

Advance all three public-key trust stores to strict schema version 2. Each key carries an explicit
`ACTIVE`, `RETIRED` or `REVOKED` state, required timezone-aware UTC `valid_from` and optional
exclusive UTC `valid_until`. The shared lifecycle boundary rejects malformed or decreasing windows.

Only `ACTIVE` keys inside their half-open validity interval may authorize an artifact. Control-pack
verification uses an explicit evaluation instant and defaults to current UTC at runtime. Release
review keys are evaluated at signed `attested_at`; promotion keys are evaluated at signed
`issued_at`. Lifecycle authorization occurs before accepting the signature's authority.

## Alternatives considered

- Remove keys without recording state: rejected because retirement, emergency revocation and
  accidental deletion are operationally different events.
- Depend only on attestation expiry: rejected because pack signatures have no expiry and a
  compromised reviewer or promotion key must be revocable independently.
- Fetch remote revocation status: rejected because the release workflow is deliberately local and
  network-silent.
- Preserve schema-v1 trust stores indefinitely: rejected because missing lifecycle metadata would
  silently retain unbounded authority.

## Consequences

Existing trust stores must be migrated before use. Planned rotations may overlap two active public
keys. Retiring or revoking a key causes artifacts selected through the active trust store to fail
closed even when their Ed25519 signature is valid. Historical verification therefore requires an
approved retained trust snapshot rather than leaving obsolete keys active.

## Security and privacy impact

The change limits stale-key authority and makes emergency revocation explicit. Trust stores contain
only public keys, non-personal identifiers and lifecycle timestamps. No private keys, credentials,
payload content or personal data are added. Compromise or rollback of the trust store itself remains
a high-integrity deployment risk.

## Operational impact

Operators must coordinate trust-store distribution before signer rollover and maintain reliable UTC
time. The packaged demo key is active without an automatic expiry; production deployments should
set organization-approved expiry windows. The runbook documents overlap rotation and emergency
revocation. No network call, database migration or provider/tool execution is introduced.

## Follow-up

- Add durable content-addressed custody for bundles, attestations and historical trust snapshots.
- Add trust-store version rollback protection and distribution acknowledgements.
- Integrate organization hardware-backed key issuance, destruction and incident response.
