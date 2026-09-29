# Changelog

All notable changes to **Regulated AI Control Plane** will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project intends to use [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once tagged releases begin.

The project is currently a **controlled pilot**. Breaking changes may occur before the stable
`v0.1.0` release.

## [Unreleased]

### Added

- PostgreSQL production persistence with versioned Alembic migrations, multi-replica execution
  claims, atomic authority/state transitions and append-only lifecycle triggers.
- Restricted two-replica Kubernetes/OpenShift reference with separate runtime and migration
  database identities and an explicit migration Job.
- Role-bound Ed25519 production operator authority with lifecycle-aware public keys, distinct
  decision/action/reconciliation scopes and verification-key identity in metadata-only receipts.

### Changed

- Production-labelled runtimes now require PostgreSQL and fail startup when the database is
  unavailable or the schema revision does not match the application.
- Production-labelled runtimes require a public operator-authority trust store and reject
  simultaneous HMAC authority configuration.

## [0.1.0rc1] - 2026-09-28

### Added

- Deterministic policy evaluation, local data transformations and metadata-only evidence.
- Signed policy, provider-capability and trusted-tool control packs with lifecycle-aware trust stores.
- Digest-bound decision approval, action approval and authenticated terminal reconciliation.
- Closed trusted-tool schemas, proposal validation, result minimization and append-only action history.
- Network-silent mock execution as the default runtime behavior.
- Opt-in governed-gateway execution and a fixed-synthetic live composition probe.
- One identity-bound, read-only enterprise sandbox connector with bounded I/O and no retries.
- Exact-ID operator timeline and server-rendered dashboard without global record discovery.
- Offline semantic diff, scenario replay, authenticated review and promotion-quorum evidence.
- Content-addressed release custody, deterministic OCI evidence layouts and trusted timestamp
  verification.
- Restricted single-replica Kubernetes/OpenShift deployment references and metadata-only
  CloudEvents/OpenTelemetry integration.
- English and Brazilian Portuguese architecture, privacy, threat-model and operator guidance.

### Security

- Required controls fail closed when trusted configuration, approvals, provider capabilities or
  evidence are missing, stale or invalid.
- Raw prompts, model responses, credentials, tool arguments/results and personal-data values are
  excluded from persisted evidence and observability payloads.
- Provider fallback cannot weaken policy and a model cannot grant itself tool authority.
- External calls use bounded timeouts; ambiguous tool outcomes are never retried automatically.

### Known limitations

- This is a non-production, single-tenant, single-replica pilot release.
- SQLite is the reference persistence implementation and is not supported for multi-replica use.
- Enterprise operator authentication, tenant isolation and asymmetric reconciliation authority are
  not implemented.
- Live integrations are restricted to the reviewed fixed-synthetic provider probe and one
  read-only sandbox connector; state-changing enterprise tools remain unsupported.
- This release is technical evidence, not legal advice, certification or a compliance claim.
