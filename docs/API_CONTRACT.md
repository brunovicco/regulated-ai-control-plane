# API contract — Phases 1 through 3a

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

Accepts the same normalized request as `POST /v1/evaluations`. It evaluates policy, applies local
field transformations and persists metadata-only enforcement state. The default runtime calls the
Phase 2 network-silent mock. Explicit gateway mode sends the sanitized text-only plan through
`governed-llm-gateway`; tool-bearing plans fail before network access.

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
  "provider_call_metadata": null
}
```

In gateway mode, `provider_execution_id` begins with `gw_` and `provider_call_metadata` may contain
only allowlisted gateway request/routing IDs, gateway policy ID/version, provider/model/deployment,
latency, attempt/fallback indexes and cache state. It never contains request content, model output,
credentials, provider response bodies or provider request IDs.

Status behavior:

- `DENY` -> `BLOCKED_DENY`, with no transformation or execution;
- `REQUIRE_APPROVAL` -> `WAITING_APPROVAL`, transformed in memory but not executed;
- allowed outcome -> `PREPARED` is persisted, an atomic claim advances it to `DISPATCHED` before
  the configured execution port, then a successful result becomes `EXECUTED`;
- replay or concurrency that observes `DISPATCHED` does not call the execution port again; this
  fail-closed state requires operational reconciliation after an interrupted process;
- `EXECUTION_FAILED` is also terminal for automatic replay because a timeout or transport failure
  may be ambiguous after external processing;
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
- `ENFORCEMENT_PERSISTENCE_FAILED`

Error messages must not echo raw sensitive input.
