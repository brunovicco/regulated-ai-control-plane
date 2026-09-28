# ADR-0034: Provide a restricted Kubernetes/OpenShift deployment reference

## Status

Accepted.

## Date

2026-09-27.

## Context

OCI packaging provides a distribution boundary but does not show how the control-plane service and
runtime trust-state verification should run. Choosing a managed Kubernetes provider or installing a
custom operator would prematurely select cluster identity, storage and secret systems. A portable
reference can establish safe defaults while keeping apply and infrastructure authority external.

## Decision

Provide a Kustomize Kubernetes reference and OpenShift restricted-SCC overlay. Run exactly one API
replica with `Recreate` while persistence is SQLite, use an image replaced by digest, mount the
signed control pack/trust/state/secrets from external resources, and apply restricted non-root
security contexts, resource bounds, health probes, no service-account token and default-deny egress.
Run a separate network-silent CronJob every five minutes to verify mounted runtime attestations at a
captured UTC instant and emit the existing metadata-only report.

## Alternatives considered

- Select a managed Kubernetes or serverless provider: rejected because cluster/provider identity,
  procurement and regional requirements are external decisions.
- Build a custom Kubernetes operator now: rejected because no reconciliation mutation is required;
  the current components are declarative workloads and externally populated evidence volumes.
- Scale the API horizontally over SQLite: rejected because concurrent local database writers and
  volume attachment semantics would be unsafe.
- Give the verifier API access to discover pods: rejected because signed assertions are supplied
  evidence and the verifier requires neither a service-account token nor cluster read authority.

## Consequences

Teams can render a provider-neutral baseline for Kubernetes or OpenShift without this repository
accessing a cluster. External resources must be populated before rollout. Gateway execution cannot
work under the default egress-deny policy and requires an explicit reviewed overlay.

## Security and privacy impact

The reference embeds no credentials or personal data. It limits Linux and network authority and
keeps trust inputs read-only. Runtime reports contain only bounded identifiers, UTC times and
digests/signature digests. Cluster logs and object metadata remain deployment-controlled evidence.

## Operational impact

Kubernetes uses fixed UID/GID 10001 plus `fsGroup` for volumes. The OpenShift overlay removes fixed
identity fields so the restricted SCC can allocate namespace ranges. Operators must replace the
non-routable image reference/digest, supply storage and authority objects, verify rendering, and use
progressive rollout/rollback procedures. A failed verifier job is an alert input, not remediation.

## Follow-up

- Migrate persistence before introducing multiple replicas or rolling overlap.
- Add a reviewed gateway-mode overlay only after endpoint identity, egress and credential controls
  are selected.
- Connect metadata-only lifecycle events to CloudEvents and OTLP in the next phase.
