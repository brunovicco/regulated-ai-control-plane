# Provider Capability Registry

## Why it exists

A regulation or enterprise policy may require a technical property, but provider behavior varies
by:
- provider;
- service;
- endpoint;
- region;
- model;
- customer eligibility/configuration;
- date.

The registry turns provider documentation into **versioned, source-backed technical facts** that
policy can query.

It does not declare legal compliance.

## Capability state

Every capability uses one of:

- `supported`
- `unsupported`
- `conditional`
- `unknown`

Never coerce `unknown` into false confidence.

## Required record metadata

```yaml
provider: openai
service: responses_api
region: global
record_version: 1
verified_at: 2026-09-22
sources:
  - https://developers.openai.com/pt-BR/api/docs/guides/your-data

capabilities:
  zero_data_retention:
    state: conditional
    conditions:
      - eligible_organization_required
      - endpoint_capability_must_be_zdr_eligible

  store_false:
    state: supported
```

The exact runtime schema may differ, but preserve the semantics.

## Freshness

Provider facts change frequently.

Every capability record must include:
- `verified_at`;
- source URL(s);
- registry version.

Policy may specify freshness:
- low assurance: warn after a configured age;
- high assurance: stale fact becomes `unknown` and fails closed when mandatory.

Do not create a global magic freshness period in the domain. Make it organization policy/config.

## Source quality

Preferred order:
1. official provider documentation;
2. official product/security/compliance documentation;
3. official release notes.

Do not use blogs, social posts or secondary articles as authoritative capability facts when primary
documentation exists.

## OpenAI baseline facts for examples

As of the verification date, official OpenAI data-control documentation states:
- API data is not used for model training by default unless the customer opts in;
- standard abuse-monitoring logs may have retention behavior documented by endpoint;
- Modified Abuse Monitoring and Zero Data Retention are eligibility/configuration-dependent;
- with ZDR, `store` for supported Responses/Chat Completions behavior is treated as false;
- data residency/processing-region support is region/endpoint/model dependent.

The example registry must treat these as capability facts, not regulatory conclusions.

## Amazon Bedrock baseline facts for examples

Official AWS documentation states that:
- Bedrock supports IAM-based control;
- Bedrock API activity can be integrated with CloudTrail, with event behavior depending on API;
- AWS PrivateLink can provide private VPC connectivity to Bedrock endpoints;
- AWS documents a shared-responsibility model for data protection;
- AWS states that model providers do not have access to the Bedrock deployment accounts, logs,
  customer prompts or completions described in its data-protection documentation;
- regional/model availability varies and must be represented at model/service granularity.

A provider record must not infer "data stays in Brazil" merely because an endpoint is reachable from
`sa-east-1`; model inference modes such as in-region, geo or global routing must be represented
explicitly when relevant.

## Registry query examples

Policy should be able to ask:

- Does target support a required private-connectivity mode?
- Is a required retention control supported and active/eligible?
- Is the selected processing mode allowed by enterprise geography policy?
- Is audit/API activity logging available?
- Is the provider fact recent enough for this assurance level?

## Change management

A capability change should:
1. create a new version;
2. retain previous source metadata;
3. trigger regression evaluation of policies/scenarios;
4. surface breaking/downgrade changes;
5. never silently mutate historical evidence.

Phase 5d copies the metadata of each resolved fact into decision evidence and binds the ordered
snapshot into the output/event digests. The snapshot preserves historical attribution even after
the active registry advances. It supports an audit statement about which source metadata informed
the decision; it does not prove that the provider still behaves the same way.

Phase 6a requires the release manifest and exact registry bytes to pass signed-pack verification.
Phase 6b compares a verified candidate against a verified base under the same trust store. Changes
to state, conditions or freshness are classified as potential decision impact; source and version
changes are evidence impact; notes are governance metadata. The report also lists policy rules that
require an affected capability key and can match its provider target. This is a conservative review
aid and does not replace scenario regression, source review or release approval.
