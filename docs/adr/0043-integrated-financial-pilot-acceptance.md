# ADR-0043: Bind individual financial-PoC evidence to two-key self-attestation

## Status

Accepted.

## Date

2026-10-04.

## Context

The repository contains the individual controls needed for a bounded enterprise pilot: PostgreSQL
persistence, offline enterprise access-token verification, governed gateway execution, separate
decision/action authority, a state-changing sandbox connector and terminal reconciliation. Passing
their isolated tests does not prove that one organization exercised the controls together against
its selected issuer, provider workloads and downstream sandbox.

This repository is an individual proof of concept rather than an organization deployment. It must
not encode external credentials, claim organizational approval or manufacture live evidence. It can
define a configurable integration contract, prove the composition and distinguish self-attestation
from independent enterprise acceptance.

## Decision

Define an integrated, non-production financial-PoC profile bound to the exact source revision,
image, signed control pack, PoC policy version, OpenAI profile and Bedrock profile. Provider profiles
contain only reviewed non-secret target, model and deployment metadata. The live fixed-synthetic
probe rejects mismatched or cached terminal gateway metadata.

Require nine distinct metadata-only observations: real PostgreSQL concurrency in CI, enterprise
identity, OpenAI and Bedrock gateway calls, tool execution, both terminal recovery outcomes,
technical policy self-review and backup/restore. CI may attest only its real PostgreSQL check;
synthetic issuer and external adapters are explicitly identified as simulated.

Bind the complete scope and evidence set into a canonical SHA-256 bundle. Accept it only when every
observation is successful, recent, exact-scope and uses its required live mode, and when distinct
Ed25519 keys for `POC_OPERATOR` and `POC_POLICY_REVIEWER` self-attest the exact bundle. The same
individual may control both keys, but the keys must be cryptographically distinct and the report
must state that review was not independent. Keep private keys and evidence outside the repository.

Use controls demonstrable by an individual: OpenAI `store=false`, Bedrock IAM authorization and the
documented provider-access behavior. Keep ZDR eligibility, PrivateLink, CloudTrail deployment and
independent organizational review in a separate future enterprise profile.

## Alternatives considered

- Treat the existing unit and integration suite as pilot acceptance: rejected because external
  issuer, provider, sandbox, backup and independent-review boundaries are substituted in tests.
- Select a hosted enterprise IdP or real financial sandbox: rejected for the PoC because a local
  compatible issuer and stateful synthetic sandbox demonstrate the boundary without implying an
  organization relationship.
- Accept screenshots or a free-form checklist: rejected because they do not reproducibly bind the
  exact artifacts, scope, observations and attestations.
- Permit one key or a runtime-held shared secret: rejected because the PoC still needs to
  demonstrate separation between operational and policy-review attestations.
- Store prompts, provider responses or tool arguments as stronger proof: rejected because it would
  violate the metadata-only evidence boundary and could retain personal or secret data.

## Consequences

The repository can show an end-to-end technical composition without claiming independent review or
enterprise adoption. A future organization can use the retained enterprise profile, but it must
supply its own authority, infrastructure and acceptance semantics.

Acceptance is deliberately blocked by placeholder scope, missing checks, simulated modes, stale or
wrong-scope evidence, duplicate evidence, invalid signatures, overlapping attestation keys, a
non-PoC policy or a missing two-key self-attestation. Producing live provider evidence still
requires the author's development accounts and synthetic sandbox.

## Security and privacy impact

Profiles and reports contain identifiers, versions, result categories and digests only. Tokens,
credentials, claims, prompt values, model output, tool arguments/results and personal data are
excluded. The identity probe verifies the route matrix with invalid mutation bodies. Provider
proof uses fixed synthetic content, while tool recovery forbids reexecution of an ambiguous action.

Ed25519 signatures are domain-separated, role-bound, lifecycle-checked and tied to the exact
bundle. A valid signature proves possession of one PoC role key; it does not provide independent
review or make a referenced external report truthful.

## Operational impact

CI runs migrations and concurrency cases against a disposable PostgreSQL 17 service and retains a
metadata-only summary. The PoC author maintains dedicated non-production databases, public trust
stores, exact gateway configuration, downstream idempotency, backup/restore proof and a seven-day
verification window. Any material scope change requires new evidence and signatures.

## Follow-up

- Configure a compatible local IdP and validate issuance, role mapping and key rotation.
- Select reviewed OpenAI and Bedrock gateway workloads and replace profile placeholders.
- Select the downstream sandbox and exercise success plus both investigated recovery outcomes.
- Self-review and sign the PoC policy; retain the stricter enterprise profile for future use.
- Run backup/restore, gather all nine evidence records and produce both PoC attestations.
