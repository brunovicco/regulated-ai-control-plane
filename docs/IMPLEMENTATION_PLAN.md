# Phase 1 implementation plan

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
