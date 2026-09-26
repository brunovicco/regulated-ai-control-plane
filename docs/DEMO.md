# Phase 1 through 4b local demo

The demo evaluates and locally enforces a synthetic Brazilian financial-services operation. It
performs no provider or network call and needs no cloud credentials.

The opt-in Phase 3a gateway path is not exercised by the default demo or automated tests.

## Start the service

```bash
uv sync --frozen --all-groups --extra observability
uv run uvicorn regulated_ai.entrypoints.api:app --host 127.0.0.1 --port 8000
```

The service verifies its signed policy/provider/tool-catalog control pack, then validates the exact
authenticated records before accepting traffic. `/v1/providers` reports the verified pack id,
version, signing-key id and canonical payload digest. Evidence is written to
`var/regulaai-evidence.sqlite3` by default. Set
`REGULAAI_EVIDENCE_DB` to another local path when needed.

The repository includes only a demo public verification key. To publish a changed pack, configure
the intended public key in the trust store and keep the matching Ed25519 private PEM outside the
repository, then run:

```bash
uv run python scripts/sign_control_pack.py \
  --manifest src/regulated_ai/resources/control-pack-manifest.yaml \
  --trust-store src/regulated_ai/resources/trust/control-pack-signing-keys.yaml \
  --private-key /approved/secret/location/control-pack-ed25519.pem
```

The helper refreshes file digests, signs the canonical manifest and verifies it against the trust
store before replacement. Do not use the packaged demo trust anchor as a production key-management
design; key custody, reviewer authorization and revocation belong to the deployment release process.
Set both `REGULAAI_CONTROL_PACK_MANIFEST` and `REGULAAI_CONTROL_PACK_TRUST_STORE` to deployment
paths to load an organization-managed release without modifying the packaged defaults.

Before promoting a candidate signed with a key in the same trust store, generate a deterministic
static impact report:

```bash
uv run python scripts/diff_control_packs.py \
  --base-manifest /approved/base/control-pack-manifest.yaml \
  --candidate-manifest /review/candidate/control-pack-manifest.yaml \
  --trust-store /approved/control-pack-signing-keys.yaml \
  --fail-on-decision-impact
```

Successful analysis prints one compact JSON document. Exit code `0` means the comparison completed
without a configured decision-impact failure; exit code `2` means decision impact was detected;
exit code `1` means verification, parsing or comparison failed. The report classifies potential
`DECISION`, `EVIDENCE` and `GOVERNANCE` impact and lists dependent policy rules for changed
capabilities. It is static review support, not proof that two releases behave identically.

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
      {"name": "cards.read"},
      {"name": "cards.unblock"}
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
- Add `"risk_class": "read_only"` to `cards.unblock`: the caller claim conflicts with the trusted
  catalog and fails closed with `TOOL_NOT_AUTHORIZED`.

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

The service persists `PREPARED`, atomically claims `DISPATCHED` before invoking the execution port
and then advances the same record to `EXECUTED`. A persistence or transformation failure stops
before execution. A repeated request that observes `DISPATCHED` does not issue another call.

To resume the high-impact example, configure a dedicated `REGULAAI_APPROVAL_HMAC_KEY` of at least
32 bytes before startup. Read `output_digest` from the evaluation evidence referenced by the
waiting response, then have the organization-owned approval workflow issue the strict Phase 4a
assertion documented in `API_CONTRACT.md`. Resend the same enforcement request with:

```json
{
  "approval_assertion": "ra1.EXTERNALLY_ISSUED_PAYLOAD.EXTERNAL_SIGNATURE"
}
```

This field is added alongside the original request fields, not sent by itself. A valid assertion is
consumed once after `DISPATCHED` is claimed and before the mock executes. The result contains only a
metadata receipt. RegulaAI intentionally provides no endpoint or CLI for creating approvals.

## Optional governed gateway execution

Set `REGULAAI_EXECUTION_MODE=gateway` and provide every gateway variable documented in
`.env.example` before process startup. Phase 4b forwards only definitions resolved from the trusted
catalog. The configured gateway workload must be reviewed to authorize only
deployments compatible with `REGULAAI_GATEWAY_ALLOWED_TARGET` and
`REGULAAI_GATEWAY_EXPECTED_PROVIDER`.

Gateway mode sends the sanitized text payload to the configured service and may incur provider
cost. Model output is discarded. A returned tool call is exposed only as metadata and an arguments
digest with `execution_authorized: false`.

## Action-specific approval proof

Configure a distinct `REGULAAI_ACTION_APPROVAL_HMAC_KEY` of at least 32 bytes. Submit the exact
proposal arguments, workload identity and idempotency key to
`POST /v1/enforcements/{enforcement_id}/tool-actions`. The first response is
`WAITING_APPROVAL` and contains the action digest. An organization-owned workflow issues the
domain-separated `ra2` assertion documented in `API_CONTRACT.md`; resend the identical request with
that assertion to reach the network-silent mock tool boundary.

The mock result is validated against the trusted output schema. The immediate successful response
contains only `safe_result`: a closed status enum may be returned, a financial reference is
replaced with `***MASKED***`, and diagnostic content is dropped. `GET /v1/tool-actions/{action_id}`
and action replay return metadata/digests only and set `safe_result` to `null`.

The demo never persists arguments, idempotency keys, raw assertions, raw tool output or the safe
result. Schema-invalid output becomes terminal `RESULT_REJECTED`; it is not retried because the
downstream effect may already have occurred. Live enterprise-system connectors and model
continuation remain disabled.

## Inspect the operator timeline

Use the exact enforcement identifier returned by the demo:

```bash
curl http://127.0.0.1:8000/v1/operator/enforcements/enf_REPLACE_WITH_RETURNED_ID/timeline
```

The response orders evaluation, enforcement and tool-action current states and highlights stable
attention codes such as `ENFORCEMENT_APPROVAL_REQUIRED`,
`TOOL_ACTION_RECONCILIATION_REQUIRED` or `TOOL_RESULT_REJECTED`. It is bounded, read-only and
metadata-only; it is not a complete transition history and cannot approve or retry work.

Phase 5b also returns `lifecycle_events`. New state transitions are appended transactionally;
records that existed before tracking show `source: MIGRATION_BASELINE` and
`history_complete: false`. This is a local append-only operational history, not a signed audit
ledger.

Phase 5c adds the matched policy/control/capability identifiers, decision and enforcement reasons,
authorized tools, provider target, transformation receipts and previous evidence digest. Approval
context excludes actor identity, assertions and authority-bearing content.

Phase 5d adds `provider_capability_snapshots` to evidence and the operator timeline. Each new
decision captures the provider target, capability state/conditions, registry/record versions,
verification date and reviewed source URLs. `provider_context_complete` is false for legacy
evidence whose source metadata was never captured.

Phase 5e renders the same timeline in a browser without JavaScript or global discovery:

```text
http://127.0.0.1:8000/operator?enforcement_id=enf_REPLACE_WITH_RETURNED_ID
```

The page shows current stages, append-only history, attention codes, control context,
transformations, provider provenance and evidence digests. It cannot approve, retry or reconcile
work and does not display approval actor identity or request/tool content.

## Compare verified releases with curated scenario replay

Run the packaged release against itself to exercise the Phase 6c replay contract without creating
a candidate:

```bash
uv run python scripts/replay_control_pack_scenarios.py \
  --base-manifest src/regulated_ai/resources/control-pack-manifest.yaml \
  --candidate-manifest src/regulated_ai/resources/control-pack-manifest.yaml \
  --trust-store src/regulated_ai/resources/trust/control-pack-signing-keys.yaml \
  --scenario-suite examples/scenarios/control-pack-regression.yaml \
  --fail-on-decision-impact
```

The expected status is `NO_OBSERVED_CHANGE`. A candidate that changes a replayed decision or exact
obligation digest returns exit code `2` when the flag is present. Invalid signatures, configuration
or scenario schema return `1`; a successful report without the CI flag returns `0`.

The suite fixes the evaluation clock and contains only metadata, field names and classification
labels. The report includes pack identities, the exact suite digest, allowlisted result metadata
and digests, never scenario values. Tools are intentionally excluded until their catalog joins the
same trusted release boundary.

## Review a provider capability draft before signing

Run the Phase 6d review gate against the authenticated packaged base and the synthetic-safe
freshness-review example:

```bash
uv run python scripts/review_provider_capability_update.py \
  --base-manifest src/regulated_ai/resources/control-pack-manifest.yaml \
  --trust-store src/regulated_ai/resources/trust/control-pack-signing-keys.yaml \
  --candidate-record examples/provider-capability-updates/openai-responses-candidate.yaml \
  --review-record examples/provider-capability-reviews/openai-responses-2026-09-26.yaml
```

The expected status is `REVIEW_GATE_PASSED` with exit code `0`. A structurally valid review with
missing, contradicted or inconclusive capability coverage returns `REVIEW_GATE_BLOCKED` and exit
code `2`. Invalid schema, digest binding, source lineage or base verification returns `1`.

The example advances record/registry versions and freshness metadata but is not a signed candidate
release. The review contains only public source URLs, capability keys and a non-personal role. The
report hashes uncovered source URLs and never includes source content. A separate organization-owned
process still decides whether an authorized private key may sign a complete pack.

## Review a policy draft before signing

Run the Phase 6e regulatory review gate against the authenticated packaged base and the
synthetic-safe policy-mapping example:

```bash
uv run python scripts/review_policy_update.py \
  --base-manifest src/regulated_ai/resources/control-pack-manifest.yaml \
  --trust-store src/regulated_ai/resources/trust/control-pack-signing-keys.yaml \
  --candidate-policy examples/policy-updates/br-financial-external-inference-candidate.yaml \
  --review-record examples/regulatory-reviews/br-financial-external-inference-2026-09-26.yaml
```

The expected status is `REGULATORY_REVIEW_PASSED` with exit code `0`. A structurally valid review
with missing coverage, `REJECTED`, `NEEDS_REVISION` or an invalid regulatory/enterprise conclusion
returns `REGULATORY_REVIEW_BLOCKED` and exit code `2`. Invalid schema, digest binding, mapping or
base lineage returns `1`.

The example adds one approved control-objective mapping to an existing policy rule and advances
both rule and policy-set versions. The review contains only identifiers, conclusions, a date,
digests and a non-personal role. It does not contain or retrieve legal text. Passing does not prove
legal correctness or compliance and does not authorize the separate signer or promotion process.

## Assemble verified release evidence

Run Phase 6f with the packaged release as both base and candidate to exercise deterministic
composition without creating a candidate:

```bash
uv run python scripts/assemble_release_evidence.py \
  --base-manifest src/regulated_ai/resources/control-pack-manifest.yaml \
  --candidate-manifest src/regulated_ai/resources/control-pack-manifest.yaml \
  --trust-store src/regulated_ai/resources/trust/control-pack-signing-keys.yaml \
  --scenario-suite examples/scenarios/control-pack-regression.yaml
```

The expected status is `EVIDENCE_COMPLETE`, with no semantic changes, no observed scenario changes
and no required reviews. The output includes a deterministic `bundle_digest` over the canonical
metadata payload.

For a changed signed candidate, repeat `--provider-review-record PATH` and
`--policy-review-record PATH` for every applicable Phase 6d/6e review, then provide the Phase 6h
review trust store and one signed attestation per changed entity:

```bash
  --review-trust-store /path/to/review-trust-store.yaml \
  --review-attestation /path/to/review-attestation.yaml
```

The composer re-runs detailed update reviews against exact candidate files and requires their id and
digest inside the signed attestation. Additions bind candidate entity bytes; removals bind the
approved-base entity bytes. Missing or rejected authenticated reviews return `EVIDENCE_INCOMPLETE`
and exit code `2`; invalid signatures, unauthorized key roles/change types, schemas, digests or
lineage return `1`. Bundle schema version 2 includes only attestation/signature metadata and digests.

Completeness authenticates bounded reviewer roles but does not approve observed impact, access a
private key, sign, promote or deploy a release. Those remain separate organization-owned decisions.

## Verify a signed promotion quorum

After archiving an `EVIDENCE_COMPLETE` Phase 6f JSON bundle, evaluate externally produced Ed25519
attestations against the organization's public-key trust store and quorum policy:

```bash
uv run python scripts/authorize_release_promotion.py \
  --evidence-bundle /path/to/release-evidence.json \
  --promotion-policy /path/to/promotion-policy.yaml \
  --attestation-trust-store /path/to/promotion-trust-store.yaml \
  --attestation /path/to/control-owner-attestation.yaml \
  --attestation /path/to/release-manager-attestation.yaml \
  --evaluated-at 2026-09-26T15:00:00+00:00
```

The expected successful status is `PROMOTION_AUTHORIZED` with exit code `0`. A valid but expired,
rejected, role-incomplete or below-quorum set returns `PROMOTION_BLOCKED` and exit code `2`.
Malformed metadata, a modified bundle, an unauthorized role, an untrusted key, a bad signature or
an incorrect bundle/candidate binding returns `1`.

Only public verification keys belong in the trust store; private keys remain in external
organization-owned signers. The output exposes attestation and signature digests, never signature
bytes or personal identity. Authorization is an offline handoff record, not an instruction that
signs, publishes, promotes, distributes or deploys the candidate.
