# ADR-0027: Require detailed owner and implementation review for tool changes

## Status

Accepted.

## Date

2026-09-27.

## Context

Phase 6i binds the trusted tool catalog into the signed release and requires an authenticated
whole-catalog review. That proves who approved exact catalog bytes, but does not show that every
changed definition has an accountable owner and implementation evidence. A broad approval could
therefore conceal an unreviewed addition, removal or schema change.

## Decision

Add an offline detailed review gate for updates to an existing catalog. Compare tools by stable
name, require one exact review for every semantic addition, removal or modification, and bind the
record to the approved pack payload digest and candidate catalog digest. Each tool review carries a
non-personal owner role, bounded HTTPS implementation references, exact change type and conclusion.
Require `schema_version` to change whenever either input or output schema changes.

For modified catalogs, release-evidence assembly requires the signed review attestation to bind the
passing detailed review id and digest. Rejection, revision request, missing coverage or mismatched
lineage fails closed.

## Alternatives considered

- Continue with whole-catalog review only: rejected because it cannot demonstrate per-definition
  coverage or ownership.
- Retrieve and validate implementation sources automatically: deferred because authentication,
  network trust and source-specific semantics require deployment-owned integrations.
- Store source content in the review: rejected to keep evidence metadata-only and avoid retaining
  proprietary code, credentials or personal data.

## Consequences

Every changed tool needs an explicit owner and at least one implementation reference. Reviewers
must update tool schema versions when contracts change. Release assembly receives one additional
optional input that becomes mandatory only when a modified tool catalog is attested.

## Security and privacy impact

The gate narrows silent tool-authority expansion and keeps raw implementation content outside the
artifact. URLs and role identifiers are organizational metadata and still need access and retention
controls. HTTPS references are evidence pointers, not proof that referenced implementations are
safe, immutable or deployed.

## Operational impact

The workflow is local, deterministic and network-silent. It does not call a tool, fetch references,
sign a review, promote a release or deploy code.
