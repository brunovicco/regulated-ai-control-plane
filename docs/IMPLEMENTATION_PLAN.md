# Implementation plan

## Phase 4c — action-bound approval and bounded tool execution

### Goal

Validate exact proposed arguments and require fresh authority bound to the resulting action digest
before any tool execution boundary is crossed.

### Work

1. Add immutable action grant, plan, record, receipt and lifecycle types plus action persistence,
   approval and execution ports.
2. Revalidate ephemeral arguments against the current trusted schema and require their canonical
   digest to match the stored proposal.
3. Bind enforcement, call, catalog/tool definition, schema, arguments, downstream workload and
   idempotency digest into one deterministic action digest.
4. Use domain-separated `ra2` assertions with a dedicated key and replay ledger; never accept a
   Phase 4a decision approval as action authority.
5. Persist and atomically claim metadata-only action state before execution. Treat ambiguous
   failures as terminal reconciliation cases with no automatic retry.
6. Expose the two-step action API and a network-silent mock tool adapter. Keep live connectors and
   tool-result/model composition out of scope.
7. Add unit, persistence and end-to-end privacy/authority tests and document ADR-0009.

### Decisions and assumptions

- Every tool effect, including catalog `read_only` operations, requires action-specific approval in
  this first execution slice.
- Raw arguments, idempotency keys, assertions and tool output are ephemeral and never persisted or
  returned.
- A proposal has at most one action binding. Changing workload identity or idempotency after the
  binding is created fails with a conflict.
- Live downstream integrations remain disabled; Phase 4c proves the authority contract locally.

## Phase 4b — trusted tool authority and proposal boundary

### Goal

Remove caller control over tool risk classification, bind authorized tool schemas to the
deterministic decision and allow the governed gateway to return metadata-only tool proposals
without granting authority to execute them.

### Work

1. Add immutable authorized-tool and tool-proposal domain types plus a trusted tool-catalog port.
2. Load one strict, versioned YAML catalog with closed JSON object schemas and stable schema
   digests.
3. Resolve requested tool names in `EvaluateAiOperation`; reject unknown, duplicate or conflicting
   caller risk claims and use only catalog risk classes for policy matching.
4. Bind catalog version, tool identifiers and schema digests to evaluation/enforcement digests and
   metadata-only evidence.
5. Translate trusted schemas to the governed gateway and accept only proposals for authorized
   definitions. Persist call identity and argument digests, never arguments.
6. Keep proposal execution out of scope. The existing approval authorizes the evaluated request,
   not model-generated arguments or an external side effect.
7. Add boundary, application, gateway, persistence and API tests; update architecture, security and
   operator documentation and run the complete quality gate.

### Decisions and assumptions

- Clients request tools by name. An optional legacy `risk_class` claim must exactly match the
  catalog but never supplies authority.
- Tool schemas are organization-owned control-plane data and use a deliberately small, closed
  JSON-object shape in this slice.
- Gateway tool names are deterministic aliases because the gateway contract has narrower name
  syntax than RegulaAI catalog identifiers.
- A returned tool call is a proposal only. RegulaAI exposes metadata and a digest but does not
  execute it or treat prior approval as action-specific authority.
- A future phase must validate exact arguments and bind a new approval to the action digest before
  any external side effect.

## Phase 4a — digest-bound external approval

### Goal

Allow an organization-owned approval system to authorize one previously evaluated high-impact
operation without giving RegulaAI or a model authority to mint approvals. Bind approval to the
deterministic decision digest, enforce expiry and one-time consumption, and retain metadata-only
evidence.

### Work

1. Add immutable approval grant/receipt types and replace the placeholder boolean approval port
   with explicit inspect-and-consume operations.
2. Implement a strict HMAC approval assertion verifier plus SQLite replay ledger. Persist only
   approval identifiers, actor identifier, decision digest, timestamps and enforcement identifier;
   never persist the signed token.
3. Extend `EnforceAiOperation` so missing approval stays `WAITING_APPROVAL`, invalid approval fails
   closed, and a valid assertion is consumed only after the atomic execution claim and before the
   execution port.
4. Accept an ephemeral secret approval assertion only on the enforcement request. Do not expose an
   approval-creation endpoint.
5. Add unit, contract and end-to-end tests for digest binding, expiry, future issuance, bounded
   lifetime, tampering, replay, approval evidence and read-only versus high-impact behavior.
6. Update the API, architecture, privacy, threat-model, demo, roadmap and ADR documentation; run
   focused security checks and the complete quality gate.

### Decisions and assumptions

- Approval assertions are issued outside RegulaAI by an organization-controlled workflow.
- The Phase 4a assertion format is strict canonical JSON protected by HMAC-SHA256 with a dedicated
  key of at least 32 bytes. A future asymmetric/OIDC adapter can implement the same port.
- `approval_id` is globally single-use. The assertion is checked before execution claim and
  consumed atomically after the claim, so losing a concurrent claim does not consume authority.
- Approval authorizes the deterministic decision digest, not free-form text, a tool name alone or
  a model response.
- Gateway tool forwarding remains disabled. The mock adapter proves read-only versus approved
  high-impact authority without crossing a live tool boundary.
- Missing approval configuration never creates an implicit allow path.

## Phase 3a — governed gateway execution

### Goal

Execute an already-sanitized text request through `governed-llm-gateway` without copying provider
routing, credentials, retry or fallback into RegulaAI. Keep the integration opt-in, metadata-only
outside the ephemeral execution payload and network-silent in the default test/runtime profile.

### Work

1. Pin the gateway's thin typed client to a reviewed Git commit and add a synchronous
   `InferenceExecutionPort` adapter over its bounded async client lifecycle.
2. Translate the execution plan into one provider-neutral text message, conservative risk/data
   classification and explicit workload/time limits. Reject tools until RegulaAI has a complete
   tool-schema and approval contract.
3. Require an explicit execution mode plus gateway URL, credential, workload, allowed RegulaAI
   target and expected terminal provider. Partial/unsafe configuration fails at startup.
4. Treat all gateway output as untrusted. Require terminal success and matching provider
   provenance, discard response content, and persist only routing/execution metadata.
5. Keep the mock adapter as the default. Add unit, persistence and composition tests with fake
   clients only; no test may make a live gateway/provider call.
6. Record the integration boundary in an ADR, update runtime/API/privacy documentation and run the
   complete quality and security gates.

### Decisions and assumptions

- Gateway mode is opt-in through `REGULAAI_EXECUTION_MODE=gateway`; unset means the existing
  network-silent mock.
- The configured gateway workload must authorize only deployments whose provider matches the
  RegulaAI target. The adapter verifies terminal provenance but cannot repair a misconfigured
  gateway after a provider call.
- The initial adapter supports text-only execution plans without tools. Unsupported plans fail
  before any network call.
- Gateway/provider response content remains ephemeral and is discarded because the current API is
  an enforcement/evidence surface, not a completion-returning product API.
- The consumer makes one gateway request. Retry and fallback remain inside the gateway's already
  authorized candidate set.
- Gateway packages are not published to PyPI, so the client is pinned to an immutable Git commit
  rather than a moving branch.

Phase 1 is complete. The following accepted iteration extends it without changing the deterministic
decision contract.

## Phase 2 — local enforcement

### Goal

Prove that field transformation is completed inside the customer trust boundary before any
provider execution port can receive data. Keep API responses, logs, receipts and persisted
enforcement records metadata-only.

### Work

1. Add immutable domain types for transformation receipts, execution plans, enforcement status,
   execution results and metadata-only enforcement records.
2. Add `EnforceAiOperation` to reuse `EvaluateAiOperation`, apply one deterministic transformation
   per target field, fail closed on conflicts/errors and gate execution on the evaluation outcome.
3. Define tokenization and enforcement-evidence ports. Implement local HMAC tokenization and a
   network-silent mock inference adapter for demonstration and tests.
4. Extend SQLite with a separate enforcement table containing only identifiers, status, reason
   codes, transformation types and cryptographic digests.
5. Add metadata-only `POST /v1/enforcements` and `GET /v1/enforcements/{enforcement_id}` endpoints.
6. Add unit, contract and end-to-end tests proving transformations precede execution, raw values
   never enter receipts/evidence/responses, `DENY` and pending approval never execute, ambiguous or
   failed transformations fail closed, and the mock path requires no network access.
7. Update architecture, API, demo, privacy and ADR documentation; run focused checks and the full
   quality gate.

### Decisions and assumptions

- `REQUIRE_APPROVAL` may produce an in-memory transformed plan, but it never calls the execution
  port until a future approval workflow explicitly authorizes the decision digest.
- Multiple transformation obligations for one field are ambiguous and fail closed rather than
  relying on an implicit ordering.
- The default local HMAC key is generated per process and is demo-only. Production must inject a
  stable secret from an approved key-management boundary; keys never appear in evidence or logs.
- The mock inference adapter returns metadata only and never simulates model content.
- Phase 2 does not add a real provider SDK, approval workflow, reversible token vault or external
  network call.

## Goal

Deliver one local, deterministic evaluation slice from normalized request through policy and
provider-capability resolution to a metadata-only evidence record and HTTP response. The slice
does not invoke an AI provider or perform transformations.

## Work

1. Add framework-free immutable domain types for evaluation context, classifications, provider
   capabilities, policy rules, obligations, decisions, control objectives and evidence metadata.
2. Define application ports and implement `EvaluateAiOperation` with deterministic matching,
   decision precedence, fail-closed capability/freshness checks, fallback validation and evidence
   creation.
3. Add strict versioned YAML adapters, a deterministic synthetic-safe identifier classifier, a
   metadata-only SQLite evidence repository and a bounded observability adapter.
4. Add a FastAPI composition root implementing `POST /v1/evaluations`,
   `GET /v1/evidence/{evidence_id}`, `GET /v1/providers` and the existing health behavior.
5. Validate runtime fixtures derived from the checked-in examples for OpenAI Responses, Amazon
   Bedrock and the Brazilian financial-services/card-unblock demonstration.
6. Add unit, adapter-contract and end-to-end scenario tests for deterministic repeatability,
   precedence, pre-boundary transformations, capability failure modes, authority approval,
   evidence privacy/versioning, fallback safety, schema rejection and network independence.
7. Update architecture, demo and local-run documentation, then run focused checks, every command
   required by `AGENTS.md`, the complete quality gate and a final diff review.

## Decisions and assumptions

- Capability freshness is declared by each policy capability requirement; there is no global
  domain freshness constant.
- Fallback targets must satisfy every mandatory capability requirement selected for the original
  operation and are never substituted implicitly.
- Runtime field values exist only in the in-memory evaluation context. Evidence, logs, errors and
  returned obligations identify fields by logical name or classification only.
- SQLite is the Phase 1 persistence adapter. Its schema is metadata-only and stores JSON arrays of
  identifiers/labels, never request content.
- YAML is parsed only in adapters with safe loading and strict boundary models. Unsupported schema
  versions and unknown fields are rejected.
- Existing provider facts retain their checked-in verification dates and source URLs; this slice
  does not refresh or infer provider claims.

## Verification

- Focused domain/application/adapter/API tests.
- `uv lock --check`
- `uv sync --frozen --all-groups`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src tests`
- `uv run pytest`
- `uv run python scripts/quality_gate.py`
- Final inspection for sensitive fixture data, unrelated edits and architecture-rule violations.
