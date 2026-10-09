# Self-attested financial proof of concept

This is an individual, non-production demonstration using synthetic data. It composes PostgreSQL,
API identity, fixed OpenAI and Amazon Bedrock gateway calls, approved sandbox tool execution,
terminal recovery, a technically reviewed PoC policy and metadata-only evidence. A successful
result is `POC_VERIFIED`: it is not independent review, organizational acceptance, production
authorization or a compliance claim.

Use the [detailed PoC execution guide](POC_EXECUTION_GUIDE.md) to configure Keycloak, both provider
workloads, the stateful tool sandbox, PostgreSQL recovery and the two final signatures.

The future organization-owned profile remains separate in [Enterprise financial pilot
profile](ENTERPRISE_FINANCIAL_PILOT.md) and `examples/financial-pilot-enterprise/`.

## Fixed scope

Start with `examples/financial-pilot/scope.json`. Replace every zero digest, record the exact source
revision and immutable image digest, and set `ready` to `true`. Schema version 2 requires
`attestation_mode=SELF_ATTESTED_POC` and binds:

- one non-production environment and exact source/image pair;
- one signed control pack containing `poc-financial@1.0.0`;
- exact OpenAI and Bedrock profile digests;
- the explicit two-key individual self-attestation model.

Replace the model and deployment placeholders in both profiles. OpenAI must run with `store=false`;
Bedrock must use IAM authorization. The PoC policy deliberately avoids claims that require
enterprise eligibility, PrivateLink or organization-managed CloudTrail configuration. The gateway
must constrain its complete candidate/fallback set and return the exact reviewed provider, model
and deployment with `cached=false`.

## Repository and identity proof

CI starts disposable PostgreSQL 17, applies migrations and exercises concurrent single-winner
dispatch, atomic Ed25519 authority, API role separation, both gateway providers, one tool attempt
and `EXECUTED`/`NOT_EXECUTED` recovery. Its metadata artifact explicitly records that provider and
issuer boundaries are simulated, so it proves only `POSTGRES_CONCURRENCY` in
`CI_REAL_POSTGRES` mode.

For a live individual demonstration, use a local IdP capable of the contract in [Enterprise API
identity](API_IDENTITY.md). Keycloak with an Ed25519 realm key, `at+jwt` access tokens and protocol
mappers for `client_id`, `aud` and top-level `roles` is one compatible option. Use three clients for
runtime, operator and reconciler roles, mount only the exported public JWKS, then run:

```bash
REGULAAI_ENVIRONMENT=pilot \
REGULAAI_PILOT_API_URL=https://regulaai-poc.local \
REGULAAI_PILOT_RUNTIME_TOKEN="$RUNTIME_TOKEN" \
REGULAAI_PILOT_OPERATOR_TOKEN="$OPERATOR_TOKEN" \
REGULAAI_PILOT_RECONCILER_TOKEN="$RECONCILER_TOKEN" \
uv run python scripts/probe_enterprise_identity.py > identity-report.json
```

The probe uses invalid mutation bodies and retains no token or claim content.

## Provider proof

Create one isolated OpenAI project and one AWS development identity, inject credentials outside
Git, and configure separate gateway workloads. Run the fixed-synthetic composition once per profile:

```bash
REGULAAI_ENVIRONMENT=pilot \
REGULAAI_EXECUTION_MODE=gateway \
REGULAAI_DATABASE_URL="$POC_DATABASE_URL" \
REGULAAI_GATEWAY_ALLOWED_TARGET=openai.responses_api.global \
REGULAAI_GATEWAY_EXPECTED_PROVIDER=openai \
uv run python scripts/run_live_composition_pilot.py \
  --profile /poc/config/openai.json \
  --correlation-prefix poc-openai > openai-report.json
```

Repeat with `aws.bedrock_runtime.sa-east-1` and the Bedrock profile. Accept each report only when it
says `LIVE_COMPOSITION_VERIFIED`, its digests match the scope and the terminal provider, model and
deployment match the configured workload.

## Tool and backup proof

Use a local stateful `cards.unblock` sandbox that durably binds idempotency key to action digest.
Demonstrate success, effect-then-timeout reconciled as `EXECUTED`, and timeout-without-effect
reconciled as `NOT_EXECUTED`. Investigation and reconciliation must never re-execute the action.

Back up the dedicated PostgreSQL database with `pg_dump -Fc`, record the SHA-256 digest, restore it
into a separate database with `pg_restore --exit-on-error --no-owner`, verify the Alembic revision
and read representative timelines. Retain only digests, bounded identifiers, timestamps, schema
revision and result.

## Policy self-review and evidence

Complete `examples/financial-pilot/policy-review.md` over the exact PoC policy bytes. The author may
perform both roles, but must use two distinct Ed25519 key pairs and keep the limitation explicit:

- `POC_OPERATOR` attests execution and operational evidence;
- `POC_POLICY_REVIEWER` attests the technical policy review.

Private keys stay outside the repository. The public trust store binds each key to exactly one
role. Reviews use schema version 2 and domain `regulaai.financial-poc.review.v1`.

Create one evidence document for every `PilotCheck`. PostgreSQL uses `CI_REAL_POSTGRES`, policy
review uses `HUMAN_REVIEW`, and the other checks use `SANDBOX_LIVE`. All observations must pass,
match the exact scope, contain non-placeholder artifact digests and be no older than seven days.

Evaluate the complete bundle with:

```bash
uv run python scripts/verify_financial_pilot_acceptance.py \
  --scope /poc/evidence/scope.json \
  --evidence /poc/evidence/postgres.json \
  --evidence /poc/evidence/identity.json \
  --evidence /poc/evidence/openai.json \
  --evidence /poc/evidence/bedrock.json \
  --evidence /poc/evidence/tool-execution.json \
  --evidence /poc/evidence/recovery-executed.json \
  --evidence /poc/evidence/recovery-not-executed.json \
  --evidence /poc/evidence/policy-review.json \
  --evidence /poc/evidence/backup-restore.json \
  --review /poc/evidence/operator-attestation.json \
  --review /poc/evidence/policy-attestation.json \
  --trust-store /poc/config/poc-attestation-keys.json
```

Exit `0` and `POC_VERIFIED` mean only that the two role-specific keys self-attested the complete,
fresh, exact-scope PoC evidence.
