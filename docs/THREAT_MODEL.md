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

### Evidence tampering

Mitigations:
- immutable IDs;
- event digests;
- optional previous-digest chain in MVP;
- later signed/append-only storage;
- policy/provider versions captured.

### Malicious policy/provider YAML

Threat:
untrusted content causes arbitrary code execution or schema confusion.

Mitigations:
- safe parser;
- strict schema;
- no dynamic expression evaluation;
- unknown fields/version handling;
- no YAML object construction features.

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
