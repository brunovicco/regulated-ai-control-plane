# Production operator authority

RegulaAI production mode verifies organization-issued Ed25519 assertions and never holds a signing
key. The same trust store supports three independently scoped authorities:

- `decision_approval` for a decision digest;
- `action_approval` for an exact tool-action digest;
- `reconciliation` for one investigated terminal outcome.

## Trust store

Mount a deployment-controlled YAML file and set
`REGULAAI_OPERATOR_AUTHORITY_TRUST_STORE` to its absolute path:

```yaml
schema_version: "1"
keys:
  operator-key-2026-01:
    algorithm: ed25519
    public_key: BASE64_RAW_32_BYTE_PUBLIC_KEY
    actor_id: operator-team-a
    authorities:
      - decision_approval
      - action_approval
    status: ACTIVE
    valid_from: 2026-09-29T00:00:00Z
    valid_until: 2027-03-29T00:00:00Z
```

Key identifiers and actor identifiers are bounded metadata. Authority lists are exact and cannot
contain duplicates. Unknown fields, duplicate YAML keys, malformed public keys, inactive keys and
out-of-window assertions fail closed. A reconciliation key may be separate from approval keys to
enforce operational separation of duties.

Only public keys belong in this file. Generate and retain private keys in an organization-approved
KMS, HSM or signing service outside the RegulaAI runtime.

## Assertion envelopes

The issuer signs the ASCII bytes before the second period:

```text
ra1e.<base64url-canonical-json>.<base64url-ed25519-signature>
ra2e.<base64url-canonical-json>.<base64url-ed25519-signature>
rr1e.<base64url-canonical-json>.<base64url-ed25519-signature>
```

Payload JSON must use UTF-8, lexicographically sorted keys, no insignificant whitespace and no
base64url padding. Exact fields are documented in `API_CONTRACT.md`. The signed `actor_id` must
equal the actor bound to `key_id`, and the key must authorize the assertion's `authority_kind`.

## Rollout and rotation

1. Apply database migration `0002_operator_authority`.
2. Distribute the trust store containing the new active public key.
3. Confirm runtime startup and validate one synthetic assertion for each authorized role.
4. Switch the external issuer to the matching private key.
5. Retire the previous key after all short-lived assertions expire; revoke immediately on
   compromise.
6. Verify receipts contain the expected `authority_key_id` and that replay remains rejected or
   exact-idempotent for reconciliation.

Do not configure any `REGULAAI_*_HMAC_KEY` together with the trust-store path. Production startup
requires the trust store. HMAC remains only a local/pilot compatibility mode.
