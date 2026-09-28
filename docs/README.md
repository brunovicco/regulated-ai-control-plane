# RegulaAI documentation

RegulaAI is a regulatory control plane for enterprise AI. This documentation is organized around
what you want to understand or accomplish—not the order in which features were implemented.

## Choose your path

| Goal | Start here |
| --- | --- |
| Understand the product | [Project context](PROJECT_CONTEXT.md) → [Product vision](PRODUCT_VISION.md) |
| See the system in action | [Guided local demo](DEMO.md) |
| Evaluate the pilot | [Controlled pilot release profile](PILOT_RELEASE.md) → [Live composition pilot](LIVE_COMPOSITION_PILOT.md) |
| Understand the design | [Architecture](ARCHITECTURE.md) → [Product architecture](PRODUCT_ARCHITECTURE.md) |
| Integrate with the API | [API contract](API_CONTRACT.md) → [Domain model](DOMAIN_MODEL.md) |
| Review security and privacy | [Threat model](THREAT_MODEL.md) → [Privacy model](PRIVACY.md) |
| Operate the service | [Kubernetes/OpenShift reference](KUBERNETES_DEPLOYMENT.md) → [Observability](LLM_OBSERVABILITY.md) |
| Review governance evidence | [Policy model](POLICY_MODEL.md) → [Release custody](RELEASE_CUSTODY.md) |

## Product and policy

- [Project context](PROJECT_CONTEXT.md): mission, vocabulary, invariants and first customer story.
- [Product vision](PRODUCT_VISION.md): users, jobs to be done, differentiation and success criteria.
- [Regulatory baseline for Brazil](REGULATORY_BASELINE_BR.md): source-backed support statements and
  legal boundary.
- [Policy model](POLICY_MODEL.md): how control objectives become deterministic technical policy.
- [Provider Capability Registry](PROVIDER_CAPABILITY_REGISTRY.md): reviewed provider facts,
  freshness and unknown-state handling.

## Architecture and contracts

- [Architecture](ARCHITECTURE.md): current runtime, governance and trust-boundary design.
- [Product architecture](PRODUCT_ARCHITECTURE.md): control-plane and enforcement-plane context.
- [Domain model](DOMAIN_MODEL.md): decisions, obligations, evidence and lifecycle entities.
- [API contract](API_CONTRACT.md): HTTP schemas, transitions and privacy constraints.
- [Evaluation strategy](EVAL_STRATEGY.md): deterministic scenarios and regression evidence.

## Authority and enterprise integrations

- [Read-only enterprise connector](READ_ONLY_ENTERPRISE_CONNECTOR.md): the bounded `cards.read`
  sandbox integration.
- [Tool-action reconciliation](TOOL_ACTION_RECONCILIATION.md): authenticated terminal resolution
  of ambiguous outcomes without reexecution.
- [Live composition pilot](LIVE_COMPOSITION_PILOT.md): fixed-synthetic provider integration proof.
- [MCP configuration](MCP.md): local MCP security policy and validation.

## Security, privacy and observability

- [Threat model](THREAT_MODEL.md): assets, attackers, mitigations and residual risks.
- [Privacy model](PRIVACY.md): data minimization and metadata-only retention boundaries.
- [LLM observability](LLM_OBSERVABILITY.md): safe optional tracing.
- [CloudEvents and OTLP](CLOUDEVENTS_OTLP.md): portable lifecycle metadata and trace correlation.

## Release trust and operations

- [Controlled pilot release](PILOT_RELEASE.md): supported profile, acceptance and exclusions.
- [Kubernetes/OpenShift deployment](KUBERNETES_DEPLOYMENT.md): restricted deployment reference.
- [Release custody](RELEASE_CUSTODY.md): content-addressed evidence retention.
- [OCI evidence](OCI_EVIDENCE.md): deterministic evidence artifacts and registry boundary.
- [Verification-key lifecycle](TRUST_KEY_LIFECYCLE.md): activation, retirement and revocation.
- [Trust-store lineage](TRUST_STORE_LINEAGE.md), [rollout](TRUST_STORE_ROLLOUT.md) and
  [runtime state](RUNTIME_TRUST_STATE.md): distribution and consumer verification.
- [Trusted timestamps](TRUSTED_TIMESTAMP.md) and [RFC 3161](RFC3161_TIMESTAMP.md): external time
  evidence verification.
- [Tool-catalog review](TOOL_CATALOG_REVIEW.md): detailed governance for trusted tool changes.

## Engineering reference

- [Development guide](DEVELOPMENT.md): local workflow and engineering commands.
- [MVP roadmap](MVP_ROADMAP.md): completed and deferred product increments.
- [Implementation plan](IMPLEMENTATION_PLAN.md): chronological implementation record.
- [Architecture Decision Records](adr/): immutable context and rationale for material decisions.
- [Changelog](../CHANGELOG.md): user-visible release history.

The roadmap, implementation plan, ADRs and changelog intentionally preserve chronology. Current
product behavior should be understood from the capability-oriented documents above.
