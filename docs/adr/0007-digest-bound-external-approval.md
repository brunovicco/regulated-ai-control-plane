# ADR-0007: Consume digest-bound external approval before execution

## Status

Accepted.

## Date

2026-09-24.

## Context

Phase 2 stops high-impact operations at `WAITING_APPROVAL`, while Phase 3a provides an atomic claim
before external execution. RegulaAI now needs to resume an unchanged decision when an
organization-owned workflow grants human authority. A free-form boolean, tool name or model claim
would be replayable and could authorize a different policy decision.

The public API and persisted evidence must remain metadata-only. RegulaAI must not expose approval
creation, and concurrent enforcement calls must not consume one grant multiple times or execute a
side effect twice.

## Decision

Define an `ApprovalPort` with separate `inspect` and `consume` operations. The first Phase 4a
adapter verifies strict canonical JSON assertions authenticated with HMAC-SHA256 and a dedicated
key of at least 32 bytes. The evaluation output digest commits to the normalized operation input
digest as well as the resulting decision. Assertions bind an external approval ID and pseudonymous
actor ID to that operation-specific digest, issuance time and expiration time. The assertion
lifetime is bounded by configuration and defaults to one hour.

Missing assertions keep the operation at `WAITING_APPROVAL`. Invalid assertions fail closed before
an execution claim. A valid grant permits the same enforcement identity to advance to `PREPARED`;
after atomically claiming `DISPATCHED`, the application consumes its globally unique approval ID in
a SQLite replay ledger. Only then is a metadata-only receipt attached to the execution plan and
passed to the execution port. Consumption failure records terminal `APPROVAL_FAILED` and no
execution occurs.

The API accepts the assertion as a bounded `SecretStr`, does not log, persist or return it, and
offers no minting endpoint. The receipt persists only identifiers, the decision digest and
timestamps. Gateway tool forwarding remains disabled until a separate tool-schema authority
contract exists.

## Alternatives considered

- Caller-supplied approval boolean: rejected because it provides no authenticated authority,
  scope, expiration or replay defense.
- Consume before the execution claim: rejected because a losing concurrent request could spend
  the only grant without owning execution.
- Consume after provider/tool execution: rejected because authority must exist before the effect.
- Store the signed assertion as evidence: rejected because it is a bearer secret and unnecessary
  once metadata-only consumption evidence exists.
- Add asymmetric/OIDC verification in this slice: deferred to avoid introducing an identity
  provider and key-discovery lifecycle before the approval contract is proven.

## Consequences

High-impact mock executions can resume with explicit human authority, retain the same enforcement
identity and produce replay-resistant approval evidence. Invalid and missing assertions never
execute. An approval consumed immediately before a process crash may leave a `DISPATCHED` record;
automatic retry remains prohibited and requires reconciliation.

HMAC verification means the enforcement runtime possesses symmetric material capable of signing.
Separation from the external issuer is therefore operational rather than cryptographic in Phase
4a, even though RegulaAI implements no issuance path.

## Security and privacy impact

The key is environment configuration and must be dedicated, access-controlled and rotated through
an approved secret-management process. Assertions have a 4096-byte maximum, strict fields and
base64url encoding, constant-time signature comparison, digest binding, future/expiry checks and a
bounded lifetime. SQLite primary-key insertion makes approval IDs single-use.

Raw assertions, prompts, responses and tool payloads are excluded from storage and output.
Approval and actor identifiers must be opaque and pseudonymous; names or email addresses are not
permitted by operational policy.

## Operational impact

Approval execution is disabled unless `REGULAAI_APPROVAL_HMAC_KEY` is configured. Operators may
lower `REGULAAI_APPROVAL_MAX_LIFETIME_SECONDS` from its 3600-second default. The issuer must produce
the exact assertion schema and use the evidence `output_digest`. The replay ledger shares the
configured SQLite database and requires the same backup, retention and access controls.

## Follow-up

- Add an asymmetric signature or OIDC/JWKS adapter so the enforcement service has verification-only
  cryptographic material.
- Define key rotation with overlapping verifier keys and explicit key identifiers.
- Add the production tool-schema authority contract before forwarding tool definitions.
- Add append-only, externally verifiable approval evidence for production backends.
