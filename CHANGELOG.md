# Changelog

All notable changes to **Regulated AI Control Plane** will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project intends to use [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once tagged releases begin.

The project is currently **pre-alpha**. Until the first release, breaking changes may occur under `Unreleased`.

## [Unreleased]

### Added

- Initial product definition for a multi-provider regulatory control plane for enterprise AI.
- Brazilian regulated-environment wedge focused initially on financial services.
- Product architecture separating control plane and enforcement plane.
- Three-layer governance model: `authoritative source -> human-reviewed control objective -> executable technical policy`.
- Initial decision model: `ALLOW`, `ALLOW_WITH_TRANSFORMATION`, `REQUIRE_APPROVAL`, `DENY`.
- Initial obligation model: `REMOVE_FIELD`, `MASK`, `TOKENIZE`, `PSEUDONYMIZE`, `REQUIRE_PROVIDER_CAPABILITY`, `REQUIRE_HUMAN_APPROVAL`, `RESTRICT_TOOL`, `REQUIRE_EVIDENCE`.
- Provider Capability Registry concept with versioned capability facts, authoritative sources, verification dates and `supported`, `unsupported`, `conditional`, `unknown` states.
- Initial provider capability examples for OpenAI Responses API and Amazon Bedrock.
- Initial Brazilian financial-services demo policy.
- Metadata-only evidence model.
- Threat model covering policy bypass, provider downgrade, stale capability data, sensitive-data leakage, evidence tampering and authority-boundary failures.
- Deterministic evaluation strategy and initial scenario-eval plan.
- Initial ADRs for control-plane/enforcement-plane separation, regulation-to-control-objective mapping and metadata-only evidence.
- Initial English and Brazilian Portuguese project documentation.
- Security policy and private vulnerability-reporting guidance.
- MIT license.
- Bootstrap baseline based on `brunovicco/codex-python-engineering-harness`.

### Planned

- Domain model implementation.
- Versioned YAML policy loader.
- Versioned provider-capability registry loader.
- Deterministic CPF/CNPJ/secret classification.
- `EvaluateAiOperation` application use case.
- Metadata-only evidence persistence.
- Phase 1 HTTP API: `POST /v1/evaluations`, `GET /v1/evidence/{evidence_id}`, `GET /v1/providers`.
- Scenario-based regression evals.
- Local transformation enforcement.
- OpenAI and Amazon Bedrock execution adapters behind an `InferenceExecutionPort`.
- Integration path with `governed-llm-gateway`.
- Human-approval workflow and agent-authority controls.

### Security

- Defined fail-closed behavior for mandatory unknown/stale provider capabilities.
- Defined prohibition on raw prompts, model responses, credentials and personal-data values in evidence.
- Defined provider fallback as unable to weaken mandatory policy.
- Defined policy decisions as deterministic and external to model output.
