# OCI evidence artifacts

Phase 6r packages allowlisted metadata-only evidence as a deterministic OCI image layout. The
command does not contact a registry and never reads credentials.

## Create a layout

Use a new output path and an explicit UTC creation time. References are normalized lowercase
identifiers, not full registry URLs or mutable tags.

```bash
uv run python scripts/manage_oci_evidence.py create \
  --output var/oci-evidence/release-2026-09 \
  --package-ref release-2026.09 \
  --created-at 2026-09-27T18:00:00+00:00 \
  --artifact RELEASE_EVIDENCE_BUNDLE=/approved/release-evidence.json \
  --artifact PROMOTION_AUTHORIZATION_REPORT=/approved/promotion-report.json \
  --artifact PUBLIC_TRUST_STORE=/approved/release-trust.yaml \
  --artifact RFC3161_TIMESTAMP_REPORT=/approved/timestamp-report.json
```

The layout contains `oci-layout`, `index.json` and `blobs/sha256/`. Its OCI manifest uses artifact
type `application/vnd.regulaai.release-evidence.v1`; the canonical config binds artifact kind,
basename, media type, size and digest.

## Verify a layout

```bash
uv run python scripts/manage_oci_evidence.py verify \
  --layout var/oci-evidence/release-2026-09 \
  --package-ref release-2026.09
```

Verification resolves the single index descriptor, checks manifest/config/layer bindings and
requires the blob directory to contain exactly the referenced SHA-256 objects. The output identity
includes the manifest digest to pin through any later transport.

## Registry boundary

Use an organization-approved OCI tool to import/export the layout and always pin the verified
manifest digest. Configure registry endpoints, workload identity, least-privilege repository access,
timeouts, bounded retries, immutability, retention, replication and deletion outside this adapter.
Apply an approved OCI signing policy before trusting evidence obtained from a registry; a mutable tag
or successful pull is not proof of origin. Re-run offline verification after export from transport.
