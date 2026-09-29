# Tool-action reconciliation

Phase 7c provides a terminal, authenticated operation for tool actions whose downstream outcome is
ambiguous. It records an independently verified operator conclusion and never invokes the tool
adapter again.

## Authority contract

The endpoint accepts only an externally issued canonical assertion:

```text
rr1e.<base64url-canonical-json>.<base64url-ed25519-signature>
```

Its exact payload is:

```json
{
  "action_digest": "sha256:...",
  "actor_id": "operator-pseudonym",
  "authority_kind": "reconciliation",
  "expires_at": 1790597100,
  "issued_at": 1790596800,
  "key_id": "operator-reconciliation-2026-01",
  "outcome": "EXECUTED",
  "reconciliation_id": "reconciliation-...",
  "schema_version": "2",
  "subject_type": "tool_action_reconciliation",
  "tool_execution_id": "sandbox-execution-..."
}
```

`outcome` is exactly `EXECUTED` or `NOT_EXECUTED`. `EXECUTED` requires a bounded downstream
execution identifier. `NOT_EXECUTED` requires `tool_execution_id: null`. Free-form notes, output,
arguments, URLs and retry instructions are not accepted.

Production configures the public trust store through
`REGULAAI_OPERATOR_AUTHORITY_TRUST_STORE`. The selected key must bind the signed `actor_id`, be
active and authorize `reconciliation`. The service holds no private signing key and does not mint
assertions. Local/pilot compatibility retains the HMAC `rr1` schema and dedicated
`REGULAAI_RECONCILIATION_HMAC_KEY`; the two modes cannot be enabled together.

## Operation

Call:

```text
POST /v1/tool-actions/{action_id}/reconciliation
```

with:

```json
{"reconciliation_assertion": "rr1e...."}
```

The action must already be `RECONCILIATION_REQUIRED`, and the signed `action_digest` must match its
immutable binding. A valid assertion advances it atomically to:

- `RECONCILED_EXECUTED`; or
- `RECONCILED_NOT_EXECUTED`.

Both states are terminal. Exact replay of the same assertion returns the stored result; a different
outcome or reconciliation identifier conflicts. The operation never reconstructs arguments,
returns tool output, changes result digests or calls `ToolExecutionPort`.

## Operator procedure

1. Locate one exact action through its metadata-only action record or operator timeline.
2. Verify the downstream sandbox audit trail using the stored action digest, idempotency digest,
   workload identity and any organization-owned correlation evidence.
3. Have the separate issuer sign exactly one closed outcome and, for `EXECUTED`, the confirmed
   downstream execution identifier.
4. Submit the assertion once and verify the terminal status and reconciliation receipt.
5. Confirm the operator timeline no longer reports reconciliation attention.

The issuer must not infer an outcome from a timeout alone. When downstream evidence is insufficient,
leave the action in `RECONCILIATION_REQUIRED`.

## Security and operations

- protect the endpoint with the deployment's operator authentication and network controls in
  addition to the signed assertion;
- keep private signing keys and raw assertions out of the runtime, files, logs, traces,
  screenshots and evidence;
- use pseudonymous bounded actor identifiers and short assertion lifetimes;
- scope and rotate reconciliation public keys independently from approval authority;
- preserve the configured SQLite or PostgreSQL database because it contains the consumption ledger
  and terminal receipt;
- do not interpret `RECONCILED_EXECUTED` as validated output: no raw or safe result is recovered;
- do not create an automatic retry from `RECONCILED_NOT_EXECUTED`; any future retry requires a new,
  separately designed action contract.

The local SQLite implementation remains a single-instance reference. PostgreSQL atomically consumes
reconciliation authority with the terminal action transition and supports multi-replica claims;
production use still requires deployment-owned migration, TLS, backup/restore and SLO evidence.
