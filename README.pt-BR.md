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
  -> Contexto operacional de controles e aprovação sanitizada, apenas com metadados
  -> Snapshots de fontes e frescor do provedor vinculados ao digest
  -> Dashboard operacional server-rendered por ID exato
  -> Verificação do pack assinado de políticas/providers/catálogo antes da composição do runtime
  -> Análise semântica offline de impacto entre releases verificadas do pack
  -> Replay de cenários apenas com metadados e relógio fixo entre releases verificadas
  -> Revisão de capabilities vinculada por digest antes da assinatura separada do pack
  -> Revisão regulatória de políticas vinculada por digest antes da assinatura separada do pack
  -> Bundle verificado de diff, replay e reviews para decisões externas de promoção
  -> Quórum de promoção assinado e vinculado ao bundle completo exato
  -> Autoridade de review assinada para updates, onboarding e remoção
  -> Diff, replay sem argumentos e review do catálogo assinado de ferramentas
```

O serviço expõe `POST /v1/evaluations`, `GET /v1/evidence/{evidence_id}`,
`POST /v1/enforcements`, `GET /v1/enforcements/{enforcement_id}`,
`POST /v1/enforcements/{enforcement_id}/tool-actions`, `GET /v1/tool-actions/{action_id}`,
`GET /v1/operator/enforcements/{enforcement_id}/timeline`,
`GET /operator?enforcement_id={enforcement_id}`, `GET /v1/providers` e `GET /health`. O modo
padrão verifica o pack local assinado de políticas/providers/catálogo e continua sem rede. Quando
configurado explicitamente, o modo gateway
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

A Fase 6a vincula o release empacotado de políticas/providers a digests SHA-256 e a uma assinatura
Ed25519 selecionada em um trust store local de chaves públicas. Falhas de digest, assinatura,
chave, composição ou caminho impedem o startup. Somente material público de verificação é
empacotado; chaves privadas de release devem permanecer em uma fronteira offline controlada pela
organização. A assinatura comprova autenticidade do release, não correção da política, atualidade
do provider ou compliance.

A Fase 6b compara uma base aprovada e uma candidata somente depois que ambas passam pelo mesmo
trust store. O relatório JSON offline classifica impacto potencial em decisão, evidência e
governança, correlaciona capabilities alteradas às regras dependentes e sinaliza reutilização de
versão ou troca de chave. É apoio conservador à revisão, não equivalência comportamental exaustiva
nem autoridade para promover o release.

A Fase 6c executa uma suíte de cenários, governada separadamente e somente com metadados, contra os
dois releases verificados em um horário fixo. O relatório registra mudanças observadas em decisão,
obrigações e evidência, vincula os bytes exatos da suíte por digest e pode falhar o CI quando houver
impacto em decisão. O corpus finito contém labels de classificação, nunca valores, e não comprova
equivalência nem autoriza promoção.

A Fase 6d adiciona um gate offline anterior à assinatura para atualizar capabilities de providers.
Um registro estrito vincula a base autenticada, os bytes exatos da candidata, o alvo, a data, o papel
revisor e as conclusões por fonte para cada capability. Revisões ausentes, contraditórias,
inconclusivas, com data inconsistente ou sem nova versão são bloqueadas. A aprovação confirma
somente consistência delimitada: não autentica o revisor, consulta fontes, assina ou promove o
release, nem comprova o comportamento do provider.

A Fase 6e adiciona um gate offline anterior à assinatura para atualizações de um policy set
existente. Ele vincula a base autenticada e os bytes exatos da candidata, exige revisão de cada
regra alterada e dos mappings exatos de objetivo de controle e suporte regulatório, e bloqueia
conclusões ausentes, rejeitadas ou que exigem revisão. Regras sem referência regulatória devem ser
marcadas como `NOT_APPLICABLE`, mantendo política corporativa de autoridade separada de requisitos
regulatórios. A aprovação não consulta ou interpreta texto legal, não autentica o revisor, não
assina ou promove o release e não declara compliance.

A Fase 6f compõe um bundle determinístico de evidências a partir de uma base/candidata verificadas,
da suíte exata de cenários e dos registros de review exigidos para policies/providers. Ela recalcula
diff e replay, reexecuta os reviews contra os bytes autenticados da candidata e aponta cobertura
ausente, bloqueada ou ainda sem governança definida. `EVIDENCE_COMPLETE` indica consistência das
evidências, não aceitação de impacto, autoridade de assinatura, aprovação de promoção ou compliance.

A Fase 6g verifica atestações Ed25519 de promoção controladas pela organização contra um trust
store público separado e uma política explícita de papéis obrigatórios e quórum de chaves distintas.
Cada voto vincula o bundle completo exato da Fase 6f, o digest do pack candidato e o digest canônico
da política de promoção, com validade avaliada em um horário UTC explícito.
`PROMOTION_AUTHORIZED` é somente um artefato de handoff com quórum autenticado: o fluxo não assina o
pack, altera o repositório, promove, distribui ou implanta o release, nem declara segurança ou
compliance.

A Fase 6h autentica papéis revisores por um trust store público Ed25519 separado, limitando cada
chave pelo tipo de artefato e de mudança. Entidades modificadas ainda precisam passar pelo review
detalhado das Fases 6d/6e, e a assinatura vincula o digest exato desse review. Adições e remoções
integrais de policies/providers são governadas pelo digest assinado dos bytes da candidata ou da
base aprovada. Isso comprova atribuição do revisor e cobertura do ciclo de vida, não correção legal,
verdade do provider, autoridade de promoção ou permissão de deployment.

A Fase 6i inclui exatamente um catálogo confiável de ferramentas em cada control pack assinado. O
runtime, o diff estático, o replay somente com metadados e as evidências de release usam os mesmos
bytes do catálogo verificados por digest. Mudanças no catálogo ficam visíveis como impacto semântico
e exigem revisão assinada do artefato completo. Isso autentica definições para avaliação; não
autoriza argumentos, executa ferramentas ou comprova o comportamento da implementação downstream.

A Fase 6j atualiza os trust stores de release, review e promoção para o schema 2 com ciclo de vida.
Cada chave pública possui início de vigência, expiração opcional e estado explícito `ACTIVE`,
`RETIRED` ou `REVOKED`. Chaves inativas ou fora da janela falham de forma fechada antes que a
assinatura conceda autoridade. Custódia das chaves privadas e distribuição dos trust stores
continuam como operações externas.

Fora do primeiro ciclo:

- adapters diretos de SDKs de providers;
- retorno de completion pela API;
- adapters reais para sistemas corporativos e retorno do resultado da ferramenta ao modelo;
- LLM decidindo política;
- descoberta global e ações administrativas no dashboard operacional;
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
- [Ciclo de vida das chaves de verificação](docs/TRUST_KEY_LIFECYCLE.md)
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
