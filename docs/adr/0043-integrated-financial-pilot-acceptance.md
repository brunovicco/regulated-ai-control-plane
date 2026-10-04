# ADR-0043: Bind integrated financial-pilot evidence to authenticated acceptance

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

The enterprise identity provider and sandbox environment have not been selected. The repository
therefore cannot encode their credentials, claim organizational approval or manufacture live
evidence. It can define a configurable integration contract, prove the composition locally and
fail closed until organization-owned evidence and reviews are supplied.

## Decision

Define an integrated, non-production financial-pilot profile bound to the exact source revision,
image, promoted control pack, organization policy version, OpenAI profile and Bedrock profile.
Provider profiles contain only reviewed non-secret target, model, deployment and organization
condition assertions. The live fixed-synthetic probe rejects mismatched or cached terminal gateway
metadata.

Require nine distinct metadata-only observations: real PostgreSQL concurrency in CI, enterprise
identity, OpenAI and Bedrock gateway calls, tool execution, both terminal recovery outcomes,
organization policy review and backup/restore. CI may attest only its real PostgreSQL check;
synthetic issuer and external adapters are explicitly identified as simulated.

Bind the complete scope and evidence set into a canonical SHA-256 bundle. Accept it only when every
observation is successful, recent, exact-scope and uses its required live mode, and when distinct
organization-owned Ed25519 keys for `OPERATIONS` and `POLICY_OWNER` approve the exact bundle. Keep
private signing keys and evidence artifacts outside the runtime and repository.

## Alternatives considered

- Treat the existing unit and integration suite as pilot acceptance: rejected because external
  issuer, provider, sandbox, backup and organization review boundaries are substituted in tests.
- Select a concrete IdP, cloud account or sandbox in source: deferred because none has been chosen
  and credentials and organizational authority belong to the deployment.
- Accept screenshots or a free-form checklist: rejected because they do not reproducibly bind the
  exact artifacts, scope, observations and reviewers.
- Permit one reviewer or a runtime-held shared secret: rejected because operations and policy
  ownership are separate decisions and runtime verification must not grant signing authority.
- Store prompts, provider responses or tool arguments as stronger proof: rejected because it would
  violate the metadata-only evidence boundary and could retain personal or secret data.

## Consequences

The repository can show an end-to-end technical composition without claiming that simulated
boundaries are live. Organizations can select compatible identity and sandbox products later by
supplying configuration and evidence rather than changing the acceptance semantics.

Acceptance is deliberately blocked by placeholder scope, missing checks, simulated modes, stale or
wrong-scope evidence, duplicate evidence, invalid signatures, overlapping reviewer keys or an
unreviewed demo policy. Producing the live evidence requires organization-owned infrastructure and
human decisions.

## Security and privacy impact

Profiles and reports contain identifiers, versions, result categories and digests only. Tokens,
credentials, claims, prompt values, model output, tool arguments/results and personal data are
excluded. The identity probe verifies the route matrix with invalid mutation bodies. Provider
proof uses fixed synthetic content, while tool recovery forbids reexecution of an ambiguous action.

Ed25519 review signatures are domain-separated, role-bound, lifecycle-checked and tied to the exact
bundle. A valid signature attests reviewer approval; it does not make a referenced external report
truthful. Evidence custody, reviewer authentication and investigation integrity remain
organization-owned controls.

## Operational impact

CI runs migrations and concurrency cases against a disposable PostgreSQL 17 service and retains a
metadata-only summary. Pilot operators must maintain dedicated non-production databases, public
trust stores, exact gateway configuration, downstream idempotency, backup/restore proof and a
seven-day acceptance window. Any material scope change requires new evidence and signatures.

## Follow-up

- Select the enterprise IdP and validate issuance, role mapping, rotation and revocation.
- Select reviewed OpenAI and Bedrock gateway workloads and replace profile placeholders.
- Select the downstream sandbox and exercise success plus both investigated recovery outcomes.
- Promote the organization policy through the existing signed release workflow.
- Run backup/restore, gather all nine evidence records and obtain both acceptance signatures.
