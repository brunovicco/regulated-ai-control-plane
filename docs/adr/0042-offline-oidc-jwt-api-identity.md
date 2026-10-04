# ADR-0042: Authenticate API callers with pinned EdDSA JWT access tokens

## Status

Accepted.

## Date

2026-09-29.

## Context

Production mutations already require role-scoped, exact-digest Ed25519 assertions, but the HTTP API
and operator dashboard lack an enterprise session or workload identity boundary. Operation-specific
authority is deliberately portable and single-use; it is not a substitute for authenticating who
may call runtime, inspection or reconciliation endpoints.

Selecting a concrete identity provider is outside this repository. Runtime discovery and remote
JWKS retrieval would also add startup/network availability, redirect, cache and key-rollover
behavior before an issuer contract has been chosen.

## Decision

Use a restricted resource-server adapter that verifies compact EdDSA JWT access tokens offline
against a deployment-mounted, strict public JWKS. Pin the exact HTTPS issuer, audience, maximum
token lifetime and bounded clock skew. Accept only Ed25519 signing keys and a protected header
containing exactly `alg=EdDSA`, trusted `kid` and `typ=at+jwt` or `typ=application/at+jwt`
(case-insensitive). Reject generic `typ=JWT` ID tokens rather than allowing them to establish API
authority. Require bounded `client_id` and `jti` claims alongside issuer, audience, subject, issued
and expiry instants, and RegulaAI roles. Identifiers use the existing safe-ID contract.

Explicit access-token typing and distinct validation rules are grounded in
[RFC 8725 §3.11](https://www.rfc-editor.org/rfc/rfc8725.html#section-3.11) and
[§3.12](https://www.rfc-editor.org/rfc/rfc8725.html#section-3.12); the access-token type and required
claims follow the relevant rules in [RFC 9068 §2](https://www.rfc-editor.org/rfc/rfc9068.html#section-2)
and [§4](https://www.rfc-editor.org/rfc/rfc9068.html#section-4). This EdDSA-only adapter does not claim
universal OAuth/OIDC compatibility, full RFC 9068 conformance or certification; in particular, it
does not implement that profile's complete required signature-algorithm set.

Bound token and JWKS sizes, key counts, audiences, roles and identifiers. Reject duplicate fields,
non-JSON constants, malformed JSON and nesting that exceeds parser capacity; reject private or
unexpected JWKS fields. Invalid JWKS or missing production identity configuration prevents startup,
while malformed bearer material fails authentication with no claim content echoed.

Authorize three application roles: `regulaai.runtime` for evaluation/enforcement/tool-action POSTs,
`regulaai.operator` for metadata inspection and dashboard access, and `regulaai.reconciler` for the
terminal reconciliation POST. Keep health and the dashboard stylesheet public. Require this mode
for production-labelled API startup while retaining an explicit disabled mode for local work.

Treat API identity as an outer boundary. Continue requiring the independent `ra1e`, `ra2e` and
`rr1e` assertions for exact protected mutations.

## Alternatives considered

- Provider-specific OIDC discovery and remote JWKS refresh: deferred until an issuer, network and
  rollover contract is selected; it would add an external availability dependency.
- Trust authentication headers from a reverse proxy: rejected as the default because header
  stripping, proxy identity and network topology are deployment-specific and easy to misconfigure.
- Reuse operation-specific Ed25519 assertions as API login: rejected because those assertions bind
  one decision/action, not a caller session or general read access.
- Shared API key or HMAC JWT: rejected for production because every verifier could mint tokens and
  rotation would distribute signing material to runtime replicas.
- Make every route require one broad role: rejected because runtime, inspection and reconciliation
  are distinct authorities.

## Consequences

Production requests have a cryptographically verified caller boundary without network calls or
provider SDKs. The selected identity provider must emit the exact access-token contract in
[API_IDENTITY.md](../API_IDENTITY.md), including application roles and bounded non-personal
identifiers, and supply a reviewed public JWKS. A valid token of another type or a provider's default
claims/algorithm is not assumed compatible. Local tests and development remain network-silent.

JWKS changes require coordinated distribution and replica restart. This first adapter intentionally
does not implement discovery, remote refresh, introspection, logout or browser login flows.

## Security and privacy impact

Tokens, claims, subjects, client and token identifiers, and roles are used ephemerally and excluded
from logs, responses, evidence and persistence. Authentication and authorization failures are
generic. Strict token type, algorithm, issuer, audience, signature, lifetime, not-before and role
validation rejects generic ID-token substitution and cross-service token reuse. Requiring `jti`
does not implement replay detection; valid bearer access tokens remain reusable until expiry, while
exact-operation assertions retain independent single-use controls.

An identity-provider signing-key compromise can still mint authorized sessions. Role assignment,
MFA, token issuance, revocation, transport TLS and IdP audit remain organization-owned controls.

## Operational impact

Deployments must mount a reviewed JWKS, configure exact issuer/audience values, keep access tokens
short-lived and rotate keys with an overlap window. Production startup fails closed without this
configuration. `/health` stays unauthenticated for platform probes.

The Kubernetes reference expects the public identity material in the
`regulaai-api-identity` ConfigMap and never stores an IdP client secret.

## Follow-up

- Validate token issuance, role mapping, signing-key rotation and denied-access audit at the chosen
  enterprise identity provider.
- Add provider discovery or automated JWKS refresh only after documenting cache, outage, TLS,
  rollover and emergency-revocation semantics.
- Add tenant isolation before serving more than one organization boundary.
