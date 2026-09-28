# Architecture

## Context

RegulaAI owns deterministic evaluation at the AI execution boundary. It accepts normalized
business context, combines caller labels with narrow deterministic classification, evaluates an
immutable organization policy set, verifies curated provider capability facts and returns an
execution plan plus metadata-only evidence. Phase 1 does not call an AI provider.

Phase 2 adds local enforcement. It applies field transformations, persists a metadata-only
`PREPARED` record and then calls a network-silent mock execution port. No real provider SDK or
external inference is present in the default runtime.

Phase 3a adds an opt-in adapter for `governed-llm-gateway`. It sends only the sanitized in-memory
execution plan, delegates provider routing/retry/fallback to the gateway and persists allowlisted
provider-call metadata. The public enforcement response remains content-free.

Phase 4a adds verification and one-time consumption of externally issued approval assertions.
Approval remains outside model authority and is bound to the deterministic evaluation digest.

Phase 4b removes caller control over tool risk. A versioned catalog supplies trusted risk classes
and closed input schemas. The gateway may propose an authorized tool call, but RegulaAI stores only
its metadata/digest and performs no tool side effect.

Phase 4c binds exact proposal arguments and separate approval to an atomic tool execution. Phase
4d then validates the untrusted result against a trusted closed output schema and exposes only an
ephemeral minimized result.

Phase 7a composes the existing boundaries in an opt-in non-production pilot. A package-owned fixed
synthetic request enters the normal enforcement use case, is tokenized locally, crosses only the
configured governed-gateway boundary and produces a metadata-only report after operator-timeline
validation. The pilot is not a second prompt API and enables no tool execution.

## Layers

```text
src/regulated_ai/
├── domain/
├── application/
├── adapters/
└── entrypoints/
```

### Domain

Pure business concepts, invariants, Value Objects, domain services, events, and domain errors.

### Application

Use cases, commands, queries, ports, authorization decisions, and transaction coordination.

### Adapters

Implementations of application ports for databases, messaging, HTTP, cache, storage, identity, and external SDKs.

### Entrypoints

HTTP, CLI, jobs, events, and serverless handlers. Entrypoints validate and translate transport data but do not own business rules.

## Dependency rule

```text
entrypoints -> application -> domain
adapters    -> application/domain
domain      -> no outer layer
```

## Cross-cutting decisions

- Configuration: environment variables validated at startup.
- Logging: structured events to stdout/stderr.
- Tracing: the service-only OpenTelemetry adapter exports trace data over OTLP HTTP/protobuf only
  when an endpoint is configured. It propagates W3C Trace Context, but not baggage, and keeps the
  SDK lifecycle at the composition-root boundary. The separate Langfuse LLM observer remains an
  opt-in adapter with its existing contract.
- Errors: infrastructure errors translated at adapters; external errors mapped at entrypoints.
- Time: UTC internally with timezone-aware values.
- Money: `Decimal` wrapped in a domain Value Object.
- Idempotency: required for externally visible side effects.
- Packaging: containerized via the repo `Dockerfile` (multi-stage, uv-based); the runtime `CMD` is defined per project.

## Phase 1 components

- `domain/models.py`: immutable value objects and decision precedence; no outer-layer imports.
- `application/evaluate_operation.py`: the `EvaluateAiOperation` orchestration use case.
- `application/ports.py`: policy, capability, classifier, evidence, observability and future
  approval/execution contracts.
- `adapters/yaml_files.py`: strict versioned policy/provider registry boundary.
- `adapters/classifier.py`: CPF/CNPJ checksum, labeled account-field and secret-field detection.
- `adapters/evidence_sqlite.py`: metadata-only local evidence persistence.
- `adapters/evaluation_observability.py`: stable, allowlisted structured lifecycle events.
- `entrypoints/api.py`: HTTP validation, error mapping, composition root and Phase 1 endpoints.

Transform obligations are returned before any configured execution port can be called. Capability
requirements selected for the primary target are also applied to every explicit fallback target.
High-assurance freshness is policy data (`max_age_days`), not a global domain constant.

See [ADR-0004](adr/0004-versioned-yaml-and-sqlite-phase-1-adapters.md) for the local adapter
decision and [the demo](DEMO.md) for the end-to-end flow.

## Phase 2 components

- `application/enforce_operation.py`: evaluation-to-transformation-to-execution orchestration.
- `adapters/tokenization.py`: injected HMAC tokenization/pseudonymization boundary.
- `adapters/mock_execution.py`: network-silent execution port used to prove boundary ordering.
- `adapters/evidence_sqlite.py`: separate metadata-only enforcement lifecycle records.
- `entrypoints/api.py`: metadata-only enforcement endpoints; transformed payloads remain internal.

The enforcement sequence is:

```text
evaluate -> transform locally -> persist PREPARED -> claim DISPATCHED -> execute -> persist EXECUTED
```

`DENY`, missing approval, conflicting transformations, transformation failure and evidence failure
all stop before execution. See
[ADR-0005](adr/0005-local-enforcement-before-execution.md).

## Phase 3a components

- `adapters/gateway_execution.py`: bounded provider-neutral request translation and terminal
  provenance validation.
- `entrypoints/api.py`: explicit mock/gateway composition selected at startup.
- `adapters/evidence_sqlite.py`: optional provider-call metadata stored with enforcement state.

The gateway path sends only sanitized text and, in Phase 4b, trusted catalog tool definitions.
Separate transport and provider timeouts are configured, while retry and fallback remain
gateway-owned. The configured
gateway workload must be constrained to the provider already evaluated by RegulaAI; terminal
provider mismatch fails closed. An atomic `PREPARED -> DISPATCHED` claim prevents concurrent or
post-crash replay from issuing a second external request; interrupted `DISPATCHED` records require
operational reconciliation. See
[ADR-0006](adr/0006-governed-gateway-execution-adapter.md).

## Phase 4a components

- `application/ports.py`: inspect-and-consume approval authority contract.
- `adapters/approval.py`: strict HMAC assertion verification and SQLite replay ledger.
- `application/enforce_operation.py`: approval validation before preparation and atomic consumption
  after the execution claim but before execution.
- `entrypoints/api.py`: ephemeral secret assertion input and metadata-only approval receipt output.

The approval sequence is:

```text
evaluate -> transform -> inspect digest-bound assertion -> persist PREPARED
         -> claim DISPATCHED -> consume approval once -> execute -> persist EXECUTED
```

Missing assertions remain `WAITING_APPROVAL`. Invalid assertions never reach an execution claim;
consumption failure after a claim becomes terminal `APPROVAL_FAILED`. The raw assertion is never
stored. See [ADR-0007](adr/0007-digest-bound-external-approval.md).

## Phase 4b components

- `domain/models.py`: immutable authorized-tool definitions and metadata-only proposals.
- `application/ports.py`: organization-owned tool-catalog contract.
- `adapters/yaml_files.py`: strict versioned tool catalog and canonical schema digests.
- `application/evaluate_operation.py`: fail-closed resolution and policy matching using catalog
  risk classes only.
- `adapters/gateway_execution.py`: trusted schema translation and proposal digesting.
- `adapters/evidence_sqlite.py`: catalog/tool identities and argument digests without arguments.

The sequence is:

```text
caller tool name -> catalog resolution -> deterministic policy -> trusted gateway definition
                 -> model proposal -> metadata/digest only -> no tool execution
```

An approval bound to the evaluation digest does not authorize model-generated arguments. Phase 4c
therefore validates exact arguments and requires new authority bound to the action digest. See
[ADR-0008](adr/0008-trusted-tool-catalog-and-proposal-boundary.md).

## Phase 6i components

- `adapters/signed_packs.py`: requires exactly one tool catalog and authenticates its exact bytes.
- `entrypoints/api.py`: constructs the runtime catalog only from verified control-pack bytes.
- `application/analyze_control_pack_diff.py`: reports catalog and definition impact.
- `application/replay_control_pack_scenarios.py`: resolves metadata-only tool requests independently
  against base and candidate catalogs without execution.
- `application/assemble_release_evidence.py`: binds the catalog artifact and authenticated review.

The signed release boundary is now:

```text
manifest signature -> policy bytes + provider bytes + tool-catalog bytes
                   -> parse trusted records -> diff/replay/review evidence
                   -> runtime evaluation (never tool execution authority)
```

See [ADR-0024](adr/0024-signed-tool-catalog-release-boundary.md).

## Phase 6j components

- `adapters/trust_key_lifecycle.py`: shared strict public-key state and UTC validity window.
- `adapters/signed_packs.py`: evaluates the selected release key at pack verification time.
- `adapters/release_review_attestations.py`: evaluates reviewer authority at `attested_at`.
- `adapters/promotion_attestations.py`: evaluates promotion authority at `issued_at`.
- `docs/TRUST_KEY_LIFECYCLE.md`: rotation, retirement, emergency revocation and validation runbook.

```text
signature + selected public key + signed/event time
    -> trust-store v2 lifecycle validation
    -> ACTIVE and within [valid_from, valid_until)
    -> cryptographic verification
```

Lifecycle authorization is additional to signature verification; it does not create or distribute
keys. See [ADR-0025](adr/0025-verification-key-lifecycle-enforcement.md).

## Phase 6k components

- `adapters/release_custody.py`: bounded content-addressed archive creation and recursive
  verification.
- `scripts/manage_release_custody.py`: offline `create` and `verify` operator commands.
- `docs/RELEASE_CUSTODY.md`: allowlist, retention boundary and operating procedure.

```text
complete evidence bundle + authorized promotion report + public release artifacts
    -> canonical core-digest verification -> private-key marker rejection
    -> content-addressed blobs + canonical custody manifest -> atomic new directory
    -> later recursive digest/binding/untracked-file verification
```

The archive is a local tamper-evident package, not an immutable or externally timestamped store.
See [ADR-0026](adr/0026-content-addressed-release-artifact-custody.md).

## Phase 6l components

- `adapters/tool_review_files.py`: strict candidate/review parsing and exact-byte digests.
- `application/review_tool_catalog_update.py`: per-tool lineage, ownership, implementation-reference
  and schema-version checks.
- `scripts/review_tool_catalog_update.py`: deterministic offline pass/block report.
- `scripts/assemble_release_evidence.py`: requires modified catalog attestations to bind the passing
  detailed review.

```text
authenticated base + candidate catalog + metadata-only per-tool review
    -> exact changed-tool coverage + owner/reference/conclusion checks
    -> signed whole-catalog attestation binds detailed result
    -> complete release evidence (never tool execution authority)
```

See [ADR-0027](adr/0027-detailed-tool-definition-review-gate.md).

## Phase 6m components

- `adapters/trust_store_lineage.py`: strict public-store parsing, signed canonical checkpoints and
  anchored lineage verification.
- `scripts/manage_trust_store_lineage.py`: offline create/verify operator commands.
- `adapters/release_custody.py`: allowlists checkpoint retention with release evidence.
- `docs/TRUST_STORE_LINEAGE.md`: rollback-floor and distribution-boundary runbook.

```text
exact public trust-store bytes + stable identity/sequence + prior checkpoint
    -> Ed25519 distribution signature -> pinned public key + rollback-floor verification
    -> accept current public authority metadata or fail closed as stale/forked
```

See [ADR-0028](adr/0028-trust-store-lineage-checkpoints.md).

## Phase 6n components

- `adapters/trust_store_acknowledgements.py`: strict rollout-policy parsing, lifecycle-aware
  acknowledgement authority and signed target-receipt verification.
- `application/verify_trust_store_rollout.py`: exact checkpoint binding, target coverage and quorum
  evaluation.
- `scripts/verify_trust_store_rollout.py`: deterministic offline rollout-evidence command.
- `docs/TRUST_STORE_ROLLOUT.md`: operator workflow and deployment boundary.

```text
verified Phase 6m checkpoint + rollout policy + signed target receipts
    -> receipt signature/lifecycle/target authorization + exact checkpoint binding
    -> required-target coverage + acknowledgement quorum
    -> complete metadata-only rollout report or fail closed
```

The receipt proves that an authorized target identity accepted the checkpoint metadata. It does not
prove that a running process loaded the store or that external delivery succeeded. Those effects
remain deployment-owned.

See [ADR-0029](adr/0029-signed-trust-store-rollout-acknowledgements.md).

## Phase 6o components

- `adapters/runtime_trust_state.py`: strict runtime-state policy, target authority and signed
  attestation verification.
- `application/verify_runtime_trust_state.py`: exact loaded-digest binding, freshness, target
  coverage and quorum evaluation.
- `scripts/verify_runtime_trust_state.py`: deterministic offline runtime-state evidence command.
- `docs/RUNTIME_TRUST_STATE.md`: operator workflow and assertion boundary.

```text
verified Phase 6m checkpoint + runtime-state policy + signed target assertions
    -> signature/lifecycle/target authorization + exact loaded-digest binding
    -> freshness + required-target coverage + distinct-target quorum
    -> current metadata-only state report or fail closed
```

The report authenticates target assertions but does not independently observe processes or prove
continuous enforcement.

See [ADR-0030](adr/0030-signed-runtime-trust-state-attestations.md).

## Phase 6p components

- `adapters/trusted_timestamp.py`: strict artifact binding, authority trust-store parsing and
  Ed25519 receipt verification.
- `scripts/verify_trusted_timestamp.py`: deterministic offline metadata-only report command.
- `docs/TRUSTED_TIMESTAMP.md`: authority, trust-floor and provider boundary runbook.

```text
exact artifact bytes + signed time receipt + authority public trust store
    -> digest/kind/authority/key lifecycle/signature verification
    -> explicit evaluation time + optional caller-pinned issue-time floor
    -> metadata-only trusted-time assertion evidence or fail closed
```

This boundary verifies the configured authority assertion; it does not acquire a receipt, implement
RFC 3161, certify the authority or provide immutable retention.

See [ADR-0031](adr/0031-provider-neutral-signed-time-authority-receipts.md).

## Phase 6q components

- `adapters/rfc3161_timestamp.py`: bounded DER parsing, exact imprint/nonce/policy binding and the
  OpenSSL verification boundary.
- `scripts/verify_rfc3161_timestamp.py`: deterministic offline metadata-only report command.
- `docs/RFC3161_TIMESTAMP.md`: PKIX trust, input-preservation and revocation boundary runbook.

```text
exact artifact bytes + original DER request/response + CA bundle
    -> strict imprint/nonce/policy/time validation
    -> CMS signature + timestamping EKU + PKIX chain verification at generation time
    -> metadata-only RFC 3161 verification report or fail closed
```

ASN.1 parsing does not establish trust. OpenSSL performs signature and PKIX verification against the
deployment-supplied CA bundle. No network, timestamp acquisition or online revocation occurs.

See [ADR-0032](adr/0032-offline-rfc3161-timestamp-verification.md).

## Phase 6r components

- `adapters/oci_evidence.py`: deterministic OCI image-layout creation, reference resolution and
  complete descriptor/blob verification.
- `scripts/manage_oci_evidence.py`: local create/verify command with metadata-only identity output.
- `docs/OCI_EVIDENCE.md`: transport, registry and signing boundary runbook.

```text
allowlisted metadata artifacts + normalized reference + explicit UTC time
    -> canonical OCI index + evidence manifest/config + SHA-256 layers
    -> complete descriptor/digest/inventory verification
    -> portable local layout identity or fail closed
```

The adapter produces and consumes a local OCI layout only. It has no registry client, credentials or
network path and does not treat transport availability or registry ACLs as evidence integrity.

See [ADR-0033](adr/0033-provider-neutral-oci-evidence-artifacts.md).

## Phase 6s components

- `Dockerfile`: non-root production API entrypoint with access logs disabled.
- `deploy/kubernetes`: restricted single-replica service, storage, service, policies and offline
  runtime-state verification CronJob.
- `deploy/openshift`: overlay that lets the platform restricted SCC allocate runtime identities.
- `scripts/verify_runtime_trust_state.py`: sorted directory discovery and current-UTC scheduler mode
  in addition to the reproducible explicit-time mode.
- `docs/KUBERNETES_DEPLOYMENT.md`: authority injection, rendering and rollout boundary.

```text
verified image digest + external signed pack/trust/secrets + persistent state
    -> restricted single-replica API with default-deny egress
mounted checkpoint/policy/attestations + explicit current UTC
    -> network-silent CronJob -> metadata-only current/blocked report
```

The manifests are a reference and are never applied by repository tooling. They do not provision
clusters, registries, identity providers, secrets, storage classes or external alert delivery.

See [ADR-0034](adr/0034-kubernetes-openshift-deployment-reference.md).

## Phase 6t components

- `adapters/evaluation_observability.py`: allowlisted CloudEvents 1.0 envelope and safe span mapping.
- `adapters/observability.py`: opt-in OTLP HTTP tracing, bounded attributes, W3C trace context and
  lifecycle isolation.
- `entrypoints/api.py`: structured-log configuration before composition plus bounded telemetry
  flush/shutdown.
- `docs/CLOUDEVENTS_OTLP.md`: event schema, configuration and collector boundary.

```text
allowlisted lifecycle event + bounded identifier metadata
    -> CloudEvent 1.0 structured envelope -> JSON structured log
    -> bounded control.lifecycle span -> optional OTLP HTTP exporter
unknown/content-bearing fields -> dropped
sink/exporter unavailable -> business decision unchanged
```

No broker client is included. An OTLP endpoint activates exporter construction only when the
observability extra is installed; the deployment image includes that extra but configures no
endpoint or egress by default.

See [ADR-0035](adr/0035-metadata-only-cloudevents-and-otlp.md).

## Phase 7a components

- `entrypoints/live_composition_pilot.py`: fixed scenario, gateway-mode assertion, terminal receipt
  and timeline validation, canonical metadata-only report.
- `scripts/run_live_composition_pilot.py`: operator CLI with no content or credential arguments.

```text
fixed synthetic request
    -> deterministic evaluation + local tokenization
    -> governed gateway + reviewed non-production provider workload
    -> metadata-only evidence + exact operator timeline
    -> LIVE_COMPOSITION_VERIFIED report (no prompt or model output)
```

The pilot makes one attempt, accepts no provider or tool selection and never changes the default
network-silent runtime. See
[ADR-0036](adr/0036-fixed-synthetic-live-composition-pilot.md).

## Phase 4c components

- `application/execute_tool_action.py`: exact schema/digest validation, action binding, atomic claim
  and fail-closed reconciliation lifecycle.
- `adapters/action_approval.py`: domain-separated `ra2` HMAC verification and replay ledger.
- `adapters/evidence_sqlite.py`: metadata-only action records and atomic `DISPATCHED` claim.
- `adapters/mock_tool_execution.py`: local, network-silent execution proof.
- `entrypoints/api.py`: two-step action submission and metadata-only inspection endpoints.

```text
stored proposal + resubmitted arguments -> schema/digest validation -> action digest
    -> WAITING_APPROVAL -> inspect ra2 -> PREPARED -> claim DISPATCHED
    -> consume once -> mock tool boundary -> EXECUTED
                              \-> ambiguous failure -> RECONCILIATION_REQUIRED
```

Raw arguments and idempotency keys exist only in the request and ephemeral action plan. Phase 4c
does not return tool output to a model or enable a live enterprise connector. See
[ADR-0009](adr/0009-action-digest-bound-tool-execution.md).

## Phase 4d components

- `adapters/yaml_files.py`: closed output schemas with classifications and handling rules.
- `application/execute_tool_action.py`: untrusted result validation, minimization and digesting.
- `adapters/evidence_sqlite.py`: result metadata and schema migration without result content.
- `entrypoints/api.py`: immediate-only `safe_result` and terminal result-rejection mapping.

```text
tool adapter output (untrusted) -> validate closed schema -> classify each field
    -> RETURN closed enum | MASK value | DROP field -> immediate safe_result
    -> persist digests/classifications/field names only
    \-> invalid/disallowed output -> RESULT_REJECTED (terminal, no retry)
```

Raw and safe values exist only during the successful request. Replays and action inspection cannot
recover them. No result is supplied to a model in this phase. See
[ADR-0010](adr/0010-trusted-tool-result-handling.md).

## Phase 5a components

- `application/get_operator_timeline.py`: exact-ID metadata correlation, integrity validation,
  stable attention codes and bounded stage composition.
- `adapters/evidence_sqlite.py`: deterministic action listing scoped to one enforcement.
- `entrypoints/api.py`: read-only operator timeline endpoint.

```text
exact enforcement id -> enforcement + immutable evidence + bounded actions
    -> integrity checks -> ordered current-state stages -> attention codes
```

This is a current-state control timeline, not an append-only transition ledger. It neither lists
activity globally nor mutates approval, execution or reconciliation state. See
[ADR-0011](adr/0011-metadata-only-operator-timeline.md).

## Phase 5b components

- `adapters/evidence_sqlite.py`: shared lifecycle-event table, transactional triggers, migration
  baselines, append-only guards and bounded event query.
- `application/get_operator_timeline.py`: event integrity validation, completeness and truncation.
- `entrypoints/api.py`: metadata-only lifecycle history within the exact-ID operator response.

```text
state INSERT/UPDATE -> SQLite trigger in the same transaction -> append lifecycle event
legacy record at upgrade -> MIGRATION_BASELINE -> history_complete=false
```

The local ledger prevents ordinary row updates/deletes but is not cryptographically tamper-evident
against a database owner. See
[ADR-0012](adr/0012-append-only-local-lifecycle-history.md).

## Phase 5c components

- `domain/models.py`: sanitized approval summary and expanded operator control context.
- `application/get_operator_timeline.py`: evidence/enforcement and approval-binding validation.
- `entrypoints/api.py`: allowlisted decision, transformation and approval metadata.

```text
exact enforcement id -> validate linked metadata and approval bindings
    -> current state + lifecycle history + control context
```

The operator response deliberately omits actor identity and does not reconstruct provider source
or freshness history from the current registry. See
[ADR-0013](adr/0013-operator-control-context.md).

## Phase 5d components

- `application/evaluate_operation.py`: captures ordered capability snapshots and binds them to
  decision/event digests.
- `adapters/evidence_sqlite.py`: persists and strictly parses snapshot JSON with legacy migration.
- `entrypoints/api.py`: exposes historical source/freshness context and completeness.

```text
resolved capability -> immutable metadata snapshot -> canonical decision digest -> evidence
legacy evidence without snapshot -> provider_context_complete=false
```

Historical snapshots are not refreshed from the current registry and do not assert current
provider behavior or compliance. See
[ADR-0014](adr/0014-immutable-provider-provenance-snapshots.md).

## Phase 5e components

- `entrypoints/operator_dashboard.py`: escaped, no-script HTML rendering and local styling.
- `entrypoints/api.py`: exact-ID dashboard route and defensive browser response headers.
- `application/get_operator_timeline.py`: unchanged source of correlation, integrity and attention
  semantics for both JSON and HTML presentations.

```text
known enforcement id -> bounded timeline use case -> escaped server-rendered HTML
unknown or inconsistent metadata -> generic 404/503 HTML state
```

The dashboard does not introduce listing, search or administrative mutations. See
[ADR-0015](adr/0015-exact-id-server-rendered-operator-dashboard.md).

## Phase 6a components

- `adapters/signed_packs.py`: strict manifest/trust-store parsing, path and digest validation, and
  Ed25519 verification.
- `entrypoints/api.py`: verifies the packaged release before constructing policy/provider/tool
  repositories and exposes its metadata through `/v1/providers`.
- `scripts/sign_control_pack.py`: offline release helper that refreshes digests, signs with an
  external private key and verifies the result before atomic replacement.

```text
deployment trust store + signed manifest + local YAML files
    -> manifest schema/key/Ed25519 verification -> bounded path/digest verification
    -> parse exact authenticated bytes
    -> runtime composition
```

The trust store is an external trust decision. Signatures establish release authenticity and
integrity, not regulatory correctness or current provider behavior. See
[ADR-0016](adr/0016-signed-policy-provider-packs.md).

## Phase 6b components

- `domain/models.py`: release, semantic change, impact and report value objects.
- `application/analyze_control_pack_diff.py`: framework-free deterministic comparison and
  capability-to-policy correlation.
- `scripts/diff_control_packs.py`: offline composition of verification, strict YAML parsing and
  metadata-only JSON output.

```text
base manifest ----\
                   -> same trust store -> verified exact bytes -> strict domain records
candidate manifest /                                         -> static semantic impact report
```

The application use case never reads files, verifies signatures or executes policies. The CLI
performs those boundary translations and can fail CI when static analysis finds potential decision
impact. Absence of reported decision impact is not proof of behavioral equivalence. See
[ADR-0017](adr/0017-verified-control-pack-impact-analysis.md).

## Phase 6c components

- `adapters/scenario_files.py`: strict, bounded parsing of metadata-only replay suites with an exact
  file digest and fixed timezone-aware evaluation timestamp.
- `application/replay_control_pack_scenarios.py`: deterministic reuse of the existing evaluator
  with release-local repositories, pass-through classifications and ephemeral evidence.
- `scripts/replay_control_pack_scenarios.py`: same-trust release verification, replay orchestration,
  stable JSON output and optional CI failure on observed decision impact.

```text
verified base release -----\
                            -> fixed metadata scenarios -> existing deterministic evaluator
verified candidate release /                              -> observed impact report
```

Scenario files contain field identifiers and classification labels but no values or tools. The
suite is outside the signed pack and is therefore identified by its exact SHA-256 digest. Replay
executes no transformation, provider, approval or tool boundary, and a finite unchanged corpus is
not evidence of exhaustive equivalence. See
[ADR-0018](adr/0018-verified-control-pack-scenario-replay.md).

## Phase 6d components

- `adapters/provider_review_files.py`: bounded exact-byte loading for one provider draft and one
  strict digest-bound source-review record.
- `application/review_provider_capability_update.py`: framework-free lineage, coverage, date,
  version and conclusion gate.
- `scripts/review_provider_capability_update.py`: verifies the approved pack, composes the review
  use case and emits deterministic metadata-only JSON before any separate signing step.

```text
verified approved pack + candidate provider draft + digest-bound human source review
    -> lineage/binding/coverage/version/date/conclusion checks
    -> REVIEW_GATE_PASSED | REVIEW_GATE_BLOCKED
    -> separate organization-owned signing decision
```

The gate never retrieves or stores source content. One URL may have distinct conclusions for
disjoint capability scopes. `CORROBORATED` means the reviewer concluded that the source is
consistent with the recorded state, including an explicit `unknown`; it does not prove provider
behavior. Passing grants no key access or promotion authority. See
[ADR-0019](adr/0019-provider-capability-pre-signing-review-gate.md).

## Phase 6e components

- `adapters/policy_review_files.py`: bounded exact-byte loading for one policy draft and one strict
  digest-bound regulatory-review record.
- `application/review_policy_update.py`: framework-free policy/rule lineage, mapping coverage,
  version and conclusion gate.
- `scripts/review_policy_update.py`: verifies the approved pack, composes the review use case and
  emits deterministic metadata-only JSON before any separate signing step.

```text
verified approved pack + candidate policy draft + digest-bound human mapping review
    -> lineage/binding/coverage/version/conclusion checks
    -> REGULATORY_REVIEW_PASSED | REGULATORY_REVIEW_BLOCKED
    -> separate organization-owned signing decision
```

The gate compares rules by stable id and binds each review to the exact control-objective and
regulatory-support mappings. A rule with regulatory references requires `APPROVED`; an enterprise
rule without them requires `NOT_APPLICABLE`, preventing internal authority policy from being
presented as a regulatory mandate. It never retrieves or interprets source text, authenticates a
reviewer, signs a pack or authorizes promotion. See
[ADR-0020](adr/0020-digest-bound-policy-regulatory-review-gate.md).

## Phase 6f components

- `application/assemble_release_evidence.py`: framework-free release-pair, candidate-file and review
  binding plus completeness findings.
- `scripts/assemble_release_evidence.py`: same-trust verification, exact-byte composition of the
  existing diff/replay/review use cases, canonical JSON and bundle digest.

```text
verified base + verified candidate + exact scenario suite + human review records
    -> recompute static diff and replay
    -> re-run reviews against authenticated candidate file bytes
    -> EVIDENCE_COMPLETE | EVIDENCE_INCOMPLETE
    -> separate organization-owned impact acceptance and promotion decision
```

The composer does not trust previously exported reports and does not treat potential or observed
change as an automatic rejection. Completeness means all supported modified entities have passing,
exact-byte review evidence. Whole policy/provider additions and removals remain incomplete because
their onboarding/removal governance is not yet defined. See
[ADR-0021](adr/0021-verified-release-evidence-bundle.md).

## Phase 6g components

- `adapters/promotion_attestations.py`: strict canonical bundle parsing, role-bound public-key trust
  policy and Ed25519 attestation verification.
- `application/authorize_release_promotion.py`: framework-free exact binding, UTC validity,
  rejection, required-role and distinct-key quorum decisions.
- `scripts/authorize_release_promotion.py`: offline orchestration and deterministic metadata-only
  authorization output.

```text
complete evidence bundle + promotion policy + role-bound public keys + signed attestations
    -> canonical digest/signature/binding/time/quorum checks
    -> PROMOTION_AUTHORIZED | PROMOTION_BLOCKED
    -> separate organization-owned promotion/distribution/deployment system
```

Private promotion keys never enter this workflow. An authorized report proves that the configured
trusted keys approved one exact evidence bundle under one explicit policy at one fixed time. It is
not a control-pack signature, deployment instruction, external timestamp or compliance/safety
claim. See [ADR-0022](adr/0022-signed-promotion-attestations-and-quorum.md).

## Phase 6h components

- `adapters/release_review_attestations.py`: strict role/artifact/change-scoped public-key trust and
  Ed25519 verification for exact review attestations.
- `application/assemble_release_evidence.py`: exact base/candidate composition, change-type and
  added/modified/removed content binding for authenticated reviews.
- `scripts/assemble_release_evidence.py`: re-runs update reviews, joins their exact digests to signed
  attestations, accepts lifecycle attestations and emits bundle schema version 2.

```text
verified base/candidate + detailed update reviews + signed review/lifecycle attestations
    -> key authority + signature + pack/content/change/review binding
    -> authenticated release-evidence bundle v2
    -> separate signed promotion quorum
```

Modified policies and provider targets cannot bypass the semantic gates from Phases 6d/6e. Added
entities bind candidate bytes; removed entities bind the approved-base bytes being retired. The
review key authenticates a bounded role assertion but grants no pack-signing, promotion or
deployment authority. See [ADR-0023](adr/0023-signed-review-and-lifecycle-governance.md).

## Diagrams

Add C4 context/container diagrams and sequence diagrams for critical flows.
