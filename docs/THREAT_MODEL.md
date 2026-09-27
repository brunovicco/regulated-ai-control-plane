# Threat model

## Assets

- policy integrity;
- provider capability integrity/freshness;
- approval decisions;
- evidence integrity;
- customer personal/sensitive data;
- gateway/provider credentials;
- tool/action authority;
- tenant/customer configuration;
- audit correlation metadata.

## Trust boundaries

1. caller -> enforcement API;
2. enforcement service -> local transform/tokenization;
3. enforcement service -> evidence persistence;
4. enforcement service -> governed gateway/provider execution;
5. external approval system -> enforcement service approval verifier;
6. control-plane policy/registry release -> runtime enforcement plane.
7. enforcement service -> organization tool system through the tool execution port.

## Threats and required mitigations

### Policy bypass

Threat:
caller omits classification/purpose or selects a weaker policy/provider path.

Mitigations:
- server-side normalization/detection for supported identifiers;
- mandatory jurisdiction/sector/purpose fields where policy needs them;
- no caller control over arbitrary policy code;
- fail closed for unresolved mandatory context.

### Prompt injection changes authority

Threat:
model/prompt instructs system to ignore policy or invoke a prohibited tool.

Mitigations:
- policy and authority decisions happen outside model output;
- tools are permission-gated;
- model cannot mutate policy/provider registry;
- approval state is external and explicit.
- tool risk, description and schema come from a versioned organization catalog, never model output
  or caller claims;
- gateway tool calls are proposals only; Phase 4c requires exact argument validation and separate
  action-specific authority before its network-silent tool boundary;
- Phase 4d treats tool output as untrusted content and allows only schema-defined, minimized fields
  to leave the result boundary; no result is composed into a model turn.

### Model proposal gains excessive authority

Threat:
a valid decision approval or altered/replayed arguments execute a model-proposed external action.

Mitigations:
- decision (`ra1`) and action (`ra2`) assertions use separate schemas, prefixes and keys;
- action digest binds enforcement/call, current catalog definition/schema, exact argument digest,
  downstream workload and idempotency digest;
- resubmitted arguments must satisfy the closed schema and reproduce the stored proposal digest;
- each proposal has one immutable action binding and one atomic execution claim;
- approval is consumed before the tool port and ambiguous failures are never retried automatically;
- Phase 4c exposes only a network-silent mock tool adapter.

### Tool result injects instructions or exfiltrates data

Threat:
a compromised or drifting tool returns free-form instructions, unexpected fields, financial or
personal values, credentials, or oversized content that is persisted or supplied to a model.

Mitigations:
- output schemas are closed, organization-owned and bound into tool/action digests;
- every field has an explicit classification and `RETURN`, `MASK` or `DROP` rule;
- directly returned strings are limited to trusted closed enums; personal/financial values cannot
  be returned directly and authentication secrets must be dropped;
- raw output is validated and minimized in memory, with only digests/classifications/field names
  persisted;
- invalid output becomes terminal `RESULT_REJECTED` and is not automatically retried;
- safe output is immediate-response-only and is not supplied to a model in Phase 4d.

### Caller downgrades tool risk

Threat:
caller labels a state-changing operation as read-only to avoid approval policy.

Mitigations:
- callers request tools by name and do not define authority;
- an optional risk claim must exactly match the trusted catalog;
- unknown, duplicate and mismatched tools fail closed before evidence or provider execution;
- catalog version, tool schema version and schema digest are bound to the deterministic decision.

### Provider downgrade/fallback

Threat:
retry/fallback selects a provider configuration with weaker controls.

Mitigations:
- fallback must be evaluated against the same mandatory requirements;
- no implicit provider substitution;
- capability registry version in decision/evidence.
- gateway mode binds one reviewed workload to one allowed RegulaAI target and expected provider;
- the gateway workload must constrain its authorized model group to compatible deployments;
- terminal provider mismatch fails closed and local retry/fallback is prohibited.

### Stale provider documentation

Threat:
product assumes an old retention/residency/network capability.

Mitigations:
- `verified_at`;
- source URLs;
- freshness policy;
- stale high-assurance fact becomes `unknown`;
- registry-change regression tests.

### Sensitive-data leakage through logs/traces/evidence

Mitigations:
- metadata allowlist;
- no raw request/response logging;
- stable reason codes;
- hashes over canonical normalized structures;
- test that sentinel secrets/PII never appear in outputs/log fixtures.

### Operator metadata enumeration

Threat:
an unauthenticated or cross-tenant caller lists operational activity or uses the operator view to
recover content and sensitive workflow state.

Mitigations:
- Phase 5a supports exact, bounded enforcement-ID lookup only; there is no list, search or filter;
- the response uses the same metadata allowlist as evidence/enforcement/action records and never
  includes payloads, arguments, assertions or tool results;
- approval context omits actor identity and action stages expose only whether approval was recorded;
- evidence/enforcement input digests and approval receipt bindings are validated before response;
- historical provider provenance comes from digest-bound evidence snapshots, never a join against
  mutable current registry configuration;
- action correlation is bounded and explicitly reports truncation;
- the HTML dashboard escapes every dynamic value, executes no JavaScript, loads only same-origin
  CSS and applies no-store, CSP, frame-denial, referrer and permissions-policy headers;
- the endpoint is read-only and cannot approve, retry or reconcile;
- deployments must restrict the JSON and HTML operator routes at the existing access boundary until product
  authentication and tenant isolation are implemented.

### Lifecycle history is altered or overstated

Threat:
application code rewrites operational history, legacy current state is presented as reconstructed
history, or a local ledger is incorrectly claimed to be cryptographically immutable.

Mitigations:
- SQLite triggers append events in the same transaction as state changes;
- event-table update/delete triggers reject ordinary mutation;
- repeated identical states do not create duplicate events;
- legacy records receive explicit `MIGRATION_BASELINE` events and set `history_complete=false`;
- bounded responses signal event truncation;
- documentation explicitly limits the guarantee to local schema enforcement and makes no signed,
  externally anchored or privileged-owner tamper-resistance claim.

### Evidence tampering

Mitigations:
- immutable IDs;
- event digests;
- optional previous-digest chain in MVP;
- later signed/append-only storage;
- policy/provider versions captured.
- provider source/freshness snapshots are bound into new decision and event digests;
- malformed, duplicate or registry-mismatched persisted snapshots fail closed.

### Malicious policy/provider YAML

Threat:
untrusted content causes arbitrary code execution or schema confusion.

Mitigations:
- policy/provider files must be declared by a trusted signed manifest and match their SHA-256
  digests before YAML parsing;
- Ed25519 signatures are checked against an explicit local public-key trust store;
- absolute, traversing, missing, symlinked and oversized pack paths fail closed;
- safe parser;
- strict schema;
- no dynamic expression evaluation;
- unknown fields/version handling;
- no YAML object construction features.

Residual risks:
- a compromised authorized signing key or malicious trust-store change can authorize a harmful
  release;
- signature validity does not establish legal correctness, source freshness, provider behavior or
  regulatory compliance;
- private-key custody and trust-store distribution remain external operational controls.

### Inactive verification key retains authority

Threat:
an expired, retired, revoked or not-yet-valid public key remains present in a trust store and a
cryptographically valid signature continues to authorize a release, review or promotion vote.

Mitigations:
- release, reviewer and promotion trust stores use strict schema version 2;
- every key declares an explicit state, UTC activation instant and optional UTC expiry;
- only `ACTIVE` keys inside the half-open validity interval are accepted;
- pack verification evaluates the selected key at an explicit instant, using UTC now at runtime;
- review and promotion keys are evaluated at their signed attestation and issuance instants;
- malformed windows, missing lifecycle fields and legacy trust-store schemas fail closed;
- the rotation and emergency-revocation runbook separates public trust metadata from private keys.

Residual risks:
- trust-store compromise or stale distribution can restore or prolong authority;
- system-clock integrity affects runtime pack verification;
- historical verification after retirement depends on the integrity and availability of retained
  Phase 6k trust snapshots;
- the repository does not generate, store, rotate or destroy private keys.

### Public trust store is rolled back during distribution

Threat:
an attacker or stale deployment replaces a current public trust store with an older valid copy,
restoring a retired/revoked key or removing a not-yet-distributed replacement.

Mitigations:
- Phase 6m binds exact trust-store bytes to a stable id, authority kind and monotonic sequence and
  authenticates the checkpoint with a dedicated Ed25519 distribution key;
- every successor binds the exact prior checkpoint digest and must advance both sequence and UTC
  issue time while changing the trust-store bytes;
- verification requires a pinned distribution public key plus a caller-pinned digest, minimum
  accepted sequence or exact predecessor;
- schema/duplicate-key errors, symlinks, private-key markers, gaps, forks and stale floors fail closed;
- checkpoints can be retained with the content-addressed Phase 6k custody evidence.

Residual risks:
- an attacker who replaces the package, pinned public key and every trusted floor can still roll back;
- checkpoint issue time is asserted local metadata, not an external trusted timestamp;
- automated distribution, node acknowledgement and recovery remain deployment-owned.

### Trust-store rollout is declared complete while required consumers remain stale

Threat:
an operator marks a signed trust-store checkpoint as deployed even though a required verifier did
not accept it, or reuses, forges or redirects another consumer's receipt to satisfy coverage.

Mitigations:
- Phase 6n binds every acknowledgement to the exact checkpoint digest, rollout-policy digest,
  store id/kind and sequence;
- acknowledgement signatures use a separate lifecycle-aware Ed25519 trust store whose keys are
  explicitly authorized for bounded target ids;
- required-target coverage and a configured minimum acknowledgement quorum must both pass;
- duplicate receipt ids, keys or targets, unknown targets, future acceptance times and stale or
  mismatched checkpoint metadata fail closed;
- reports retain only bounded ids, UTC metadata and cryptographic digests.

Residual risks:
- a signed acknowledgement proves acceptance by the authorized target identity, not that every
  running process loaded the trust store or continuously enforced it;
- compromised target signing keys and incorrect target assignments can create false acceptance;
- delivery, target health, external trusted timestamping and recovery remain deployment-owned.

### Runtime target reports stale or false loaded trust state

Threat:
a target replays an old observation, reports a different trust-store digest as current or another
target substitutes its signed state so stale runtime authority is treated as active.

Mitigations:
- Phase 6o binds every signed assertion to the exact checkpoint, runtime-policy digest, store
  identity/kind, sequence, target and loaded trust-store digest;
- lifecycle-aware Ed25519 keys are explicitly authorized for bounded target ids;
- observations before the checkpoint or after the evaluation time fail closed;
- a bounded maximum age, required-target coverage and distinct-target quorum block stale or
  incomplete evidence;
- duplicate attestation, key and target identities cannot increase coverage.

Residual risks:
- a compromised target or authorized signing key can falsely assert loaded state;
- target and evaluator clock integrity is deployment-owned;
- the verifier authenticates supplied assertions but does not independently probe processes or
  prove continuous enforcement.

### Local artifact time is mistaken for an independent trusted timestamp

Threat:
an operator relies on mutable filesystem/archive time, reuses a receipt for different bytes or lets
an untrusted package establish its own freshness floor.

Mitigations:
- Phase 6p binds an allowlisted artifact kind and exact SHA-256 bytes to a signed external-authority
  UTC assertion;
- authority identity and lifecycle-aware Ed25519 key authorization are explicit;
- expected subject kind, evaluation time and optional minimum issue time are caller-selected;
- changed bytes, wrong authority/kind, inactive keys, invalid signatures and future or below-floor
  receipts fail closed;
- reports emit ids, times and digests rather than artifact content or signature bytes.

Residual risks:
- a compromised authority key or dishonest authority can assert false time;
- the custom provider-neutral format is not RFC 3161 and has no implicit interoperability;
- receipt acquisition, authority availability, immutable retention and transparency remain external.

### An RFC 3161 token is accepted without exact request or PKIX binding

Threat:
an operator accepts a token for different bytes, permits a substituted policy or nonce, validates a
certificate at the wrong time, or assumes offline verification checked current revocation state.

Mitigations:
- Phase 6q requires the preserved original request and matches its imprint, nonce and policy to the
  response and exact artifact bytes;
- only SHA-256, SHA-384 and SHA-512 plus caller-allowlisted policy OIDs are accepted;
- OpenSSL verifies CMS signature, timestamping EKU and the deployment-supplied PKIX chain at the
  asserted generation time with a bounded timeout;
- future and below-floor timestamps fail closed and reports contain only metadata and digests.

Residual risks:
- offline verification performs no CRL/OCSP retrieval and depends on a current, correctly scoped CA
  bundle and preserved revocation evidence where policy requires it;
- a compromised or dishonest timestamp authority can assert false time;
- acquisition availability, immutable retention and long-term archival renewal remain external.

### Release evidence is lost, altered or archived with secrets

Threat:
an operator retains an incomplete release record, silently alters one artifact, loses the trust
snapshot needed for historical verification or accidentally archives a private key with evidence.

Mitigations:
- custody accepts only bounded allowlisted JSON/YAML artifact kinds with safe basenames;
- one complete evidence bundle, one authorized promotion report and at least one public trust
  snapshot are mandatory;
- canonical bundle and authorization digests are recomputed and must bind each other;
- each artifact is stored under its SHA-256 digest and listed with exact size in a canonical
  manifest whose own digest is recomputed;
- creation is fail-if-present and atomic, avoiding partial or accidental overwrite;
- symlinks, untracked files and common PEM private-key markers fail closed;
- verification is local, recursive and network-silent.

Residual risks:
- content addressing does not provide immutable storage, trusted time, access control, encryption,
  replication, backup or proof that an artifact was complete in the real world;
- non-PEM secrets or sensitive metadata can still be mislabeled as an allowed artifact;
- local archive and manifest can be replaced together unless anchored externally;
- retention duration, approved deletion and off-site recovery remain organization-owned.

### Control-pack change bypasses review

Threat:
a signed candidate changes policy outcomes or provider assumptions without reviewers recognizing
the affected runtime surface, or a comparison is performed against a separately trusted lineage.

Mitigations:
- base and candidate must both verify against one explicitly selected trust store and share a pack
  identifier;
- changes are compared by stable policy/provider identities with deterministic ordering;
- state, conditions, freshness, rule match/decision/obligations and additions/removals are marked
  as potential decision impact;
- changed capabilities list policy rules that require the same key and can match the target;
- same-version/different-payload releases and signing-key changes are explicit report signals;
- CI can fail with exit code 2 when potential decision impact exists;
- output is metadata-only and never includes signing secrets or arbitrary YAML values.

Residual risks:
- static correlation does not enumerate all possible evaluation contexts or prove equivalence;
- compromised trusted keys or trust-store changes remain outside the comparison guarantee;
- human review, approval quorum and release promotion are not automated in Phase 6b.

### Scenario replay leaks data or overstates release safety

Threat:
a regression corpus includes raw customer content, evaluates freshness at an implicit moving time,
or an unchanged finite replay is presented as proof that a candidate is safe or compliant.

Mitigations:
- the strict suite schema has no value, prompt, tool arguments, output or free-form content field;
- only bounded field identifiers, classification labels, normalized context, boolean organization
  assertions and schema-v2 tool names/claimed risk classes are accepted;
- a mandatory timezone-aware timestamp fixes freshness evaluation across both releases;
- both packs pass the same trust store and share one pack id before replay;
- the exact suite bytes are bound to the report with SHA-256;
- results expose only allowlisted metadata and digests, and evidence storage is ephemeral;
- output and documentation state that replay is finite review evidence, not equivalence,
  certification or promotion authority.

Residual risks:
- an incomplete or biased corpus can miss material behavior changes;
- field names, labels and control identifiers remain organization metadata requiring retention and
  access controls;
- the suite itself is separately governed and is not authenticated by the control-pack signature;
- scenario replay covers catalog authorization metadata but does not execute tools or prove their
  downstream behavior.

### Tool catalog bypasses the signed release

Threat:
the runtime, diff or replay loads a separately mutable catalog after verifying policy/provider
files, allowing tool authority or schemas to diverge from reviewed release evidence.

Mitigations:
- every signed pack contains exactly one catalog with its path and SHA-256 digest in the canonical
  Ed25519 payload;
- parsers receive the exact verified bytes and never reopen the catalog path;
- runtime startup rejects an independent catalog override;
- semantic diff marks definition lifecycle, risk-class and schema changes as decision impact;
- scenario replay resolves tool names independently against both catalogs without arguments or
  execution;
- changed catalogs require an authenticated whole-file review bound to the exact signed bytes.

Residual risks:
- signature validity and review approval do not prove tool implementation behavior or ownership;
- a compromised release/reviewer key can approve malicious definitions;
- whole-catalog review is less granular than a future per-definition review workflow;
- action execution still depends on the separate Phase 4c exact-argument authority boundary.

### Provider capability freshness is asserted without bounded source review

Threat:
a provider record advances `verified_at` or changes a capability without binding the draft to the
approved lineage, reviewing every record-wide claim, or surfacing contradictory source evidence.

Mitigations:
- the approved base pack must pass signature/digest verification;
- the review binds the approved pack payload digest and exact candidate record bytes;
- only an existing provider target may be updated in this phase;
- every capability retained, changed or removed and every candidate source must be covered;
- unchanged record/registry versions, date regression and review-date mismatch block the gate;
- contradicted, inconclusive or missing coverage produces stable findings and exit code 2;
- source content, quotes, credentials, personal reviewer identity and private keys are excluded;
- passing does not invoke the signer or grant promotion authority.

Residual risks:
- conclusions remain human assertions and are not cryptographically attributable to a reviewer;
- source URLs can change after review and no content snapshot or transparency log is retained;
- a compromised base signing key or trust store remains outside this gate's guarantee;
- new-target onboarding, reviewer quorum, signed attestations and key authorization remain external.

### Policy mapping enters signing without bounded regulatory review

Threat:
a policy draft changes executable rules, control-objective mappings or regulatory-support
references without binding a human conclusion to the authenticated base and exact candidate bytes;
or an enterprise authority rule is presented as a regulatory requirement.

Mitigations:
- the approved base pack must pass signature/digest verification;
- the review binds the approved pack payload digest, exact candidate policy bytes and policy-set id;
- only an existing policy-set lineage may be updated in this phase;
- every added, modified or removed rule must be reviewed with its exact change type and mappings;
- changed policy-set metadata, policy version and modified rule versions fail closed when coverage
  or version advancement is missing;
- regulatory mappings pass only with `APPROVED`, while rules without regulatory references pass
  only with `NOT_APPLICABLE`;
- legal text, quotes, personal reviewer identity, customer data, credentials and private keys are
  excluded;
- passing never invokes the signer or grants promotion authority.

Residual risks:
- conclusions remain unauthenticated human assertions and may be wrong or malicious;
- opaque support-reference ids do not prove source authenticity, applicability or current text;
- a compromised base signing key or trust store remains outside this gate's guarantee;
- new-policy onboarding, control-objective catalog approval, reviewer quorum and signed
  attestations remain external.

### Release evidence is mixed, omitted or mistaken for promotion authority

Threat:
a release pipeline combines diff, replay or review artifacts from different release pairs, omits a
changed entity, reviews bytes that differ from the signed candidate, or treats complete evidence as
authorization to promote.

Mitigations:
- base and candidate are verified through one explicit trust store;
- static analysis and scenario replay are recomputed for the same in-memory release identities;
- review records are re-run against exact candidate file bytes returned by signed-pack verification;
- candidate entity/file-digest composition must match exactly and duplicate evidence is rejected;
- every modified existing policy set and provider target requires one passing review;
- additions/removals remain explicit incomplete findings rather than being inferred as reviewed;
- output binds the canonical metadata payload with SHA-256 and states that completeness grants no
  signing, impact-acceptance, promotion or deployment authority.

Residual risks:
- the bundle digest is not a signature or external timestamp;
- Phase 6h reviewer keys and Phase 6g promotion keys remain only as trustworthy as their separate
  trust stores, custody and role assignments;
- an incomplete scenario suite can miss behavior changes even when evidence is complete;
- compromised signing keys/trust stores or malicious human assertions remain outside the guarantee;
- external systems may ignore exit codes or misrepresent the documented evidence scope.

### Release review identity is forged or lifecycle changes bypass review

Threat:
an attacker invents a reviewer role, swaps a detailed review result, signs a different entity,
removes an approved entity without review, introduces a new policy/provider outside the existing
update-only lineage or approves a modified tool catalog without detailed coverage.

Mitigations:
- review attestations are Ed25519-verified against a separate public-key trust store;
- each trusted key is constrained by reviewer role, policy/provider/tool artifact kind and
  added/modified/removed change type;
- signatures bind both pack payload digests, stable subject id, exact reviewed content digest,
  change type, conclusion and UTC attestation time;
- modified entities must bind the exact Phase 6d/6e/6l review id/digest and cannot sign an approval
  over a blocked detailed review;
- additions bind candidate bytes and removals bind approved-base bytes;
- duplicate attestation ids and duplicate entity targets fail closed; raw signatures are replaced
  by digests in bundle output.

Residual risks:
- compromised reviewer keys or trust-store role assignments can produce malicious approvals;
- lifecycle review signs a whole entity and does not independently prove every regulatory mapping
  or provider source is correct;
- Phase 6j enforces supplied revocation/retirement state and validity windows; hardware custody,
  trust-store distribution and external timestamping remain organization-owned;
- Phase 6g promotion signers must still accept the complete evidence and intended impact.

### Tool authority expands without per-definition review

Threat:
a signed catalog adds, removes or changes a tool while a broad whole-catalog approval conceals a
missing owner, an unreviewed implementation reference or a schema change that reuses its version.

Mitigations:
- the detailed record binds the authenticated base payload and exact candidate catalog digest;
- every semantic tool change requires one matching change type, non-personal owner role, bounded
  HTTPS implementation references and explicit conclusion;
- changed input or output schemas require a different tool schema version;
- missing, rejected or revision-requested coverage blocks the gate;
- a modified catalog's signed attestation must bind the passing detailed review id and digest.

Residual risks:
- references may change or describe a different deployment and are not retrieved by this workflow;
- a malicious or mistaken owner/reviewer can approve an unsafe implementation;
- implementation deployment identity and live enterprise credentials remain outside this gate.

### Promotion approval is forged, replayed or counted twice

Threat:
an attacker edits a release bundle, forges a human approval, reuses one key as multiple voters,
substitutes a candidate digest, replays an expired vote or treats a quorum result as permission to
deploy through an unrelated system.

Mitigations:
- the complete Phase 6f bundle is strictly parsed and its canonical SHA-256 digest is recomputed;
- each attestation is Ed25519-verified against a separate organization-controlled public-key trust
  store that binds the key to allowed non-personal roles;
- signatures bind the exact bundle, candidate pack and promotion-policy digests plus decision,
  role, key, identifier and UTC validity window;
- duplicate attestation ids and repeated signing keys fail closed, so one key counts once;
- all required roles, the configured distinct-key quorum and absence of an active rejection are
  required at one explicit UTC evaluation time;
- output contains only bounded identities and cryptographic digests and states that authorization
  does not sign, promote, distribute or deploy the release.

Residual risks:
- compromised promotion private keys or trust/policy files can authorize a malicious release;
- Phase 6j enforces supplied revocation/retirement state and validity windows; key issuance,
  custody, distribution and external timestamping remain organization-owned;
- signers can approve incomplete real-world analysis even when the bundle is structurally complete;
- a downstream system can ignore the report scope or deploy a different artifact unless it
  independently enforces the candidate digest binding.

### Cross-tenant leakage (future SaaS)

Not Phase 1, but architecture must not make tenant id optional once SaaS mode exists.

### SSRF/arbitrary outbound access

Mitigations:
- explicit provider adapters/endpoints;
- allowlisted egress;
- bounded timeouts;
- gateway URL is deployment configuration, never request input;
- the gateway SDK accepts HTTPS or literal loopback HTTP and rejects userinfo/query/fragment;
- no user-supplied arbitrary provider URL in production mode.

### Gateway credential or response leakage

Mitigations:
- credential comes from an environment variable and is excluded from representations, evidence,
  errors and logs;
- the pinned gateway client normalizes transport/protocol failures without raw response bodies;
- response content is used only ephemerally and discarded;
- only allowlisted routing/execution metadata is persisted or returned.

### Duplicate execution after crash or concurrent replay

Mitigations:
- persist `PREPARED` before external I/O;
- atomically claim `DISPATCHED` before the gateway call;
- never automatically execute a record already observed as `DISPATCHED`, `EXECUTION_FAILED` or
  `EXECUTED`;
- require operational reconciliation for an interrupted, uncertain `DISPATCHED` record.

### Approval spoofing or replay

Mitigations:
- dedicated HMAC-authenticated external issuer and strict assertion schema;
- actor identity and policy/provider versions are transitively bound by the decision digest;
- bounded lifetime, future-issuance rejection and globally single-use approval IDs;
- atomic consumption after the execution claim and before execution;
- no approval minting endpoint and no persistence/logging of raw assertions;
- approval applies to an operation-specific decision digest that commits to normalized input and
  policy output, not free-form text, a tool name or model output.

The HMAC verifier necessarily possesses symmetric signing material. Issuer/verifier separation is
therefore operational in Phase 4a, not cryptographic; deployments must restrict key access. A
future asymmetric or OIDC adapter should remove signing capability from the enforcement service.

## Abuse cases to test

- user puts a fake `ALLOW` directive inside prompt text;
- request asks for a state-changing tool while declaring `read_only`;
- registry capability missing;
- capability changed from supported to unknown;
- policy set has malformed/unknown schema;
- evidence repository unavailable;
- transform fails;
- attempted log injection with secret-looking values;
- fallback attempts weaker provider.
- partial/unsafe gateway configuration;
- gateway terminal provider differs from the configured provider boundary;
- tool-bearing plan reaches the text-only gateway adapter;
- malformed, failed or content-free terminal gateway response.
- malformed, tampered, expired, future, wrong-digest or replayed approval assertion;
- approval consumption fails after the execution claim;
- decision approval is presented as action approval;
- action arguments or current catalog schema differ from the stored proposal;
- concurrent action attempts or a changed idempotency key target the same proposal;
- tool timeout produces `RECONCILIATION_REQUIRED` without an automatic retry;
- caller supplies a false tool risk class or unknown tool name;
- gateway proposes an unlisted tool, duplicate call id or non-JSON/oversized arguments;
- tool proposal metadata leaks raw arguments or is mistaken for execution authority.
- tool result has missing/extra fields, invalid types/enums, oversized values or a disallowed
  classification/handling combination;
- raw or masked tool-result values appear in SQLite, replay/GET responses, errors or logs;
- tool-result text attempts prompt injection or result-driven authority escalation.
- operator timeline is queried with a missing/invalid identifier, inconsistent linked metadata or
  more actions than its bounded view;
- sentinel payload, argument, assertion or result values appear in an operator response.
- lifecycle event rows are updated/deleted, duplicate replay events appear, or a legacy baseline is
  reported as complete transition history;
- more lifecycle events than the response bound exist without truncation being signaled.
