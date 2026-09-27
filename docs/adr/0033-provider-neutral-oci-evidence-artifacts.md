# ADR-0033: Package release evidence as OCI artifacts

## Status

Accepted.

## Date

2026-09-27.

## Context

Release, trust and timestamp evidence needs a portable distribution format. Selecting a registry or
cloud platform would couple integrity logic to procurement, credentials and deployment topology.
OCI image layouts provide content-addressed descriptors and broad tooling compatibility while still
allowing package creation and verification to remain offline.

## Decision

Create a deterministic OCI image layout containing one OCI image index, one RegulaAI evidence
artifact manifest, a canonical config and one layer per allowlisted JSON/YAML artifact. Bind a
normalized package reference and explicit UTC creation time in both the index descriptor and config.
Use SHA-256 descriptors throughout and verify the exact blob inventory. Do not implement registry
operations or credentials.

## Alternatives considered

- Select a cloud-specific artifact service and SDK: rejected because provider choice, identity and
  availability policy are deployment decisions.
- Distribute a tar/zip archive only: rejected because it lacks OCI-native descriptor and registry
  interoperability; Phase 6k remains the local custody format.
- Invoke an OCI CLI from the adapter: rejected because tool availability/version and credential
  behavior would enter the trusted verification boundary.
- Add artifact signing in the same phase: deferred so transport packaging does not silently choose a
  signing identity, trust store or key-custody system.

## Consequences

Approved OCI tools can transport the resulting directory to compatible registries, and consumers
can verify the exported layout independently. The package reference is a local resolution identity,
not proof that a remote tag still points to the same digest.

## Security and privacy impact

Only allowlisted artifact kinds with bounded safe JSON/YAML filenames are accepted. Symlinks,
untracked blobs, digest/size/metadata mismatches and common PEM private-key markers fail closed. The
marker check is defense in depth, not general secret or personal-data detection.

## Operational impact

Creation is atomic and never overwrites an output. Verification is deterministic, offline and checks
the complete layout inventory. Deployments must pin the verified manifest digest when pushing or
pulling and independently configure registry authentication, authorization, signing, retention,
replication, immutability and deletion.

## Follow-up

- Add deployment manifests that consume pinned OCI evidence digests without embedding credentials.
- Select organization-approved OCI signing and transparency controls when trust requirements are
  defined.
- Add registry integration only with explicit identity, timeout, retry and availability semantics.
