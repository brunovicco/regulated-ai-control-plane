# State-changing enterprise sandbox connector

Phase 7d adds one opt-in HTTP connector for the trusted `cards.unblock` tool. It is a controlled,
non-production proof of state-changing enterprise authority after transactional persistence,
asymmetric operator authority and terminal reconciliation were implemented. It is not a generic
HTTP tool and it is rejected when `REGULAAI_ENVIRONMENT` is `prod` or `production`.

Mock tool execution remains the default. Select this connector only with:

```text
REGULAAI_TOOL_EXECUTION_MODE=state_change_http
```

The endpoint, bearer credential and workload identity documented in `.env.example` are required.
The credential must come from an approved secret mechanism and must never be stored in an env
file, shell history, command argument, log, screenshot or repository.

## Downstream contract

The configured endpoint receives exactly one `POST` with bearer authentication and the already
approved idempotency key in `Idempotency-Key`. The canonical body contains only:

```json
{
  "action_id": "act_...",
  "action_digest": "sha256:...",
  "arguments": {
    "account_token": "tok_...",
    "reason_code": "CUSTOMER_VERIFIED"
  },
  "idempotency_key_digest": "sha256:...",
  "tool": "cards.unblock",
  "workload_identity": "workload.cards-unblock-sandbox"
}
```

The sandbox must atomically bind the supplied idempotency key to the exact operation. A successful
first request or downstream idempotent replay returns HTTP 200 and exactly:

```json
{
  "action_id": "act_...",
  "action_digest": "sha256:...",
  "execution_id": "sandbox-unblock-...",
  "idempotency_key_digest": "sha256:...",
  "output": {
    "operation_status": "SUCCEEDED",
    "operation_reference": "synthetic-reference",
    "diagnostic": "synthetic-diagnostic"
  }
}
```

RegulaAI verifies the action ID, action digest and idempotency-key digest before accepting the receipt. The output
then crosses the existing signed, closed catalog schema: status is returned, the financial
reference is masked and diagnostics are dropped. Raw output and the idempotency key are never
persisted.

## Required operating controls

- Use a dedicated non-production endpoint and workload identity authorized only for
  `cards.unblock`.
- Issue a separate, exact-action approval only after the proposal and action digest are reviewed.
- Make the downstream idempotency store durable and enforce identical-result replay for the same
  key; reject the same key with different operation data.
- Permit one request only. RegulaAI performs no connector retry, redirect or fallback.
- Treat every timeout, transport failure, non-200 response or malformed response as ambiguous and
  investigate it before issuing a terminal reconciliation assertion.
- Never infer `NOT_EXECUTED` from a timeout alone and never re-run the original action from the
  reconciliation operation.
- Enforce DNS, certificate, destination-IP and egress allowlists outside the process.
- Exercise success, duplicate delivery, timeout-before-effect, timeout-after-effect, late success
  and conflicting-idempotency-key cases before any broader rollout.

HTTPS is mandatory except for a literal loopback IP used by a local sandbox. Environment proxies,
redirects and compressed responses are disabled; request/response bytes and timeout are bounded.

## Evidence boundary

Persisted action metadata already contains the action digest, SHA-256 idempotency-key digest,
approval receipt, execution ID, output digests and terminal status. Exact arguments, bearer
credentials, idempotency keys and raw or minimized results are excluded from persistence and logs.

Promotion beyond this non-production connector requires a new review of the concrete enterprise
system's identity, authorization, durable idempotency semantics, recovery evidence, availability,
data handling and incident procedures.
