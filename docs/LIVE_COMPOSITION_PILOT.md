# Live composition pilot

Phase 7a provides an explicit non-production proof that RegulaAI can apply deterministic controls,
transform a synthetic identifier, call a real provider through `governed-llm-gateway`, persist only
allowlisted evidence and reconstruct the operator timeline. The integrated financial-pilot profile
extends the proof to separately reviewed OpenAI and Amazon Bedrock gateway workloads.

The pilot is deliberately not a general prompt client. It accepts no request text, tool arguments
or arbitrary provider choice. Its two input values are fixed synthetic strings in the package and
it never enables tool execution. Without `--profile` it retains the legacy
`openai.responses_api.global` demo. A reviewed profile selects exactly one supported target:
`openai.responses_api.global` or `aws.bedrock_runtime.sa-east-1`.

## Prerequisites

- a non-production `governed-llm-gateway` deployment with one reviewed OpenAI- or Bedrock-backed
  workload;
- synthetic/test credentials issued through the deployment secret boundary;
- an empty or dedicated non-production evidence database;
- the complete gateway configuration listed in `.env.example`;
- an egress policy permitting only the reviewed gateway endpoint.

The workload must authorize only the target and terminal provider declared by the selected profile.
For example:

```text
REGULAAI_GATEWAY_ALLOWED_TARGET=openai.responses_api.global
REGULAAI_GATEWAY_EXPECTED_PROVIDER=openai
```

The profile also requires exact terminal model and deployment identifiers. It is strict,
non-secret JSON and its digest covers all organization condition assertions. The draft examples in
`examples/financial-pilot/` contain placeholders and false assertions; they cannot be accepted as
live configuration.

The process must also set a non-production environment label and an explicit dedicated database:

```text
REGULAAI_ENVIRONMENT=pilot
REGULAAI_EVIDENCE_DB=var/regulaai-pilot-evidence.sqlite3
```

The command rejects missing environment/database settings and the environment labels `prod` or
`production`.

Never put gateway or provider credentials in shell history, command arguments, environment files,
logs, screenshots or the repository. Inject them using the platform's approved secret mechanism.

## Run

After injecting configuration into the process environment:

```bash
uv run python scripts/run_live_composition_pilot.py
```

For the integrated financial pilot, always supply the reviewed profile:

```bash
uv run python scripts/run_live_composition_pilot.py \
  --profile /approved/config/financial-pilot-openai.json
```

An optional safe correlation prefix can associate a run with a non-sensitive change identifier:

```bash
uv run python scripts/run_live_composition_pilot.py \
  --correlation-prefix pilot-change-ticket-123
```

The command always adds a new random suffix so a previous idempotent enforcement cannot be
misreported as a fresh provider call.

The command fails before execution unless `REGULAAI_EXECUTION_MODE=gateway`. It makes exactly one
RegulaAI inference attempt; local retry remains prohibited and gateway-owned retry/fallback stays
inside the reviewed workload. A timeout or ambiguous transport failure is terminal and must not be
rerun automatically with the same operational assumption.

## Output and acceptance

Success writes one canonical JSON object to stdout with
`status=LIVE_COMPOSITION_VERIFIED`. The report contains:

- signed control-pack identity;
- evidence, evaluation, enforcement and provider-execution identifiers;
- output/report digests and transformation categories;
- allowlisted gateway routing/execution metadata;
- operator timeline completeness and stage statuses;
- explicit data-handling and scope statements.

The report contains no prompt, field value, transformed value, model output, credential, provider
response body or tool argument. The underlying evidence database is still organization metadata
and must use an approved retention policy and access boundary.

Structured lifecycle logs and CloudEvents use stderr so stdout remains one machine-readable JSON
document. Capture and protect both streams according to the non-production logging policy.

Accept the pilot only when the command exits `0`, the report status is verified, timeline history
and provider context are complete, there are no attention codes, `cached=false`, and the provider,
model and deployment shown in the report match the reviewed non-production workload. The proof does
not establish provider compliance, production readiness, continuous enforcement or enterprise-tool
authority. See [Integrated financial pilot](FINANCIAL_PILOT.md) for the complete acceptance profile.
