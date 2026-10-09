# Detailed execution guide for the financial PoC

This runbook turns the self-attested financial proof of concept into a reproducible, metadata-only
demonstration. It uses synthetic data and an individual author. A successful final result is
`POC_VERIFIED`; it is not independent review, organizational acceptance, production authorization
or a compliance claim.

The commands assume macOS or Linux, a checkout of this repository, Python 3.13, `uv`, Docker,
PostgreSQL client tools, `jq`, `openssl`, `mkcert`, Caddy, AWS CLI v2 and an HTTPS governed gateway.
Run every command from the repository root unless the step says otherwise.

Two naming details are fixed by the current verifier:

- final attestation roles are `POC_OPERATOR` and `POC_POLICY_REVIEWER`;
- the final accepted status is `POC_VERIFIED`.

`POC_OPERATIONS` and `POC_POLICY_REVIEW` would be rejected. The enterprise profile remains
separate under `examples/financial-pilot-enterprise/`.

## 0. Prepare an isolated PoC workspace

Keep credentials, private keys, tokens, generated reports and database dumps outside Git. This
guide uses one private directory as an example:

```bash
export REGULAAI_POC_HOME="$HOME/.local/share/regulaai-poc"
umask 077
mkdir -p \
  "$REGULAAI_POC_HOME"/config \
  "$REGULAAI_POC_HOME"/control-pack/policies \
  "$REGULAAI_POC_HOME"/control-pack/provider-capabilities \
  "$REGULAAI_POC_HOME"/control-pack/tools \
  "$REGULAAI_POC_HOME"/evidence \
  "$REGULAAI_POC_HOME"/keys \
  "$REGULAAI_POC_HOME"/tls
chmod 700 "$REGULAAI_POC_HOME" "$REGULAAI_POC_HOME"/*
```

Install the locked project dependencies and record the exact source:

```bash
uv lock --check
uv sync --frozen --all-groups
git status --short
git rev-parse HEAD | tee "$REGULAAI_POC_HOME/evidence/source-revision.txt"
```

Proceed only from a known commit with no unrelated changes. Build the application image and retain
its immutable local image ID. The local image ID is suitable for this PoC scope; use a registry
manifest digest if the image is pushed to a registry.

```bash
SOURCE_REVISION="$(git rev-parse HEAD)"
docker build -t "regulaai-poc:$SOURCE_REVISION" .
docker image inspect --format '{{.Id}}' "regulaai-poc:$SOURCE_REVISION" \
  | tee "$REGULAAI_POC_HOME/evidence/image-digest.txt"
```

Do not put provider keys, client secrets or bearer tokens in shell command arguments, checked-in
`.env` files, logs or screenshots. Load them interactively or through the operating system's
secret manager and export them only in the terminal that runs the PoC.

### 0.1 Start the dedicated PostgreSQL database

For the first local execution, put the container variables in a protected file outside Git. This
also works across terminal sessions and avoids shell-specific `read` behavior:

```bash
umask 077
openssl rand -hex 24 > "$REGULAAI_POC_HOME/keys/postgres-password"
{
  printf 'POSTGRES_USER=regulaai\n'
  printf 'POSTGRES_PASSWORD=%s\n' "$(cat "$REGULAAI_POC_HOME/keys/postgres-password")"
  printf 'POSTGRES_DB=regulaai_poc\n'
} > "$REGULAAI_POC_HOME/config/postgres.env"
chmod 600 \
  "$REGULAAI_POC_HOME/keys/postgres-password" \
  "$REGULAAI_POC_HOME/config/postgres.env"

docker volume create regulaai-poc-postgres
docker run -d \
  --name regulaai-poc-postgres \
  --restart unless-stopped \
  -p 127.0.0.1:55432:5432 \
  --env-file "$REGULAAI_POC_HOME/config/postgres.env" \
  --mount source=regulaai-poc-postgres,target=/var/lib/postgresql/data \
  postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73
```

Wait for `pg_isready`, construct the application URL from the protected password and apply the
migrations:

```bash
until docker exec regulaai-poc-postgres \
  pg_isready -U regulaai -d regulaai_poc >/dev/null 2>&1
do
  sleep 1
done

POC_PG_PASSWORD="$(cat "$REGULAAI_POC_HOME/keys/postgres-password")"
export POC_DATABASE_URL="postgresql://regulaai:${POC_PG_PASSWORD}@127.0.0.1:55432/regulaai_poc"
export REGULAAI_DATABASE_URL="$POC_DATABASE_URL"

uv run alembic upgrade head
uv run alembic current
```

The expected revision is `0002_operator_authority (head)`. If a first attempt failed before
initialization because `POSTGRES_PASSWORD` was absent, remove that failed container and its empty
volume before repeating this procedure. Never remove a volume after evidence has been created
without first completing the backup exercise.

### 0.2 Rehearse the integrated PostgreSQL cases locally

Use a separate database whose name ends in `_test`. The focused command disables the repository's
global coverage threshold because it intentionally runs only the 12 PostgreSQL pilot cases; the
complete quality gate below remains responsible for project-wide coverage.

```bash
if ! docker exec regulaai-poc-postgres \
  psql -U regulaai -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='regulaai_poc_test'" \
  | grep -qx 1
then
  docker exec regulaai-poc-postgres createdb -U regulaai regulaai_poc_test
fi

export REGULAAI_TEST_POSTGRES_URL="postgresql://regulaai:${POC_PG_PASSWORD}@127.0.0.1:55432/regulaai_poc_test"
export REGULAAI_REQUIRE_POSTGRES_TESTS=1

uv run pytest \
  tests/integration/test_postgres_concurrency.py \
  tests/integration/test_financial_pilot.py \
  -m integration \
  --no-cov \
  -vv
```

All 12 cases must pass without skips. These cases use PostgreSQL 17 and exercise the complete
identity, approval, gateway-adapter and recovery composition with synthetic issuer and simulated
external services. They are a local rehearsal and are not the retained `CI_REAL_POSTGRES`
artifact.

Run the complete gate with the same isolated test database to prove project-wide coverage and all
required checks:

```bash
UV_CACHE_DIR=/tmp/regulaai-uv-cache \
  uv run python scripts/quality_gate.py
```

## 1. Configure Keycloak as the local IdP

The example fixes Keycloak 26.5.7 by tag and multi-architecture OCI digest:

```text
quay.io/keycloak/keycloak:26.5.7@sha256:45ae20191531eb608ddb0b775d012b40d3e4f942697f3214694887dd7c108d13
```

Keycloak 26.2 introduced the client setting that emits access tokens with `typ=at+jwt`. Keycloak
also provides a generated EdDSA key provider. The RegulaAI verifier accepts only Ed25519 and a
strict `at+jwt` header, so both settings are required. See the official
[Keycloak 26.2 release notes](https://www.keycloak.org/2025/04/keycloak-2620-released) and
[generated EdDSA provider API](https://www.keycloak.org/docs-api/26.5.7/javadocs/org/keycloak/keys/GeneratedEddsaKeyProviderFactory.html).

### 1.1 Start Keycloak on loopback

Create `$REGULAAI_POC_HOME/config/keycloak-compose.yaml`:

```yaml
services:
  keycloak:
    image: quay.io/keycloak/keycloak:26.5.7@sha256:45ae20191531eb608ddb0b775d012b40d3e4f942697f3214694887dd7c108d13
    command: ["start-dev"]
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: ${KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME:?required}
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD:?required}
      KC_HTTP_ENABLED: "true"
      KC_HOSTNAME: https://idp.regulaai.test:8443
      KC_PROXY_HEADERS: xforwarded
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - keycloak_data:/opt/keycloak/data
    restart: unless-stopped

volumes:
  keycloak_data:
```

Set the administrator password interactively and start the service:

```bash
export KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME=admin
printf 'Keycloak bootstrap password: '
read -r -s KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD; printf '\n'
export KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD
docker compose -f "$REGULAAI_POC_HOME/config/keycloak-compose.yaml" up -d
docker compose -f "$REGULAAI_POC_HOME/config/keycloak-compose.yaml" ps
```

`start-dev` and Keycloak's embedded database are acceptable only for this local PoC. The named
volume makes realm state survive a container restart; it is not a production database design.

### 1.2 Put local HTTPS in front of Keycloak

Add `127.0.0.1 idp.regulaai.test` to the local hosts file, then generate and trust a certificate:

```bash
mkcert -install
mkcert \
  -cert-file "$REGULAAI_POC_HOME/tls/idp.crt" \
  -key-file "$REGULAAI_POC_HOME/tls/idp.key" \
  idp.regulaai.test localhost 127.0.0.1 ::1
```

Create `$REGULAAI_POC_HOME/config/Caddyfile`:

```caddyfile
idp.regulaai.test:8443 {
    tls {$REGULAAI_POC_HOME}/tls/idp.crt {$REGULAAI_POC_HOME}/tls/idp.key
    reverse_proxy 127.0.0.1:8080
}
```

Run Caddy in a separate terminal:

```bash
REGULAAI_POC_HOME="$REGULAAI_POC_HOME" \
  caddy run --config "$REGULAAI_POC_HOME/config/Caddyfile" --adapter caddyfile
```

Keycloak receives `X-Forwarded-*` headers and publishes the fixed HTTPS hostname. This matches the
official [Keycloak reverse proxy guidance](https://www.keycloak.org/server/reverseproxy) and
Caddy's [reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) and
[TLS](https://caddyserver.com/docs/caddyfile/directives/tls) directives.

```bash
export REGULAAI_OIDC_ISSUER='https://idp.regulaai.test:8443/realms/regulaai-poc'
curl --fail --silent --show-error \
  --cacert "$(mkcert -CAROOT)/rootCA.pem" \
  "$REGULAAI_OIDC_ISSUER/.well-known/openid-configuration" \
  | jq -e --arg issuer "$REGULAAI_OIDC_ISSUER" '.issuer == $issuer'
```

### 1.3 Create the realm, key and clients

Open `https://idp.regulaai.test:8443/admin/` and perform these steps:

1. Create realm `regulaai-poc`.
2. Add a generated EdDSA realm key provider, configure Ed25519 signing and make it active.
3. Select `EdDSA` as the realm's default signature algorithm.
4. Create these OpenID Connect clients:

   | Client | Assigned RegulaAI role |
   | --- | --- |
   | `regulaai-poc-runtime` | `regulaai.runtime` |
   | `regulaai-poc-operator` | `regulaai.operator` |
   | `regulaai-poc-reconciler` | `regulaai.reconciler` |

5. For each client, enable client authentication and service accounts. Disable Standard Flow,
   Direct Access Grants, Implicit Flow and device authorization if present.
6. In the client's advanced compatibility settings, enable **Use "at+jwt" as access token header
   type**. Select `EdDSA` as the access-token signature algorithm if there is an explicit override.
7. Create one client role using the table above and assign it to that client's service account.
8. Add an Audience mapper that includes `regulaai-api` in access-token `aud`.
9. Add a hardcoded `client_id` claim whose value is the exact client ID.
10. Add a User Client Role mapper for that client. Set token claim name to `roles`, enable
    multivalued output and include it in access tokens. The top-level array must contain only the
    one assigned RegulaAI role.

Keycloak must also emit `iss`, `sub`, `jti`, integer `iat` and `exp`, and optional integer `nbf`.
Keep token lifetime at or below 3600 seconds. See [Enterprise API identity](API_IDENTITY.md).

### 1.4 Export a strict public JWKS

RegulaAI rejects unknown JWKS fields. Do not mount Keycloak's raw response because it can contain
certificate-chain fields. Select Ed25519 signing keys and copy only the six accepted public fields:

```bash
curl --fail --silent --show-error \
  --cacert "$(mkcert -CAROOT)/rootCA.pem" \
  "$REGULAAI_OIDC_ISSUER/protocol/openid-connect/certs" \
  > "$REGULAAI_POC_HOME/config/keycloak-jwks.raw.json"

jq -S '{keys: [.keys[]
  | select(.kty == "OKP" and .crv == "Ed25519" and .use == "sig" and .alg == "EdDSA")
  | {alg, crv, kid, kty, use, x}]}' \
  "$REGULAAI_POC_HOME/config/keycloak-jwks.raw.json" \
  > "$REGULAAI_POC_HOME/config/keycloak-jwks.json"

jq -e '
  (.keys | length) >= 1 and (.keys | length) <= 64 and
  all(.keys[];
    (.kty == "OKP") and (.crv == "Ed25519") and (.use == "sig") and
    (.alg == "EdDSA") and
    ((keys | sort) == ["alg", "crv", "kid", "kty", "use", "x"]))
' "$REGULAAI_POC_HOME/config/keycloak-jwks.json"

rm "$REGULAAI_POC_HOME/config/keycloak-jwks.raw.json"
```

Refresh the file deliberately during rotation, retain overlap for the maximum token lifetime, then
restart RegulaAI to load it.

### 1.5 Obtain short-lived tokens and run the role probe

The helper reads client secrets from the environment and does not put them in command arguments:

```bash
fetch_keycloak_token() {
  KC_CLIENT_ID="$1" KC_CLIENT_SECRET="$2" \
  REGULAAI_OIDC_ISSUER="$REGULAAI_OIDC_ISSUER" \
  MKCERT_CA_FILE="$(mkcert -CAROOT)/rootCA.pem" \
  uv run python - <<'PY'
import os
import httpx

response = httpx.post(
    f"{os.environ['REGULAAI_OIDC_ISSUER']}/protocol/openid-connect/token",
    data={
        "grant_type": "client_credentials",
        "client_id": os.environ["KC_CLIENT_ID"],
        "client_secret": os.environ["KC_CLIENT_SECRET"],
    },
    verify=os.environ["MKCERT_CA_FILE"],
    timeout=10.0,
)
response.raise_for_status()
print(response.json()["access_token"])
PY
}

printf 'Runtime client secret: '; read -r -s KC_RUNTIME_SECRET; printf '\n'
printf 'Operator client secret: '; read -r -s KC_OPERATOR_SECRET; printf '\n'
printf 'Reconciler client secret: '; read -r -s KC_RECONCILER_SECRET; printf '\n'
export REGULAAI_PILOT_RUNTIME_TOKEN="$(fetch_keycloak_token regulaai-poc-runtime "$KC_RUNTIME_SECRET")"
export REGULAAI_PILOT_OPERATOR_TOKEN="$(fetch_keycloak_token regulaai-poc-operator "$KC_OPERATOR_SECRET")"
export REGULAAI_PILOT_RECONCILER_TOKEN="$(fetch_keycloak_token regulaai-poc-reconciler "$KC_RECONCILER_SECRET")"
unset KC_RUNTIME_SECRET KC_OPERATOR_SECRET KC_RECONCILER_SECRET
```

After section 5, start RegulaAI with the signed PoC pack:

```bash
export REGULAAI_ENVIRONMENT=pilot
export REGULAAI_API_AUTH_MODE=oidc_jwt
export REGULAAI_OIDC_AUDIENCE=regulaai-api
export REGULAAI_OIDC_JWKS_PATH="$REGULAAI_POC_HOME/config/keycloak-jwks.json"
export REGULAAI_OIDC_MAX_TOKEN_AGE_SECONDS=3600
export REGULAAI_OIDC_CLOCK_SKEW_SECONDS=30
export REGULAAI_DATABASE_URL="$POC_DATABASE_URL"
export REGULAAI_CONTROL_PACK_MANIFEST="$REGULAAI_POC_HOME/control-pack/control-pack-manifest.yaml"
export REGULAAI_CONTROL_PACK_TRUST_STORE="$REGULAAI_POC_HOME/config/control-pack-keys.yaml"
uv run uvicorn regulated_ai.entrypoints.api:app --host 127.0.0.1 --port 8000
```

In another terminal containing the three token variables:

```bash
REGULAAI_ENVIRONMENT=pilot \
REGULAAI_PILOT_API_URL=http://127.0.0.1:8000 \
uv run python scripts/probe_enterprise_identity.py \
  > "$REGULAAI_POC_HOME/evidence/identity-report.json"

jq -e '
  .status == "ENTERPRISE_IDENTITY_VERIFIED" and
  .business_mutations == 0 and (.checks | length) == 12
' "$REGULAAI_POC_HOME/evidence/identity-report.json"
```

The report must contain the same control-pack digest used by both provider runs.

## 2. Configure the OpenAI workload

Create an OpenAI project named `regulaai-poc`. Use a dedicated project key, keep it outside Git,
rotate or delete it after the exercise, and configure a low budget plus alerts. OpenAI recommends
separating environments by project, protecting keys and setting spend controls in its
[production best practices](https://developers.openai.com/api/docs/guides/production-best-practices)
and [spend limits guide](https://developers.openai.com/api/docs/guides/spend-limits).

The current data-controls documentation says API data is not used for training unless the customer
opts in, while default abuse-monitoring logs may retain content for up to 30 days. Modified abuse
monitoring and Zero Data Retention require approval. `store=false` does not itself establish ZDR.
See [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

### 2.1 Select and bind the model

1. Confirm one model is available to that exact project at execution time.
2. Record the exact model identifier returned by the API.
3. Create governed-gateway workload `poc-openai`.
4. Make it call the Responses API with `store=false` on every request.
5. Restrict every candidate and fallback to the reviewed model/deployment and disable cache hits.
6. Require the normalized response to identify provider `openai`, exact model/deployment,
   gateway request ID, routing decision ID, policy version and `cached=false`.

RegulaAI talks to the governed gateway, which owns the provider credential and enforces
`store=false`. Copy and edit the profile outside Git:

```bash
cp examples/financial-pilot/openai.json "$REGULAAI_POC_HOME/config/openai.json"
```

Replace `gateway_model` and `gateway_deployment`. Leave `organization_assertions` empty; do not add
`eligible_organization_required=true` or claim ZDR. Calculate the normalized profile digest:

```bash
OPENAI_PROFILE_DIGEST="$(uv run python - "$REGULAAI_POC_HOME/config/openai.json" <<'PY'
import sys
from pathlib import Path
from regulated_ai.adapters.pilot_profile import load_pilot_profile

print(load_pilot_profile(Path(sys.argv[1])).digest)
PY
)"
printf '%s\n' "$OPENAI_PROFILE_DIGEST" \
  | tee "$REGULAAI_POC_HOME/evidence/openai-profile-digest.txt"
```

### 2.2 Execute and verify the OpenAI proof

```bash
printf 'Governed gateway key: '; read -r -s GOVERNED_LLM_GATEWAY_API_KEY; printf '\n'
export GOVERNED_LLM_GATEWAY_API_KEY
export GOVERNED_LLM_GATEWAY_URL='https://gateway.example.test'
export REGULAAI_GATEWAY_WORKLOAD=poc-openai
export REGULAAI_GATEWAY_ALLOWED_TARGET=openai.responses_api.global
export REGULAAI_GATEWAY_EXPECTED_PROVIDER=openai
export REGULAAI_EXECUTION_MODE=gateway
export REGULAAI_ENVIRONMENT=pilot
export REGULAAI_DATABASE_URL="$POC_DATABASE_URL"
export REGULAAI_CONTROL_PACK_MANIFEST="$REGULAAI_POC_HOME/control-pack/control-pack-manifest.yaml"
export REGULAAI_CONTROL_PACK_TRUST_STORE="$REGULAAI_POC_HOME/config/control-pack-keys.yaml"

uv run python scripts/run_live_composition_pilot.py \
  --profile "$REGULAAI_POC_HOME/config/openai.json" \
  --correlation-prefix poc-openai \
  > "$REGULAAI_POC_HOME/evidence/openai-report.json"

jq -e --arg profile "$OPENAI_PROFILE_DIGEST" '
  .status == "LIVE_COMPOSITION_VERIFIED" and
  .profile_digest == $profile and
  .provider_profile == "openai" and .gateway.provider == "openai" and
  .gateway.cached == false and
  .data_handling.input_profile == "FIXED_SYNTHETIC" and
  .data_handling.request_content_persisted == false and
  .data_handling.model_output_persisted == false and
  .data_handling.model_output_returned == false
' "$REGULAAI_POC_HOME/evidence/openai-report.json"
```

Compare `.gateway.model`, `.gateway.deployment` and `.control_pack.payload_digest` with the exact
reviewed bindings.

## 3. Configure the Amazon Bedrock workload

Use an AWS development account and prefer AWS CLI sign-in or IAM Identity Center temporary
credentials. AWS documents `aws login` for recent AWS CLI v2 releases. A 30-day Bedrock API key is
for exploration and development, not durable operation. See
[AWS CLI sign-in](https://docs.aws.amazon.com/signin/latest/userguide/command-line-sign-in.html),
[Bedrock API keys](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html) and the
[development-key quick start](https://docs.aws.amazon.com/bedrock/latest/userguide/getting-started-api-keys.html).

### 3.1 Confirm a model in São Paulo

```bash
aws --version
aws login --profile regulaai-poc
aws sts get-caller-identity --profile regulaai-poc
aws bedrock list-foundation-models \
  --profile regulaai-poc \
  --region sa-east-1 \
  --by-output-modality TEXT \
  --query 'modelSummaries[].{id:modelId,name:modelName,status:modelLifecycle.status}' \
  --output table
```

Choose a model listed in `sa-east-1` that the gateway supports and that does not require an
unreviewed cross-region inference profile. Confirm it with `aws bedrock get-foundation-model` and
the current [regional compatibility table](https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html)
and [model-information API](https://docs.aws.amazon.com/bedrock/latest/userguide/models-get-info.html).

### 3.2 Restrict IAM and configure the gateway

Grant only `bedrock:InvokeModel` to the selected resource:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeOneReviewedBedrockModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:sa-east-1::foundation-model/REPLACE_WITH_MODEL_ID"
    }
  ]
}
```

Validate the exact resource type and ARN for the chosen model. AWS provides
[identity-policy examples](https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html).

Create gateway workload `poc-bedrock` with temporary AWS credentials, region `sa-east-1`, the
public TLS `bedrock-runtime` endpoint, exact model/deployment, no unreviewed fallback and normalized
provider `aws`. AWS recommends `bedrock-runtime` for new inference applications; see
[endpoint availability](https://docs.aws.amazon.com/bedrock/latest/userguide/models-endpoint-availability.html).
Do not claim PrivateLink, CloudTrail configuration or data residency.

```bash
cp examples/financial-pilot/bedrock.json "$REGULAAI_POC_HOME/config/bedrock.json"

BEDROCK_PROFILE_DIGEST="$(uv run python - "$REGULAAI_POC_HOME/config/bedrock.json" <<'PY'
import sys
from pathlib import Path
from regulated_ai.adapters.pilot_profile import load_pilot_profile

print(load_pilot_profile(Path(sys.argv[1])).digest)
PY
)"
printf '%s\n' "$BEDROCK_PROFILE_DIGEST" \
  | tee "$REGULAAI_POC_HOME/evidence/bedrock-profile-digest.txt"
```

### 3.3 Execute and verify the Bedrock proof

```bash
export REGULAAI_GATEWAY_WORKLOAD=poc-bedrock
export REGULAAI_GATEWAY_ALLOWED_TARGET=aws.bedrock_runtime.sa-east-1
export REGULAAI_GATEWAY_EXPECTED_PROVIDER=aws

uv run python scripts/run_live_composition_pilot.py \
  --profile "$REGULAAI_POC_HOME/config/bedrock.json" \
  --correlation-prefix poc-bedrock \
  > "$REGULAAI_POC_HOME/evidence/bedrock-report.json"

jq -e --arg profile "$BEDROCK_PROFILE_DIGEST" '
  .status == "LIVE_COMPOSITION_VERIFIED" and
  .profile_digest == $profile and
  .provider_profile == "bedrock" and .gateway.provider == "aws" and
  .gateway.cached == false and
  .data_handling.input_profile == "FIXED_SYNTHETIC" and
  .data_handling.request_content_persisted == false and
  .data_handling.model_output_persisted == false
' "$REGULAAI_POC_HOME/evidence/bedrock-report.json"
```

Compare the exact model/deployment and control-pack digest with the reviewed configuration.

## 4. Build and exercise the `cards-sandbox`

Create `cards-sandbox` as a separate local FastAPI service, with its own dependency lock and a
dedicated SQLite database or PostgreSQL schema. It accepts only `cards.unblock`, uses synthetic
account tokens and never shares a database with RegulaAI.

### 4.1 Persist the idempotency decision before responding

Use a table equivalent to:

```sql
CREATE TABLE card_unblock_operation (
    idempotency_key_digest TEXT PRIMARY KEY,
    action_id TEXT NOT NULL,
    action_digest TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    execution_id TEXT,
    effect_applied BOOLEAN NOT NULL,
    mode TEXT NOT NULL CHECK (
        mode IN ('success', 'effect_then_timeout', 'timeout_without_effect')
    ),
    created_at TEXT NOT NULL,
    response_json TEXT
);
```

Persist only the SHA-256 idempotency-key digest, action digest, bounded synthetic identifiers,
mode, effect state and canonical response needed for an identical replay. Do not persist bearer
credentials, raw idempotency keys, real card/account data or unrestricted request/response bodies.

The public endpoint is `POST /v1/card-unblocks`. It must:

1. require a dedicated bearer secret and exact workload identity
   `workload.cards-unblock-sandbox`;
2. reject any tool other than `cards.unblock`;
3. validate the exact contracts in
   [State-changing enterprise sandbox connector](STATE_CHANGING_ENTERPRISE_CONNECTOR.md);
4. recompute `idempotency_key_digest` from `Idempotency-Key` and compare it to the body;
5. atomically insert the key/digest binding before performing or recording an effect;
6. return the saved response for an identical replay;
7. return HTTP 409 when the same idempotency key has a different action or request digest.

Provide a separately authenticated administrative endpoint such as
`GET /admin/operations/{idempotency_key_digest}`. It returns only bounded investigation metadata:

```json
{
  "idempotency_key_digest": "sha256:...",
  "action_digest": "sha256:...",
  "execution_id": "sandbox-unblock-...",
  "effect_applied": true,
  "mode": "effect_then_timeout"
}
```

Use a different administrator credential from the execution credential. Bind both services to
loopback. The RegulaAI connector accepts HTTP only for a literal loopback IP.

### 4.2 Implement the three deterministic modes

Select the mode through an authenticated administrative operation before creating each new action;
the public request must not select it.

| Mode | Durable state before response | Public behavior | Correct investigation result |
| --- | --- | --- | --- |
| `success` | save effect and canonical success | HTTP 200 exact receipt | action completes normally |
| `effect_then_timeout` | save effect and execution ID | delay beyond connector timeout | reconcile `EXECUTED` with saved execution ID |
| `timeout_without_effect` | save no-effect record | delay beyond connector timeout | reconcile `NOT_EXECUTED` with `tool_execution_id: null` |

For timeout modes, the administrative lookup must remain available after client cancellation. Use
database transactions and a worker model that does not lose saved state when a request disconnects.

### 4.3 Connect RegulaAI and exercise recovery

```bash
printf 'cards-sandbox execution key: '
read -r -s REGULAAI_STATE_CHANGE_TOOL_API_KEY; printf '\n'
export REGULAAI_STATE_CHANGE_TOOL_API_KEY
export REGULAAI_TOOL_EXECUTION_MODE=state_change_http
export REGULAAI_STATE_CHANGE_TOOL_URL=http://127.0.0.1:8090/v1/card-unblocks
export REGULAAI_STATE_CHANGE_TOOL_WORKLOAD_IDENTITY=workload.cards-unblock-sandbox
export REGULAAI_STATE_CHANGE_TOOL_TIMEOUT_SECONDS=2
export REGULAAI_STATE_CHANGE_TOOL_MAX_REQUEST_BYTES=65536
export REGULAAI_STATE_CHANGE_TOOL_MAX_RESPONSE_BYTES=65536
```

Use the flow in [API contract](API_CONTRACT.md) to create an evaluation, enforce it, select the
`cards.unblock` proposal, issue an exact action approval and submit it once. For this individual
PoC, the local HMAC compatibility mode is acceptable if all three operational keys are distinct:

```bash
printf 'Decision approval HMAC key: '
read -r -s REGULAAI_APPROVAL_HMAC_KEY; printf '\n'
printf 'Action approval HMAC key: '
read -r -s REGULAAI_ACTION_APPROVAL_HMAC_KEY; printf '\n'
printf 'Reconciliation HMAC key: '
read -r -s REGULAAI_RECONCILIATION_HMAC_KEY; printf '\n'
export REGULAAI_APPROVAL_HMAC_KEY REGULAAI_ACTION_APPROVAL_HMAC_KEY
export REGULAAI_RECONCILIATION_HMAC_KEY
```

Each key must contain at least 32 bytes. The decision assertion uses `ra1` and binds the evaluation
evidence `output_digest`; the action assertion uses `ra2` and binds the returned `action_digest`;
the reconciliation assertion uses `rr1` and binds the investigated outcome. Generate these
canonical HMAC assertions in a process that reads the matching key from the environment. The exact
local payload fields and versions are documented in [API contract](API_CONTRACT.md); never persist
the assertion text.

Configure the gateway call used for this proof to return one deterministic synthetic tool call for
the gateway-provided alias of `cards.unblock`, with a bounded call ID and exactly these arguments:

```json
{
  "account_token": "tok_poc_synthetic",
  "reason_code": "CUSTOMER_VERIFIED"
}
```

The execution sequence is:

1. Submit the synthetic enforcement body with `tools: [{"name":"cards.unblock"}]` and no decision
   assertion; require `WAITING_APPROVAL` and no gateway or sandbox call.
2. Read the evaluation evidence as the operator, issue `ra1` over its `output_digest`, and resubmit
   the identical enforcement body. Require `EXECUTED` plus one unexecuted tool proposal.
3. Submit the proposal's exact `call_id` and arguments, the configured workload identity and a new
   idempotency key without an action assertion. Require `WAITING_APPROVAL` and no sandbox call.
4. Issue `ra2` over the returned `action_digest` and resubmit the identical action body once.
5. On an ambiguous result, investigate the sandbox by idempotency-key digest, issue one `rr1`
   assertion for the established outcome, and POST it as `reconciliation_assertion` using the
   reconciler access token.

Run three cases with separate action IDs and idempotency keys:

1. **Success:** assert one HTTP call, terminal execution, an execution receipt and identical replay
   behavior in the sandbox.
2. **Effect followed by timeout:** assert one call and `RECONCILIATION_REQUIRED`; query the admin
   endpoint; verify `effect_applied=true` and the exact action digest; submit an `EXECUTED`
   reconciliation containing the saved execution ID.
3. **Timeout without effect:** assert one call and `RECONCILIATION_REQUIRED`; query the admin
   endpoint; verify `effect_applied=false`; submit `NOT_EXECUTED` with
   `tool_execution_id: null`.

Never infer the result from a timeout, resend the original action or turn reconciliation into a
retry. Retain metadata-only investigation summaries and operator timelines. Follow
[Tool-action reconciliation](TOOL_ACTION_RECONCILIATION.md).

## 5. Review and sign the PoC policy pack

The repository policy `poc-financial@1.0.0` requires OpenAI `store_false` and Bedrock
`iam_authorization`. It does not require ZDR, PrivateLink, residence or organization-managed
CloudTrail. Those requirements remain in the separate enterprise profile.

### 5.1 Record the self-review

```bash
cp examples/financial-pilot/policy.yaml \
  "$REGULAAI_POC_HOME/control-pack/policies/poc-financial.yaml"
cp examples/financial-pilot/policy-review.md \
  "$REGULAAI_POC_HOME/evidence/policy-review.md"
shasum -a 256 "$REGULAAI_POC_HOME/control-pack/policies/poc-financial.yaml" \
  | tee "$REGULAAI_POC_HOME/evidence/policy-digest.txt"
```

Complete the worksheet and add a structured review record with at least:

```yaml
review_type: self_attested_poc
reviewer: poc-author
reviewed_at: 2026-10-04T00:00:00Z # replace with actual UTC time
policy_set_version: poc-financial@1.0.0
policy_sha256: sha256:REPLACE
data_profile: fixed_synthetic_only
interpretation: technical_demonstration_only
compliance_claim: none
sources:
  - https://developers.openai.com/api/docs/guides/your-data
  - https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html
controls:
  openai_store_false: reviewed
  bedrock_iam_authorization: reviewed
  bedrock_model_region_binding: reviewed
not_tested:
  - openai_zero_data_retention
  - aws_privatelink
  - data_residency
  - organization_managed_cloudtrail
  - independent_organizational_review
limitations:
  - both final attestation keys are controlled by the same individual
  - no legal interpretation or compliance certification
```

Replace the date and digest. Record applicability, reasoning, unresolved risks and a future review
due date. Do not use `organization approved` or equivalent wording.

### 5.2 Assemble a dedicated signed control pack

```bash
cp src/regulated_ai/resources/provider-capabilities/*.yaml \
  "$REGULAAI_POC_HOME/control-pack/provider-capabilities/"
cp src/regulated_ai/resources/tools/br-financial-tools.yaml \
  "$REGULAAI_POC_HOME/control-pack/tools/"
```

Create `$REGULAAI_POC_HOME/control-pack/control-pack-manifest.yaml`. The signer refreshes the
placeholder file digests before signing:

```yaml
schema_version: "1"
pack_id: "regulaai-financial-poc"
pack_version: "1.0.0"
files:
  - kind: "policy"
    path: "policies/poc-financial.yaml"
    sha256: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  - kind: "provider_capability"
    path: "provider-capabilities/aws-bedrock.yaml"
    sha256: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  - kind: "provider_capability"
    path: "provider-capabilities/openai-responses.yaml"
    sha256: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  - kind: "tool_catalog"
    path: "tools/br-financial-tools.yaml"
    sha256: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
signing:
  algorithm: "ed25519"
  key_id: "poc-control-pack-1"
  signature: "placeholder"
```

Generate a dedicated key outside Git and derive the raw public key:

```bash
openssl genpkey -algorithm Ed25519 \
  -out "$REGULAAI_POC_HOME/keys/control-pack-private.pem"
chmod 600 "$REGULAAI_POC_HOME/keys/control-pack-private.pem"

CONTROL_PACK_PUBLIC_KEY="$(openssl pkey \
  -in "$REGULAAI_POC_HOME/keys/control-pack-private.pem" \
  -pubout -outform DER | tail -c 32 | base64 | tr -d '\n')"
printf '%s\n' "$CONTROL_PACK_PUBLIC_KEY"
```

Create `$REGULAAI_POC_HOME/config/control-pack-keys.yaml`, replacing the public key and using an
actual UTC activation time at or before signing:

```yaml
schema_version: "2"
keys:
  poc-control-pack-1:
    algorithm: "ed25519"
    public_key: "REPLACE_WITH_CONTROL_PACK_PUBLIC_KEY"
    status: "ACTIVE"
    valid_from: "2026-10-04T00:00:00Z"
```

Sign and verify:

```bash
uv run python scripts/sign_control_pack.py \
  --manifest "$REGULAAI_POC_HOME/control-pack/control-pack-manifest.yaml" \
  --trust-store "$REGULAAI_POC_HOME/config/control-pack-keys.yaml" \
  --private-key "$REGULAAI_POC_HOME/keys/control-pack-private.pem"

CONTROL_PACK_DIGEST="$(uv run python - \
  "$REGULAAI_POC_HOME/control-pack/control-pack-manifest.yaml" \
  "$REGULAAI_POC_HOME/config/control-pack-keys.yaml" <<'PY'
import sys
from pathlib import Path
from regulated_ai.adapters.signed_packs import verify_control_pack

pack = verify_control_pack(Path(sys.argv[1]), Path(sys.argv[2]))
print(pack.identity.payload_digest)
PY
)"
printf '%s\n' "$CONTROL_PACK_DIGEST" \
  | tee "$REGULAAI_POC_HOME/evidence/control-pack-digest.txt"
```

Run identity and both provider proofs against this exact pack. Any pack change invalidates their
binding and requires new proof runs.

## 6. Back up and restore PostgreSQL

Use a dedicated database and persistent volume. Apply migrations before provider/tool exercises:

```bash
export POC_DATABASE_URL='postgresql://REPLACE_WITH_LOCAL_POC_CONNECTION'
REGULAAI_DATABASE_URL="$POC_DATABASE_URL" uv run alembic upgrade head
REGULAAI_DATABASE_URL="$POC_DATABASE_URL" uv run alembic current
```

Keep credentials out of Git and captured output. Prefer `.pgpass` mode `0600` or temporary `PG*`
variables over placing a password in shell history.

### 6.1 Create and hash the dump

```bash
pg_dump -Fc --dbname "$POC_DATABASE_URL" \
  --file "$REGULAAI_POC_HOME/evidence/regulaai-poc.dump"
shasum -a 256 "$REGULAAI_POC_HOME/evidence/regulaai-poc.dump" \
  | tee "$REGULAAI_POC_HOME/evidence/regulaai-poc.dump.sha256"
```

See PostgreSQL's [SQL dump backup guide](https://www.postgresql.org/docs/16/backup-dump.html) and
[`pg_restore` reference](https://www.postgresql.org/docs/17/app-pgrestore.html).

### 6.2 Restore into a separate empty database

```bash
createdb --maintenance-db "$POC_DATABASE_URL" regulaai_poc_restore
pg_restore --exit-on-error --no-owner \
  --dbname "postgresql://REPLACE_WITH_LOCAL_POC_RESTORE_CONNECTION" \
  "$REGULAAI_POC_HOME/evidence/regulaai-poc.dump"
```

Construct the restore URL deliberately; do not concatenate another database name onto an existing
path. The target must be empty.

### 6.3 Verify schema, counts, timeline and minimization

Write the following results to a metadata-only report:

```sql
SELECT version_num FROM alembic_version;

SELECT 'evidence' AS table_name, count(*) AS row_count FROM evidence
UNION ALL SELECT 'enforcement', count(*) FROM enforcement
UNION ALL SELECT 'tool_action', count(*) FROM tool_action
UNION ALL SELECT 'operator_lifecycle_event', count(*) FROM operator_lifecycle_event
UNION ALL SELECT 'approval_consumption', count(*) FROM approval_consumption
UNION ALL SELECT 'action_approval_consumption', count(*) FROM action_approval_consumption
UNION ALL
SELECT 'tool_action_reconciliation_consumption', count(*)
FROM tool_action_reconciliation_consumption
ORDER BY table_name;

SELECT enforcement_id, status, count(*) AS lifecycle_events
FROM operator_lifecycle_event
WHERE enforcement_id = 'REPLACE_WITH_ONE_SYNTHETIC_ENFORCEMENT_ID'
GROUP BY enforcement_id, status
ORDER BY status;
```

Confirm revision `0002_operator_authority` and matching source/restore counts. Start a read-only
RegulaAI instance against the restored database and request one exact operator timeline with the
operator token. Verify `history_complete=true` and the terminal status.

Inspect sampled rows for the absence of raw prompts, tokens, arguments, model outputs, credentials,
idempotency keys and personal data. Search only for fixed synthetic canaries chosen before the
exercise. Record dump digest, non-secret database identifiers, revision, counts, timeline ID and
integrity result, canary-absence checks, timestamps and PostgreSQL version. Then hash the report:

```bash
shasum -a 256 "$REGULAAI_POC_HOME/evidence/backup-restore-report.json" \
  | tee "$REGULAAI_POC_HOME/evidence/backup-restore-report.sha256"
```

The portable artifact is the dump; after restore, record the dump digest and deterministic report
digest rather than claiming a digest of a database file.

## 7. Create evidence and two Ed25519 self-attestations

One person may control both keys for this PoC, but they must be cryptographically distinct and
role-bound. Record the lack of organizational segregation. Private keys remain outside Git.

### 7.1 Finalize the exact scope

```bash
cp examples/financial-pilot/scope.json "$REGULAAI_POC_HOME/evidence/scope.json"
```

Set `source_revision`, `image_digest`, `control_pack_digest`, both normalized profile digests,
`policy_set_version=poc-financial@1.0.0`, `attestation_mode=SELF_ATTESTED_POC` and `ready=true`.
Calculate the exact scope digest:

```bash
SCOPE_DIGEST="$(uv run python - "$REGULAAI_POC_HOME/evidence/scope.json" <<'PY'
import sys
from pathlib import Path
from regulated_ai.adapters.financial_pilot_evidence import load_pilot_scope
from regulated_ai.application.accept_financial_pilot import pilot_scope_digest

print(pilot_scope_digest(load_pilot_scope(Path(sys.argv[1]))))
PY
)"
printf '%s\n' "$SCOPE_DIGEST" \
  | tee "$REGULAAI_POC_HOME/evidence/scope-digest.txt"
```

### 7.2 Create all nine evidence documents

Each closed document has this form:

```json
{
  "schema_version": "1",
  "check": "OPENAI_GATEWAY",
  "scope_digest": "sha256:...",
  "artifact_digest": "sha256:...",
  "observed_at": "2026-10-04T00:00:00+00:00",
  "passed": true,
  "execution_mode": "SANDBOX_LIVE"
}
```

Use SHA-256 over exact artifact bytes and the actual UTC observation time. Every item must be at
most seven days old when evaluated.

| Check | Execution mode | Recommended artifact |
| --- | --- | --- |
| `POSTGRES_CONCURRENCY` | `CI_REAL_POSTGRES` | successful CI PostgreSQL artifact for the exact revision |
| `ENTERPRISE_IDENTITY` | `SANDBOX_LIVE` | `identity-report.json` |
| `OPENAI_GATEWAY` | `SANDBOX_LIVE` | `openai-report.json` |
| `BEDROCK_GATEWAY` | `SANDBOX_LIVE` | `bedrock-report.json` |
| `TOOL_EXECUTION` | `SANDBOX_LIVE` | successful action/timeline report |
| `TOOL_RECOVERY_EXECUTED` | `SANDBOX_LIVE` | effect-then-timeout investigation/timeline |
| `TOOL_RECOVERY_NOT_EXECUTED` | `SANDBOX_LIVE` | no-effect investigation/timeline |
| `POLICY_REVIEW` | `HUMAN_REVIEW` | completed policy self-review |
| `BACKUP_RESTORE` | `SANDBOX_LIVE` | backup/restore report |

Create `$REGULAAI_POC_HOME/config/evidence-inputs.json` with one entry per check. Each value contains
an absolute artifact path and its actual UTC observation time:

```json
{
  "POSTGRES_CONCURRENCY": {
    "artifact": "/absolute/path/to/ci-postgres-report.json",
    "observed_at": "2026-10-04T00:00:00+00:00"
  },
  "ENTERPRISE_IDENTITY": {
    "artifact": "/absolute/path/to/identity-report.json",
    "observed_at": "2026-10-04T00:00:00+00:00"
  }
}
```

Add the remaining seven entries, then use the project enum and parser to generate all wrappers:

```bash
uv run python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

from regulated_ai.adapters.financial_pilot_evidence import load_pilot_scope
from regulated_ai.application.accept_financial_pilot import pilot_scope_digest
from regulated_ai.domain.financial_pilot import PilotCheck

home = Path(os.environ["REGULAAI_POC_HOME"])
scope_digest = pilot_scope_digest(load_pilot_scope(home / "evidence/scope.json"))
inputs = json.loads((home / "config/evidence-inputs.json").read_text())
names = {
    "POSTGRES_CONCURRENCY": "postgres.json",
    "ENTERPRISE_IDENTITY": "identity.json",
    "OPENAI_GATEWAY": "openai.json",
    "BEDROCK_GATEWAY": "bedrock.json",
    "TOOL_EXECUTION": "tool-execution.json",
    "TOOL_RECOVERY_EXECUTED": "recovery-executed.json",
    "TOOL_RECOVERY_NOT_EXECUTED": "recovery-not-executed.json",
    "POLICY_REVIEW": "policy-review.json",
    "BACKUP_RESTORE": "backup-restore.json",
}
if set(inputs) != {item.value for item in PilotCheck}:
    raise SystemExit("evidence-inputs.json must contain every PilotCheck exactly once")
for check, name in names.items():
    source = Path(inputs[check]["artifact"])
    mode = (
        "CI_REAL_POSTGRES"
        if check == "POSTGRES_CONCURRENCY"
        else "HUMAN_REVIEW"
        if check == "POLICY_REVIEW"
        else "SANDBOX_LIVE"
    )
    document = {
        "schema_version": "1",
        "check": check,
        "scope_digest": scope_digest,
        "artifact_digest": f"sha256:{hashlib.sha256(source.read_bytes()).hexdigest()}",
        "observed_at": inputs[check]["observed_at"],
        "passed": True,
        "execution_mode": mode,
    }
    target = home / "evidence" / name
    target.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n")
PY
```

Load every generated file with `load_pilot_evidence` and run the final verifier before retaining the
bundle. Together they catch unknown fields, bad digests, non-UTC timestamps and invalid modes.

A local database run cannot be labeled `CI_REAL_POSTGRES`. Confirm the CI artifact records the same
source revision before including it.

### 7.3 Generate the two role keys

```bash
openssl genpkey -algorithm Ed25519 \
  -out "$REGULAAI_POC_HOME/keys/poc-operator-private.pem"
openssl genpkey -algorithm Ed25519 \
  -out "$REGULAAI_POC_HOME/keys/poc-policy-reviewer-private.pem"
chmod 600 "$REGULAAI_POC_HOME/keys/"*-private.pem
```

Create strict JSON trust store `$REGULAAI_POC_HOME/config/poc-attestation-keys.json` with schema
version 1 and two entries:

```json
{
  "schema_version": "1",
  "keys": {
    "poc-operator-1": {
      "algorithm": "ed25519",
      "public_key": "BASE64_RAW_32_BYTE_PUBLIC_KEY",
      "role": "POC_OPERATOR",
      "status": "ACTIVE",
      "valid_from": "2026-10-04T00:00:00+00:00",
      "valid_until": "2026-10-11T00:00:00+00:00"
    },
    "poc-policy-reviewer-1": {
      "algorithm": "ed25519",
      "public_key": "DIFFERENT_BASE64_RAW_32_BYTE_PUBLIC_KEY",
      "role": "POC_POLICY_REVIEWER",
      "status": "ACTIVE",
      "valid_from": "2026-10-04T00:00:00+00:00",
      "valid_until": "2026-10-11T00:00:00+00:00"
    }
  }
}
```

Activation must be at or before review issuance and evaluation; expiration must be after both.

### 7.4 Calculate the bundle, sign and verify

After all nine evidence files exist, calculate the exact bundle:

```bash
uv run python - \
  "$REGULAAI_POC_HOME/evidence/scope.json" \
  "$REGULAAI_POC_HOME/evidence/postgres.json" \
  "$REGULAAI_POC_HOME/evidence/identity.json" \
  "$REGULAAI_POC_HOME/evidence/openai.json" \
  "$REGULAAI_POC_HOME/evidence/bedrock.json" \
  "$REGULAAI_POC_HOME/evidence/tool-execution.json" \
  "$REGULAAI_POC_HOME/evidence/recovery-executed.json" \
  "$REGULAAI_POC_HOME/evidence/recovery-not-executed.json" \
  "$REGULAAI_POC_HOME/evidence/policy-review.json" \
  "$REGULAAI_POC_HOME/evidence/backup-restore.json" <<'PY'
import sys
from pathlib import Path
from regulated_ai.adapters.financial_pilot_evidence import load_pilot_evidence, load_pilot_scope
from regulated_ai.application.accept_financial_pilot import pilot_bundle_digest

scope = load_pilot_scope(Path(sys.argv[1]))
evidence = tuple(load_pilot_evidence(Path(item)) for item in sys.argv[2:])
print(pilot_bundle_digest(scope, evidence))
PY
```

Create two review documents with schema version 2 and exactly these fields:

```json
{
  "schema_version": "2",
  "domain": "regulaai.financial-poc.review.v1",
  "bundle_digest": "sha256:...",
  "role": "POC_OPERATOR",
  "key_id": "poc-operator-1",
  "approved": true,
  "issued_at": "2026-10-04T00:00:00+00:00",
  "expires_at": "2026-10-11T00:00:00+00:00",
  "signature": "BASE64_ED25519_SIGNATURE"
}
```

Sign canonical ASCII JSON after removing `signature`, sorting keys, using `,` and `:` separators
and escaping non-ASCII. Sign only after every evidence observation; expiration may be at most seven
days after issuance. Repeat with `POC_POLICY_REVIEWER`, `poc-policy-reviewer-1` and the second key.

The following helper derives both raw public keys, writes the strict trust store and signs the exact
bundle. It reads private keys from the protected PoC directory and never copies them into evidence:

```bash
uv run python - <<'PY'
import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key

from regulated_ai.adapters.financial_pilot_evidence import load_pilot_evidence, load_pilot_scope
from regulated_ai.application.accept_financial_pilot import pilot_bundle_digest

home = Path(os.environ["REGULAAI_POC_HOME"])
evidence_dir = home / "evidence"
evidence_names = (
    "postgres.json",
    "identity.json",
    "openai.json",
    "bedrock.json",
    "tool-execution.json",
    "recovery-executed.json",
    "recovery-not-executed.json",
    "policy-review.json",
    "backup-restore.json",
)
scope = load_pilot_scope(evidence_dir / "scope.json")
evidence = tuple(load_pilot_evidence(evidence_dir / name) for name in evidence_names)
bundle_digest = pilot_bundle_digest(scope, evidence)
issued_at = datetime.now(UTC).replace(microsecond=0)
expires_at = issued_at + timedelta(days=6)
trust_expires_at = issued_at + timedelta(days=7)

key_specs = (
    (
        "POC_OPERATOR",
        "poc-operator-1",
        home / "keys/poc-operator-private.pem",
        evidence_dir / "operator-attestation.json",
    ),
    (
        "POC_POLICY_REVIEWER",
        "poc-policy-reviewer-1",
        home / "keys/poc-policy-reviewer-private.pem",
        evidence_dir / "policy-attestation.json",
    ),
)
trust_keys = {}
for role, key_id, private_path, review_path in key_specs:
    private = load_pem_private_key(private_path.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise SystemExit(f"{key_id} is not an Ed25519 key")
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    trust_keys[key_id] = {
        "algorithm": "ed25519",
        "public_key": base64.b64encode(public).decode("ascii"),
        "role": role,
        "status": "ACTIVE",
        "valid_from": issued_at.isoformat(),
        "valid_until": trust_expires_at.isoformat(),
    }
    payload = {
        "schema_version": "2",
        "domain": "regulaai.financial-poc.review.v1",
        "bundle_digest": bundle_digest,
        "role": role,
        "key_id": key_id,
        "approved": True,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    payload["signature"] = base64.b64encode(private.sign(canonical)).decode("ascii")
    review_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")

trust = {"schema_version": "1", "keys": trust_keys}
(home / "config/poc-attestation-keys.json").write_text(
    json.dumps(trust, sort_keys=True, indent=2) + "\n"
)
print(bundle_digest)
PY
```

Run the exact acceptance command:

```bash
uv run python scripts/verify_financial_pilot_acceptance.py \
  --scope "$REGULAAI_POC_HOME/evidence/scope.json" \
  --evidence "$REGULAAI_POC_HOME/evidence/postgres.json" \
  --evidence "$REGULAAI_POC_HOME/evidence/identity.json" \
  --evidence "$REGULAAI_POC_HOME/evidence/openai.json" \
  --evidence "$REGULAAI_POC_HOME/evidence/bedrock.json" \
  --evidence "$REGULAAI_POC_HOME/evidence/tool-execution.json" \
  --evidence "$REGULAAI_POC_HOME/evidence/recovery-executed.json" \
  --evidence "$REGULAAI_POC_HOME/evidence/recovery-not-executed.json" \
  --evidence "$REGULAAI_POC_HOME/evidence/policy-review.json" \
  --evidence "$REGULAAI_POC_HOME/evidence/backup-restore.json" \
  --review "$REGULAAI_POC_HOME/evidence/operator-attestation.json" \
  --review "$REGULAAI_POC_HOME/evidence/policy-attestation.json" \
  --trust-store "$REGULAAI_POC_HOME/config/poc-attestation-keys.json" \
  > "$REGULAAI_POC_HOME/evidence/final-acceptance.json"

jq -e '
  .status == "POC_VERIFIED" and .findings == [] and
  (.scope_digest | startswith("sha256:")) and
  (.bundle_digest | startswith("sha256:"))
' "$REGULAAI_POC_HOME/evidence/final-acceptance.json"
```

Exit `0`, `POC_VERIFIED` and no findings prove only that two role-specific keys self-attested the
complete, fresh, exact-scope, non-production PoC bundle.

## Completion checklist

- [ ] Source and application image are fixed by immutable digests.
- [ ] Keycloak is fixed by tag/digest; issuer is HTTPS; tokens use EdDSA, `at+jwt`, exact audience,
      `client_id` and one top-level RegulaAI role.
- [ ] Mounted JWKS contains only strict public Ed25519 fields.
- [ ] Identity probe passes 12 cases without business mutations.
- [ ] OpenAI project/key/workload are isolated, requests use `store=false`, and no ZDR claim exists.
- [ ] Bedrock uses a development identity, temporary credentials, `sa-east-1`, exact model IAM and
      the public `bedrock-runtime` endpoint.
- [ ] Gateway reports exact provider/model/deployment and `cached=false` for both providers.
- [ ] `cards-sandbox` proves success and both ambiguous outcomes with durable idempotency.
- [ ] Policy review is `self_attested_poc`, technical only, and records every untested control.
- [ ] PostgreSQL restores separately with matching revision, counts and timeline.
- [ ] Evidence contains no prompts, tokens, credentials, arguments, raw outputs or personal data.
- [ ] Nine fresh evidence documents bind the exact scope with required execution modes.
- [ ] Distinct Ed25519 keys bind `POC_OPERATOR` and `POC_POLICY_REVIEWER`.
- [ ] Final verifier exits `0` with `POC_VERIFIED` and no findings.

Retain public keys, signed reviews, scope, evidence references and metadata reports for the chosen
PoC retention period. Delete or rotate OpenAI, AWS, Keycloak, gateway and sandbox credentials after
the exercise. Retain private signing keys only if the documented retention policy requires them.
