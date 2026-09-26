# Release artifact custody

Phase 6k packages the metadata and public verification material needed to reproduce one completed
release decision. It does not retain policy/provider/tool content, prompts, responses, tool
arguments/results, credentials, private keys or customer data.

## Required core artifacts

Every archive requires:

- one `RELEASE_EVIDENCE_BUNDLE` with `EVIDENCE_COMPLETE`, no findings and a valid canonical digest;
- one `PROMOTION_AUTHORIZATION_REPORT` with `PROMOTION_AUTHORIZED`, no findings, a valid canonical
  digest and the exact evidence-bundle digest;
- at least one `PUBLIC_TRUST_STORE` snapshot.

Additional allowlisted artifacts are control-pack manifests, release-review attestations, promotion
attestations, promotion policies and metadata-only scenario suites. Input files must be regular
JSON/YAML files with safe basenames. Symlinks, oversized inputs and common PEM private-key markers
are rejected.

## Create an archive

Use a new output path. The command never overwrites an existing file or directory.

```bash
uv run python scripts/manage_release_custody.py create \
  --output var/release-custody/release-2026-09-26 \
  --archive-id release-2026-09-26 \
  --created-at 2026-09-26T18:00:00+00:00 \
  --artifact RELEASE_EVIDENCE_BUNDLE=/approved/release-evidence.json \
  --artifact PROMOTION_AUTHORIZATION_REPORT=/approved/promotion-report.json \
  --artifact PUBLIC_TRUST_STORE=/approved/control-pack-trust.yaml \
  --artifact PUBLIC_TRUST_STORE=/approved/review-trust.yaml \
  --artifact PUBLIC_TRUST_STORE=/approved/promotion-trust.yaml
```

Artifacts are stored under SHA-256 filenames. `custody-manifest.json` records the archive id,
explicit UTC creation time, core digests, artifact kinds, original basenames, sizes and digests, plus
its own canonical digest. Creation uses a sibling staging directory and atomic rename.

## Verify an archive

```bash
uv run python scripts/manage_release_custody.py verify \
  --archive var/release-custody/release-2026-09-26
```

Verification recomputes the manifest digest, every blob digest/size, the bundle and authorization
digests, their exact binding and the complete tracked-file set. It performs no network call and does
not trust file timestamps.

## Operating boundary

Move or replicate the completed archive only through organization-approved storage controls.
Configure retention, access control, encryption at rest, immutable/WORM policy, off-site backup,
restoration tests, trusted timestamping and approved deletion outside this repository. Preserve the
directory as one unit; adding even an explanatory file makes verification fail until a new custody
archive is deliberately created.

The private-key marker check is defense in depth, not general secret detection. Review the artifact
allowlist before creation and never pass arbitrary application configuration or production data.
