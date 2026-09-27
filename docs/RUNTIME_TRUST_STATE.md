# Runtime trust-state attestations

Phase 6o verifies fresh, signed target assertions about the exact public trust-store digest loaded
by a runtime consumer. Each attestation binds the Phase 6m checkpoint, runtime policy, store
identity/kind, sequence, loaded trust-store digest, target id and UTC observation time.

The organization supplies a policy containing allowed targets, required targets, a minimum number
of fresh attestations and a maximum observation age. Target keys live in a separate lifecycle-aware
schema-v2 public trust store and are authorized for explicit non-personal target ids.

```bash
uv run python scripts/verify_runtime_trust_state.py \
  --trust-store /runtime/control-pack-signing-keys.yaml \
  --checkpoint /distributed/control-pack-trust-2.json \
  --checkpoint-public-key /pinned/checkpoint-signing-public.pem \
  --checkpoint-signing-key-id production-distribution-root \
  --minimum-sequence 2 \
  --runtime-policy /approved/runtime-state-policy.yaml \
  --attestation-trust-store /approved/runtime-target-keys.yaml \
  --attestation /observations/node-a.yaml \
  --attestation /observations/node-b.yaml \
  --evaluated-at 2026-09-27T15:00:00+00:00
```

Exit code `0` means fresh required-target and quorum coverage, `2` means valid but stale or
incomplete evidence and `1` means invalid schema, signature, authority, digest, target or time
binding. One target, key and attestation id can count only once.

The report proves authenticated assertions from target identities. It does not independently probe
a process, prove continuous enforcement, establish trusted time or prevent a compromised target
from lying. Probe implementation, collection, clock integrity, alerts and remediation remain
deployment responsibilities.
