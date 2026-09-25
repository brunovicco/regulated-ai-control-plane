# Regulated AI Control Plane

[![Python 3.13-3.14](https://img.shields.io/badge/Python-3.13--3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Pre-Alpha](https://img.shields.io/badge/status-pre--alpha-orange)](#project-status)

> Multi-provider regulatory control plane for enterprise AI, starting with LGPD, ANPD and Brazilian financial-services requirements.

[Português (Brasil)](README.pt-BR.md)

## Overview

**Regulated AI Control Plane** is an infrastructure project for applying organization-approved privacy, security, regulatory and authority controls at the AI execution boundary.

The initial product wedge is Brazil and regulated financial-services environments. The project is designed to sit between enterprise applications or agents and AI providers. It evaluates runtime context, resolves provider capabilities, applies deterministic policy, produces obligations such as data transformation or human approval, and records metadata-only evidence about the decision.

```text
Enterprise Application/Agent
            |
            v
+-------------------------------+
| Regulatory Enforcement Point  |
|-------------------------------|
| Data classification           |
| Policy evaluation             |
| Provider capability checks    |
| Transformation requirements   |
| Tool/action authority       |
| Evidence generation           |
+-------------------------------+
            |
            v
    Inference Execution Port
            |
      +-----+-----+------+
      |           |      |
   OpenAI      Bedrock  Future
```

The first implementation phase intentionally stops **before live model inference**. The goal is to prove the deterministic decision, enforcement and evidence contracts before adding provider SDKs or model routing.

## Why this project exists

Enterprise AI adoption in regulated environments involves more than access to an LLM. A production architecture may need to coordinate data classification and minimization, international-transfer policy, provider/service/region capabilities, identity and authority boundaries, tool permissions, human approval, retention, observability and audit evidence.

Cloud and model providers expose many of these capabilities, but behavior varies by provider, service, endpoint, region and customer configuration. Organizations also need their own reviewed policies to remain portable across providers.

This project explores a control layer above those providers.

## Core model

A central design rule is that regulatory text is **not executed directly**.

```text
Authoritative source
        |
        v
Human-reviewed control objective
        |
        v
Executable enterprise policy
        |
        v
Technical enforcement
        |
        v
Metadata-only evidence
```

The project does not make legal determinations and does not return results such as `"lgpd_compliant": true`.

## Initial scope

- **Jurisdiction:** Brazil
- **Sector:** financial services
- **Regulatory baseline:** LGPD, ANPD international-transfer regulation, selected CMN/BCB cybersecurity and cloud-contracting requirements
- **Provider capability examples:** OpenAI API and Amazon Bedrock
- **Decision outcomes:** `ALLOW`, `ALLOW_WITH_TRANSFORMATION`, `REQUIRE_APPROVAL`, `DENY`
- **Evidence:** metadata-only, versioned and reproducible

Initial obligations include:

- `REMOVE_FIELD`
- `MASK`
- `TOKENIZE`
- `PSEUDONYMIZE`
- `REQUIRE_PROVIDER_CAPABILITY`
- `REQUIRE_HUMAN_APPROVAL`
- `RESTRICT_TOOL`
- `REQUIRE_EVIDENCE`

## Project status

**Pre-alpha with deterministic evaluation, local enforcement, digest-bound decision/action
approval, trusted tool proposals/results and an opt-in governed-gateway execution adapter.**

Current local flow:

```text
Context
  -> Classification
  -> Policy matching
  -> Provider capability resolution
  -> Decision
  -> Obligations
  -> Local transformations
  -> Metadata-only transformation receipts
  -> External approval verification/one-time consumption when required
  -> Persisted PREPARED enforcement state
  -> Network-silent mock (default) or governed gateway (opt-in)
  -> Exact tool-proposal validation and action-specific approval
  -> Network-silent tool execution mock
  -> Closed output validation and ephemeral safe result
  -> Metadata-only operator timeline and attention codes
  -> Append-only local lifecycle history with explicit migration baselines
  -> Metadata-only operator control and sanitized approval context
  -> Digest-bound provider source and freshness snapshots
  -> Exact-ID server-rendered operator dashboard
  -> Signed policy/provider pack verification before startup composition
```

The service exposes `POST /v1/evaluations`, `GET /v1/evidence/{evidence_id}`,
`POST /v1/enforcements`, `GET /v1/enforcements/{enforcement_id}`,
`POST /v1/enforcements/{enforcement_id}/tool-actions`, `GET /v1/tool-actions/{action_id}`,
`GET /v1/operator/enforcements/{enforcement_id}/timeline`,
`GET /operator?enforcement_id={enforcement_id}`, `GET /v1/providers` and `GET /health`. It
verifies a signed policy/provider pack and validates its versioned YAML records at startup,
applies transformations
inside the local trust boundary and stores only metadata evidence in SQLite. It still stops before
real provider inference unless gateway mode is explicitly configured. Gateway mode uses bounded
timeouts, performs no local retry, discards model output and accepts only tool definitions resolved
from the versioned organization catalog. Returned tool calls remain unauthorized proposals until
their exact arguments are resubmitted, validated and approved using separate action authority.
Phase 4d validates untrusted mock results against closed catalog schemas, masks or drops classified
fields and returns the minimized result only on the immediate successful response. Raw and safe
result content are not persisted or recoverable on replay. Tool execution remains network-silent.
Approval assertions are issued
outside the service, bound to the decision digest, accepted only ephemerally and consumed once
before execution.

Phase 6a binds the packaged policy/provider release to SHA-256 file digests and an Ed25519
signature selected from a local public-key trust store. Any digest, signature, key, composition or
path failure prevents startup. Only public verification material is packaged; release private keys
must remain in an organization-owned offline boundary. Signature validity establishes release
authenticity, not policy correctness, provider freshness or compliance.

Not implemented in the first slice:

- direct provider SDK adapters;
- completion-returning API behavior;
- live enterprise-system tool adapters and returning tool results to a model;
- LLM-based policy judging;
- global operator discovery and administrative dashboard actions;
- SaaS multi-tenancy;
- automated ingestion of regulatory text;
- full DLP;
- production legal/compliance certification.

See [docs/MVP_ROADMAP.md](docs/MVP_ROADMAP.md).

## Architecture principles

### Deterministic policy enforcement

A model must never decide whether a security, privacy or regulatory policy applies. The same normalized input and the same policy/provider-registry versions must produce the same decision.

### Fail closed

Mandatory controls do not silently degrade.

```text
mandatory provider capability = unknown
    -> fail closed

high-assurance capability fact = stale
    -> fail closed

fallback provider weakens mandatory control
    -> reject fallback
```

### Provider capability intelligence

Provider behavior is represented as versioned, source-backed facts. Each record includes provider, service, region when applicable, capability state, conditions, authoritative source URLs, verification date and record version.

Capability states are:

```text
supported
unsupported
conditional
unknown
```

`unknown` is a valid and important state.

### Metadata-only evidence

Evidence may contain decisions, reason codes, classification labels, policy and registry versions, obligation types, timestamps and cryptographic digests.

Evidence must not contain raw prompts, raw model responses, personal-data values, credentials, API keys, tokens or unredacted tool payloads.

### Provider portability

The architecture keeps regulatory and enterprise policy above the inference provider. The first
real execution adapter integrates with
[`governed-llm-gateway`](https://github.com/brunovicco/governed-llm-gateway) instead of duplicating
routing, resilience, provider credentials and provider normalization. It is opt-in; mock mode is
the default.

## Decision precedence

```text
DENY
  >
REQUIRE_APPROVAL
  >
ALLOW_WITH_TRANSFORMATION
  >
ALLOW
```

A lower-severity decision must never override a stronger restriction.

## Repository structure

```text
regulated-ai-control-plane/
├── AGENTS.md
├── README.md
├── README.pt-BR.md
├── SECURITY.md
├── LICENSE
├── CHANGELOG.md
├── SOURCES.md
├── docs/
│   ├── PROJECT_CONTEXT.md
│   ├── PRODUCT_VISION.md
│   ├── PRODUCT_ARCHITECTURE.md
│   ├── DOMAIN_MODEL.md
│   ├── REGULATORY_BASELINE_BR.md
│   ├── PROVIDER_CAPABILITY_REGISTRY.md
│   ├── POLICY_MODEL.md
│   ├── API_CONTRACT.md
│   ├── THREAT_MODEL.md
│   ├── EVAL_STRATEGY.md
│   ├── MVP_ROADMAP.md
│   └── ADRs/
├── examples/
│   ├── policies/
│   ├── provider-capabilities/
│   └── scenarios/
├── governance/
├── src/
└── tests/
```

## Development baseline

This repository is bootstrapped from [`brunovicco/codex-python-engineering-harness`](https://github.com/brunovicco/codex-python-engineering-harness).

Requirements:

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/)

Install and run the repository quality gate:

```bash
uv lock --check
uv sync --frozen --all-groups --extra observability
uv run python scripts/quality_gate.py
```

Run the local API:

```bash
uv run uvicorn regulated_ai.entrypoints.api:app --host 127.0.0.1 --port 8000
```

See [docs/DEMO.md](docs/DEMO.md) for a synthetic end-to-end request, expected obligations and
evidence inspection.

The generated engineering contract in `AGENTS.md` is authoritative for development workflow, architecture, testing and security rules.

## Documentation

Start with:

- [Project context](docs/PROJECT_CONTEXT.md)
- [Product vision](docs/PRODUCT_VISION.md)
- [Product architecture](docs/PRODUCT_ARCHITECTURE.md)
- [Domain model](docs/DOMAIN_MODEL.md)
- [Brazilian regulatory baseline](docs/REGULATORY_BASELINE_BR.md)
- [Provider Capability Registry](docs/PROVIDER_CAPABILITY_REGISTRY.md)
- [Policy model](docs/POLICY_MODEL.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Evaluation strategy](docs/EVAL_STRATEGY.md)
- [MVP roadmap](docs/MVP_ROADMAP.md)
- [Primary sources](SOURCES.md)

## Security

Do not use real customer data, production credentials or production secrets in development, examples or tests. See [SECURITY.md](SECURITY.md).

## Regulatory and legal boundary

This project is an engineering reference and control-plane implementation. It does **not** provide legal advice, regulatory certification or a guarantee of compliance with LGPD, ANPD rules, CMN/BCB regulation, ISO/IEC 42001, NIST guidance or any other framework.

Regulatory and framework mappings describe how technical controls may support an organization-approved control objective. Applicability and interpretation remain the responsibility of qualified organizational stakeholders.

## License

Licensed under the [MIT License](LICENSE).

## Author

**Bruno Vicco**
Generative AI Engineering · AI Platforms · Agentic Security · Governance
