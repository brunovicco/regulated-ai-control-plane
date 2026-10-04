# ADR-0040: Use role-bound Ed25519 assertions for production operator authority

## Status

Accepted.

## Date

2026-09-29.

## Context

Decision approval, exact tool-action approval and terminal reconciliation were authenticated with
separate HMAC secrets. Their digest binding, bounded lifetime and single-use ledgers constrain
replay, but every service replica holding a verifier secret can also mint valid authority. That is
appropriate for local demonstrations, not for a production authority boundary or independently
managed operator identity.

Production persistence now supports multiple replicas and atomic authority/state transitions. The
next boundary must preserve those transactions while making the runtime verification-only and
recording which organization-controlled key authorized each mutation.

## Decision

Use canonical Ed25519 assertions verified through one deployment-controlled public trust store.
Each key is bound to one pseudonymous `actor_id`, an explicit subset of `decision_approval`,
`action_approval` and `reconciliation`, and lifecycle fields `ACTIVE`, `RETIRED` or `REVOKED` with
UTC validity bounds.

Use distinct `ra1e`, `ra2e` and `rr1e` prefixes and exact schemas so asymmetric assertions cannot
be confused with the existing HMAC formats. Assertions remain digest-bound, short-lived and
single-use. Persist the non-secret `authority_key_id` in consumption ledgers and receipts. Keep
private keys and assertion issuance outside RegulaAI.

Production startup requires `REGULAAI_OPERATOR_AUTHORITY_TRUST_STORE` and rejects simultaneous
HMAC authority configuration. HMAC remains available for local development and the bounded
controlled-pilot profile.

## Alternatives considered

- Continue using isolated HMAC secrets: rejected for production because runtime compromise grants
  signing capability and symmetric keys must be distributed to every replica.
- Validate an enterprise OIDC/JWT issuer directly: deferred because issuer discovery, audience,
  algorithm policy, role claims and availability semantics are deployment-specific. A future
  adapter can implement the same application ports.
- Use mutual TLS identity alone: rejected because channel identity does not provide portable,
  exact-digest authority or offline replay evidence.
- Use one unrestricted signing key: rejected because compromise would collapse the decision,
  action and reconciliation authority boundaries.

## Consequences

RegulaAI production replicas hold public verification material only. Key scope and actor binding
are enforced before authority consumption, and receipts identify the verification key. Existing
application use cases and PostgreSQL atomic transitions remain unchanged.

Deployments must distribute and rotate an additional public trust store. HMAC assertions are not
accepted when that store is configured, so migration requires coordinated issuer and runtime
rollout.

## Security and privacy impact

Private signing keys never enter the repository, service environment, database, logs or evidence.
Assertions remain ephemeral. Persisted additions are bounded non-secret key identifiers; prompts,
responses, arguments, credentials and raw assertions remain excluded.

An authorized private-key compromise can still mint assertions within that key's configured
scope. Revocation, trust-store distribution integrity, operator authentication, signing ceremony
and separation of duties remain organization-owned controls.

## Operational impact

Create and mount a strict schema-version-1 trust store before production startup. Rotate keys with
overlapping validity only after distributing the new public key, then retire or revoke the old key.
Monitor fail-closed assertion errors and retain the consumption ledger for replay protection.

Database migration `0002_operator_authority` must complete before deploying this
runtime revision.

## Follow-up

- Validate trust-store distribution and key rotation in pre-production.
- Add an enterprise OIDC/workload-identity adapter when a concrete issuer contract is selected.
- Require a separate review before enabling any state-changing enterprise connector.
