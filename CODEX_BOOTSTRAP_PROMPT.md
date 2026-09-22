# Codex bootstrap prompt — Regulated AI Control Plane

You are starting development of a new production-oriented Python service generated from
`brunovicco/codex-python-engineering-harness`.

The working product name is **RegulaAI** and the repository name is
`regulated-ai-control-plane`.

## First action: understand the repository

Before changing code:

1. Read the repository root `AGENTS.md` completely.
2. Read all documents under:
   - `docs/PROJECT_CONTEXT.md`
   - `docs/PRODUCT_VISION.md`
   - `docs/PRODUCT_ARCHITECTURE.md`
   - `docs/DOMAIN_MODEL.md`
   - `docs/REGULATORY_BASELINE_BR.md`
   - `docs/PROVIDER_CAPABILITY_REGISTRY.md`
   - `docs/POLICY_MODEL.md`
   - `docs/API_CONTRACT.md`
   - `docs/THREAT_MODEL.md`
   - `docs/EVAL_STRATEGY.md`
   - `docs/MVP_ROADMAP.md`
   - `docs/ADRs/`
   - `SOURCES.md`
3. Inspect the harness-generated architecture, quality gates, governance assets, dependency rules,
   hooks and tests before selecting implementation details.
4. Do not weaken or bypass any harness quality/security/governance rule.
5. Create `docs/IMPLEMENTATION_PLAN.md` with a concise plan for this iteration before implementing.
6. Amend `AGENTS.md` only if needed, adding a small project-specific section that points to
   `docs/PROJECT_CONTEXT.md` as mandatory product context. Preserve all harness-generated rules.

## Product mission

Build a **multi-provider regulatory control plane for enterprise AI**, starting with Brazilian
regulated environments.

The system receives normalized runtime context and determines whether an AI operation may proceed,
which controls must be applied, which provider capabilities are required, whether human approval is
needed, and what metadata-only evidence must be recorded.

The first product wedge is:

- jurisdiction: Brazil;
- regulatory baseline: LGPD + ANPD international-transfer regulation + selected BCB/CMN controls;
- sector: financial services;
- provider capability examples: OpenAI API and Amazon Bedrock;
- execution mode: evaluation only in this iteration.

The project is **not** a legal-compliance oracle. Regulatory text must never be translated directly
into executable behavior without an explicit intermediate control objective approved by the
organization.

## Architecture principles

Preserve the harness dependency direction:

`entrypoints -> application -> domain`

Adapters may depend on application/domain. Domain must not depend on FastAPI, Pydantic transport
models, provider SDKs, databases, YAML libraries, OpenTelemetry SDKs, or other infrastructure.

The product must separate:

1. **Regulatory source** — what an authoritative source says.
2. **Control objective** — the organization-approved security/privacy/governance objective.
3. **Technical enforcement** — deterministic runtime behavior implementing that objective.

Also separate:

- **Control plane**: policy definitions, provider capability knowledge, versions and configuration.
- **Enforcement plane**: evaluation, transformations, authority checks and evidence at runtime.

## Non-negotiable invariants

Implement these as domain rules and tests where applicable:

- A model must never decide whether a regulatory/security policy is enforced.
- Policy evaluation is deterministic for the same normalized input and the same policy/provider
  registry versions.
- `DENY` has the strongest precedence.
- Unknown provider capability cannot satisfy a mandatory capability requirement.
- Stale capability information must not silently satisfy a high-assurance requirement.
- Fallback to another provider/model must never weaken required controls.
- Required transformations occur before the external-provider trust boundary.
- Raw prompts, model responses, credentials, secrets and personal data must not be written to
  evidence, logs, traces or test fixtures.
- Evidence is metadata-only and must reference policy/provider versions and cryptographic digests,
  not raw sensitive content.
- Regulatory mappings are support mappings and must never claim legal compliance or certification.
- Provider capabilities are facts with source URL, verification date and explicit
  `supported | unsupported | conditional | unknown` state.
- Missing/invalid policy or registry data fails closed for policy-relevant operations.
- Tests perform no live network calls.

## Decision model

Support exactly these top-level outcomes in the first iteration:

- `ALLOW`
- `ALLOW_WITH_TRANSFORMATION`
- `REQUIRE_APPROVAL`
- `DENY`

A decision may contain zero or more obligations:

- `REMOVE_FIELD`
- `MASK`
- `TOKENIZE`
- `PSEUDONYMIZE`
- `REQUIRE_PROVIDER_CAPABILITY`
- `REQUIRE_HUMAN_APPROVAL`
- `RESTRICT_TOOL`
- `REQUIRE_EVIDENCE`

Do not pretend that a transformation alone makes an operation legally compliant.

Decision precedence:

`DENY > REQUIRE_APPROVAL > ALLOW_WITH_TRANSFORMATION > ALLOW`

## Phase 1 scope to implement now

Implement one complete vertical slice.

### Domain

Create framework-free domain types for:

- evaluation context;
- data classification;
- purpose;
- jurisdiction/sector;
- provider target;
- provider capability;
- policy rule;
- control objective;
- obligation;
- decision;
- evidence metadata.

Prefer immutable value objects where practical.

### Provider capability registry

Create a file-backed registry adapter using versioned YAML records.

Every capability record must carry:

- provider;
- service;
- optional region;
- capability key;
- capability state;
- conditions/notes;
- authoritative source URLs;
- `verified_at`;
- record version.

The domain/application layer must not parse YAML directly.

Do not implement automated web scraping. The registry is curated input in Phase 1.

### Policy loading

Create a file-backed policy adapter using versioned YAML validated at the boundary.

Keep policy syntax intentionally small. Do not build a general-purpose rules language.

A policy rule should be able to match a subset of:

- jurisdiction;
- sector;
- purpose;
- data class;
- provider/service;
- operation kind;
- tool/action risk class.

And produce:

- decision contribution;
- obligations;
- required provider capabilities;
- control-objective references;
- regulatory-support references.

### Evaluation service

Implement a use case such as `EvaluateAiOperation`.

Input:
- normalized business context;
- data classifications supplied by the caller plus deterministic detector output;
- requested provider/service;
- requested tools/actions;
- policy-set version.

Behavior:
1. normalize input;
2. classify only deterministic identifiers supported in MVP;
3. load applicable policies;
4. resolve provider capabilities;
5. evaluate conditions;
6. aggregate obligations;
7. compute final decision using documented precedence;
8. create metadata-only evidence;
9. return a typed result.

### Deterministic data classifier

For the initial demo support synthetic-safe detection/validation for:
- CPF-like identifier;
- CNPJ-like identifier;
- account identifier when explicitly structured/labeled;
- authentication secret pattern.

Do not claim semantic detection of all sensitive financial/health data.
For non-deterministic classes, accept caller-supplied labels.

Never put real CPF/CNPJ/customer data in fixtures.

### Evidence adapter

Use a simple local adapter suitable for demo/tests, preferably stdlib SQLite unless the generated
repository already provides a better persistence boundary.

Store only metadata such as:
- evidence id;
- timestamp;
- correlation id;
- decision;
- policy-set version;
- provider-registry version;
- control-objective ids;
- obligation types;
- classification labels;
- stable digests of normalized inputs/outputs;
- previous event digest if implementing a simple tamper-evident chain.

Never store raw prompts, responses, field values, API keys or credentials.

### HTTP API

Implement the contract in `docs/API_CONTRACT.md`.

At minimum:
- `POST /v1/evaluations`
- `GET /v1/evidence/{evidence_id}`
- `GET /v1/providers`
- existing health endpoint if generated by the harness

Return machine-readable error codes. Do not leak sensitive request content in errors.

### Observability

Use the harness observability boundary.

Emit stable metadata-only events/spans for:
- evaluation started;
- policy matched;
- capability resolved;
- decision produced;
- evidence persisted;
- evaluation failed.

Never attach raw payloads.

## Explicitly out of scope for this iteration

Do not implement yet:

- live OpenAI calls;
- live Bedrock calls;
- LangChain/LangGraph;
- an LLM-based policy judge;
- OPA/Rego dependency;
- frontend/dashboard;
- user authentication product;
- SaaS multi-tenancy;
- vector database/RAG;
- automated legal-text ingestion;
- automatic provider-doc scraping;
- full DLP;
- full GRC/inventory platform;
- SUSEP or healthcare policy packs;
- production deployment;
- commits, pushes, releases or deployments unless explicitly requested.

Define clean ports for future provider execution and approval workflows, but do not call them.

## Required example records

Use the files under `examples/` as design fixtures, not unquestioned truth.

Create validated runtime fixtures derived from them for:
- OpenAI Responses API capability facts;
- Amazon Bedrock capability facts;
- a Brazilian financial-services external-inference policy;
- a card-unblock scenario.

Provider facts are time-sensitive. The loader must preserve `verified_at` and sources.
Do not silently invent provider capabilities.

## Required tests

At minimum cover:

1. deterministic repeatability;
2. `DENY` precedence;
3. transformation obligation before external processing;
4. mandatory unknown capability -> fail closed;
5. stale high-assurance capability -> fail closed;
6. human approval for an organization-defined state-changing action;
7. evidence excludes raw input values;
8. evidence includes policy and registry versions;
9. fallback/provider substitution cannot weaken requirements;
10. malformed YAML rejected at the boundary;
11. unsupported policy schema version rejected;
12. no network access required by the test suite.

Add behavior-focused regression tests, not implementation-detail tests.

## Documentation produced by this iteration

Update/create:

- `docs/IMPLEMENTATION_PLAN.md`
- `docs/ARCHITECTURE.md` only as needed, preserving harness architecture rules
- `docs/DEMO.md` showing the first end-to-end evaluation example
- `README.md` with a concise product explanation and local run/evaluation instructions
- any ADR needed for a meaningful new architectural decision

## Definition of done

The iteration is complete only when:

- the vertical slice works locally without cloud credentials;
- all tests pass;
- strict typing passes;
- lint/format passes;
- governance and quality gates pass;
- no sensitive data appears in fixtures/logs/evidence;
- docs match the implementation;
- final diff is reviewed for unrelated changes.

Run the repository-required commands from `AGENTS.md`, including the complete quality gate.

At completion, report:
- behavior implemented;
- files changed;
- test/gate results;
- architectural decisions;
- assumptions;
- remaining risks;
- exact next recommended slice.

Do not commit or push.
