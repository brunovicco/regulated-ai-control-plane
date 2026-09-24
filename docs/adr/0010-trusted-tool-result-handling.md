# ADR-0010: Validate and minimize untrusted tool results before exposure

## Status

Accepted.

## Date

2026-09-24.

## Context

Phase 4c proves action-specific authority and crosses a network-silent tool execution boundary, but
intentionally discards tool output. A real tool result is untrusted external input: it can violate
its declared shape, carry personal or financial data, expose credentials, or contain instructions
intended to influence a later model turn. Returning or persisting that result without a separate
control would turn successful execution into a content-exfiltration and prompt-injection path.

The control plane therefore needs an organization-owned output contract that is bound to the tool
definition and action authority, while preserving the existing metadata-only evidence boundary.

## Decision

Each trusted tool definition must include a closed, versioned output schema. Every field declares a
classification (`PUBLIC`, `INTERNAL`, `PERSONAL`, `FINANCIAL`, or `AUTHENTICATION_SECRET`) and a
handling rule (`RETURN`, `MASK`, or `DROP`). Directly returned fields must use a closed enum;
personal and financial fields cannot be returned directly; authentication secrets must be dropped.

The output schema is canonicalized and its digest is included in the tool-definition and action
digests. After execution, RegulaAI treats the adapter output as untrusted, validates the complete
object and field constraints, applies the trusted handling policy in memory, and computes separate
digests for the raw and safe forms. Invalid, extra, missing, oversized, mistyped, or disallowed
content becomes terminal `RESULT_REJECTED` and is not retried.

Only the immediate successful `POST` response may contain the minimized `safe_result`. SQLite,
action replay, and `GET /v1/tool-actions/{action_id}` retain only schema/result digests,
classifications and exposed field names. Raw and safe result content are never persisted. This
phase does not feed results into a model and does not enable a live enterprise connector.

## Alternatives considered

- Trust the adapter to sanitize output: rejected because adapter compromise or drift would bypass
  the control plane's independent validation boundary.
- Persist the safe result: rejected because masking is not anonymization and retained content would
  expand privacy, access-control and deletion obligations.
- Allow arbitrary strings marked `RETURN`: rejected because free-form external text could become a
  prompt-injection channel in later composition.
- Reject every sensitive field rather than mask/drop: rejected because bounded evidence that a
  value exists can be useful without exposing the value itself.

## Consequences

Catalog authors must define and review output schemas and field handling. Clients receive a safe
result only on the first successful execution response and must not expect content recovery from
the action resource. A schema or policy change alters the tool definition and action binding.

## Security and privacy impact

The design limits tool-result injection and data exfiltration, fails closed on schema drift, and
keeps credentials and sensitive values out of persistence, logs, errors and replay responses.
Digests provide correlation without making result content recoverable. Masked values still signal
field presence and must be treated as classified metadata.

## Operational impact

`RESULT_REJECTED` means the downstream call completed but its result was not safe to expose. It is
terminal and requires investigation of the tool contract or implementation, not automatic retry.
Operators can correlate the action, execution ID, output-schema digest and stable lifecycle event
without accessing raw content.

## Follow-up

- Add reviewed live connectors with explicit egress allowlists, identity and bounded timeouts.
- Define a separately authorized, injection-resistant composition boundary before any safe result
  is supplied to a model.
- Add operator workflows for `RESULT_REJECTED` and ambiguous execution reconciliation.
- Extend output types only through an explicit schema and policy review.
