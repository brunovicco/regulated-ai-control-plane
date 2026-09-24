# Phase 1 implementation plan

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
