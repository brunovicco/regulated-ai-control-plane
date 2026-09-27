# ADR-0026: Retain release authority evidence in a content-addressed custody package

## Status

Accepted.

## Date

2026-09-26.

## Context

The release workflow can produce a complete evidence bundle, authenticated reviews and an authorized
promotion report, while Phase 6j can retire or revoke keys from active trust stores. Without one
bounded retained package, an organization may lose the exact public trust snapshots and attestations
needed to reproduce why a candidate was authorized. Ad hoc directories also allow silent mutation,
partial copies and accidental private-key retention.

## Decision

Provide an offline create/verify custody boundary. Creation requires exactly one canonically valid
complete evidence bundle, exactly one canonically valid authorized promotion report bound to that
bundle and at least one public trust-store snapshot. Additional inputs are limited to named release
metadata/public-verification artifact kinds.

Reject symlinks, unsafe filenames, empty/oversized artifacts and common PEM private-key markers.
Store exact bytes under SHA-256 filenames. Emit a canonical manifest binding archive id, explicit UTC
creation time, core identities, artifact kinds, original basenames, sizes and digests. Create only a
new directory through atomic rename. Verification recomputes every binding and rejects missing,
changed or untracked files.

## Alternatives considered

- Keep CI logs as the release record: rejected because logs are not a stable exact-byte custody
  boundary and may omit trust snapshots.
- Store artifacts in SQLite: rejected because release artifacts have a file-oriented lifecycle and
  should not enlarge the runtime evidence database.
- Archive policy/provider/tool source files too: rejected because Phase 6k is metadata/public
  verification custody; signed manifests already bind those separately governed contents.
- Implement remote object storage or WORM APIs: deferred because credentials, provider choice,
  retention policy and external mutation authority belong to deployment infrastructure.

## Consequences

Operators receive a reproducible local package and deterministic verification command. Archives are
fail-if-present and intentionally reject any untracked explanatory file. Storage use increases by the
exact retained metadata artifact sizes plus a small manifest; duplicate bytes inside one archive are
stored once when their digest and suffix coincide.

## Security and privacy impact

The allowlist and private-key marker checks reduce accidental secret retention, while content
addressing detects mutation. Original basenames and release identifiers remain organization metadata
and require access/retention controls. The check is not a general secret scanner, and an attacker who
can replace an entire unanchored archive can replace its manifest too.

## Operational impact

Creation and verification are local, synchronous and network-silent. The output must be moved to an
organization-approved store with retention, encryption, immutable-storage, backup and deletion
controls. No runtime API, database schema, provider call or tool execution changes.

## Follow-up

- Anchor manifest digests in an externally trusted timestamp or transparency service.
- Add deployment-specific immutable object storage and restore verification.
- Add organization policy for retention duration, legal hold and approved deletion.
