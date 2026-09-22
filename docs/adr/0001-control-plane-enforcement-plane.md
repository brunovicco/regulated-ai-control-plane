# ADR-0001: Separate control plane from enforcement plane

Status: Proposed

## Context

Regulatory/provider intelligence changes independently from application traffic. Sensitive payloads
should stay as close as possible to the customer's trust boundary.

## Decision

Separate:

- control plane: policies, provider capabilities, versions, approvals/configuration;
- enforcement plane: runtime classification, evaluation, transformation, authority checks,
  evidence and future execution.

The first repository may host both logical components for simplicity, but code boundaries must
preserve the separation.

## Consequences

Benefits:
- supports future self-hosted enforcement;
- limits exposure of customer content;
- makes policy/provider updates independently versionable;
- supports multiple execution backends.

Costs:
- version distribution/synchronization becomes a product concern;
- stale configuration must be handled explicitly.
