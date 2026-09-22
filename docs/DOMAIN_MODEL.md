# Domain model

## EvaluationContext

Represents business/runtime context without transport concerns.

Suggested fields:
- `correlation_id`
- `jurisdiction`
- `sector`
- `purpose`
- `operation_kind`
- `data_items`
- `requested_provider`
- `requested_tools`
- `policy_set_version`
- `assurance_level`

The context must be normalized before evaluation.

## DataItem

A value should not need to survive into evidence.

Suggested runtime-only fields:
- logical field name;
- raw value (ephemeral in memory);
- caller-supplied labels;
- detected labels.

Suggested classification labels:
- `PERSONAL_DIRECT_IDENTIFIER`
- `BRAZIL_CPF`
- `BRAZIL_CNPJ`
- `FINANCIAL_ACCOUNT_IDENTIFIER`
- `FINANCIAL_TRANSACTION_DATA`
- `AUTHENTICATION_SECRET`
- future `HEALTH_DATA`
- future `BIOMETRIC_DATA`

Do not claim semantic detection where the engine only knows caller metadata.

## ProviderTarget

Identifies the intended execution surface:
- provider;
- service;
- optional region;
- optional model family;
- requested processing mode.

Examples:
- `openai / responses_api`
- `aws / bedrock_runtime / sa-east-1`

## ProviderCapability

A source-backed fact.

Required semantic fields:
- `key`
- `state`: `supported | unsupported | conditional | unknown`
- `conditions`
- `source_urls`
- `verified_at`
- `record_version`

`conditional` must include machine-readable or reviewable conditions.

## RegulatorySourceRef

Reference only; not executable:
- `source_id`
- issuing authority;
- document identifier;
- article/section if known;
- canonical URL;
- effective/verified metadata.

## ControlObjective

Organization-approved objective.

Examples:
- minimize personal data before external processing;
- use only provider configurations approved for a required processing geography;
- preserve traceability of AI decisions;
- require approval before high-impact state changes.

A control objective may have several regulatory/security/internal sources.

## PolicyRule

Matches runtime context and emits:
- decision contribution;
- obligations;
- required capability predicates;
- control-objective references;
- support mappings.

Policy rules are organization policy, not raw law.

## Obligation

First MVP types:
- `REMOVE_FIELD`
- `MASK`
- `TOKENIZE`
- `PSEUDONYMIZE`
- `REQUIRE_PROVIDER_CAPABILITY`
- `REQUIRE_HUMAN_APPROVAL`
- `RESTRICT_TOOL`
- `REQUIRE_EVIDENCE`

An obligation includes:
- type;
- target;
- parameters;
- control-objective ids;
- reason code.

## Decision

Top-level:
- `ALLOW`
- `ALLOW_WITH_TRANSFORMATION`
- `REQUIRE_APPROVAL`
- `DENY`

Precedence:
`DENY > REQUIRE_APPROVAL > ALLOW_WITH_TRANSFORMATION > ALLOW`.

Suggested fields:
- outcome;
- obligations;
- matched policy ids/versions;
- capability facts used;
- reason codes;
- evidence id;
- policy-set version;
- provider-registry version.

## EvidenceRecord

Metadata only.

Allowed:
- ids;
- UTC timestamps;
- classification labels;
- decision;
- obligation types;
- source/control/policy/provider record ids and versions;
- cryptographic digest of canonical normalized context;
- digest chaining metadata.

Forbidden:
- raw prompt;
- raw response;
- raw personal data;
- secrets/tokens/credentials;
- unredacted tool payload;
- full provider request/response.

## Domain invariants

- Unknown capability cannot satisfy mandatory requirement.
- Stale capability cannot satisfy a high-assurance requirement.
- Required transformation precedes provider execution.
- A `DENY` cannot be overridden by another matching policy.
- Human approval is explicit state, never inferred from model output.
- Evidence creation is part of a successful evaluation.
- Same normalized input + same versioned knowledge yields same decision.
