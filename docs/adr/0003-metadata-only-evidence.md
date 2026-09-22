# ADR-0003: Evidence is metadata-only

Status: Proposed

## Context

Auditability is necessary, but storing prompts/responses/personal data in an evidence store creates
a second sensitive-data repository and can undermine minimization objectives.

## Decision

Evidence records contain only:
- IDs/timestamps;
- classifications;
- decision/obligation/reason codes;
- version references;
- provider capability fact IDs;
- cryptographic digests;
- optional tamper-evident chaining metadata.

They do not contain raw prompt/response/tool payload/customer values/credentials.

## Consequences

Benefits:
- lower leakage/retention surface;
- easier observability hygiene;
- supports reproducibility through versions/digests.

Costs:
- forensic replay requires authorized access to source systems if raw content is needed;
- digest canonicalization must be stable.
