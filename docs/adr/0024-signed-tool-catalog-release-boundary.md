# ADR-0024: Include the trusted tool catalog in the signed release boundary

## Status

Accepted.

## Date

2026-09-26.

## Context

The runtime resolved tools from a strict versioned catalog, but that file was loaded independently
after the control-pack verifier authenticated only policies and provider capabilities. Static diff,
scenario replay and release evidence therefore could not prove which tool definitions were active.
An operator could review one release while runtime startup consumed separately mutable catalog
bytes.

## Decision

Every signed control pack must contain exactly one `tool_catalog` file. Its path and SHA-256 digest
are part of the canonical Ed25519 payload. Verification returns the exact authenticated bytes and
all runtime and offline parsers consume those bytes without reopening the path. The runtime rejects
the former independent catalog override.

The release domain carries catalog version and immutable definitions. Static analysis compares
tools by stable name and treats additions, removals, risk-class changes and input/output schema
changes as potential decision impact. Scenario schema version 2 accepts only bounded tool names and
optional claimed risk classes; replay resolves them separately in each release and records catalog
and authorized-tool identities without arguments or execution.

Release evidence includes the exact catalog artifact digest. Any catalog change requires an
authenticated whole-catalog review attestation with the stable subject id
`trusted-tool-catalog`. Detailed per-definition review is deferred.

## Alternatives considered

- Keep a separately configured runtime catalog: rejected because reviewed release identity would
  not determine active tool authority.
- Put the catalog in the manifest but reopen its path later: rejected because it preserves a
  verification/use race.
- Add tool arguments to scenario replay: rejected because it would expand the metadata-only corpus
  and conflate evaluation with action authorization.
- Reuse policy review records for tools: rejected because tool schemas and ownership require a
  distinct review contract.

## Consequences

Older manifests without a tool catalog fail closed and must be repackaged. Runtime callers can no
longer override the catalog independently. Diff and replay outputs gain tool-related metadata, and
changed catalogs require one additional signed review artifact before release evidence is complete.

## Security and privacy impact

The change closes catalog substitution and time-of-check/time-of-use gaps. Scenario files and
reports retain only names, risk claims, versioned identifiers and digests; they contain no tool
arguments, results, prompts, credentials or customer data. A valid signature or review still does
not prove that downstream tool code matches its schema or is safe.

## Operational impact

Release automation must add one catalog entry before signing and provision reviewer authority for
`TOOL_CATALOG`. Private signing keys remain external. Verification, diff, replay and review remain
local and network-silent.

## Follow-up

- Define detailed per-tool ownership, source and change-review evidence.
- Add release-key rotation, revocation and durable signed-artifact retention.
- Bind downstream tool implementation provenance to reviewed catalog definitions.
