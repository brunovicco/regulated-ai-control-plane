# Integrated financial pilot

The integrated financial pilot is the acceptance profile for the current source candidate. It
combines a real PostgreSQL transaction boundary, enterprise-issued API identity, fixed synthetic
OpenAI and Amazon Bedrock calls through the governed gateway, a separately approved state-changing
sandbox action, terminal recovery of both ambiguous outcomes, an organization-owned policy pack
and authenticated acceptance of the resulting metadata evidence.

This profile is non-production and uses synthetic data. Repository CI proves the composition with
real PostgreSQL and in-process external substitutes. It does not prove an enterprise issuer,
provider account, network path, sandbox system, backup or organizational approval. Those checks
become acceptable only when run against the selected organization-owned environment.

## Fixed scope

Create one acceptance scope from `examples/financial-pilot/scope.json`. Replace every zero digest,
record the exact 40-character source revision and immutable image digest, then set `ready` to
`true`. The scope binds:

- one non-production environment and source/image pair;
- one promoted, signed organization control pack;
- the exact `org-financial-pilot@1.0.0` policy version;
- one reviewed OpenAI profile and one reviewed Bedrock profile.

The example profiles and policy are drafts. Copy them to organization-controlled configuration,
replace the model and deployment placeholders, and change a condition assertion to `true` only
when deployment evidence supports it. Compute each profile digest from the normalized loader
output; do not edit the digest after evidence or reviews have been issued.

The gateway workload must constrain its complete candidate and fallback set. A successful terminal
response must report the reviewed provider, model and deployment and must not be a cached result.
For Bedrock, the current fixed target is `aws.bedrock_runtime.sa-east-1`; selecting another region
requires a reviewed code/profile change rather than a runtime string override.

## Repository proof

CI starts a disposable PostgreSQL 17 service, applies Alembic migrations and requires the
integration suite. The suite exercises concurrent single-winner dispatch, atomic Ed25519 authority
consumption, API role separation, OpenAI and Bedrock gateway responses, exact decision/action
approval, one state-changing tool attempt and terminal `EXECUTED` and `NOT_EXECUTED`
reconciliation. `scripts/report_financial_pilot_ci.py` reduces the JUnit document to counts,
revision and a digest; failure details are excluded from the retained pilot artifact.

The CI report declares `external_provider_mode=SIMULATED` and
`enterprise_issuer_mode=SYNTHETIC`. It can satisfy only `POSTGRES_CONCURRENCY` with execution mode
`CI_REAL_POSTGRES`; it cannot satisfy any live sandbox check.

## Enterprise identity proof

Choose an issuer that can produce the exact access-token contract in [Enterprise API
identity](API_IDENTITY.md). Configure the deployment with its issuer, audience and public JWKS.
Inject three short-lived test tokens through the process environment and run:

```bash
REGULAAI_ENVIRONMENT=pilot \
REGULAAI_PILOT_API_URL=https://regulaai-pilot.example.internal \
REGULAAI_PILOT_RUNTIME_TOKEN="$RUNTIME_TOKEN" \
REGULAAI_PILOT_OPERATOR_TOKEN="$OPERATOR_TOKEN" \
REGULAAI_PILOT_RECONCILER_TOKEN="$RECONCILER_TOKEN" \
uv run python scripts/probe_enterprise_identity.py > identity-report.json
```

The probe sends invalid mutation bodies, so it verifies authentication and the complete role matrix
without creating business records. It records only status codes, a control-pack digest and report
digest. Tokens, claims, subjects and roles are neither printed nor persisted. Retain issuer-side
issuance and denied-access audit evidence separately; exercise signing-key overlap and emergency
revocation before approval.

## OpenAI and Bedrock gateway proof

For each reviewed profile, inject gateway credentials using the platform secret boundary. Set the
allowed target and expected provider exactly as declared by the profile, then run:

```bash
REGULAAI_ENVIRONMENT=pilot \
REGULAAI_EXECUTION_MODE=gateway \
REGULAAI_DATABASE_URL="$PILOT_DATABASE_URL" \
REGULAAI_GATEWAY_ALLOWED_TARGET=openai.responses_api.global \
REGULAAI_GATEWAY_EXPECTED_PROVIDER=openai \
uv run python scripts/run_live_composition_pilot.py \
  --profile /approved/config/financial-pilot-openai.json \
  --correlation-prefix approved-change-reference > openai-report.json
```

Repeat with `aws.bedrock_runtime.sa-east-1`, the profile's reviewed Bedrock gateway provider and
the Bedrock profile. The command sends fixed synthetic content, locally tokenizes the identifier,
enables no tools and returns metadata only. Accept a report only when it says
`LIVE_COMPOSITION_VERIFIED`, its profile/control-pack digests match the scope, and its terminal
provider, model and deployment match the reviewed workload.

## Tool approval and recovery proof

Use only the bound `cards.unblock` non-production connector described in [State-changing enterprise
connector](STATE_CHANGING_ENTERPRISE_CONNECTOR.md). The organization must demonstrate all three
paths against a sandbox that durably binds the idempotency key to the exact operation:

1. consume distinct decision and action approvals, execute once, and record a successful terminal
   action;
2. create an ambiguous outcome, investigate downstream, issue a reconciliation assertion for
   `EXECUTED`, and prove exact replay is idempotent;
3. create a separate ambiguous outcome, investigate downstream, issue a reconciliation assertion
   for `NOT_EXECUTED`, and prove the original action was not re-executed.

Retain metadata-only API/timeline exports, downstream idempotency/audit references and report
digests. Do not retain request fields, action arguments, tool output, credentials, tokens or
personal data in pilot evidence.

## Policy and operational review

Review `examples/financial-pilot/policy.yaml` using the existing signed-pack onboarding, scenario
replay, release-evidence and promotion-quorum workflow. The worksheet in
`examples/financial-pilot/policy-review.md` names the required owner decisions. The repository
does not infer legal requirements or approve the draft.

Run backup and restore against the exact dedicated PostgreSQL pilot database under the deployment's
TLS, least-privilege and retention controls. Verify the restored schema revision and metadata
records in an isolated database. Record only the backup artifact digest, source/recovered database
identifiers suitable for evidence, timestamps, schema revision and result.

## Acceptance evidence

Create one strict evidence JSON document per required check:

```json
{
  "schema_version": "1",
  "check": "ENTERPRISE_IDENTITY",
  "scope_digest": "sha256:...",
  "artifact_digest": "sha256:...",
  "observed_at": "2026-10-04T12:00:00+00:00",
  "passed": true,
  "execution_mode": "SANDBOX_LIVE"
}
```

The nine required check names are defined by `PilotCheck` in
`src/regulated_ai/domain/financial_pilot.py`. PostgreSQL uses `CI_REAL_POSTGRES`, policy review uses
`HUMAN_REVIEW`, and every other check uses `SANDBOX_LIVE`. All evidence must be scoped exactly,
successful, non-placeholder and no older than seven days when evaluated.

After all evidence exists, distinct organization-owned `OPERATIONS` and `POLICY_OWNER` Ed25519 keys
sign the exact bundle digest with domain `regulaai.financial-pilot.review.v1`. Runtime receives only
the lifecycle-aware public trust store. Evaluate the bundle with:

```bash
uv run python scripts/verify_financial_pilot_acceptance.py \
  --scope /approved/evidence/scope.json \
  --evidence /approved/evidence/postgres.json \
  --evidence /approved/evidence/identity.json \
  --evidence /approved/evidence/openai.json \
  --evidence /approved/evidence/bedrock.json \
  --evidence /approved/evidence/tool-execution.json \
  --evidence /approved/evidence/recovery-executed.json \
  --evidence /approved/evidence/recovery-not-executed.json \
  --evidence /approved/evidence/policy-review.json \
  --evidence /approved/evidence/backup-restore.json \
  --review /approved/evidence/operations-review.json \
  --review /approved/evidence/policy-owner-review.json \
  --trust-store /approved/config/pilot-review-keys.json
```

Exit `0` and `PILOT_ACCEPTED` mean that the supplied organization reviewers accepted the exact
referenced non-production evidence. They do not independently verify providers, authorize a
deployment, establish production readiness or make a compliance claim.
