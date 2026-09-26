# Implementation plan

## Phase 6e — policy regulatory review gate

### Goal

Require explicit, bounded human review of control-objective and regulatory-support mappings for an
existing policy-set draft before it can enter the separate control-pack signing workflow.

### Work

1. Verify the approved base pack and load its exact authenticated policy sets.
2. Parse one strict candidate policy draft and bind its exact bytes with SHA-256.
3. Load a strict review record bound to the base pack digest, candidate digest, policy-set id,
   review date and non-personal reviewer role.
4. Compare rules by stable id and require exact review coverage for every addition, modification or
   removal plus every changed policy-set metadata field.
5. Require version advances and control-objective mappings; separate approved regulatory mappings
   from explicitly non-regulatory enterprise rules and fail closed on rejected, revision-needed or
   missing review.
6. Emit deterministic metadata-only JSON, add a synthetic-safe example, unit/contract tests and
   ADR-0020.

### Decisions and assumptions

- Source retrieval, legal interpretation, applicability and reviewer authorization remain human
  and organization-owned activities; the workflow performs no network access and stores no source
  text or reviewer identity.
- Phase 6e handles updates to one policy set already authenticated in the approved base. New-policy
  onboarding and a complete control-objective catalog remain separate governance decisions.
- Rule ids are stable lineage identifiers. Added and modified rules bind candidate mappings;
  removed rules bind their authenticated base mappings.
- Rules with regulatory-support references require `APPROVED`; rules without them require
  `NOT_APPLICABLE` so enterprise authority policy is not misrepresented as regulation.
- Passing means the review record is internally consistent enough to proceed to separate signing;
  it does not prove legal correctness, compliance, runtime safety or release authorization.

## Phase 6d — provider capability review gate

### Goal

Require a bounded, source-by-source human review record for a provider capability draft before it
can enter the existing control-pack signing workflow.

### Work

1. Verify the approved base pack and load its exact authenticated provider records.
2. Parse one strict candidate capability draft and bind its exact bytes with SHA-256.
3. Load a strict review record bound to the base pack digest, candidate digest, provider target,
   review date and non-personal reviewer role.
4. Require every capability in the record lineage and every candidate source to be covered; block
   contradicted, inconclusive, missing, stale-date or unversioned updates.
5. Emit deterministic metadata-only JSON and exit code 2 for a valid but blocked review gate.
6. Add a synthetic-safe freshness-review example, unit/contract tests and ADR-0019.

### Decisions and assumptions

- Source retrieval and interpretation remain human activities; the workflow performs no scraping or
  network access and stores no quotes or source content.
- Phase 6d handles updates to an existing provider target. New-target onboarding remains a separate
  governance decision.
- Registry and record versions are opaque organization identifiers, so the gate requires change but
  does not infer ordering.
- A record-level `verified_at` date asserts review of the whole record; every retained, changed or
  removed capability must therefore be covered by a source check.
- The review record is digest-bound but not signed and does not authenticate an individual reviewer
  or grant signing/promotion authority.
- Passing the gate means the review evidence is internally consistent enough to proceed to the
  separate signing boundary; it does not prove provider behavior, compliance or legal correctness.

## Phase 6c — verified control-pack scenario replay

### Goal

Replay a bounded, metadata-only scenario corpus against an approved base and a candidate control
pack, then report observed decision and evidence changes alongside the Phase 6b static analysis.

### Work

1. Verify both releases through one Phase 6a trust store and require the same pack id.
2. Load a strict scenario suite that contains only normalized metadata, classifications and a fixed
   evaluation timestamp; reject raw values and tool requests.
3. Resolve each scenario's logical policy-set id independently in both releases and run the existing
   deterministic evaluator with ephemeral evidence storage and no external execution.
4. Compare decisions and exact obligation digests as decision impact; compare matched controls,
   capability ids, reason codes and release-version metadata as evidence impact.
5. Emit stable JSON with the suite digest, release identities, bounded per-scenario outcomes and an
   optional CI failure exit code for observed decision impact.
6. Add unit/contract tests, a synthetic-safe example suite and ADR-0018.

### Decisions and assumptions

- Scenario replay complements conservative static analysis; a finite corpus cannot prove semantic
  equivalence or regulatory correctness.
- The suite is a separately governed local input, not part of either signed pack, so its exact
  SHA-256 digest is included in the report.
- The fixed timezone-aware evaluation timestamp makes freshness decisions reproducible.
- Scenarios carry fields and classification labels but never raw values. The evaluator receives an
  empty ephemeral value and a pass-through classifier so no content is persisted or reported.
- Tool scenarios are rejected until trusted tool catalogs participate in the same release and
  comparison boundary.
- Replay performs no network access, enforcement, approval, provider execution or promotion.

## Phase 6b — verified control-pack impact analysis

### Goal

Compare two authenticated policy/provider releases offline and produce a deterministic,
metadata-only report of potential decision, evidence and governance impact before promotion.

### Work

1. Load base and candidate manifests through the Phase 6a verifier using one explicit trust store.
2. Compare policy sets/rules and provider targets/capabilities by stable identities.
3. Classify changed fields conservatively as `DECISION`, `EVIDENCE` or `GOVERNANCE` impact.
4. Correlate changed capabilities with policy rules that require the capability and can match the
   affected provider target.
5. Emit stable JSON with pack identities, summaries, version-reuse/key-change signals and bounded
   metadata-only changes.
6. Add an optional CI failure exit code for potential decision impact, tests and ADR-0017.

### Decisions and assumptions

- Both releases must share a pack id and pass the same trust policy before semantic parsing.
- The report is conservative static analysis, not exhaustive evaluation-context simulation.
- Added or removed policies, rules, provider targets and capabilities are decision-impacting.
- Provider state, conditions and freshness can affect decisions; provenance/version changes affect
  evidence; notes and regulatory-support mappings are governance metadata.
- The workflow performs no network access, source ingestion, signing, promotion or runtime mutation.
- Pack-version ordering is organization-defined; reuse of one version with a different payload is
  signaled but not automatically interpreted as malicious.

## Phase 6a — signed policy and provider packs

### Goal

Fail closed unless the local policy/provider release matches an organization-trusted Ed25519
signature and every declared file digest.

### Work

1. Define a strict manifest containing a stable pack identity, version, policy/provider file list,
   SHA-256 digests and one signing-key identifier.
2. Verify normalized local paths, bounded file sizes, content digests and the Ed25519
   signature before parsing any runtime policy or provider record.
3. Keep the trust store deployment-controlled and package only public keys; never place a private
   signing key in the repository or service runtime.
4. Expose verified pack identity through the provider metadata endpoint and add an offline signing
   helper that validates the result before replacing a manifest.
5. Add tamper, unknown-key, traversal and packaged-runtime tests plus ADR-0016.

### Decisions and assumptions

- The signature authenticates an approved release; it does not prove source freshness, provider
  behavior, legal correctness or compliance.
- Ed25519 uses the maintained `cryptography` dependency; signatures cover deterministic canonical
  JSON derived from the strict YAML manifest.
- Pack files remain YAML and retain their existing schema validation after signature verification.
- Key generation, custody, authorization and revocation belong to an external organization-owned
  release process. The repository contains a demo public trust anchor only.
- Tool catalogs remain outside this phase and retain their existing strict local validation.

## Phase 5e — exact-ID operator dashboard

### Goal

Provide a visual, read-only view of the stable operator timeline without introducing global
metadata discovery or a client-side execution surface.

### Work

1. Add a server-rendered dashboard that accepts one exact enforcement identifier.
2. Reuse `GetOperatorTimeline` for all correlation, integrity and attention semantics.
3. Escape every dynamic value, avoid JavaScript and serve only same-origin styling.
4. Apply no-store caching, restrictive CSP, frame denial, referrer suppression and permissions
   policy headers.
5. Add renderer and end-to-end privacy/security tests plus ADR-0015.

### Decisions and assumptions

- The dashboard is presentation over the existing timeline contract, not a second read model.
- It does not list, search or discover records; the operator must already know the exact ID.
- Existing deployment access controls remain responsible for protecting the operator surface.
- The page is read-only and cannot approve, retry or reconcile work.

## Phase 5d — immutable provider provenance snapshots

### Goal

Bind source and freshness metadata for each resolved provider capability to the decision evidence so
historical operator views never depend on mutable current registry configuration.

### Work

1. Add a metadata-only provider capability snapshot containing target, fact identity/state,
   conditions, record/registry versions, verification date and official source URLs.
2. Include ordered snapshots in canonical decision output and event digests.
3. Persist snapshots in SQLite with strict JSON parsing and migrate legacy rows to an empty list.
4. Expose snapshots through evidence and operator APIs with an explicit completeness flag.
5. Add evaluation, persistence, migration, boundary and end-to-end privacy tests plus ADR-0014.

### Decisions and assumptions

- Snapshot metadata is part of new decision identity, so output/evaluation/evidence IDs change when
  the captured provider facts or sources change.
- Legacy evidence remains valid but reports incomplete provider context; provenance is not
  reconstructed.
- Sources are reviewed public HTTPS documentation URLs from the versioned provider registry.
- A historical snapshot proves what metadata informed a decision, not current provider behavior or
  regulatory compliance.

## Phase 5c — operator control context

### Goal

Expose the allowlisted control metadata needed to explain one exact enforcement without adding
global discovery, payload recovery or administrative mutations.

### Work

1. Extend the operator timeline with matched policies, control objectives, capability identifiers,
   reason codes, authorized tools and provider target.
2. Return metadata-only transformation receipts and the existing previous-event digest.
3. Expose a sanitized enforcement approval summary without actor identity and only an
   `approval_recorded` signal for each stage.
4. Validate evidence/enforcement input binding and approval receipt bindings before composing the
   response.
5. Add unit and end-to-end privacy tests plus ADR-0013 and operator documentation.

### Decisions and assumptions

- Only metadata already persisted by earlier phases is exposed; there is no new storage schema.
- Provider source/freshness history is not reconstructed from the current registry because the
  evidence record does not contain an immutable source snapshot.
- The endpoint remains exact-ID, bounded and read-only.
- Approval actor identity, assertions, payloads, arguments and results remain excluded.

## Phase 5b — append-only lifecycle history

### Goal

Record bounded, metadata-only lifecycle transitions atomically with SQLite state changes so the
operator timeline can distinguish real history from its current-state snapshot.

### Work

1. Add immutable lifecycle-event/source types and a read-only event repository port.
2. Create an append-only SQLite event table with triggers for evidence insertion and
   enforcement/tool-action status transitions.
3. Protect event rows from update/delete and insert explicit migration baselines for legacy records
   that predate event tracking.
4. Extend the operator query with at most 256 ordered events, explicit truncation and a
   `history_complete` indicator.
5. Persist only sequence, UTC timestamp, source, entity kind/id, enforcement id and status.
6. Add contract, application and end-to-end tests plus ADR-0012 and operator documentation.

### Decisions and assumptions

- Trigger writes share the same SQLite transaction as the state change they describe.
- `MIGRATION_BASELINE` is an observation at upgrade time, not reconstructed history.
- Append-only is enforced by the local schema; it is not a signed or externally anchored ledger.
- The phase remains read-only at the API and does not add global discovery, approval, retry or
  reconciliation mutations.

## Phase 5a — metadata-only operator timeline

### Goal

Provide one read-only operational view that correlates an exact enforcement, its decision evidence
and tool actions without adding payload retention, global discovery or administrative mutations.

### Work

1. Add immutable operator-timeline and attention-code types plus a focused application query.
2. Extend the tool-action repository with a deterministic, enforcement-scoped listing operation.
3. Build ordered control stages from existing evaluation, enforcement and action records; do not
   invent unavailable transition timestamps or claim append-only history.
4. Derive stable attention codes for pending approval, execution failure, ambiguous reconciliation,
   approval failure and rejected tool results.
5. Expose `GET /v1/operator/enforcements/{enforcement_id}/timeline` using an exact identifier only.
6. Keep the response metadata-only and add unit, SQLite contract and end-to-end privacy tests.

### Decisions and assumptions

- This is a current-state control timeline, not a complete historical event ledger.
- The endpoint does not list or search tenants, correlations or recent activity.
- Existing deployment access controls must protect the operator surface; product authentication and
  a visual dashboard remain out of scope.
- The phase does not reconcile, retry, approve or otherwise mutate enforcement/action state.

## Phase 4d — trusted tool-result handling

### Goal

Treat every tool result as untrusted, validate it against an action-bound organization schema and
expose only an ephemeral minimized view without expanding persisted evidence into content storage.

### Work

1. Add closed output schemas with per-field classification and `RETURN`, `MASK` or `DROP` handling
   to the trusted catalog; bind their canonical digests into tool definitions and actions.
2. Validate complete output shape, types, constraints and size after execution. Require returned
   text to be a closed enum, prevent direct personal/financial exposure and always drop secrets.
3. Compute control-plane-owned raw/safe result digests and persist only digests, classifications,
   exposed field names and execution identity.
4. Return the minimized result only in the immediate successful action response. Never persist or
   recover raw or safe content through replay or the action inspection endpoint.
5. Record invalid output as terminal `RESULT_REJECTED`, emit bounded lifecycle metadata and never
   retry the already completed side effect automatically.
6. Add boundary, application, persistence, migration and end-to-end privacy tests; document
   ADR-0010.

### Decisions and assumptions

- Tool output, including adapter output, is untrusted external input.
- Masking is presentation minimization, not anonymization; masked content is not retained.
- The phase does not continue a model turn or enable a live enterprise connector.
- `RESULT_REJECTED` describes rejected content after execution, not proof that the downstream side
  effect failed.

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
