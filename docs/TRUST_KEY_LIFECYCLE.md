# Verification-key lifecycle runbook

RegulaAI has three separate public-key authority boundaries: control-pack signing, release review
and release promotion. Their trust stores use schema version 2 and every key declares:

- `status`: `ACTIVE`, `RETIRED` or `REVOKED`;
- `valid_from`: required timezone-aware UTC activation instant;
- `valid_until`: optional exclusive timezone-aware UTC expiry instant.

Only an `ACTIVE` key within `[valid_from, valid_until)` is accepted. The verifier rejects malformed
windows and all legacy trust-store schemas. Private keys must never enter this repository, logs,
reports or trust stores.

## Planned rotation

1. Generate the replacement key in the organization-approved signer or hardware boundary.
2. Add only its public key to the correct trust store with a future `valid_from`, `ACTIVE` state and
   a deliberate overlap with the incumbent key.
3. Distribute and validate the trust store everywhere before using the new private key.
4. Start signing new artifacts with the replacement key after its activation instant.
5. Confirm every required verifier has accepted the new key and no in-flight artifact still depends
   on the incumbent key.
6. Change the incumbent key to `RETIRED` and distribute the updated trust store.
7. Retain the exact historical trust-store snapshots with release evidence under the Phase 6k
   custody procedure; do not keep retired keys active merely for convenience.

## Emergency revocation

1. Change the affected public key to `REVOKED` in the authoritative trust store.
2. Distribute the updated trust store through the approved emergency path.
3. Stop signing and reject pending artifacts produced by the affected private key.
4. Provision a distinct replacement key; never reuse the compromised public/private key pair.
5. Identify packs, reviews and promotion votes whose authority depended on the key and trigger the
   organization incident/reassessment process.

Revocation metadata is not a remote revocation service. Verification is only as current as the
local trust-store copy, so distribution monitoring and rollback protection remain required.

## Verification clocks

- Control packs: explicit verifier time; runtime startup defaults to current UTC.
- Release reviews: signed `attested_at` UTC time.
- Promotion attestations: signed `issued_at` UTC time. The separate promotion use case still checks
  whether the vote itself is active at its explicit evaluation time.

Time synchronization and rollback resistance are deployment responsibilities. Offline CI should
pass explicit instants when reproducing control-pack verification.

## Validation

Run the complete repository quality gate after every trust-store change:

```bash
uv run python scripts/quality_gate.py
```

Then verify the intended pack/review/promotion workflow with its normal offline command. Never test
key changes with production private keys or production personal data.
