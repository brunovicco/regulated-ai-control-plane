# Regulated AI Control Plane

[![Python 3.13-3.14](https://img.shields.io/badge/Python-3.13--3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Licença: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Pre-Alpha](https://img.shields.io/badge/status-pre--alpha-orange)](#status-do-projeto)

> Control plane regulatório multi-provider para IA corporativa, começando por LGPD, ANPD e requisitos do setor financeiro brasileiro.

[English](README.md)

## Visão geral

**Regulated AI Control Plane** é um projeto de infraestrutura para aplicar controles de privacidade, segurança, regulação e autoridade aprovados pela organização na fronteira de execução de IA.

O primeiro recorte do produto é o Brasil, com foco inicial em ambientes regulados do setor financeiro. O projeto foi desenhado para operar entre aplicações ou agentes corporativos e provedores de IA. Ele avalia o contexto da operação, consulta capacidades do provedor, aplica políticas determinísticas, gera obrigações como transformação de dados ou aprovação humana e registra evidências apenas com metadados.

```text
Aplicação/Agente corporativo
            |
            v
+--------------------------------+
| Regulatory Enforcement Point   |
|--------------------------------|
| Classificação de dados         |
| Avaliação de políticas         |
| Capacidades do provedor        |
| Transformações necessárias     |
| Autoridade sobre ferramentas   |
| Geração de evidências          |
+--------------------------------+
            |
            v
    Inference Execution Port
            |
      +-----+-----+------+
      |           |      |
   OpenAI      Bedrock  Futuros
```

O modo padrão termina deliberadamente **antes da inferência real**. O modo gateway é opt-in e
existe para validar a integração sem tornar credenciais, roteamento ou resiliência responsabilidade
deste serviço.

## Por que este projeto existe

Adotar IA em produção em ambientes regulados envolve muito mais do que obter acesso a um LLM. Uma arquitetura corporativa pode precisar coordenar classificação e minimização de dados, políticas para transferência internacional, capacidades de provedor/serviço/região, identidade e fronteiras de autoridade, permissões para ferramentas e ações, aprovação humana, retenção, observabilidade e evidências para auditoria.

Clouds e provedores de modelos oferecem vários desses componentes, mas o comportamento muda conforme provedor, serviço, endpoint, região e configuração contratual. A organização também precisa manter suas políticas de forma portável entre provedores.

Este projeto explora essa camada de controle.

## Modelo central

Uma regra arquitetural fundamental é que o texto regulatório **não vira código diretamente**.

```text
Fonte regulatória oficial
        |
        v
Objetivo de controle revisado por humanos
        |
        v
Política corporativa executável
        |
        v
Controle técnico
        |
        v
Evidência apenas com metadados
```

O sistema não emite conclusões como `{"lgpd_compliant": true}`.

## Escopo inicial

- **Jurisdição:** Brasil
- **Setor:** serviços financeiros
- **Baseline regulatório:** LGPD, regulamentação da ANPD sobre transferência internacional e requisitos selecionados de segurança cibernética e contratação de cloud do CMN/BCB
- **Exemplos de providers:** OpenAI API e Amazon Bedrock
- **Decisões:** `ALLOW`, `ALLOW_WITH_TRANSFORMATION`, `REQUIRE_APPROVAL`, `DENY`
- **Evidência:** versionada, reproduzível e sem conteúdo sensível

Obrigações iniciais:

- `REMOVE_FIELD`
- `MASK`
- `TOKENIZE`
- `PSEUDONYMIZE`
- `REQUIRE_PROVIDER_CAPABILITY`
- `REQUIRE_HUMAN_APPROVAL`
- `RESTRICT_TOOL`
- `REQUIRE_EVIDENCE`

## Status do projeto

**Pre-alpha com avaliação determinística, enforcement local, aprovações de decisão e ação
vinculadas a digests, catálogo confiável de ferramentas e adapter opt-in via gateway governado.**

Objetivo atual:

```text
Contexto
  -> Classificação
  -> Resolução de ferramentas pelo catálogo confiável
  -> Matching de políticas
  -> Resolução de capacidades do provider
  -> Decisão
  -> Obrigações
  -> Transformações locais
  -> Recibos de transformação apenas com metadados
  -> Verificação e consumo único de aprovação externa quando exigida
  -> Estado PREPARED persistido
  -> Mock sem rede (padrão) ou gateway governado (opt-in)
  -> Validação exata da proposta e aprovação específica da ação
  -> Mock de execução de ferramenta sem rede
  -> Validação fechada do output e resultado seguro efêmero
  -> Timeline operacional apenas com metadados e códigos de atenção
  -> Histórico local append-only com baselines explícitas de migração
```

O serviço expõe `POST /v1/evaluations`, `GET /v1/evidence/{evidence_id}`,
`POST /v1/enforcements`, `GET /v1/enforcements/{enforcement_id}`,
`POST /v1/enforcements/{enforcement_id}/tool-actions`, `GET /v1/tool-actions/{action_id}`,
`GET /v1/operator/enforcements/{enforcement_id}/timeline`,
`GET /v1/providers` e `GET /health`. O modo padrão continua sem rede. Quando configurado explicitamente, o modo gateway
usa timeouts limitados, não realiza retry local, descarta a saída do modelo e aceita somente
definições de ferramentas resolvidas pelo catálogo versionado da organização. Chamadas de
ferramentas retornadas pelo modelo continuam sem autoridade até que os argumentos exatos sejam
reenviados, validados e aprovados com uma autoridade de ação separada. A execução da Fase 4c usa
somente um mock sem rede. A Fase 4d valida o resultado não confiável contra schemas fechados do
catálogo, mascara ou remove campos classificados e retorna o resultado minimizado somente na
resposta imediata de sucesso. Outputs brutos e seguros não são persistidos nem recuperáveis em
replays.
As asserções de aprovação são emitidas fora do serviço, vinculadas ao digest determinístico da
decisão, recebidas apenas de forma efêmera e consumidas uma única vez antes da execução.

Fora do primeiro ciclo:

- adapters diretos de SDKs de providers;
- retorno de completion pela API;
- adapters reais para sistemas corporativos e retorno do resultado da ferramenta ao modelo;
- LLM decidindo política;
- frontend/dashboard;
- SaaS multi-tenant;
- ingestão automática de legislação;
- DLP completo;
- certificação jurídica ou regulatória.

Consulte [docs/MVP_ROADMAP.md](docs/MVP_ROADMAP.md).

## Princípios de arquitetura

### Enforcement determinístico

O modelo de IA nunca decide se uma política de segurança, privacidade ou regulação deve ser cumprida. A mesma entrada normalizada, usando as mesmas versões de políticas e do provider registry, deve produzir a mesma decisão.

### Fail closed

```text
capacidade obrigatória = unknown
    -> fail closed

capacidade high-assurance desatualizada
    -> fail closed

fallback reduz controle obrigatório
    -> rejeitar fallback

ferramenta ausente do catálogo ou com risk_class divergente
    -> rejeitar solicitação
```

### Autoridade sobre ferramentas

Clientes solicitam ferramentas por nome, mas não definem sua autoridade. A classe de risco, a
descrição e o schema vêm de um catálogo YAML versionado e validado no startup. Um `risk_class`
enviado pelo cliente é tratado apenas como uma alegação não confiável e deve corresponder
exatamente ao catálogo.

O gateway pode retornar uma proposta de chamada para uma ferramenta autorizada. O serviço registra
somente o identificador da ferramenta, a versão e o digest do schema e o digest dos argumentos. Os
argumentos brutos não são persistidos ou retornados, e a proposta não produz efeito externo.

### Provider Capability Registry

O comportamento dos provedores é representado por fatos versionados e respaldados por fontes oficiais. Cada registro inclui provider, serviço, região quando aplicável, estado da capacidade, condições, fontes oficiais, data de verificação e versão.

Estados possíveis:

```text
supported
unsupported
conditional
unknown
```

`unknown` é um estado válido e importante.

### Evidência sem conteúdo sensível

A trilha de evidências pode registrar decisão, reason codes, classificações, versões de políticas e registry, tipos de obrigações, referências de controles, timestamps e hashes criptográficos.

Ela não deve registrar prompts completos, respostas de modelos, valores de dados pessoais,
credenciais, API keys, tokens, argumentos brutos ou outputs de ferramentas.

### Portabilidade entre providers

A arquitetura mantém a inteligência regulatória e as políticas corporativas acima do provedor de
inferência. O primeiro adapter real integra com o
[`governed-llm-gateway`](https://github.com/brunovicco/governed-llm-gateway), evitando duplicar
roteamento, resiliência, credenciais de providers e normalização multi-provider. O modo é opt-in;
mock continua sendo o padrão.

## Precedência de decisão

```text
DENY
  >
REQUIRE_APPROVAL
  >
ALLOW_WITH_TRANSFORMATION
  >
ALLOW
```

Uma decisão menos restritiva nunca pode sobrescrever uma restrição mais forte.

## Estrutura do repositório

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
│   └── adr/
├── examples/
│   ├── policies/
│   ├── provider-capabilities/
│   ├── scenarios/
│   └── tools/
├── governance/
├── src/
└── tests/
```

## Desenvolvimento

O repositório utiliza como baseline o [`brunovicco/codex-python-engineering-harness`](https://github.com/brunovicco/codex-python-engineering-harness).

Requisitos:

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/)

Instalação e quality gate:

```bash
uv lock --check
uv sync --frozen --all-groups --extra observability
uv run python scripts/quality_gate.py
```

Execute a API local:

```bash
uv run uvicorn regulated_ai.entrypoints.api:app --host 127.0.0.1 --port 8000
```

Consulte [docs/DEMO.md](docs/DEMO.md) para uma requisição sintética ponta a ponta, as obrigações
esperadas e a inspeção das evidências.

O `AGENTS.md` gerado pelo harness é o contrato principal para workflow de desenvolvimento, arquitetura, testes e segurança.

## Documentação

Comece por:

- [Contexto do projeto](docs/PROJECT_CONTEXT.md)
- [Visão do produto](docs/PRODUCT_VISION.md)
- [Arquitetura](docs/PRODUCT_ARCHITECTURE.md)
- [Modelo de domínio](docs/DOMAIN_MODEL.md)
- [Baseline regulatório brasileiro](docs/REGULATORY_BASELINE_BR.md)
- [Provider Capability Registry](docs/PROVIDER_CAPABILITY_REGISTRY.md)
- [Modelo de políticas](docs/POLICY_MODEL.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Estratégia de evals](docs/EVAL_STRATEGY.md)
- [Roadmap](docs/MVP_ROADMAP.md)
- [Fontes primárias](SOURCES.md)

## Segurança

Não utilize dados reais de clientes, credenciais de produção ou secrets de produção em desenvolvimento, exemplos ou testes. Consulte [SECURITY.md](SECURITY.md).

## Limite jurídico e regulatório

Este projeto é uma implementação de engenharia e referência arquitetural. Ele **não** fornece aconselhamento jurídico, certificação regulatória nem garantia de conformidade com LGPD, regulamentações da ANPD, CMN/BCB, ISO/IEC 42001, NIST ou outros frameworks.

Os mappings regulatórios e de frameworks representam como controles técnicos podem apoiar objetivos de controle aprovados pela organização. A aplicabilidade e a interpretação permanecem sob responsabilidade dos stakeholders qualificados da organização.

## Licença

Distribuído sob a [Licença MIT](LICENSE).

## Autor

**Bruno Vicco**
Generative AI Engineering · AI Platforms · Agentic Security · Governance
