# Sources

Baseline verified: **2026-09-22**

Use primary sources for registry/regulatory facts. Re-check before shipping a production policy
pack because provider capabilities and regulations change.

## Brazil

### LGPD — Lei nº 13.709/2018
https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm

Use for:
- statutory privacy/data-protection baseline.

### ANPD — Resolução CD/ANPD nº 19/2024
https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/resolucao-cd-anpd-no-19-de-23-de-agosto-de-2024

Use for:
- international data-transfer rules;
- legitimate/specific purposes;
- legal basis + transfer mechanism;
- minimum necessary;
- demonstrable measures/accountability.

### ANPD — International Data Transfer topic
https://www.gov.br/anpd/pt-br/assuntos/assuntos-internacionais/transferencia-internacional-de-dados

Use for:
- ANPD topic landing/reference material.

### Banco Central — Resolução CMN nº 4.893/2021 (current consolidated page)
https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=4893&tipo=Resolu%C3%A7%C3%A3o+CMN

Use for:
- cybersecurity policy;
- relevant processing/storage/cloud contracting requirements;
- scope and current text.

### Banco Central — Resolução CMN nº 5.274/2025
https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=5274&tipo=Resolu%C3%A7%C3%A3o+CMN

Use for:
- amendments to CMN 4.893;
- expanded/detailed cybersecurity-control requirements.

## OpenAI

### Data controls
https://developers.openai.com/pt-BR/api/docs/guides/your-data

Use for current facts about:
- API training default;
- abuse-monitoring retention;
- Modified Abuse Monitoring;
- Zero Data Retention;
- endpoint-specific application-state retention;
- `store` behavior;
- data residency/processing regions and limitations.

Important:
`store=false` is not by itself equivalent to organization-level Zero Data Retention. Model this
difference explicitly.

## AWS / Amazon Bedrock

### Data protection
https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html

Use for:
- shared responsibility;
- IAM/security recommendations;
- provider access model described by AWS;
- data-protection references.

### AWS PrivateLink / Bedrock VPC endpoints
https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html

Use for:
- private VPC connectivity;
- endpoint policies;
- supported endpoint categories.

### Bedrock CloudTrail logging
https://docs.aws.amazon.com/bedrock/latest/userguide/logging-using-cloudtrail.html

Use for:
- API/activity logging capability and distinctions between management/data events.

### Model/region compatibility
https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html

Use for:
- in-region/geo/global model availability.
- Never infer residency solely from the AWS region of the client endpoint.

## NIST

### AI Risk Management Framework
https://www.nist.gov/itl/ai-risk-management-framework

### NIST AI 600-1 — Generative AI Profile
https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence

Use as voluntary risk-management guidance, not law.

## Source handling rules

- Never copy licensed standard text into the repository unless its license permits it.
- Framework mappings describe support, never certification.
- Every provider capability fact requires `verified_at` and source URL.
- Every regulatory mapping requires a human-reviewed control objective before becoming executable.
