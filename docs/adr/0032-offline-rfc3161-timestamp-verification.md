# ADR-0032: Verify RFC 3161 timestamps offline

## Status

Accepted.

## Date

2026-09-27.

## Context

Phase 6p defines a small provider-neutral time receipt, but enterprise evidence systems commonly
exchange RFC 3161 timestamp requests and responses. Interoperability requires strict ASN.1 parsing,
exact artifact binding and PKIX verification without silently turning verification into a network
dependency or selecting a timestamp authority.

## Decision

Require the original DER request, DER response, exact artifact bytes, caller-allowlisted policy OIDs,
explicit UTC evaluation time and a deployment-supplied CA bundle. Parse request/response metadata
with `asn1crypto`; accept only SHA-256, SHA-384 or SHA-512; require matching imprints, nonce and
policy; and use `openssl ts -verify` with a bounded timeout to verify CMS signature, timestamping EKU
and PKIX chain at the asserted generation time. Emit only a deterministic metadata report.

## Alternatives considered

- Treat the Phase 6p receipt as standards-compatible: rejected because its schema and trust model
  are intentionally not RFC 3161.
- Implement CMS signature and PKIX validation directly in application code: rejected because it
  duplicates mature cryptographic validation and increases parser/verification risk.
- Contact a TSA, CRL or OCSP endpoint during verification: rejected because deterministic offline
  operation and explicit deployment availability boundaries are required.
- Select a hosted timestamp provider: deferred because procurement, jurisdiction, SLA and evidence
  retention requirements are organization-specific.

## Consequences

Existing RFC 3161 evidence can be checked against exact release/trust artifact bytes and local PKIX
trust. Verification requires OpenSSL and preservation of the original request; the response alone
cannot establish the expected nonce or artifact claim.

## Security and privacy impact

Inputs are bounded regular files and policy OIDs are allowlisted. The report contains only digests,
policy OID, serial number and UTC generation time—not artifact bytes, certificate subjects, people,
credentials or private keys. ASN.1 parsing is not trusted as cryptographic verification; OpenSSL
performs CMS and PKIX checks.

## Operational impact

Deployments must provide OpenSSL, the correct CA/intermediate bundles and explicit time bounds.
Offline verification does not retrieve current revocation state. Long-term validation therefore
depends on organization-retained revocation evidence, trust snapshots and renewal policy.

## Follow-up

- Add provider-specific acquisition only after authority, jurisdiction, SLA and retry semantics are
  approved.
- Define revocation-evidence retention and archival renewal when legal-record requirements demand it.
- Distribute metadata reports and related evidence through a provider-neutral OCI artifact phase.
