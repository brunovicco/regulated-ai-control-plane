# Read-only enterprise sandbox connector

Phase 7b adds one opt-in HTTP connector for the trusted `cards.read` tool. It exists to prove the
enterprise authority boundary against an organization-controlled sandbox without enabling generic
HTTP tools or state-changing integrations.

Mock tool execution remains the default. The connector is selected only with:

```text
REGULAAI_TOOL_EXECUTION_MODE=read_only_http
```

The endpoint, credential and workload identity documented in `.env.example` are then required;
timeout and size limits have bounded defaults. Credentials must be injected by an approved secret
mechanism; never place them in an env file, shell history, command argument, log, screenshot or
repository.

## Downstream contract

The configured endpoint receives exactly one `POST` with `Content-Type: application/json`, bearer
authentication and the already approved idempotency key. The canonical body is:

```json
{
  "action_id": "act_...",
  "arguments": {"account_token": "tok_..."},
  "tool": "cards.read",
  "workload_identity": "workload.cards-sandbox"
}
```

The sandbox must return HTTP 200 and `application/json` with exactly:

```json
{
  "action_id": "act_...",
  "execution_id": "sandbox-read-...",
  "output": {
    "card_status": "ACTIVE",
    "internal_reference": "synthetic-reference",
    "diagnostic": "synthetic-diagnostic"
  }
}
```

RegulaAI binds `action_id`, validates `execution_id`, rejects duplicate/extra envelope fields and
passes `output` to the existing closed catalog schema. Only the status enum is returned directly;
the financial reference is masked and diagnostics are dropped. Raw output is ephemeral and never
persisted.

## Security and operations

- only `cards.read` with catalog risk `read_only` is accepted;
- the request workload identity must exactly match deployment configuration;
- all actions still require separate `ra2` approval after an atomic execution claim;
- HTTPS is required except for literal loopback HTTP used by local sandboxes;
- userinfo, query strings, fragments and redirects are rejected;
- environment proxy settings are ignored and TLS verification remains enabled;
- compressed responses are refused so the response limit applies to received JSON bytes;
- request/response sizes and one transport timeout are bounded;
- RegulaAI performs no connector retry or fallback;
- non-200, malformed, oversized, timeout and transport outcomes become
  `RECONCILIATION_REQUIRED` because authority has already been consumed and the remote outcome may
  be ambiguous;
- schema-invalid output becomes `RESULT_REJECTED` and is never supplied to a model.

Deployment must enforce DNS, certificate, destination-IP and egress allowlists for the exact
sandbox service. The endpoint is configuration, not request input, but a compromised configuration
or DNS path can still redirect approved data. The Kubernetes reference denies egress by default;
enable only the specific destination in a separately reviewed overlay.

This connector does not establish production readiness, downstream correctness, continuous
availability or permission to enable state-changing tools.
