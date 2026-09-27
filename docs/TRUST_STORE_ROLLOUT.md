# Trust-store rollout acknowledgements

Phase 6n verifies which explicitly allowlisted consumers accepted one exact Phase 6m checkpoint.
Each consumer signs a metadata-only acknowledgement containing the checkpoint and rollout-policy
digests, store identity/kind, sequence, target id and UTC acceptance time.

The organization supplies a rollout policy with allowed targets, required targets and a minimum
distinct-target quorum. Consumer keys live in a separate lifecycle-aware schema-v2 public trust
store and are authorized for explicit target ids.

```bash
uv run python scripts/verify_trust_store_rollout.py \
  --trust-store /distributed/control-pack-signing-keys.yaml \
  --checkpoint /distributed/control-pack-trust-2.json \
  --checkpoint-public-key /pinned/checkpoint-signing-public.pem \
  --checkpoint-signing-key-id production-distribution-root \
  --minimum-sequence 2 \
  --rollout-policy /approved/rollout-policy.yaml \
  --acknowledgement-trust-store /approved/consumer-keys.yaml \
  --acknowledgement /receipts/node-a.yaml \
  --acknowledgement /receipts/node-b.yaml \
  --evaluated-at 2026-09-27T15:00:00+00:00
```

Exit code `0` means all required targets and the quorum are present, `2` means valid evidence is
incomplete and `1` means a signature, authority, binding or schema is invalid. One target, key and
acknowledgement id can count only once.

The report proves signed acceptance metadata, not that a distribution system delivered the file,
that the consumer loaded it into a running process or that every fleet node is healthy. Collection,
delivery, runtime health checks, alerts and remediation remain deployment responsibilities.
