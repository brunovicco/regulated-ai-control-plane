# Signed time-authority receipts

Phase 6p verifies a provider-neutral Ed25519 receipt from an explicitly trusted external time
authority. The receipt binds one allowlisted artifact kind, its exact SHA-256 digest, a UTC issue
time, authority id and lifecycle-aware signing key.

```bash
uv run python scripts/verify_trusted_timestamp.py \
  --artifact /custody/release-evidence.json \
  --receipt /timestamps/release-evidence.yaml \
  --trust-store /approved/time-authority-keys.yaml \
  --subject-kind RELEASE_EVIDENCE_BUNDLE \
  --evaluated-at 2026-09-27T15:00:00+00:00 \
  --minimum-issued-at 2026-09-27T13:00:00+00:00
```

The optional issue-time floor is caller-pinned; it cannot be supplied by the receipt itself. Exact
artifact bytes, expected subject kind, authority identity, key lifecycle, signature and future-time
checks fail closed. Output contains only ids, times and cryptographic digests.

This format is not RFC 3161 and does not contact, select or certify a timestamp provider. Its trust
depends on organization-approved authority keys, authority operations and clock integrity. Service
availability, receipt acquisition, immutable retention and independent transparency remain external.
