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

Status: complete.

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

Status: implemented with a network-silent mock execution port.

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

Status: Phase 3a implemented as an opt-in `governed-llm-gateway` adapter. Phase 4b adds trusted tool
definitions and proposal-only results. Mock execution remains the default; live composition proof
and tool side-effect execution remain pending.

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

Implemented in Phase 3a:
- Git-pinned thin gateway client;
- explicit workload/target/provider configuration assertions;
- bounded transport/provider timeouts and no consumer-side retry;
- conservative request translation and metadata-only gateway provenance;
- fail-closed tool rejection and terminal provider validation;
- network-silent fake-client tests.

## Phase 4 — Approval and agent authority

Status: Phases 4a–4d implemented. Decision approval is bound to the pre-inference deterministic
digest; trusted tool proposals stop at metadata; exact resubmitted arguments require a separate,
domain-separated action approval before a network-silent tool execution boundary is crossed.
Tool results are validated and minimized against action-bound output schemas, but live
enterprise-system side effects and model continuation remain deferred.

Deliver:
- approval port; **implemented in Phase 4a**
- decision-digest-bound approval; **implemented in Phase 4a**
- expiry/replay protection; **implemented in Phase 4a**
- trusted tool allow/deny/approval matrix; **implemented in Phase 4b**
- proposal-only gateway tool definitions and metadata; **implemented in Phase 4b**
- exact argument/schema/digest validation; **implemented in Phase 4c**
- action-digest-bound approval and single-use consumption; **implemented in Phase 4c**
- atomic action claim and ambiguous-outcome reconciliation state; **implemented in Phase 4c**
- trusted closed output schemas and per-field handling; **implemented in Phase 4d**
- ephemeral safe results with metadata-only persistence; **implemented in Phase 4d**
- terminal rejection of unsafe or schema-invalid results; **implemented in Phase 4d**
- demo with read vs high-impact action. **implemented against the mock boundary**

## Phase 5 — Operator dashboard

Status: Phase 5a implements the bounded metadata-only operator timeline API. Global discovery,
complete transition history, reconciliation mutations and a visual dashboard remain pending.

Show:
- decision timeline;
- detected labels (not values);
- transformations;
- provider capability sources/freshness;
- matched policies/control objectives;
- approval state;
- evidence chain.

Implemented in Phase 5a:
- exact-enforcement current-state timeline;
- deterministic evaluation/enforcement/action stage ordering;
- stable attention codes for approval, failure, reconciliation and rejected results;
- bounded action correlation with explicit truncation;
- no payload recovery or administrative mutation.

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
