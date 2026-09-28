# ADR-0036: Prove live composition with a fixed synthetic request

## Status

Accepted.

## Date

2026-09-28.

## Context

The governed-gateway adapter, deterministic enforcement, metadata-only evidence, operator timeline
and opt-in telemetry have been implemented independently. The roadmap still lacks one reproducible
proof that these boundaries compose around a real non-production gateway/provider call. A general
pilot CLI accepting prompts or customer fields would create a second content API, increase leakage
risk and weaken the product's existing metadata-only operator boundary.

## Decision

Add an explicit Phase 7a pilot entrypoint that runs one fixed, package-owned synthetic request. It
uses the existing `EnforceAiOperation`, gateway adapter, SQLite evidence repositories and operator
timeline without introducing another execution path. The request targets the reviewed
`openai.responses_api.global` record, labels a synthetic document for mandatory local tokenization,
contains no tools and cannot be customized with content or provider arguments.

The entrypoint requires gateway mode, performs one attempt, validates the terminal provider
receipt and complete operator timeline, and emits a deterministic metadata-only JSON report with a
report digest. It requires an explicit non-production environment and dedicated evidence database,
and always appends a random suffix to the bounded operator correlation prefix so an idempotent replay
cannot be presented as a fresh call. Mock mode fails before execution. Model output remains
discarded by the existing adapter. The canonical report uses stdout while structured lifecycle
logs use stderr.

## Alternatives considered

- Accept arbitrary pilot prompts and fields: rejected because it would create an unmanaged content
  ingress and make accidental production-data use likely.
- Call the gateway client directly from the script: rejected because that would bypass evaluation,
  transformation, persistence and timeline controls the pilot exists to prove.
- Exercise a state-changing enterprise tool in the same pilot: deferred because Phase 7a proves
  provider composition only; live tool authority needs a separately reviewed connector and
  reconciliation design.
- Run the live call in the default test suite: rejected because automated tests must stay
  deterministic, credential-free and network-silent.

## Consequences

Operators gain a repeatable proof of the first real composition boundary without changing the
public API or returning completion content. The proof is intentionally narrow: one provider target,
one policy scenario and one fixed synthetic payload. Unit and end-to-end tests use an in-process
fake execution port while existing gateway contract tests cover protocol validation.

## Security and privacy impact

The pilot accepts only a bounded correlation identifier. It does not accept prompts, field values,
tools, credentials or provider selection as arguments. The synthetic document is tokenized before
the gateway boundary. Reports and persisted records contain only existing allowlisted identifiers,
digests, status, transformation categories and routing metadata. Credentials remain deployment
environment inputs and model output remains ephemeral and discarded.

## Operational impact

The command is opt-in, may incur provider cost and must run only against a reviewed non-production
gateway workload with a dedicated evidence database and approved egress. It performs no local
retry. Timeout and transport failure remain potentially ambiguous after dispatch and require
operator review rather than automatic replay.

## Follow-up

- Record a successful pilot report in the organization's controlled evidence system, not in Git.
- Add one reviewed read-only enterprise connector in a separate phase.
- Define reconciliation and production persistence before enabling state-changing integrations.
- Generalize provider targets only after each workload/capability binding is separately reviewed.
