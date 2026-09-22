# MVP roadmap

## Phase 0 — Repository and contracts

Goal:
establish the engineering/product contract.

Deliver:
- harness-generated service baseline;
- product docs/ADRs;
- policy/provider schemas;
- implementation plan;
- sample fixtures;
- quality gates green.

No provider calls.

## Phase 1 — Deterministic decision vertical slice

Goal:
prove that runtime context can produce a reproducible decision.

Deliver:
- domain model;
- provider capability registry loader;
- policy loader;
- deterministic CPF/CNPJ/secret detector;
- evaluation engine;
- transformation plan;
- tool authority policy;
- metadata-only evidence;
- HTTP API;
- scenario evals.

Exit demo:
request -> decision/obligations/evidence.

## Phase 2 — Local enforcement

Goal:
prove obligations are applied before provider boundary.

Deliver:
- deterministic field transformation;
- tokenization abstraction;
- transformation receipts without raw data;
- enforcement failure -> fail closed;
- execution-plan object suitable for provider adapter.

Still allow a mock provider.

## Phase 3 — Provider execution adapters

Goal:
execute a sanitized request without duplicating gateway responsibilities.

Start with:
- OpenAI direct adapter or integration;
- Amazon Bedrock adapter/integration.

Preferred architecture:
integrate with `governed-llm-gateway` through an `InferenceExecutionPort` rather than copying model
routing/resilience code.

Deliver:
- bounded timeouts;
- provider-specific request translation;
- config assertions;
- no policy downgrade on fallback;
- provider-call metadata evidence.

## Phase 4 — Approval and agent authority

Deliver:
- approval port;
- decision-digest-bound approval;
- expiry/replay protection;
- tool allow/deny/approval matrix;
- demo with read vs high-impact action.

## Phase 5 — Operator dashboard

Show:
- decision timeline;
- detected labels (not values);
- transformations;
- provider capability sources/freshness;
- matched policies/control objectives;
- approval state;
- evidence chain.

## Phase 6 — Maintained intelligence

Explore:
- signed policy/provider packs;
- provider capability update workflow;
- regulatory review workflow;
- diff impact analysis;
- enterprise integrations;
- additional sectors.

## Defer

Until product value is proven:
- generic GRC inventory;
- full legal knowledge graph;
- every Brazilian regulator;
- every model provider;
- multi-cloud deployment automation;
- custom ML classifiers;
- SaaS multi-tenancy.
