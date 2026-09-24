# ADR-0006: Use the governed gateway as the first real execution adapter

## Status

Accepted.

## Date

2026-09-24.

## Context

Phase 2 proves that RegulaAI applies required transformations before an execution port can observe
the payload. Phase 3 needs a real execution boundary, but this repository must not copy provider
credential handling, model routing, retry, fallback, streaming normalization or provider-specific
resilience already owned by `governed-llm-gateway`.

The gateway publishes a thin typed consumer SDK directly from its Git repository. It accepts a
provider-neutral workload, risk level, data classification and sanitized messages, performs one
bounded client request, and returns normalized routing and execution provenance. The package is not
published to PyPI at this time.

## Decision

Add an opt-in `GovernedGatewayExecutionAdapter` behind the existing synchronous
`InferenceExecutionPort`. Pin the gateway client to the reviewed commit
`751dda744fcb0ecadbf2aac7ce1c48b29334de17` and permit the direct reference explicitly in Hatch
metadata.

Gateway mode requires an explicit URL, gateway credential, workload, allowed RegulaAI provider
target and expected terminal provider. Mock execution remains the default. The first adapter:

- sends one canonical text message containing only the locally sanitized data;
- maps RegulaAI assurance and data labels conservatively to gateway risk/classification metadata;
- rejects tools because RegulaAI does not yet have a complete tool-schema/approval execution
  contract;
- configures separate transport and provider timeouts;
- performs no local retry or fallback;
- atomically advances enforcement state from `PREPARED` to `DISPATCHED` before external I/O, so
  concurrent/replayed requests do not duplicate an uncertain execution;
- requires terminal success and matching provider provenance;
- discards response content and persists only allowlisted routing/execution metadata.

The configured gateway workload must authorize only deployments compatible with the provider
target already evaluated by RegulaAI. Terminal provider validation is a defensive assertion, not a
substitute for correct gateway policy configuration.

## Alternatives considered

- Add direct OpenAI and Bedrock SDK adapters first: rejected for this slice because it would put
  provider credentials, translation and resilience in every consumer and duplicate gateway work.
- Implement the gateway SSE protocol locally: rejected because the existing SDK already owns
  bounded parsing, request binding, response validation and sanitized transport errors.
- Install an unpinned gateway branch: rejected because a moving supply-chain input would make
  builds and reviews non-reproducible.
- Return model content from the enforcement endpoint: deferred because the current public API is a
  metadata-only enforcement/evidence surface.

## Consequences

RegulaAI can now execute a sanitized, text-only request through a real provider-neutral gateway
without receiving provider credentials. The runtime gains a Git-pinned Apache-2.0 dependency and
an explicit opt-in deployment configuration. Gateway operation is not available for plans with
tools, and the endpoint still does not return model output.

## Security and privacy impact

The gateway credential is read only from the environment, excluded from representations and never
persisted or logged. The SDK rejects unsafe remote HTTP URLs, userinfo, query strings and fragments;
only HTTPS or literal loopback HTTP is accepted. Raw source values remain outside evidence, while
sanitized values and model output exist ephemerally in memory during the request. A mismatched
provider, malformed response, timeout, transport failure or unsupported plan fails closed.

Provider/model/deployment, gateway request/routing identifiers, policy identifiers, latency,
attempt/fallback indexes and cache state are metadata and may be persisted. Prompts, completions,
provider response bodies, credentials and provider request identifiers are not persisted.

## Operational impact

Deployments select `REGULAAI_EXECUTION_MODE=gateway` and provide the reviewed gateway binding.
Startup fails for partial or unsafe configuration. The gateway workload and its authorized model
group must be reviewed together with the RegulaAI target configuration. The client makes one
request; gateway-owned retry/fallback remains constrained by gateway authorization. An interrupted
`DISPATCHED` record is intentionally not retried automatically and requires operational
reconciliation. `EXECUTION_FAILED` is also terminal for automatic replay because transport and
timeout failures may be ambiguous after provider processing.

## Follow-up

- Add an end-to-end composition proof against a local gateway deployment without production data.
- Define the completion-returning product contract separately from metadata-only enforcement.
- Add approval and tool-schema authority before forwarding tool definitions.
- Add additional reviewed workload/target bindings, including Bedrock-backed deployments.
