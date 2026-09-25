# API contract — Phases 1 through 4d

The exact wire schema may be refined during implementation, but behavior and privacy boundaries
must remain stable.

## POST /v1/evaluations

Evaluates an AI operation. Does not invoke a provider in Phase 1.

### Example request

Use synthetic values only.

```json
{
  "correlation_id": "demo-001",
  "jurisdiction": "BR",
  "sector": "financial_services",
  "purpose": "customer_support",
  "operation_kind": "external_inference",
  "assurance_level": "high",
  "provider": {
    "provider": "openai",
    "service": "responses_api",
    "region": "global"
  },
  "organization_assertions": {
    "eligible_organization_required": true,
    "endpoint_or_feature_must_be_zdr_eligible": true
  },
  "data": [
    {
      "field": "customer_document",
      "value": "111.444.777-35",
      "labels": ["PERSONAL_DIRECT_IDENTIFIER"]
    },
    {
      "field": "customer_question",
      "value": "Synthetic support request",
      "labels": []
    }
  ],
  "tools": [
    {
      "name": "cards.read",
      "risk_class": "read_only"
    },
    {
      "name": "cards.unblock",
      "risk_class": "high_impact_state_change"
    }
  ],
  "policy_set_version": "br-financial-demo@1.0.0"
}
```

`fallback_providers` is an optional list using the same provider shape. Every fallback is checked
against the mandatory capability requirements selected for the primary operation; it is never
selected implicitly. `organization_assertions` is an optional boolean map for organization-owned
configuration facts required by conditional capabilities.

Correlation IDs, logical field names, provider identifiers, policy versions and tool identifiers
must use bounded machine-identifier syntax. Arbitrary content belongs only in ephemeral `value`
fields and is never echoed in validation errors.

Each requested tool requires only `name`. The legacy-compatible `risk_class` field is optional and
is treated as an untrusted assertion: when present it must exactly match the organization-owned,
versioned tool catalog. Unknown tools, duplicate names and mismatched claims fail closed with
`TOOL_NOT_AUTHORIZED`. Catalog risk and schema data, never caller claims, drive policy matching.

The CPF above is a public algorithm test/example value only. Tests may prefer clearly synthetic,
non-person values generated specifically for the suite.

### Example response

```json
{
  "evaluation_id": "eval_...",
  "decision": "REQUIRE_APPROVAL",
  "obligations": [
    {
      "type": "TOKENIZE",
      "target": "customer_document",
      "reason_code": "MINIMIZE_EXTERNAL_IDENTIFIER"
    },
    {
      "type": "REQUIRE_HUMAN_APPROVAL",
      "target": "cards.unblock",
      "reason_code": "HIGH_IMPACT_STATE_CHANGE"
    }
  ],
  "matched_policies": [
    "br.financial.external_inference.minimize@1.0.0",
    "org.agent.high_impact_approval@1.0.0"
  ],
  "provider_capabilities_used": [
    "openai.responses_api.zero_data_retention"
  ],
  "policy_set_version": "br-financial-demo@1.0.0",
  "provider_registry_version": "2026-09-22.1",
  "evidence_id": "ev_..."
}
```

Do not return regulatory-compliance claims such as `"lgpd_compliant": true`.

## GET /v1/evidence/{evidence_id}

Returns metadata only.

Must never return original field values/prompts/responses.

Example:

```json
{
  "evidence_id": "ev_...",
  "decision": "REQUIRE_APPROVAL",
  "classification_labels": ["BRAZIL_CPF"],
  "obligation_types": ["TOKENIZE", "REQUIRE_HUMAN_APPROVAL"],
  "provider_capability_snapshots": [
    {
      "capability_id": "openai.responses_api.zero_data_retention",
      "provider_target": "openai.responses_api.global",
      "key": "zero_data_retention",
      "state": "conditional",
      "conditions": ["eligible_organization_required"],
      "verified_at": "2026-09-22",
      "record_version": "1",
      "registry_version": "2026-09-22.1",
      "source_urls": ["https://developers.openai.com/pt-BR/api/docs/guides/your-data"]
    }
  ],
  "provider_context_complete": true,
  "policy_set_version": "br-financial-demo@1.0.0",
  "provider_registry_version": "2026-09-22.1",
  "input_digest": "sha256:...",
  "event_digest": "sha256:..."
}
```

## GET /v1/providers

Returns capability metadata suitable for debugging/demo:
- provider/service/region identifiers;
- capability states;
- verified date;
- source URLs;
- registry version.

No credentials/config secrets.

## POST /v1/enforcements

Accepts the same normalized request as `POST /v1/evaluations`, plus an optional
`approval_assertion` string (maximum 4096 bytes). It evaluates policy, applies local field
transformations and persists metadata-only enforcement state. The assertion is treated as a
secret, is never persisted or returned and is inspected only for `REQUIRE_APPROVAL`. The default
runtime calls the network-silent mock. Explicit gateway mode sends the sanitized plan through
`governed-llm-gateway`; tool-bearing plans include only definitions resolved from the trusted
catalog.

The Phase 4a assertion is issued by an external organization-owned workflow and has the form
`ra1.<base64url-canonical-json>.<base64url-hmac-sha256>`. Its exact fields are `schema_version=1`,
`approval_id`, pseudonymous `actor_id`, `decision_digest`, `issued_at` and `expires_at`. Unix
timestamps are seconds. The configured verifier rejects malformed, future, expired, over-lifetime,
wrong-digest and previously consumed approvals. The decision digest commits to both the normalized
operation input digest and the resulting policy decision, so an approval cannot be moved to another
operation with the same policy outcome. RegulaAI exposes no approval-issuance endpoint.

The response never includes source or transformed values:

```json
{
  "enforcement_id": "enf_...",
  "evaluation_id": "eval_...",
  "evaluation_evidence_id": "ev_...",
  "decision": "ALLOW_WITH_TRANSFORMATION",
  "status": "EXECUTED",
  "transformation_receipts": [
    {
      "receipt_id": "tr_...",
      "type": "TOKENIZE",
      "target": "customer_document",
      "input_digest": "sha256:...",
      "output_digest": "sha256:...",
      "reason_code": "MINIMIZE_EXTERNAL_IDENTIFIER"
    }
  ],
  "reason_codes": [],
  "output_digest": "sha256:...",
  "provider_execution_id": "mockexec_...",
  "provider_call_metadata": null,
  "approval_receipt": null,
  "tool_proposals": []
}
```

In gateway mode, `provider_execution_id` begins with `gw_` and `provider_call_metadata` may contain
only allowlisted gateway request/routing IDs, gateway policy ID/version, provider/model/deployment,
latency, attempt/fallback indexes and cache state. It never contains request content, model output,
credentials, provider response bodies or provider request IDs.

When the gateway proposes a tool call, `tool_proposals` contains only `call_id`, trusted tool name,
schema version/digest, an arguments digest and `execution_authorized: false`. Raw arguments are
neither returned nor persisted. A proposal is not an executed action, and Phase 4a approval does
not authorize its model-generated arguments.

## POST /v1/enforcements/{enforcement_id}/tool-actions

Resubmit one proposal's exact arguments with a downstream `workload_identity` and ephemeral
`idempotency_key`. RegulaAI validates the closed trusted schema and stored proposal digest, then
returns metadata-only `WAITING_APPROVAL` state and an `action_digest`. Every tool effect requires a
separate action approval in Phase 4c.

Resend the identical request with an externally issued `approval_assertion` using
`ra2.<base64url-canonical-json>.<base64url-hmac-sha256>`. Its payload contains
`schema_version=2`, `subject_type=tool_action`, `approval_id`, pseudonymous `actor_id`,
`action_digest`, `issued_at` and `expires_at`. `ra1` decision approvals are rejected.

After an atomic `DISPATCHED` claim, authority is consumed once and the network-silent mock tool
port executes. Success is accepted only when the untrusted output exactly matches the trusted,
action-bound closed output schema. Per-field catalog rules return a closed enum, replace a value
with `***MASKED***`, or drop the field. Personal/financial values cannot be returned directly and
authentication secrets are always dropped.

The immediate successful response includes the minimized result and metadata:

```json
{
  "status": "EXECUTED",
  "output_schema_digest": "sha256:...",
  "output_digest": "sha256:...",
  "safe_output_digest": "sha256:...",
  "result_classifications": ["FINANCIAL", "INTERNAL"],
  "exposed_result_fields": ["operation_reference", "operation_status"],
  "safe_result": {
    "operation_reference": "***MASKED***",
    "operation_status": "SUCCEEDED"
  }
}
```

`safe_result` is ephemeral and appears only on that immediate success response. An ambiguous
execution failure becomes terminal `RECONCILIATION_REQUIRED`. Invalid, extra, missing, mistyped,
oversized or disallowed result content becomes terminal `RESULT_REJECTED` with HTTP 502. Neither
state is automatically retried because the downstream effect may already have occurred.

## GET /v1/tool-actions/{action_id}

Returns action identity, trusted input/output schema, argument, action and result digests, workload
identity, status, classifications, exposed field names and metadata-only approval/execution
receipts. `safe_result` is always `null`; raw and minimized result values are never persisted or
recoverable from this endpoint.

## GET /v1/operator/enforcements/{enforcement_id}/timeline

Returns a bounded, read-only current-state timeline for one exact enforcement identifier. It
correlates metadata already available from evaluation evidence, enforcement and tool actions; it
does not provide global listing or search.

```json
{
  "timeline_version": "1",
  "enforcement_id": "enf_...",
  "evaluation_id": "eval_...",
  "evidence_id": "ev_...",
  "correlation_id": "demo-001",
  "policy_set_version": "br-financial-demo@1.0.0",
  "provider_registry_version": "2026-09-22.1",
  "tool_catalog_version": "br-financial-tools@1.1.0",
  "classification_labels": ["BRAZIL_CPF"],
  "obligation_types": ["TOKENIZE", "REQUIRE_HUMAN_APPROVAL"],
  "matched_policy_ids": ["br.financial.external_inference.minimize_identifier@1.0.0"],
  "provider_capability_ids": ["openai.responses_api.zero_data_retention"],
  "provider_capability_snapshots": [
    {
      "capability_id": "openai.responses_api.zero_data_retention",
      "provider_target": "openai.responses_api.global",
      "key": "zero_data_retention",
      "state": "conditional",
      "conditions": ["eligible_organization_required"],
      "verified_at": "2026-09-22",
      "record_version": "1",
      "registry_version": "2026-09-22.1",
      "source_urls": ["https://developers.openai.com/pt-BR/api/docs/guides/your-data"]
    }
  ],
  "provider_context_complete": true,
  "control_objective_ids": ["BR.PRIV.MINIMIZE_EXTERNAL_DATA"],
  "decision_reason_codes": [],
  "enforcement_reason_codes": [],
  "authorized_tool_ids": ["cards.unblock@1.1.0"],
  "provider_target": "openai.responses_api.global",
  "transformation_receipts": [
    {
      "receipt_id": "tr_...",
      "type": "TOKENIZE",
      "target": "customer_document",
      "input_digest": "sha256:...",
      "output_digest": "sha256:...",
      "reason_code": "MINIMIZE_EXTERNAL_IDENTIFIER"
    }
  ],
  "approval": {
    "approval_id": "approval-...",
    "issued_at": "2026-09-24T11:55:00+00:00",
    "expires_at": "2026-09-24T12:05:00+00:00",
    "consumed_at": "2026-09-24T12:00:00+00:00"
  },
  "previous_event_digest": null,
  "attention_required": true,
  "attention_codes": ["TOOL_RESULT_REJECTED"],
  "history_complete": true,
  "actions_truncated": false,
  "events_truncated": false,
  "stages": [
    {
      "sequence": 1,
      "kind": "EVALUATION",
      "record_id": "ev_...",
      "created_at": "2026-09-24T12:00:00+00:00",
      "status": "REQUIRE_APPROVAL",
      "attention_codes": [],
      "tool_name": null,
      "call_id": null,
      "approval_recorded": false
    }
  ],
  "lifecycle_events": [
    {
      "sequence": 1,
      "event_id": "ole_00000000000000000001",
      "recorded_at": "2026-09-24T12:00:00+00:00",
      "source": "TRANSITION",
      "kind": "EVALUATION",
      "record_id": "ev_...",
      "enforcement_id": null,
      "status": "REQUIRE_APPROVAL"
    }
  ]
}
```

Stages reflect architectural order and current state, not complete transition history. At most 128
tool-action stages are returned. When more exist, `actions_truncated` is true and
`ACTION_LIST_TRUNCATED` appears in `attention_codes`. The endpoint never returns prompts, data
values, tool arguments, approval assertions or raw/safe tool results, and it cannot mutate state.

`lifecycle_events` contains transitions recorded atomically after Phase 5b tracking was enabled.
Legacy records receive a `MIGRATION_BASELINE`, which makes `history_complete` false rather than
inventing earlier transitions. At most 256 events are returned; a longer sequence sets
`events_truncated=true`, adds `EVENT_LIST_TRUNCATED`, and also makes `history_complete=false`.
The completeness flag is also false when current actions are truncated or the transition events do
not cover the current evaluation, enforcement and returned action states.
Append-only enforcement is local to SQLite and is not a signed or externally anchored audit claim.

The control context uses only metadata captured by the linked evidence and enforcement records.
Approval summaries omit actor identity, and tool-action stages expose only whether an approval was
recorded. For new evaluations, provider source URLs, fact state and verification dates come from
digest-bound historical snapshots, not a join against the current registry. Legacy evidence with
used capability IDs but no snapshot reports `provider_context_complete=false`; the API does not
invent provenance. `previous_event_digest` is returned when present but does not by itself claim a
complete or externally anchored evidence chain.

Status behavior:

- `DENY` -> `BLOCKED_DENY`, with no transformation or execution;
- `REQUIRE_APPROVAL` without an assertion -> `WAITING_APPROVAL`, transformed in memory but not
  executed;
- a valid digest-bound assertion is consumed once after the atomic execution claim and before the
  execution port; the metadata-only `approval_receipt` is returned and persisted;
- invalid/unavailable approval verification returns `APPROVAL_FAILED` with HTTP 403 while keeping
  the record waiting; failure while atomically consuming a verified grant records terminal
  `APPROVAL_FAILED` and never executes;
- allowed outcome -> `PREPARED` is persisted, an atomic claim advances it to `DISPATCHED` before
  the configured execution port, then a successful result becomes `EXECUTED`;
- replay or concurrency that observes `DISPATCHED` does not call the execution port again; this
  fail-closed state requires operational reconciliation after an interrupted process;
- `EXECUTION_FAILED` is also terminal for automatic replay because a timeout or transport failure
  may be ambiguous after external processing;
- `RESULT_REJECTED` is terminal after a completed tool call whose untrusted output failed the
  trusted schema/handling contract; content is discarded and the action is not retried;
- transformation or execution error -> fail closed with a stable error code.

## GET /v1/enforcements/{enforcement_id}

Returns the persisted metadata-only enforcement record, including policy/provider versions,
receipt digests and execution status. It never returns the execution payload.

## GET /health

Returns `{"status": "ok"}` when the local HTTP process is available. Policy/registry validation
occurs during startup, so invalid control-plane configuration prevents the service from serving.

## Errors

Use stable machine-readable codes, for example:
- `POLICY_SET_NOT_FOUND`
- `POLICY_SCHEMA_UNSUPPORTED`
- `PROVIDER_CAPABILITY_UNKNOWN`
- `PROVIDER_CAPABILITY_STALE`
- `INVALID_EVALUATION_CONTEXT`
- `EVIDENCE_PERSISTENCE_FAILED`
- `TRANSFORMATION_FAILED`
- `EXECUTION_FAILED`
- `APPROVAL_FAILED`
- `TOOL_NOT_AUTHORIZED`
- `TOOL_RESULT_REJECTED`
- `ENFORCEMENT_PERSISTENCE_FAILED`

Error messages must not echo raw sensitive input.
