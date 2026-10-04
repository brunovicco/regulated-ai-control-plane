# Controlled pilot release profile

`v0.1.0rc1` is the first publishable RegulaAI release candidate. It packages the completed
deterministic control-plane, governed execution and evidence work as a deliberately bounded pilot.
It is not a production release or a compliance claim.

## Supported profile

The supported deployment is:

- one non-production environment and one service replica;
- one organization-controlled tenant and dedicated SQLite evidence database;
- mock provider and tool execution by default;
- optional fixed-synthetic provider composition through the reviewed governed-gateway target;
- optional `cards.read` connector bound to one sandbox endpoint and workload identity;
- synthetic data only, with secrets injected by the deployment platform;
- exact-ID operator access without global discovery or administrative mutation.

All live paths remain opt-in. The provider pilot accepts no arbitrary prompt, tool or provider
selection. The enterprise connector is read-only, performs one bounded attempt and never retries an
ambiguous result. Terminal reconciliation requires a separate authority assertion and never
reexecutes the action.

## Release verification

Verify the source checkout and build artifacts before operating the release:

```bash
uv lock --check
uv sync --frozen --all-groups --extra observability
uv run python scripts/quality_gate.py
uv build
shasum -a 256 dist/*
```

Release assets include the Python source distribution, wheel and a SHA-256 checksum file. Install
from a locally verified artifact in an isolated non-production environment. The Git-pinned gateway
client dependency still requires access to its reviewed source when resolving a fresh environment.

The repository-provided Kubernetes and OpenShift manifests are reviewable references, not a
deployment action. Before use, follow `docs/KUBERNETES_DEPLOYMENT.md`, replace the non-routable
image with a scanned and signed immutable digest, provision trust material and runtime secrets
outside Git, and perform an approved server-side dry run.

## Pilot acceptance

An organization may accept its own pilot only after it has:

1. run the synthetic local API demonstration and retained no input values in evidence;
2. run the fixed-synthetic live composition probe against the approved non-production gateway;
3. exercised the bound read-only sandbox connector for success, timeout and ambiguous outcome;
4. reconciled one ambiguous outcome through the separately authenticated terminal operation;
5. inspected an attention-free operator timeline for each accepted path;
6. verified backup and restore of the dedicated SQLite evidence database;
7. recorded the exact source tag, artifact checksum, image digest, control-pack digest and
   organization-owned configuration used for the run.

Steps involving live infrastructure are intentionally outside automated repository tests because
they require organization-owned identities, credentials, endpoints and change authority. Never use
production credentials, personal data or customer systems to satisfy pilot acceptance.

## Explicitly unsupported

- production traffic or production personal data;
- production use of the PostgreSQL adapter without deployment-owned migration, TLS, backup,
  restore and SLO evidence;
- SaaS multi-tenancy or tenant-wide record discovery;
- state-changing enterprise connectors or model continuation with tool results;
- product-grade OIDC/RBAC for the operator surface;
- a guarantee of provider behavior, regulatory compliance or legal correctness.

The PostgreSQL transactional adapter, migrations and role-bound Ed25519 operator verifier now
provide the application boundary for multi-replica execution with public-key-only runtime
authority. Production readiness still requires organization-owned validation of those adapters,
trust-store distribution/rotation, deployment-owned TLS/egress/secrets/backup controls,
operational SLOs and incident exercises.
