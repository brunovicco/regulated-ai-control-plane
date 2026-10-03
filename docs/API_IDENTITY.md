# Enterprise API identity and RBAC

RegulaAI verifies enterprise-issued, short-lived JWT access tokens under a restricted EdDSA
resource-server contract. Verification is offline against a deployment-mounted public JWKS: the
runtime does not perform issuer discovery, contact a token endpoint or hold an identity-provider
secret. The identity provider must emit the token contract below; generic OAuth/OIDC compatibility,
full RFC 9068 conformance and certification are not claimed. Only Ed25519 signatures are supported,
not the full algorithm set required by that profile.

Local development keeps authentication disabled unless explicitly configured. A
production-labelled API fails startup unless `REGULAAI_API_AUTH_MODE=oidc_jwt` is set with an exact
issuer, audience and readable JWKS path.

## Configuration

```text
REGULAAI_API_AUTH_MODE=oidc_jwt
REGULAAI_OIDC_ISSUER=https://identity.example.internal/tenant/regulaai
REGULAAI_OIDC_AUDIENCE=regulaai-api
REGULAAI_OIDC_JWKS_PATH=/etc/regulaai/api-identity/jwks.json
REGULAAI_OIDC_MAX_TOKEN_AGE_SECONDS=3600
REGULAAI_OIDC_CLOCK_SKEW_SECONDS=30
```

The JWKS is strict and contains only Ed25519 signing keys. Startup rejects unreadable, malformed,
duplicate-field or oversized documents, nesting that exceeds parser capacity, non-JSON constants,
private-key fields and unknown schema fields. Its size is limited to 262,144 bytes and it may contain
1–64 keys with unique, bounded key identifiers:

```json
{
  "keys": [
    {
      "alg": "EdDSA",
      "crv": "Ed25519",
      "kid": "enterprise-api-2026-01",
      "kty": "OKP",
      "use": "sig",
      "x": "BASE64URL_RAW_32_BYTE_PUBLIC_KEY"
    }
  ]
}
```

Private keys remain in the organization identity provider. Distribute and validate the new public
JWKS before rotating issuer signing keys, retain overlap for already-issued short-lived tokens, and
restart replicas to load a changed JWKS. Do not place access tokens in command lines, logs,
screenshots, evidence or persistent storage.

## Token contract

The compact JWS header must contain exactly `alg=EdDSA`, a trusted `kid`, and `typ=at+jwt` or
`typ=application/at+jwt` (case-insensitive). Generic `typ=JWT`, including an otherwise correctly
signed ID token, is rejected. This distinction uses explicit typing and separate token-validation
rules described in [RFC 8725 §3.11](https://www.rfc-editor.org/rfc/rfc8725.html#section-3.11) and
[§3.12](https://www.rfc-editor.org/rfc/rfc8725.html#section-3.12), and the access-token type in
[RFC 9068 §2](https://www.rfc-editor.org/rfc/rfc9068.html#section-2) and
[§4](https://www.rfc-editor.org/rfc/rfc9068.html#section-4).

Required claims are:

- `iss`: exact configured HTTPS issuer;
- `aud`: configured audience, either directly or in a bounded unique list;
- `sub`: bounded non-personal workload or operator subject identifier;
- `client_id`: bounded non-personal identifier of the client application that obtained the token;
- `jti`: bounded identifier assigned by the issuer to the access token;
- `iat`, optional `nbf`, and `exp`: integer NumericDate values within the configured lifetime and
  clock-skew limits;
- `roles`: a bounded unique list containing only recognized RegulaAI roles.

`sub`, `client_id`, `jti`, `kid` and audience values must match
`[A-Za-z0-9][A-Za-z0-9._:@|/-]{0,127}`. Tokens are limited to 8,192 bytes, and their JSON rejects
duplicate fields, non-JSON constants, nesting that exceeds parser capacity and malformed encodings.
Audience lists contain at most eight unique values and role lists contain only the three recognized
roles.

Tokens and claims, including `client_id` and `jti`, are ephemeral. RegulaAI uses them only for request
authorization and does not persist or include subject, roles, token, signature or claims in
application evidence or logs. Identity events contain the required route role and HTTP method, not
the presented token's claim values. A required `jti` is not a replay cache: a valid bearer access
token can be reused until expiry. Exact-operation assertions retain their separate single-use
controls.

## Role matrix

| Role | Authorized surface |
| --- | --- |
| `regulaai.runtime` | Evaluation, enforcement and exact tool-action POST operations |
| `regulaai.operator` | Metadata-only GET APIs, OpenAPI/docs and the exact-ID operator dashboard |
| `regulaai.reconciler` | Exact tool-action reconciliation POST operation |

`/health` and `/operator/assets/dashboard.css` are public so platform probes and static styling do
not need bearer material. The dashboard data route remains protected. Role checks use the decoded
ASGI route path and its deployment prefix, matching the router even with encoded path characters.

API identity is an outer session/workload boundary. It never grants model or tool authority and
never replaces `ra1e`, `ra2e` or `rr1e` exact-digest assertions. A caller needs both the appropriate
API role and the separately issued operation-specific authority where the use case requires it.

## Failure behavior

Missing, malformed, wrongly typed, expired, future, wrong-issuer, wrong-audience, unknown-key or
invalid-signature tokens return generic HTTP 401 with `WWW-Authenticate: Bearer` and
`Cache-Control: no-store`.
Authenticated callers missing the exact route role receive generic HTTP 403. Responses do not echo
tokens, claims, subjects or key material. All authenticated responses carry `Cache-Control: no-store`.

Transport TLS, login/user interaction, MFA, conditional access, token issuance, revocation feeds,
group-to-role mapping and identity-provider audit retention remain deployment responsibilities.
