# ADR-0041: Bind the first state-changing connector to one sandbox operation

## Status

Accepted.

## Date

2026-09-29.

## Context

RegulaAI already treats model tool calls as proposals, requires exact action-digest approval,
atomically consumes authority with a single-winner dispatch claim, validates closed outputs and
supports authenticated terminal reconciliation without reexecution. PostgreSQL now preserves
those transitions across replicas, and production authority uses role-bound Ed25519 assertions.

The remaining product proof is a state-changing enterprise boundary. A generic HTTP executor or a
production connector would exceed the available evidence because no concrete enterprise provider,
identity protocol or production recovery contract has been selected.

## Decision

Add an opt-in, non-production `ToolExecutionPort` adapter fixed to the signed-catalog
`cards.unblock` definition, its `high_impact_state_change` risk class, one configured workload
identity and one sandbox endpoint. Reject this mode in production-labelled runtimes.

Send exactly one bounded canonical POST after action-specific authority has been consumed. Place
the approved idempotency key only in the `Idempotency-Key` header, include its SHA-256 digest in the
body, and require it plus the exact action digest in the closed success response alongside the
action and execution identifiers. Disable redirects, environment proxies, local retries and fallback.

Any timeout, transport error, non-200 response or invalid response remains ambiguous and advances
through the existing `RECONCILIATION_REQUIRED` path. Successful output remains untrusted and must
pass the signed catalog's closed schema and minimization rules.

## Alternatives considered

- Generalize the read-only adapter with runtime-selected tool and risk: rejected because it would
  create a configurable generic egress/effect boundary.
- Enable a production connector immediately: rejected because deployment-specific identity,
  downstream authorization, idempotency durability and recovery evidence are not yet available.
- Retry after timeout: rejected because the downstream effect may already have occurred.
- Treat any HTTP error as `NOT_EXECUTED`: rejected because transport status does not prove absence
  of an effect.
- Persist the idempotency key for diagnostics: rejected because only its digest is needed for
  binding and retention of the key would enlarge the sensitive operational surface.

## Consequences

The product can demonstrate one separately approved state change through the same action and
reconciliation lifecycle used by the network-silent boundary. The adapter cannot execute
`cards.read`, another tool, another risk class or a caller-selected destination.

The downstream sandbox must implement durable exact-operation idempotency. RegulaAI verifies the
response binding but cannot prove the downstream implementation honored it internally.

## Security and privacy impact

Exact arguments and the raw idempotency key cross only the configured sandbox boundary and remain
ephemeral. The bearer credential is header-only and excluded from representations. Persisted
metadata contains existing bounded identifiers and digests, not arguments, credentials or result
content.

A compromised endpoint, credential, workload identity, DNS path or authorized operator key can
still cause an effect. Deployment egress, TLS, secret custody, operator issuance and downstream
authorization remain required controls.

## Operational impact

Operators must configure the endpoint, credential and exact workload identity, keep mock execution
as the default, and exercise downstream duplicate/conflict and ambiguous-outcome cases. A timeout
must trigger investigation and a separately signed reconciliation decision; it must never trigger
automatic reexecution.

The reference Kubernetes deployment does not enable this connector or its egress. Enabling it
requires a separately reviewed non-production overlay.

## Follow-up

- Collect sandbox evidence for duplicate, conflict, timeout-before-effect, timeout-after-effect and
  late-success behavior.
- Select and review a concrete enterprise identity and authorization contract.
- Define production downstream idempotency, SLO, audit, recovery and incident evidence.
- Require another ADR before removing the non-production guard.
