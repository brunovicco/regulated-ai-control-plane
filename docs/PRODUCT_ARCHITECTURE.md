# Product architecture

## Context

```mermaid
flowchart LR
    APP[Enterprise application/agent]
    EP[Regulatory Enforcement Point]
    PE[Policy Decision Engine]
    PCR[Provider Capability Registry]
    PP[Policy Packs]
    EV[Evidence Ledger]
    AP[Approval Workflow]
    GW[Inference Execution Port]
    P1[OpenAI]
    P2[Amazon Bedrock]
    P3[Future providers]

    APP --> EP
    EP --> PE
    PE --> PP
    PE --> PCR
    PE --> AP
    PE --> EV
    EP --> GW
    GW --> P1
    GW --> P2
    GW --> P3
```

Phase 1 stops before `GW`: it evaluates and returns obligations. Phase 2 builds a locally
transformed execution plan and sends it to a network-silent mock port. Phase 3a adds an opt-in,
text-only integration with `governed-llm-gateway`; mock execution remains the default.

## Control plane vs enforcement plane

### Control plane

Owns versioned knowledge/configuration:
- approved control objectives;
- policies;
- provider capability registry;
- regulatory support mappings;
- freshness rules;
- policy-set releases.

It does not receive production customer prompts in the target architecture.

### Enforcement plane

Runs in or near the customer trust boundary:
- accepts normalized runtime context;
- performs deterministic identifier classification;
- evaluates policy;
- computes transformations/authority obligations;
- writes metadata-only evidence;
- later invokes the execution port.

Target deployment should support running the enforcement plane in the customer's cloud/VPC/Kubernetes
environment.

## Trust boundaries

```mermaid
flowchart TB
    subgraph CUST["Customer trust boundary"]
        A[Application]
        E[Enforcement service]
        T[Local transform/tokenization]
        L[Metadata-only evidence]
        A --> E
        E --> T
        E --> L
    end

    T -->|sanitized payload only after policy allows| EXT[External AI provider boundary]
    EXT --> MODEL[Model service]
    E -->|approval request, metadata only| HUMAN[Human approval system]
```

## Clean architecture mapping

Suggested modules; adjust to the generated harness rather than fighting it.

```text
src/regulated_ai/
  domain/
    classifications.py
    capabilities.py
    controls.py
    decisions.py
    evidence.py
    policies.py
    value_objects.py

  application/
    evaluate_operation.py
    ports.py
    services.py

  adapters/
    policy_yaml/
    capability_yaml/
    evidence_sqlite/
    classifier_deterministic/
    observability/

  entrypoints/
    api/
```

### Domain

Framework-free. No FastAPI/Pydantic transport models/YAML/SQL/provider SDK imports.

### Application

Coordinates use cases and defines infrastructure ports.

Potential ports:
- `PolicyRepository`
- `ProviderCapabilityRepository`
- `EvidenceRepository`
- `DataClassifier`
- future `ApprovalPort`
- `InferenceExecutionPort`

### Adapters

Translate external formats into application/domain types.

### Entrypoints

HTTP validation and response mapping only.

## Evaluation flow

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Eval as EvaluateAiOperation
    participant Classifier
    participant Policies
    participant Registry
    participant Evidence

    Client->>API: normalized evaluation request
    API->>Eval: typed command
    Eval->>Classifier: deterministic classifications
    Eval->>Policies: applicable policy set
    Eval->>Registry: required provider capabilities
    Eval->>Eval: deterministic decision + obligations
    Eval->>Evidence: metadata-only event
    Evidence-->>Eval: evidence_id
    Eval-->>API: decision plan
    API-->>Client: decision + obligations + evidence_id
```

## Execution integration

The application exposes an `InferenceExecutionPort` so the product can:
- integrate with `governed-llm-gateway`;
- call a direct provider adapter;
- call a hyperscaler adapter;
- keep provider fallback constrained by the same decision plan.

The first real adapter uses `governed-llm-gateway` and does not copy its routing, retry, fallback or
provider credential handling into this repository. Direct provider adapters remain optional future
work.

## Local enforcement flow

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Enforce as EnforceAiOperation
    participant Eval as EvaluateAiOperation
    participant Token as TokenizationPort
    participant Evidence as EnforcementRepository
    participant Mock as MockExecutionPort

    Client->>API: normalized enforcement request
    API->>Enforce: typed context
    Enforce->>Eval: deterministic evaluation
    Eval-->>Enforce: decision + obligations + digest
    Enforce->>Token: transform required fields locally
    Enforce->>Evidence: persist PREPARED metadata
    Enforce->>Mock: sanitized execution plan
    Mock-->>Enforce: metadata-only execution receipt
    Enforce->>Evidence: persist EXECUTED metadata
    Enforce-->>API: metadata-only enforcement result
```

## Failure model

Fail closed when:
- policy data required for the operation cannot be loaded/validated;
- mandatory capability is `unknown` or `unsupported`;
- high-assurance capability evidence exceeds configured freshness;
- a required transformation fails;
- an approval is required but not granted;
- policy-set/provider-registry versions cannot be resolved.

Operational/health endpoints may remain available while policy evaluation is unavailable.
