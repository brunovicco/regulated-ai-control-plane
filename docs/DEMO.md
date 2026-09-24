# Phase 1 and 2 local demo

The demo evaluates and locally enforces a synthetic Brazilian financial-services operation. It
performs no provider or network call and needs no cloud credentials.

## Start the service

```bash
uv sync --frozen --all-groups --extra observability
uv run uvicorn regulated_ai.entrypoints.api:app --host 127.0.0.1 --port 8000
```

The service validates its packaged policy and provider registry before accepting traffic. Evidence
is written to `var/regulaai-evidence.sqlite3` by default. Set `REGULAAI_EVIDENCE_DB` to another
local path when needed.

The default tokenization key is generated per process. To keep demo tokens stable across restarts,
set `REGULAAI_TOKENIZATION_KEY` to a local value of at least 32 bytes. Production key material must
come from an approved secret-management boundary and must never be committed.

## Evaluate a synthetic operation

```bash
curl --request POST http://127.0.0.1:8000/v1/evaluations \
  --header 'content-type: application/json' \
  --data '{
    "correlation_id": "demo-card-001",
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
        "value": "SYNTHETIC_DOCUMENT_VALUE",
        "labels": ["PERSONAL_DIRECT_IDENTIFIER"]
      },
      {
        "field": "question",
        "value": "Synthetic support question",
        "labels": []
      }
    ],
    "tools": [
      {"name": "cards.read", "risk_class": "read_only"},
      {"name": "cards.unblock", "risk_class": "high_impact_state_change"}
    ],
    "policy_set_version": "br-financial-demo@1.0.0"
  }'
```

The expected top-level outcome is `REQUIRE_APPROVAL`. The response also contains `TOKENIZE`,
`REQUIRE_HUMAN_APPROVAL`, `REQUIRE_PROVIDER_CAPABILITY` and `REQUIRE_EVIDENCE` obligations. An
obligation is an execution plan: Phase 1 does not claim the transformation was already performed.

Use the returned `evidence_id` with:

```bash
curl http://127.0.0.1:8000/v1/evidence/ev_REPLACE_WITH_RETURNED_ID
curl http://127.0.0.1:8000/v1/providers
curl http://127.0.0.1:8000/health
```

The evidence response contains classification labels, version references and cryptographic
digests. It must not contain either synthetic field value from the request.

## Fail-closed demonstrations

- Remove `eligible_organization_required` or set it to `false`: the conditional retention
  capability is unsatisfied and the decision becomes `DENY`.
- Request a fallback target without the same mandatory capability: fallback validation returns
  `DENY` rather than weakening the original requirement.
- Advance the evaluation date beyond the policy's `max_age_days`: high-assurance capability data
  becomes stale and the decision becomes `DENY`.

These are organization-policy outcomes, not statements of legal compliance or certification.

## Enforce locally

Send the same request body to `POST /v1/enforcements`.

- With `cards.unblock`, the result is `WAITING_APPROVAL`; the document is tokenized in memory, but
  the mock execution port is not called.
- Remove `cards.unblock` and retain only `cards.read` to obtain `EXECUTED`. The response contains a
  metadata-only transformation receipt and `mockexec_...` execution ID, never either request value.

Inspect the stored metadata with:

```bash
curl http://127.0.0.1:8000/v1/enforcements/enf_REPLACE_WITH_RETURNED_ID
```

The service persists `PREPARED` before invoking the mock port and then advances the same record to
`EXECUTED`. A persistence or transformation failure stops before execution.
