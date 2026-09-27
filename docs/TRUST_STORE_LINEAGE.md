# Trust-store lineage checkpoints

Phase 6m adds deterministic checkpoints for the three public verification-key trust stores:
control-pack signing, release review and release promotion. A checkpoint binds the exact trust-store
bytes, a stable store id, authority kind, monotonic sequence, UTC issue time and the prior checkpoint
digest.

Every checkpoint is signed by a dedicated offline Ed25519 distribution authority. Only its public
verification key is installed at consumers; the private key must remain in the approved signer or
hardware boundary and must never be packaged with a trust store.

Create the first checkpoint:

```bash
uv run python scripts/manage_trust_store_lineage.py create \
  --trust-store /approved/control-pack-signing-keys.yaml \
  --output /approved/control-pack-trust-1.json \
  --store-id production-control-pack-signing \
  --store-kind CONTROL_PACK \
  --sequence 1 \
  --issued-at 2026-09-27T12:00:00+00:00 \
  --signing-key-id production-distribution-root \
  --private-key /secure/checkpoint-signing-private.pem
```

For each actual trust-store change, create the next checkpoint with exactly the prior checkpoint:

```bash
uv run python scripts/manage_trust_store_lineage.py create \
  --trust-store /approved/control-pack-signing-keys.yaml \
  --output /approved/control-pack-trust-2.json \
  --store-id production-control-pack-signing \
  --store-kind CONTROL_PACK \
  --sequence 2 \
  --issued-at 2026-09-27T13:00:00+00:00 \
  --signing-key-id production-distribution-root \
  --private-key /secure/checkpoint-signing-private.pem \
  --previous-checkpoint /approved/control-pack-trust-1.json
```

Creation rejects skipped/reused sequence numbers, changed identity/kind, non-increasing time,
unchanged trust-store bytes, private-key PEM markers, symlinks and existing output paths.

Verification always requires a trusted rollback anchor: an expected checkpoint digest, a minimum
sequence maintained outside the candidate package, or the exact prior checkpoint. For example:

```bash
uv run python scripts/manage_trust_store_lineage.py verify \
  --trust-store /distributed/control-pack-signing-keys.yaml \
  --checkpoint /distributed/control-pack-trust-2.json \
  --signing-key-id production-distribution-root \
  --public-key /pinned/checkpoint-signing-public.pem \
  --minimum-sequence 2 \
  --expected-checkpoint-digest sha256:...
```

The signature authenticates the checkpoint, while the minimum sequence or expected digest detects
rollback. If an attacker can replace the pinned public key and rollback floor together, this
mechanism cannot detect rollback. Keep both outside the newly distributed package and retain
checkpoints with release custody using `TRUST_STORE_CHECKPOINT`. Automated distribution, remote
consensus, trusted timestamping and private-key custody remain external.
