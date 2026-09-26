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

Status: Phase 5a implements the bounded metadata-only operator timeline API. Phase 5b adds local
append-only transition history with explicit legacy baselines. Phase 5c adds decision, control,
transformation and sanitized approval context. Phase 5d binds provider source/freshness snapshots
to new decision evidence. Phase 5e adds a server-rendered exact-ID dashboard. Global discovery,
cryptographic anchoring and reconciliation mutations remain pending.

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

Implemented in Phase 5b:
- transactionally recorded evidence/enforcement/action lifecycle events;
- schema-level append-only guards and duplicate suppression;
- explicit migration baselines instead of inferred legacy history;
- bounded event history with completeness and truncation indicators.

Implemented in Phase 5c:
- matched policy, control-objective and provider-capability identifiers;
- decision/enforcement reasons, authorized tools and provider target;
- metadata-only transformation receipts and previous evidence digest;
- sanitized approval context without actor identity;
- stronger evidence/enforcement and approval-binding integrity checks.

Implemented in Phase 5d:
- immutable capability snapshots with provider target, state and conditions;
- captured provider record/registry versions, verification date and source URLs;
- snapshot-bound output and event digests for new evaluations;
- explicit incomplete context for migrated legacy evidence;
- strict persistence-boundary validation without current-registry reconstruction.

Implemented in Phase 5e:
- responsive server-rendered operator view over the existing timeline use case;
- exact-ID lookup without global list/search/discovery;
- no JavaScript or external assets;
- escaped metadata and restrictive browser security headers;
- no approval, retry, reconciliation or other administrative mutation.

## Phase 6 — Maintained intelligence

Status: Phase 6a implements signed local policy/provider releases with fail-closed digest,
signature, trust-anchor and path verification. Phase 6b adds offline semantic diff and conservative
impact classification between verified releases. Phase 6c adds fixed-clock, metadata-only scenario
replay for observed decision and evidence changes. Phase 6d adds a digest-bound offline review gate
for updates to existing provider capability targets. Phase 6e adds a digest-bound regulatory review
gate for updates to existing policy sets. Phase 6f composes verified static, replay and exact-byte
review evidence into one deterministic release bundle. Phase 6g authenticates a role-bound Ed25519
promotion quorum for that exact bundle. Automated source ingestion, key lifecycle automation,
onboarding/removal governance and enterprise distribution remain pending.

Explore:
- signed policy/provider packs; **implemented in Phase 6a**
- provider capability update workflow; **implemented in Phase 6d for existing targets**
- regulatory review workflow; **implemented in Phase 6e for existing policy sets**
- diff impact analysis; **implemented in Phase 6b**
- curated scenario replay; **implemented in Phase 6c**
- enterprise integrations;
- additional sectors.

Implemented in Phase 6a:
- strict versioned policy/provider manifest with bounded normalized paths;
- SHA-256 binding for every declared file;
- Ed25519 signature verification against a deployment-controlled public-key trust store;
- fail-closed startup before runtime YAML parsing;
- verified pack identity in provider metadata;
- offline signer that accepts an external private key and verifies before manifest replacement.

Implemented in Phase 6b:
- same-trust verification of base and candidate packs before comparison;
- stable policy/rule and provider/capability semantic changes;
- decision, evidence and governance impact classification;
- conservative capability-to-dependent-policy correlation;
- version-reuse and signing-key-change signals;
- deterministic metadata-only JSON and optional CI failure on decision impact.

Implemented in Phase 6c:
- strict bounded scenario suites with no raw values or tools;
- exact suite digest and fixed timezone-aware freshness clock;
- same-context evaluation of an approved base and verified candidate;
- observed decision/obligation and evidence-impact classification;
- per-scenario fail-closed outcomes and deterministic metadata-only JSON;
- optional CI failure when curated replay observes decision impact.

Implemented in Phase 6d:
- authenticated approved-base selection and exact-byte candidate binding;
- strict source-review records without quotes or source content;
- whole-record capability/source coverage for record-level freshness claims;
- fail-closed version, date, lineage and review-conclusion checks;
- deterministic metadata-only pass/block report before separate signing;
- no scraping, reviewer authentication, signing or promotion authority.

Implemented in Phase 6e:
- authenticated approved-base selection and exact-byte policy-draft binding;
- stable-rule lineage with exact change type, control-objective and support-reference coverage;
- explicit review of changed policy-set metadata and per-rule conclusions;
- fail-closed policy/rule version, objective, missing, rejected and revision checks;
- explicit separation of regulatory mappings from non-regulatory enterprise authority policy;
- deterministic metadata-only pass/block report before separate signing;
- no source retrieval, legal interpretation, reviewer authentication, signing or promotion.

Implemented in Phase 6f:
- same-trust verification of the base and signed candidate before evidence composition;
- recomputed static diff and fixed-clock scenario replay for one exact release pair;
- review records re-evaluated against exact authenticated candidate file bytes;
- required passing review coverage for every modified existing policy/provider entity;
- explicit incomplete findings for missing/blocked reviews and unsupported additions/removals;
- deterministic metadata-only JSON with a canonical bundle digest;
- no automatic impact acceptance, signing, promotion, deployment or external calls.

Implemented in Phase 6g:
- canonical verification of one complete Phase 6f evidence bundle;
- separate Ed25519 promotion trust store with key-to-role authorization;
- explicit required-role and distinct-key quorum policy;
- exact bundle/candidate/promotion-policy binding, UTC validity windows and active rejection
  handling;
- deterministic metadata-only authorization report and digest;
- no control-pack signing, repository mutation, publication, promotion, distribution or deployment.

## Defer

Until product value is proven:
- generic GRC inventory;
- full legal knowledge graph;
- every Brazilian regulator;
- every model provider;
- multi-cloud deployment automation;
- custom ML classifiers;
- SaaS multi-tenancy.
