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

The default runtime intentionally stops **before live model inference**. An explicit non-production
pilot can prove one fixed-synthetic call through the governed gateway after the deterministic
decision, enforcement and evidence contracts are configured.

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
  -> Signed policy/provider/tool-catalog pack verification before startup composition
  -> Offline semantic impact analysis between verified pack releases
  -> Fixed-clock metadata-only scenario replay across verified releases
  -> Digest-bound provider capability review before separate pack signing
  -> Digest-bound policy regulatory review before separate pack signing
  -> Verified static/replay/review evidence bundle for external promotion decisions
  -> Signed role-bound promotion quorum for the exact complete evidence bundle
  -> Signed reviewer authority for updates, onboarding and removal
  -> Signed tool-catalog diff, metadata-only replay and release review
```

The service exposes `POST /v1/evaluations`, `GET /v1/evidence/{evidence_id}`,
`POST /v1/enforcements`, `GET /v1/enforcements/{enforcement_id}`,
`POST /v1/enforcements/{enforcement_id}/tool-actions`, `GET /v1/tool-actions/{action_id}`,
`GET /v1/operator/enforcements/{enforcement_id}/timeline`,
`GET /operator?enforcement_id={enforcement_id}`, `GET /v1/providers` and `GET /health`. It
verifies a signed policy/provider/tool-catalog pack and validates its versioned YAML records at startup,
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

Phase 6b compares an approved base and candidate only after both pass the same trust store. Its
offline JSON report classifies potential decision, evidence and governance impact, correlates
changed provider capabilities with dependent policy rules and flags version reuse or signing-key
changes. It is conservative review support, not exhaustive behavioral equivalence or release
authority.

Phase 6c replays a separately governed, metadata-only scenario suite against both verified
releases at one fixed timestamp. It reports observed decision, obligation and evidence changes,
binds the exact suite bytes by digest and can fail CI on decision impact. The finite corpus contains
classification labels but no values and does not prove equivalence or authorize promotion.

Phase 6d adds an offline pre-signing gate for provider capability updates. A strict review record
binds the authenticated base, exact candidate bytes, provider target, review date, reviewer role and
source conclusions for every capability. Missing, contradicted, inconclusive, stale-date or
unversioned reviews are blocked. Passing confirms bounded record consistency only; it does not
authenticate a reviewer, retrieve sources, sign or promote a release, or prove provider behavior.

Phase 6e adds an offline pre-signing gate for updates to an existing policy set. It binds the
authenticated base and exact candidate bytes, requires review of every changed rule and exact
control-objective/regulatory-support mapping, and fails closed on missing, rejected or
revision-needed conclusions. Rules without regulatory references must be marked
`NOT_APPLICABLE`, keeping enterprise authority policy distinct from regulatory requirements.
Passing does not retrieve or interpret legal text, authenticate the reviewer, sign or promote a
release, or assert compliance.

Phase 6f composes one deterministic release-evidence bundle from a verified base/candidate pair,
the exact scenario suite and any required provider/policy review records. It recomputes diff and
replay, re-runs reviews against authenticated candidate bytes and reports missing, blocked or
unsupported review transitions. `EVIDENCE_COMPLETE` is evidence consistency, not impact acceptance,
signing authority, promotion approval or a compliance result.

Phase 6g verifies organization-owned Ed25519 promotion attestations against a separate public-key
trust store and explicit required-role/distinct-key quorum policy. Every vote binds the exact
complete Phase 6f bundle, candidate pack digest and canonical promotion-policy digest and must be
active at an explicit UTC evaluation time. `PROMOTION_AUTHORIZED` is a signed-quorum handoff result
only; the workflow never signs the pack, mutates a repository, promotes, distributes or deploys a
release, or asserts safety or compliance.

Phase 6h authenticates release-review roles through a separate Ed25519 public-key trust store that
limits each key by artifact kind and change type. Modified entities must still pass the detailed
Phase 6d/6e review and the signature binds that exact review digest. Whole policy/provider additions
and removals are governed by signed whole-entity digests from the candidate or approved base. This
establishes reviewer attribution and lifecycle coverage, not legal correctness, provider truth,
promotion authority or deployment permission.

Phase 6i includes exactly one trusted tool catalog in every signed control pack. Runtime parsing,
static diff, metadata-only replay and release evidence all use the same digest-verified catalog
bytes. Catalog changes are visible as semantic impact and require a signed whole-catalog review.
This authenticates tool definitions for evaluation only; it does not authorize arguments, execute
tools or prove downstream implementation behavior.

Phase 6j upgrades release, reviewer and promotion trust stores to lifecycle-aware schema version 2.
Every public key has an activation instant, optional expiry and explicit `ACTIVE`, `RETIRED` or
`REVOKED` state. Inactive or out-of-window keys fail closed before their signatures can grant
authority. Private-key custody and trust-store distribution remain external operations.

Phase 6k creates and verifies a local content-addressed custody package for the complete evidence
bundle, authorized promotion report, attestations and public trust snapshots. It rejects private-key
PEM material, never overwrites an archive and detects changed or untracked files. The package is
tamper-evident local retention, not immutable storage, trusted timestamping or backup.

Phase 6l adds a digest-bound detailed gate for every changed trusted-tool definition. Each change
requires an accountable non-personal owner role, HTTPS implementation references, the exact change
type and an approving conclusion; schema changes must advance the tool schema version. Modified
catalog attestations must bind the passing detailed result before release evidence is complete. The
gate is network-silent and does not validate or execute the referenced implementation.

Phase 6m creates monotonic lineage checkpoints for exact public trust-store bytes. Successors bind
the prior checkpoint and reject identity changes, sequence gaps, non-increasing time and unchanged
content. Each checkpoint is Ed25519-signed, and verification requires a pinned distribution public
key plus a deployment-pinned digest, minimum sequence or exact predecessor,
so a newly distributed package cannot establish its own rollback floor. This does not distribute
keys, provide trusted time or protect an anchor that is replaced with the package.

Phase 6n verifies signed consumer acknowledgements for one exact checkpoint against an explicit
allowed/required target policy and distinct-target quorum. It rejects duplicate targets/keys and
cross-checkpoint or future receipts. The result is rollout evidence only: it neither distributes
the trust store nor proves that a running process loaded it.

Phase 6o verifies fresh signed target assertions for the exact trust-store digest bound to that
checkpoint. Required targets, quorum and maximum age fail closed at an explicit UTC evaluation
time. This remains offline evidence: it does not implement probes or prove continuous enforcement.

Phase 6p verifies provider-neutral signed time-authority receipts for exact release/trust artifact
bytes. It enforces explicit artifact kind, authority/key lifecycle and caller-pinned time bounds,
without claiming RFC 3161 compatibility, acquiring receipts or selecting a timestamp provider.

Phase 6q adds interoperable offline RFC 3161 verification for an original DER request and response.
It binds the exact artifact imprint, nonce and allowlisted policy, then delegates CMS signature,
timestamping EKU and PKIX-chain verification at the asserted time to OpenSSL. Timestamp acquisition,
provider selection, online revocation and long-term evidence renewal remain deployment concerns.

Phase 6r packages allowlisted metadata evidence in a deterministic OCI image layout. Canonical
index, manifest and config documents bind normalized package references and content-addressed
SHA-256 layers, while offline verification rejects changed, missing or untracked content. Registry
transport, access control, artifact signing and retention remain external deployment controls.

Phase 6s adds a non-applied Kubernetes/OpenShift Kustomize reference for the control-plane service
and periodic runtime trust-state verifier. It pins the image through the Kustomize digest field,
mounts authority from external PVC/ConfigMap/Secret objects, uses restricted non-root contexts and
denies egress by default. The SQLite reference intentionally remains a single replica.

Phase 6t emits allowlisted control lifecycle metadata as CloudEvents 1.0 structured envelopes and,
when explicitly configured, correlates them with bounded OTLP spans. Prompt/response/tool content,
credentials, arbitrary attributes and baggage are excluded. With no endpoint, no exporter or
network path is created; observability failure never changes a policy result.

Phase 7a adds an opt-in live composition pilot for one fixed synthetic financial-services request.
It reuses the complete enforcement path, proves local tokenization before a reviewed non-production
gateway/provider call, validates the operator timeline and emits a metadata-only report. It accepts
no arbitrary prompt, provider, tool or credential arguments and does not return model output. See
[the live composition pilot runbook](docs/LIVE_COMPOSITION_PILOT.md).

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
- [Verification-key lifecycle](docs/TRUST_KEY_LIFECYCLE.md)
- [Release artifact custody](docs/RELEASE_CUSTODY.md)
- [Live composition pilot](docs/LIVE_COMPOSITION_PILOT.md)
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
