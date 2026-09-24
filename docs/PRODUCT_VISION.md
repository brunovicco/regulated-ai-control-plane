# Product vision

## Problem

Enterprise AI adoption in regulated environments is slowed by a recurring integration problem:
model access, privacy, provider-region behavior, authority, observability and audit evidence are
handled by different teams and tools.

A business team may know *what* it wants the AI system to do. Security/privacy/legal may know
*which constraints* must apply. Cloud/model providers expose implementation primitives. The gap is
a runtime layer that turns organization-approved constraints into deterministic execution decisions.

## Primary users

### AI platform/applied AI teams
Need a consistent policy boundary across applications and providers.

### Security and privacy engineering
Need enforceable controls at data and authority boundaries, not only documentation.

### Architecture/cloud platform teams
Need a portable decision layer that avoids baking all governance logic into one hyperscaler.

### Risk, compliance and legal partners
Need traceable mappings from approved control objectives to runtime behavior and evidence, while
retaining human ownership of interpretation.

## Jobs to be done

- Decide whether a request may cross an external model-provider boundary.
- Determine which transformations must occur first.
- Select only provider/service configurations that satisfy mandatory enterprise requirements.
- Gate tool/actions by authority level and human approval.
- Prove which policy/control/provider facts were used for a decision.
- Detect policy or provider-capability drift before silently changing behavior.

## Value proposition

A portable, provider-aware **regulatory enforcement layer** for enterprise AI.

The product should reduce:
- per-application reimplementation of privacy/security rules;
- manual provider-comparison work;
- inconsistent enforcement;
- evidence gaps;
- hidden policy downgrades during fallback.

## Differentiation

Do not position the product as a replacement for GRC, privacy-management or AI-governance suites.

Differentiate on:
- Brazilian regulatory/sector packs as the initial wedge;
- runtime enforcement at the AI execution boundary;
- provider/service/region capability intelligence;
- multi-provider portability;
- agent/tool authority controls;
- evidence generated from actual runtime decisions.

## Non-goals

The product does not:
- issue legal opinions;
- certify compliance;
- promise that a technical control alone satisfies a regulation;
- replace DPO/legal/security review;
- replace enterprise IAM/KMS/SIEM/DLP;
- become a full model gateway in the first product boundary;
- use an LLM as the final policy decision maker.

## Commercial direction

Potential forms:
- self-hosted enforcement plane + hosted regulatory/provider control plane;
- enterprise subscription for maintained policy/capability packs;
- deployment accelerator for model providers/hyperscalers/system integrators;
- cloud marketplace distribution.

Open source can cover schemas, engine primitives and sample packs. Commercial value may sit in
maintained intelligence, approvals/workflows, enterprise integrations, signed evidence and support.

## First success criteria

A technical stakeholder should be able to run a demo locally and answer:

1. Why was this request allowed/denied?
2. Which data transformations were required?
3. Which provider capabilities were required and what sources support them?
4. Which tool/action required approval?
5. Which policy/control versions produced the result?
6. Can the result be reproduced without storing the sensitive payload?
