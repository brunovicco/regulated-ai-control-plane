# ADR-0004: Use strict versioned YAML and metadata-only SQLite for Phase 1

## Status

Accepted

## Date

2026-09-23

## Context

Phase 1 needs reproducible local policy and provider-capability inputs plus durable evidence, while
remaining runnable without cloud credentials or network access. Domain and application code must
not depend on YAML, Pydantic, SQL, provider SDKs or transport frameworks. Configuration errors must
fail closed, and the evidence store must not become a second repository of prompts or personal
data.

## Decision

Use versioned YAML files as curated control-plane inputs and parse them only in adapters with
`yaml.safe_load` followed by strict Pydantic boundary models that forbid unknown fields. Reject
unknown schema versions, malformed records, duplicate identifiers and mixed provider-registry
versions before serving evaluation traffic.

Use a stdlib SQLite adapter for Phase 1 evidence. Persist only the fields allowlisted by the
framework-free `EvidenceMetadata` domain type: identifiers, UTC time, outcomes, classification and
obligation labels, policy/control/provider references, reason codes and SHA-256 digests. Do not
persist request field values, prompts, responses, tool payloads or credentials.

## Alternatives considered

- Keep the example YAML files unvalidated and parse dictionaries inside the evaluator: rejected
  because schema ambiguity would enter the application layer and invalid data could weaken policy.
- Introduce a general-purpose policy engine such as OPA/Rego: rejected as outside Phase 1 and
  unnecessarily broad for the intentionally small policy syntax.
- Use a database ORM or external database: rejected because it adds infrastructure and dependency
  surface without improving the local evaluation-only slice.
- Store evidence only in memory: rejected because the HTTP evidence endpoint and local audit demo
  need durable records across requests.

## Consequences

The service is deterministic and network-independent for the checked-in policy/registry versions,
and adapter contract tests can reject malformed input before evaluation. YAML schema evolution now
requires explicit version handling. SQLite is appropriate for local/demo use but does not provide
the access control, replication, append-only guarantees or scale expected of a production ledger.

## Security and privacy impact

Safe YAML loading and forbidden extra fields prevent executable YAML objects and silent schema
confusion. Provider sources must be HTTPS URLs, but their contents are not fetched by the runtime.
The SQLite schema is metadata-only; stable digests permit comparison without retaining raw values.
Correlation and logical identifiers accepted over HTTP are restricted to bounded identifier
syntax. The evidence database still requires filesystem access controls and lifecycle management.

## Operational impact

Startup validates all packaged records and fails when control-plane inputs are invalid. The local
database defaults to `var/regulaai-evidence.sqlite3` and can be relocated with
`REGULAAI_EVIDENCE_DB`. Operators must back up, retain and delete that file according to their
metadata policy. Provider verification dates can cause high-assurance requirements to fail closed
once the policy-defined freshness limit is exceeded.

## Follow-up

- Add signed policy/registry bundles and explicit release promotion in a later control-plane slice.
- Replace or wrap SQLite with an append-only, access-controlled evidence backend for production.
- Define retention/deletion and backup procedures before processing production correlation data.
- Add migration notes whenever a YAML schema version changes.
