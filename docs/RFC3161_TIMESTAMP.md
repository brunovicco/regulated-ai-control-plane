# RFC 3161 timestamp verification

Phase 6q verifies an existing RFC 3161 request/response pair for one exact artifact. It does not
request a timestamp, choose a timestamp authority or contact any network service.

## Verify

Preserve the original DER request (`.tsq`) and response (`.tsr`). Configure policy OIDs and trust
material from organization-approved deployment configuration, never from the evidence package.

```bash
uv run python scripts/verify_rfc3161_timestamp.py \
  --artifact /approved/release-evidence.json \
  --request /approved/release-evidence.tsq \
  --response /approved/release-evidence.tsr \
  --ca-bundle /approved/tsa-ca.pem \
  --subject-kind RELEASE_EVIDENCE_BUNDLE \
  --policy-oid 1.2.3.4.1 \
  --evaluated-at 2026-09-27T18:00:00+00:00 \
  --minimum-generated-at 2026-09-27T00:00:00+00:00
```

Supply `--untrusted-certificates` for deployment-approved intermediates when they are not embedded
in the response. Repeat `--policy-oid` to allow more than one policy. The command exits zero and
prints a deterministic metadata-only JSON report only after all checks pass.

## Fail-closed checks

- inputs are non-empty, bounded regular files and not symlinks;
- request and response are strict DER with one supported signer;
- request and response contain the same SHA-256/SHA-384/SHA-512 imprint for the exact artifact;
- the required nonce and policy match, and the policy is caller-allowlisted;
- generation time is UTC, not after evaluation and not below the optional external floor;
- OpenSSL verifies the CMS signature, timestamping EKU and PKIX chain at generation time within ten
  seconds.

## Operating boundary

The CA bundle, policy allowlist and time floor are trust anchors; distribute and pin them separately
from untrusted evidence. Verification is offline and therefore does not fetch CRLs or use OCSP.
Where retention policy requires long-term validation, preserve the original DER inputs, applicable
trust/revocation material and renewal evidence in an approved immutable system. The custody archive
can retain the JSON verification report, but intentionally rejects binary DER and PEM artifacts.
