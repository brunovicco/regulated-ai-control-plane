# Privacy and data handling

Complete this document before processing personal or regulated data.

## Data inventory

| Data category | Source | Purpose | Legal/contractual basis | Destination | Retention | Deletion method |
|---|---|---|---|---|---|---|
| Evaluation evidence metadata | Evaluation API | Reproduce policy decisions without content retention | Organization-defined | Local SQLite evidence store | Organization-defined; configure before production | Delete/rotate the configured database under an approved evidence-retention procedure |
| Approval consumption metadata | External approval workflow | Prove scoped human authority and prevent replay | Organization-defined | Local SQLite evidence store | Organization-defined; configure before production | Delete/rotate under the same approved evidence-retention procedure |
| Tool-action metadata | Tool-action API | Prove exact action authority and execution state without retaining payloads | Organization-defined | Local SQLite evidence store | Organization-defined; configure before production | Delete/rotate under the same approved evidence-retention procedure |
| Tool-result metadata | Tool execution port | Prove output-schema enforcement without retaining result content | Organization-defined | Local SQLite evidence store | Organization-defined; configure before production | Delete/rotate under the same approved evidence-retention procedure |

## Controls

- Data minimization: evidence stores only identifiers, labels, versions, outcomes, reason codes and
  cryptographic digests; raw field values are excluded.
- Approval assertions are ephemeral secrets and are never stored or returned. Approval receipts
  retain only the approval ID, pseudonymous actor ID, bound decision digest, enforcement ID and
  timestamps. Do not place names, email addresses or other personal data in either identifier.
- Access control:
- Encryption in transit:
- Encryption at rest:
- Masking/tokenization: Phase 2 executes field removal, fixed masking, HMAC tokenization and HMAC
  pseudonymization locally before any execution boundary. Receipts contain digests, never
  source or transformed values.
- Non-production data strategy: tests and examples use generated or explicitly synthetic values;
  tests assert that sentinels do not appear in evidence or errors.
- Logging and tracing restrictions: document any enabled backend, content-capture approval,
  redaction, retention, and access policy. Add and follow a backend-specific policy before enabling
  content-bearing tracing. Generic OpenTelemetry spans are metadata-only: custom attributes pass
  through a bounded allowlist and must never contain prompts, responses, credentials,
  authorization headers, personal data, arbitrary URLs, tool output, or production payloads.
  The public tracing wrappers enforce this policy for span and event attributes, operation names,
  status descriptions, and exception details. W3C baggage is not propagated by default.
- Data-subject deletion/anonymization: define evidence retention and correlation-id deletion
  handling before production use.
- External processors: none in the default mock mode. Opt-in gateway mode sends only the sanitized
  execution payload to the explicitly configured `governed-llm-gateway`, which may invoke an
  organization-authorized provider. Gateway/model response content remains ephemeral and is
  discarded by this service. Provider/model/deployment and bounded routing/execution provenance
  may be retained as evidence metadata.
- Tool definitions contain organization-owned names, descriptions and schemas. Model-produced and
  resubmitted arguments, idempotency keys, approval assertions and raw/safe tool output remain
  ephemeral. Phase 4d validates output fields against trusted classifications and applies
  `RETURN`, `MASK` or `DROP` before the immediate response. RegulaAI persists only trusted
  identities, statuses, approval metadata, schema/result digests, classifications and exposed
  field names. Execution still uses only a network-silent mock tool adapter.
- The Phase 5a operator timeline requires one exact enforcement ID and composes only metadata
  already allowlisted in evidence/enforcement/action records. It does not list activity globally or
  recover payloads. Deployments must protect this operator surface with their existing access and
  network controls until product authentication and tenant isolation are implemented.
- Incident-response owner:

## Prohibited logging

Secrets, authentication headers, personal identifiers, full financial identifiers, complete request/response payloads, prompts, and model outputs containing sensitive data.
