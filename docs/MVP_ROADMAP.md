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
promotion quorum for that exact bundle. Phase 6h authenticates release reviewers and governs whole
policy/provider onboarding and removal by exact digest. Phase 6i moves the trusted tool catalog into
the signed release, diff, replay and review-evidence boundary. Phase 6l adds detailed owner and
implementation-reference review for every changed tool definition. Automated source ingestion,
automated key distribution, external timestamping and enterprise distribution remain pending.
Phase 6m provides provider-neutral trust-store lineage and rollback-floor verification for those
future distribution systems. Phase 6n adds signed consumer acknowledgement coverage and quorum.
Phase 6o adds fresh signed target assertions for the exact loaded trust-store digest.
Phase 6p adds offline verification for provider-neutral signed external time-authority receipts.
Phase 6q adds offline RFC 3161 verification with exact request, artifact and PKIX trust binding.
Phase 6r adds deterministic OCI image-layout packaging and offline content-addressed verification.
Phase 6s adds restricted Kubernetes/OpenShift service and runtime-state verifier references.
Phase 6t adds metadata-only CloudEvents and opt-in OTLP trace export.

Explore:
- signed policy/provider packs; **implemented in Phase 6a**
- provider capability update workflow; **implemented in Phase 6d for existing targets**
- regulatory review workflow; **implemented in Phase 6e for existing policy sets**
- diff impact analysis; **implemented in Phase 6b**
- curated scenario replay; **implemented in Phase 6c**
- signed tool catalog and replay; **implemented in Phase 6i**
- verification-key lifecycle enforcement; **implemented in Phase 6j**
- content-addressed release custody; **implemented in Phase 6k**
- detailed tool-definition review; **implemented in Phase 6l**
- trust-store lineage checkpoints; **implemented in Phase 6m**
- signed trust-store rollout acknowledgements; **implemented in Phase 6n**
- signed runtime trust-state attestations; **implemented in Phase 6o**
- provider-neutral signed time-authority receipt verification; **implemented in Phase 6p**
- standards-based RFC 3161 timestamp verification; **implemented in Phase 6q**
- provider-neutral OCI evidence artifacts; **implemented in Phase 6r**
- Kubernetes/OpenShift deployment reference; **implemented in Phase 6s**
- CloudEvents and OTLP observability contract; **implemented in Phase 6t**
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

Implemented in Phase 6c and extended in Phase 6i:
- strict bounded scenario suites with no raw values or tool arguments;
- exact suite digest and fixed timezone-aware freshness clock;
- same-context evaluation of an approved base and verified candidate;
- observed decision/obligation and evidence-impact classification;
- per-scenario fail-closed outcomes and deterministic metadata-only JSON;
- optional CI failure when curated replay observes decision impact.

Implemented in Phase 6i:
- exactly one tool catalog included in the canonical signed-pack composition;
- exact verified catalog bytes used by runtime, diff, replay and release evidence;
- conservative semantic impact for tool lifecycle, risk and schema changes;
- schema-v2 metadata-only tool scenarios without arguments or execution;
- signed whole-catalog review required for changed release evidence;
- fail-closed rejection of independent runtime catalog overrides.

Implemented in Phase 6j:
- trust-store schema v2 for release, review and promotion public keys;
- explicit active, retired and revoked states;
- required UTC activation and optional expiry instants;
- authority checks at pack verification, review attestation and promotion issuance times;
- fail-closed not-yet-valid, expired, retired and revoked keys;
- documented overlap rotation and emergency revocation procedure.

Implemented in Phase 6k:
- allowlisted bounded metadata/public-key artifact packaging;
- canonical bundle and promotion-authorization digest verification;
- content-addressed artifact names and canonical custody manifest;
- atomic fail-if-present archive creation;
- private-key marker and symlink rejection;
- recursive tamper and untracked-file verification without network access.

Implemented in Phase 6l:
- exact approved-base and candidate-catalog digest binding;
- per-tool owner role, HTTPS implementation references and exact change-type coverage;
- explicit approved, rejected and needs-revision conclusions;
- schema-version bump enforcement for changed input/output contracts;
- mandatory detailed-review binding for modified signed catalog attestations;
- deterministic metadata-only pass/block output without source retrieval or tool execution.

Implemented in Phase 6m:
- Ed25519-signed exact-byte checkpoints for all three public trust-store authority kinds;
- monotonic sequence, increasing UTC time and predecessor-digest linkage;
- deployment-pinned digest/minimum-sequence verification and stale-package rejection;
- fail-if-present creation plus duplicate-key, symlink and private-key marker rejection;
- optional checkpoint retention in content-addressed release custody;
- external private-key use only during offline signing; no key generation, remote distribution or
  trusted-time claim.

Implemented in Phase 6n:
- exact checkpoint and rollout-policy binding in every consumer acknowledgement;
- lifecycle-aware consumer keys authorized by explicit non-personal target id;
- allowed/required target coverage and minimum distinct-target quorum;
- duplicate target/key/receipt and future/mismatched acknowledgement rejection;
- deterministic metadata-only complete/incomplete report and custody artifact kinds;
- no configuration delivery, node contact, runtime mutation or adoption claim.

Implemented in Phase 6o:
- exact checkpoint, runtime-policy and loaded trust-store digest binding;
- lifecycle-aware target keys authorized by explicit non-personal target id;
- required-target coverage, minimum fresh-target quorum and bounded maximum age;
- duplicate target/key/attestation, pre-checkpoint, future and mismatched assertion rejection;
- deterministic metadata-only current/blocked report and custody artifact kinds;
- no runtime probe, process contact, mutation or continuous-enforcement claim.

Implemented in Phase 6p:
- exact artifact-byte digest and explicit allowlisted subject-kind binding;
- lifecycle-aware Ed25519 time-authority keys and authority identity binding;
- explicit evaluation time, future-receipt rejection and optional caller-pinned issue-time floor;
- deterministic metadata-only verification report and custody artifact kind;
- no receipt acquisition, provider selection, RFC 3161 compatibility or immutable-storage claim.

Implemented in Phase 6q:
- strict bounded DER request/response parsing and exact artifact message-imprint binding;
- required matching nonce and caller-allowlisted RFC 3161 policy OID;
- OpenSSL CMS signature, timestamping EKU and PKIX-chain verification at generation time;
- explicit evaluation time, optional minimum generation time and metadata-only report;
- no acquisition, provider selection, online revocation or long-term evidence-renewal claim.

Implemented in Phase 6r:
- canonical OCI index, evidence manifest/config and SHA-256 artifact layers;
- normalized package reference, explicit UTC time and allowlisted artifact-kind binding;
- complete descriptor, digest, size, metadata and tracked-blob inventory verification;
- bounded JSON/YAML inputs with safe names, no symlinks and private-key marker rejection;
- no registry access, credentials, transport policy, signing, retention or availability claim.

Implemented in Phase 6s:
- real non-root API container entrypoint and digest-substituted Kustomize image;
- restricted single-replica SQLite service with external state, signed-pack, trust and secret mounts;
- startup/readiness/liveness probes, resource limits, no token and read-only root filesystem;
- default-deny egress, labeled-client ingress and network-silent verifier policy;
- periodic mounted-attestation discovery and offline runtime trust-state verification;
- OpenShift restricted-SCC overlay with no cluster mutation or provider-specific operator.

Implemented in Phase 6t:
- CloudEvents 1.0 envelopes for stable allowlisted lifecycle events and bounded metadata;
- deterministic structured JSON encoding with generated event id and explicit UTC time;
- safe CloudEvent-to-span mapping over opt-in OTLP HTTP/protobuf export;
- structured logging before runtime composition and bounded flush/shutdown on API exit;
- no exporter without an endpoint, no baggage/content fields and no business failure on telemetry
  failure;
- no broker delivery, collector provisioning, retention or audit-ledger claim.

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

Implemented in Phase 6h:
- separate Ed25519 reviewer trust store with role, artifact-kind and change-type authority;
- exact base/candidate pack and reviewed-content binding for every attestation;
- mandatory signed binding to the detailed Phase 6d/6e result for modified entities;
- whole-entity onboarding/removal review bound to added candidate or removed base bytes;
- bundle schema version 2 with metadata-only reviewer and signature identities/digests;
- no source retrieval, legal interpretation, promotion, distribution or deployment authority.

## Defer

Until product value is proven:
- generic GRC inventory;
- full legal knowledge graph;
- every Brazilian regulator;
- every model provider;
- multi-cloud deployment automation;
- custom ML classifiers;
- SaaS multi-tenancy.
