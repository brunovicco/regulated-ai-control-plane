# ADR-0008: Resolve tool authority from a trusted catalog and stop at proposals

## Status

Accepted.

## Date

2026-09-24.

## Context

The evaluation API previously accepted a caller-supplied tool risk class. Policy matching therefore
depended on an untrusted claim and a caller could describe a state-changing tool as read-only.
Phase 3a rejected every tool-bearing gateway plan, while the pinned gateway contract already
supports provider-neutral tool definitions and returns model-produced tool calls.

A model-produced call cannot authorize itself. Phase 4a approval is bound to the deterministic
evaluation input and decision before inference; it does not bind the exact arguments produced by a
model afterward. Forwarding those arguments to a side-effecting system would therefore cross the
authority boundary without action-specific approval.

## Decision

Introduce an application `ToolCatalogRepository` backed by one strict, versioned YAML catalog.
Each organization-owned definition contains a stable name, description, risk class, schema version
and closed JSON object input schema. The adapter canonicalizes the schema and computes its digest.

Clients request tools by name. A legacy-compatible risk claim is optional, untrusted and must match
the catalog exactly. `EvaluateAiOperation` rejects unknown, duplicate or conflicting requests and
uses only catalog risk classes for policy matching. Catalog version, definition identity and schema
digest are included in deterministic evaluation and enforcement digests and metadata-only evidence.

The gateway adapter translates authorized definitions to deterministic gateway-safe aliases. A
terminal gateway tool call must map to an authorized definition. RegulaAI returns and persists only
the call identifier, trusted tool identity, schema metadata and a digest of canonical arguments.
It does not persist/return arguments or invoke a tool execution port.

## Alternatives considered

- Trust caller risk classes: rejected because callers would control the policy predicate intended
  to constrain them.
- Reject tools indefinitely: rejected because the gateway can safely expose a proposal boundary
  once definitions are organization-owned and no side effect occurs.
- Execute read-only calls immediately: deferred because read-only classification, argument
  validation, output handling and downstream identity still need an explicit execution contract.
- Treat Phase 4a approval as authorization for model-produced arguments: rejected because the
  approved digest predates and therefore cannot bind those arguments.
- Add a general JSON Schema engine now: deferred; the catalog accepts a deliberately small closed
  object schema and action execution remains out of scope.

## Consequences

Policy decisions no longer depend on caller-defined tool risk. Gateway workloads may receive
reviewed definitions and return auditable proposals. Existing callers may omit `risk_class`; callers
that still send it receive a fail-closed error on disagreement.

Tool proposals are not useful as completed business actions. A separate action-execution workflow
is required to validate arguments, obtain exact authority and invoke enterprise systems.

## Security and privacy impact

Unknown, duplicate and risk-conflicting requests fail before execution. Closed schemas and bounded
descriptions reduce prompt/schema injection surface. Gateway output remains untrusted: tool names
must map to the authorized set, call IDs must be unique, and arguments must be JSON-serializable and
bounded before digesting.

Raw tool arguments and outputs are excluded from API responses, logs and persistence. The digest is
metadata for later binding, not proof that an action was safe or executed.

## Operational impact

Startup now requires a valid packaged or explicitly supplied tool catalog. Catalog changes require
a new version and change evaluation digests, so previously issued approvals do not transfer across
schema/risk updates. Gateway tool aliases are deterministic but are not public catalog identifiers.

SQLite repositories add metadata-only catalog/tool columns using additive startup migration.

## Follow-up

- Define an action-execution port with downstream workload identity and idempotency.
- Validate exact proposed arguments against the catalog schema before approval.
- Issue and consume approval bound to the action digest after proposal generation.
- Define safe handling of tool results before returning them to a model.
- Add a local gateway composition proof without production data.
