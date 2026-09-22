# Project context

## Working identity

**RegulaAI** is the working product name. The repository is intentionally named
`regulated-ai-control-plane` so the architecture is understandable without relying on branding.

## Mission

Provide a technical control plane for enterprise AI that can:

1. understand runtime context relevant to approved policy;
2. resolve provider/service capabilities from curated, source-backed facts;
3. apply deterministic policy decisions before sensitive data or authority crosses a trust boundary;
4. return enforceable obligations such as transformation or human approval;
5. record metadata-only evidence proving which controls ran.

Brazilian regulated industries are the first product wedge, beginning with financial services.

## Product thesis

Regulated enterprises increasingly need more than model access. They need data handling,
identity/authority, provider selection, observability, policy enforcement and evidence to work
together.

Cloud and model providers expose many of the necessary primitives, but the exact combination of
capabilities differs by provider, product, endpoint and region. Enterprise policy also depends on
local regulatory requirements.

The product should sit above model providers and below business applications.

## Vocabulary

- **Regulatory source**: authoritative law/regulation/guidance used as input to governance work.
- **Control objective**: organization-approved objective derived from legal, regulatory, security,
  privacy or internal requirements.
- **Technical control**: executable mechanism intended to support a control objective.
- **Policy**: machine-readable organization rule that selects technical controls for a runtime
  context.
- **Provider capability**: source-backed fact about a provider/service/region.
- **Obligation**: action that must occur for a request to proceed.
- **Decision**: final runtime result (`ALLOW`, `ALLOW_WITH_TRANSFORMATION`,
  `REQUIRE_APPROVAL`, `DENY`).
- **Evidence**: metadata proving evaluation inputs by category/version and controls applied without
  retaining sensitive content.
- **Authority boundary**: point where an AI system may read or change external state.
- **Trust boundary**: point where data or authority crosses between differently controlled systems.

## Core invariants

1. Regulations do not directly execute code.
2. Legal interpretation is reviewed by humans and becomes an approved control objective.
3. A model never grants itself authority.
4. Provider marketing claims are not capabilities until represented as source-backed registry data.
5. `unknown` is a first-class capability state.
6. Required controls fail closed when the evidence needed to satisfy them is missing or stale.
7. Provider fallback cannot weaken controls.
8. Sensitive input is not observability/evidence payload.
9. The product records why a decision occurred using IDs, versions and digests.
10. Every material decision should be reproducible from versioned inputs.

## First customer story

A Brazilian financial institution has an AI customer-support workflow. A request includes a
customer question, structured customer/account fields and a request to call tools.

Before an external LLM is invoked, RegulaAI evaluates:
- data classifications;
- business purpose;
- requested provider/service;
- provider capabilities;
- organization-approved Brazilian financial-services policy;
- tool/action risk.

It may remove/tokenize selected identifiers, disallow a provider configuration, permit read-only
tools, require human approval for a state-changing action, and emit evidence.

The first MVP does not itself invoke the LLM. It proves the decision/enforcement contract first.
