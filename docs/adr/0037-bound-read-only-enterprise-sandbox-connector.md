# ADR-0037: Bind the first enterprise connector to one read-only sandbox tool

## Status

Accepted.

## Date

2026-09-28.

## Context

Phase 4 proves exact tool proposal, action-specific approval, atomic claim and closed output
handling against a network-silent adapter. Phase 7a proves live provider composition but enables no
tool effect. The next product proof needs one enterprise boundary without introducing a generic
HTTP tool, trusting caller-selected endpoints or enabling a state-changing action before recovery
operations exist.

## Decision

Add an opt-in `ToolExecutionPort` adapter bound to the signed-catalog `cards.read` definition, its
`read_only` risk class, one deployment-configured workload identity and one sandbox endpoint. The
adapter sends the exact validated arguments only after action-specific approval has been consumed.
It makes one bounded POST, disables redirects and environment proxies, validates a closed response
envelope and returns the untrusted output to the existing Phase 4d schema/minimization boundary.

Mock execution remains the default. HTTPS is mandatory except for literal loopback IPs. Endpoint,
credential, workload, timeout and size limits must be complete at startup. Header-unsafe
idempotency keys fail before persistence or approval consumption.

## Alternatives considered

- Generic configurable HTTP tools: rejected because endpoint/method/header authority would become
  caller- or catalog-driven egress and substantially expand SSRF and exfiltration risk.
- A state-changing card connector: deferred until reconciliation operations and downstream
  idempotency are proven operationally.
- Embed a vendor SDK: rejected because no concrete enterprise platform was selected and the first
  proof needs a minimal organization-owned sandbox contract.
- Retry read failures locally: rejected because a timeout can occur after downstream processing and
  retry ownership must remain explicit.

## Consequences

The control plane can cross one live enterprise read boundary while preserving its existing action
authority and result-safety contracts. The adapter is intentionally not reusable for arbitrary
tools. Adding another tool or workload requires a separately reviewed binding rather than a runtime
allowlist expansion.

## Security and privacy impact

The bearer credential is excluded from representations and supplied only in the authorization
header. Arguments and raw output remain ephemeral; persisted records contain only existing action,
schema, result and execution metadata/digests. Redirects and environment proxies are disabled,
compressed responses are refused, responses are bounded and duplicate JSON keys are rejected.
Deployment-controlled DNS and HTTPS still require egress, certificate and destination monitoring
because configuration compromise is a residual SSRF/exfiltration risk.

## Operational impact

The sandbox must implement the documented request/response envelope, exact idempotency behavior and
one reviewed workload identity. Any uncertain transport result is terminal
`RECONCILIATION_REQUIRED`; malformed safe-output content is terminal `RESULT_REJECTED`. Kubernetes
deployments require a separately reviewed egress overlay because the reference policy denies
egress by default.

## Follow-up

- Implement authenticated operator reconciliation without automatic re-execution.
- Collect sandbox evidence for duplicate, timeout and late-success behavior.
- Move from SQLite before multi-replica production rollout.
- Require a separate ADR and recovery analysis before any state-changing connector.
