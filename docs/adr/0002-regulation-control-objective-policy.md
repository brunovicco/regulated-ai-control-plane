# ADR-0002: Do not execute regulation text directly

Status: Proposed

## Context

Legal/regulatory text requires interpretation, scope analysis and organizational risk decisions.
Automatically turning text into blocking runtime behavior would create false legal certainty.

## Decision

Use a mandatory three-layer mapping:

1. authoritative regulatory/security source;
2. human-reviewed organization control objective;
3. executable technical policy/control.

Regulatory references are informative support mappings. They never produce a `"compliant": true`
runtime result.

## Consequences

Benefits:
- clearer accountability;
- legal interpretation remains human-owned;
- technical rules remain testable;
- source changes can be assessed without silently changing runtime.

Costs:
- requires governance/review workflow;
- mappings require maintenance.
