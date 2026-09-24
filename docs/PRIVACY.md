# Privacy and data handling

Complete this document before processing personal or regulated data.

## Data inventory

| Data category | Source | Purpose | Legal/contractual basis | Destination | Retention | Deletion method |
|---|---|---|---|---|---|---|
| Evaluation evidence metadata | Evaluation API | Reproduce policy decisions without content retention | Organization-defined | Local SQLite evidence store | Organization-defined; configure before production | Delete/rotate the configured database under an approved evidence-retention procedure |

## Controls

- Data minimization: evidence stores only identifiers, labels, versions, outcomes, reason codes and
  cryptographic digests; raw field values are excluded.
- Access control:
- Encryption in transit:
- Encryption at rest:
- Masking/tokenization: Phase 2 executes field removal, fixed masking, HMAC tokenization and HMAC
  pseudonymization locally before the mock execution boundary. Receipts contain digests, never
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
- External processors: none through Phase 2; evaluation and mock execution perform no provider or
  network call.
- Incident-response owner:

## Prohibited logging

Secrets, authentication headers, personal identifiers, full financial identifiers, complete request/response payloads, prompts, and model outputs containing sensitive data.
