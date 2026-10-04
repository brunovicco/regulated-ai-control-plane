# ADR-0039: Use PostgreSQL for transactional production persistence

## Status

Accepted.

## Date

2026-09-28.

## Context

The controlled pilot stores metadata-only evidence, enforcement, approval consumption, tool-action
state and append-only lifecycle events in one SQLite database. SQLite provides useful local
transaction semantics but constrains the deployment to one replica and a `ReadWriteOnce` volume.
That boundary prevents horizontal rollout and leaves production recovery and migration ownership
undefined.

The application ports already separate persistence from policy and domain behavior. Production
persistence must preserve the existing guarded transitions, single-use authority, exact replay,
metadata minimization and atomic lifecycle-event recording.

## Decision

Use PostgreSQL through the synchronous Psycopg 3 adapter for production. Keep SQLite as the local,
test and controlled-pilot adapter. Select PostgreSQL only through `REGULAAI_DATABASE_URL`; a
production-labelled process fails startup when that setting is absent or the Alembic revision is
not the exact revision supported by the application.

Manage the PostgreSQL schema with forward versioned Alembic migrations. Database triggers append
lifecycle events in the same transaction as evidence insertion and state transitions, and reject
updates or deletes to lifecycle rows. Conditional updates provide single-winner provider and tool
execution claims across replicas. PostgreSQL authority adapters atomically pair approval
consumption with the relevant execution claim, and pair reconciliation consumption with its
irreversible terminal action state.

Deploy two API replicas with rolling updates only after the migration job succeeds. Database
credentials, TLS policy, availability, backups, point-in-time recovery and egress rules remain
deployment-owned controls.

## Alternatives considered

- Continue with SQLite on a shared volume: rejected because filesystem locking and `ReadWriteOnce`
  storage do not provide the intended multi-replica production boundary.
- Replace all adapters with an ORM abstraction: rejected for this step because the existing ports
  already isolate persistence and direct SQL keeps guarded state transitions explicit.
- Use a distributed key-value store: rejected because the records and authority transitions need
  relational uniqueness, transactions and operationally familiar migration/backup tooling.
- Automatically create or mutate schemas at API startup: rejected because concurrent startup is
  not a safe migration coordinator and obscures deployment change authority.
- Remove SQLite immediately: rejected because it remains useful for deterministic local work and
  the bounded single-replica pilot.

## Consequences

Production deployments can run multiple API replicas while retaining one-winner claims and
single-use authority. Startup fails closed on unavailable or mismatched schema. Local development
remains network-silent by default.

The service now carries PostgreSQL and Alembic dependencies, and operators must run a migration
step before application rollout. SQLite and PostgreSQL adapters must continue to satisfy the same
application-port behavior.

## Security and privacy impact

The PostgreSQL schema stores the same allowlisted metadata as SQLite. Raw prompts, field values,
tool arguments, idempotency keys, assertions, credentials and tool results are not added. Database
URLs are accepted only from the environment and are never logged or returned.

Connection and statement timeouts bound database calls. Production operators must enforce TLS,
least-privilege database roles, encryption at rest, secret rotation, restricted network egress,
retention and audited backup access. Append-only triggers prevent ordinary application mutations
of lifecycle history but do not replace privileged database audit controls.

## Operational impact

Run `uv run alembic upgrade head` with a dedicated migration identity, verify the migration job,
then roll out the API. The runtime identity needs data access but should not own schema DDL.
Backups and point-in-time recovery must be exercised against a non-production database. The API
requires the exact schema head and does not attempt opportunistic migration.

## Follow-up

- Validate concurrent claims and authority consumption against the organization-managed
  PostgreSQL service in pre-production.
- Add deployment-specific TLS, NetworkPolicy/egress and least-privilege role configuration.
- Establish backup, point-in-time recovery, retention, SLO and incident procedures.
- Implement enterprise identity-backed operator authority before state-changing connectors.
