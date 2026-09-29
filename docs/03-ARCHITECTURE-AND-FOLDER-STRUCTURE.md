# AI Engineering Harness — Arquitetura e Estrutura de Pastas

## 1. Objetivo

Este documento descreve a arquitetura atual e a estrutura de pastas do AI Engineering Harness após a conclusão do **V0.4 — Decision Foundation** (sobre o V0.3 — Memory Foundation).

Ele possui dois objetivos complementares:

1. documentar com precisão o que existe hoje no repositório;
2. preservar a direção arquitetural necessária para as próximas versões sem antecipar implementação.

A estrutura deve continuar permitindo evolução incremental, mantendo separação entre:

- core Python;
- configuração;
- intake e admission;
- providers;
- memória;
- contexto;
- decisões;
- skills;
- specialties;
- policies;
- guidelines;
- gates;
- pipelines;
- Git;
- release;
- deploy;
- observabilidade;
- artefatos de execução.

A existência dessas áreas na arquitetura alvo não implica que todas estejam implementadas no estágio atual.

---

## 2. Autoridade dos documentos

Cada documento possui uma responsabilidade diferente.

### Project Vision

Define:

- propósito;
- princípios;
- modelo operacional;
- visão de longo prazo.

### Functional and Nonfunctional Requirements

Define:

- requisitos funcionais;
- requisitos não funcionais;
- invariantes;
- restrições do sistema.

### Architecture and Folder Structure

Este documento define:

- boundaries;
- organização estrutural;
- responsabilidades dos módulos;
- regras de dependência;
- estado atual da implementação;
- target architecture.

### Roadmap

`AI-Engineering-Harness-Roadmap.md` é a autoridade para:

- numeração das versões;
- ordem de implementação;
- escopo de cada versão;
- critérios de saída por versão.

Quando houver divergência entre uma sequência histórica descrita neste documento e o roadmap atual, **o roadmap prevalece para versionamento e ordem de execução**.

### ADRs

ADRs aprovadas prevalecem sobre descrições arquiteturais anteriores quando formalizam uma decisão específica.

---

## 3. Estado atual

Status atual:

```text
V0   — Project Foundation       COMPLETE
V0.1 — Mode Foundation          COMPLETE
V0.2 — Provider Abstraction     COMPLETE
V0.3 — Memory Foundation        COMPLETE
V0.4 — Decision Foundation      COMPLETE
```

Próxima versão: **V1 — Global Library** (não implementada).

O projeto possui agora:

- fundação Python funcional;
- configuração declarativa tipada;
- CLI e `doctor`;
- intake e admission de requisições;
- `EngineeringRequest`;
- `ExecutionMode`;
- `RequestSource`;
- `Intent`;
- `WorkflowState.PLANNED`;
- abstração de providers;
- `LLMProvider`;
- `DecisionProvider`;
- provider registry;
- model resolution;
- fake providers;
- memória operacional de longo prazo (`MemoryProvider`, adapter Mem0 self-hosted);
- scopes de memória (project, task, run, agent, release), lineage básico e safe ingestion policy;
- comandos `memory` (health/add/search/update/delete) e check opcional de memória no `doctor`;
- decision provider real: adapter Jev (TypeSafe System One, HTTP) sobre o `DecisionProvider` (V0.4);
- typed decisions (`DecisionKind`: classification, routing, severity, context relevance) com choice, score, probability e confidence;
- threshold configurável (`decisions.yaml` → `thresholds.minimum_confidence`);
- fallback contract (`DecisionOutcome`: `decided` | `fallback_required` + motivo), apenas sinalizado;
- telemetria mínima de decisão (`DecisionTelemetry`, log JSON estruturado);
- comandos `decision` (classify/route/severity/relevance/health) e check opcional de decisões no `doctor`;
- contract tests;
- testes unitários e de integração (incluindo prova real opt-in contra Mem0 e contra Jev);
- quality gates locais com pytest, Ruff e Mypy.

Ainda não estão implementados:

- provider real OpenAI;
- provider real Anthropic;
- provider real NVIDIA;
- Decision Policy Engine (deterministic → Jev → LLM → human; V5);
- fallback automático para LLM ou humano;
- ingestão automática de memória;
- Context Engine (inclusive uso de memória na seleção de contexto);
- agent execution;
- gates framework;
- review system;
- state machine completa;
- Git orchestration;
- run artifacts completos;
- risk engine;
- release;
- deploy;
- observabilidade externa;
- autonomous loop;
- MCP;
- HTTP API.

---

## 4. Raiz portátil do Harness

O Harness vive em:

```text
engineering/
```

Essa pasta deve permanecer portátil e autocontida o suficiente para ser copiada ou integrada a outros projetos.

A documentação oficial do projeto permanece fora dela, em:

```text
docs/
```

A configuração específica do Harness vive dentro de:

```text
engineering/config/
```

O package Python principal é:

```text
engineering/orchestrator/
```

---

## 5. Estrutura real após o V0.4

A estrutura funcional atualmente implementada é:

```text
engineering/
├── orchestrator/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── doctor.py
│   ├── intake.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── admission.py
│   │   ├── exceptions.py
│   │   └── request.py
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── fake.py
│   │   ├── jev.py            # V0.4: JevDecisionProvider (TypeSafe HTTP)
│   │   ├── registry.py
│   │   └── resolution.py
│   │
│   ├── decisions/            # V0.4
│   │   ├── __init__.py
│   │   ├── models.py         # DecisionOutcome, FallbackReason, DecisionTelemetry
│   │   └── service.py        # DecisionService, open_decisions
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── fake.py
│   │   ├── mem0.py
│   │   ├── models.py
│   │   ├── safety.py
│   │   └── service.py
│   │
│   └── utils/
│       ├── files.py
│       ├── logging.py
│       └── shell.py
│
├── config/
│   ├── project.yaml
│   ├── providers.yaml
│   ├── models.yaml
│   ├── agents.yaml
│   ├── modes.yaml
│   ├── context.yaml
│   ├── memory.yaml
│   ├── decisions.yaml
│   ├── risks.yaml
│   └── pipelines.yaml
│
├── templates/
│   ├── README.md
│   ├── adr.md
│   ├── sprint.md
│   └── task.md
│
├── docs/
│   ├── architecture.md
│   └── sprints/
│       ├── sprint-v0.md
│       ├── sprint-v0.1.md
│       ├── sprint-v0.2.md
│       ├── sprint-v0.3.md
│       └── sprint-v0.4.md
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── contract/
│
├── pyproject.toml
├── .gitignore
└── README.md
```

A árvore acima representa o estado funcional pós-V0.4.

Diretórios futuros devem ser adicionados somente quando a versão correspondente os exigir.

---

## 6. Regras de organização atuais

### `orchestrator/`

Contém o core Python genérico do Harness.

Não deve conter configuração específica de um projeto consumidor.

### `orchestrator/cli.py`

Responsável pela interface CLI atual.

A CLI existente suporta os comandos já implementados pelo projeto: `doctor`, `intake`, o grupo `memory` (V0.3) e o grupo `decision` (V0.4: classify, route, severity, relevance, health).

Ela deve permanecer fina.

A CLI coordena serviços, mas não deve concentrar regras de domínio.

### `orchestrator/intake.py`

Responsável por normalizar entradas em um contrato único:

```text
Raw Input
→ normalize_request()
→ EngineeringRequest
```

Interactive e Autonomous Mode compartilham esse caminho.

A camada de intake não deve conhecer providers.

### `orchestrator/core/request.py`

Contém o modelo de domínio introduzido no V0.1:

- `EngineeringRequest`;
- `ExecutionMode`;
- `RequestSource`;
- `Intent`;
- `WorkflowState`;
- regras de compatibilidade entre mode e source.

Princípios:

- contrato único;
- validação explícita;
- request imutável;
- nenhum acoplamento com YAML, CLI ou provider concreto.

### `orchestrator/core/admission.py`

Responsável por admitir uma requisição normalizada.

Fluxo atual:

```text
EngineeringRequest
→ admit()
→ AdmittedRequest(state=PLANNED)
```

A admissão recebe configurações necessárias como dados.

Ela não deve carregar configuração diretamente.

### `orchestrator/config.py`

Responsável por:

- carregamento dos YAMLs;
- validação tipada;
- resolução da raiz do Harness;
- invariantes de configuração;
- referências cruzadas entre arquivos.

A resolução da raiz segue:

```text
--root
→ HARNESS_ROOT
→ diretório do próprio package
```

O comportamento não depende do current working directory.

### `orchestrator/doctor.py`

Responsável por diagnósticos determinísticos da fundação local.

Resultados possíveis:

```text
PASS
WARN
FAIL
```

O `doctor` não deve exigir integrações externas ainda não pertencentes à versão atual.

Exceção opt-in (V0.3): com `memory.enabled: true`, o check `memory` consulta o backend
(healthy → PASS, unavailable → WARN, misconfigured → FAIL). Com memória desabilitada
(padrão), nenhuma chamada de rede é feita.

Exceção opt-in (V0.4): quando o provider do `decisions.model` está `enabled: true`, o check
`decisions` faz um round trip autenticado sem inferência (Jev: `GET /v1/models`):
healthy → PASS, unavailable → WARN, chave ausente/rejeitada → FAIL. Com Jev desabilitado
(padrão), nenhuma chamada de rede é feita.

### `orchestrator/core/exceptions.py`

Define erros tipados do Harness, incluindo erros de configuração, request e provider.

A hierarquia deve permanecer pequena e evoluir apenas quando existirem consumidores reais.

### `orchestrator/providers/`

Implementado no V0.2.

Responsável por:

- contracts de providers;
- registry;
- model resolution;
- fake adapters;
- boundary de erros;
- adapter real Jev (`jev.py`, V0.4), único módulo que conhece a API TypeSafe.

Não contém adapters reais de LLM (OpenAI/Anthropic/NVIDIA: V2.x).

### `orchestrator/decisions/`

Implementado no V0.4.

Responsável por:

- `DecisionService`: request tipado → `DecisionProvider` → validação no boundary do Harness
  (`choice ∈ options`, identidade, distribuição, score só para opções ordenadas) → threshold → outcome;
- fallback contract (`DecisionOutcome`: `decided` | `fallback_required` + `low_confidence` |
  `unavailable` | `timeout` | `invalid_response`) — apenas sinalizado, nunca executado;
- telemetria mínima (`DecisionTelemetry`, log JSON sem pergunta, subject ou segredos);
- composição a partir de `decisions.yaml` + `models.yaml` + `providers.yaml` + ambiente (`open_decisions`).

Não implementa o Decision Policy Engine (combinação deterministic → Jev → LLM → human: V5),
retries, sampling nem calibração. Jev é probabilístico: nunca substitui uma regra determinística.

### `orchestrator/memory/`

Implementado no V0.3.

Responsável por:

- contract `MemoryProvider` (separado de `LLMProvider`/`DecisionProvider`);
- modelos tipados: scope, lineage, record, query, health;
- safe ingestion policy determinística (ALLOW/BLOCK);
- `MemoryService` (validação → policy → provider) e composição a partir de `memory.yaml`;
- adapter Mem0 self-hosted (único módulo que conhece Mem0);
- fake provider para testes.

O core (`core/`) não importa `memory/`. Somente CLI e `doctor` abrem a memória.

### `orchestrator/utils/shell.py`

Responsável por execução local de processos.

Princípios:

- sem shell por padrão;
- captura stdout;
- captura stderr;
- exit code explícito;
- timeout;
- erros tipados;
- resultado estruturado.

### `orchestrator/utils/files.py`

Contém apenas operações de filesystem realmente utilizadas pelo core.

### `orchestrator/utils/logging.py`

Centraliza configuração de logging.

Princípios:

- logger do Harness separado do output principal da CLI;
- logs em stderr;
- não registrar secrets;
- evitar argumentos, ambiente ou outputs sensíveis;
- preparado para structured logging futuro.

---

## 7. Mode Foundation

O V0.1 formalizou dois modos:

```text
INTERACTIVE
AUTONOMOUS
```

Ambos convergem para o mesmo contrato.

### Interactive Mode

Fontes previstas/representadas:

- CLI;
- MCP;
- Claude Code;
- Codex;
- HTTP API.

### Autonomous Mode

Fontes previstas/representadas:

- roadmap;
- sprint;
- task;
- previous run;
- persisted state.

O V0.1 não implementa autonomous loop.

Ele apenas representa semanticamente essas origens e normaliza o request.

### Fluxo atual

```text
Interactive Input ─┐
                   │
                   ├→ normalize_request()
                   │        ↓
Autonomous Input ──┘  EngineeringRequest
                            ↓
                          admit()
                            ↓
                 AdmittedRequest(PLANNED)
```

---

## 8. Provider Abstraction

O V0.2 introduziu a camada de providers.

### Objetivo

Permitir que provider e model possam ser trocados sem alteração do core.

### Contracts atuais

#### `LLMProvider`

Responsável por inferência generativa.

Contrato atual:

```text
LLMRequest
→ complete()
→ LLMResult
```

#### `DecisionProvider`

Responsável por decisão estruturada/probabilística.

Contrato atual:

```text
DecisionRequest
→ decide()
→ DecisionResult
```

Os dois contratos são separados intencionalmente.

Não existe uma interface genérica `AIProvider`.

### Provider Registry

O `ProviderRegistry` mantém mapas tipados por contract.

Princípios:

- provider id único;
- duplicate registration falha explicitamente;
- provider desconhecido falha explicitamente;
- type mismatch falha explicitamente.

### Model Resolution

O `ModelResolver` resolve:

```text
logical alias
→ provider
→ enabled?
→ provider model_id
→ adapter registrado
```

O alias lógico é separado do identificador externo do vendor.

### Fake Providers

Existem:

```text
FakeLLMProvider
FakeDecisionProvider
```

Eles:

- são determinísticos;
- registram requests;
- funcionam offline;
- não exigem secrets;
- permitem simular erro;
- traduzem falha para erro do Harness.

### Fluxo atual

```text
providers.yaml + models.yaml
          ↓
     ModelResolver
          ↓
   ProviderRegistry
      ┌────┴────┐
      ↓         ↓
LLMProvider  DecisionProvider
      ↓         ↓
 FakeLLM   FakeDecision
```

---

## 8.1 Memory Foundation

O V0.3 introduziu memória operacional de longo prazo.

### Contract

```text
MemoryProvider
  health()                   -> MemoryHealth (healthy | unavailable | misconfigured)
  add(NewMemory)             -> MemoryRecord
  search(MemoryQuery)        -> MemoryHit[]
  update(memory_id, content) -> MemoryRecord
  delete(memory_id)
```

### Scopes e lineage

- scopes: `project`, `task:<id>`, `run:<id>`, `agent:<id>`, `release:<id>`, sempre dentro do projeto;
- isolamento estrito: uma busca vê apenas o seu scope exato;
- lineage obrigatório: `<source_type>:<id>` (task_result, decision, finding, remediation,
  release, incident, implementation_note — RF-017).

### Safe ingestion

Antes de qualquer persistência, conteúdo e source id passam por regras determinísticas
(formatos conhecidos de API keys/tokens, private keys, authorization headers, credenciais em
URLs, atribuições de secrets em `.env`/YAML/literais). Resultado: ALLOW ou BLOCK (sem
redação). Nada bloqueado sai do processo.

### Fluxo atual

```text
harness memory ...  (operações explícitas)
      ↓
open_memory(config) → MemoryService
      ↓ validação → safe ingestion
MemoryProvider
      ↓
Mem0MemoryProvider → Mem0 self-hosted REST → pgvector
```

### Invariante

Memória é contexto auxiliar e **nunca** source of truth. Docs oficiais, ADRs, policies,
task/sprint contracts e Git prevalecem. No V0.3 nenhum componente lê memória para decidir;
a resolução de conflitos entre fontes pertence ao Context Engineering (V1.x).

---

## 9. Configuração declarativa

O projeto utiliza:

```text
config/
├── project.yaml
├── providers.yaml
├── models.yaml
├── agents.yaml
├── modes.yaml
├── context.yaml
├── memory.yaml
├── decisions.yaml
├── risks.yaml
└── pipelines.yaml
```

Cada configuração possui:

```yaml
version: 1
```

A presença de uma configuração não implica implementação da capacidade correspondente.

Exemplos:

- `providers.yaml` agora possui consumidor real;
- `models.yaml` agora possui consumidor real;
- `modes.yaml` possui consumidor real;
- `memory.yaml` possui consumidor real (V0.3: `open_memory`, CLI `memory`, `doctor`), desabilitado por padrão;
- `context.yaml` ainda não possui Context Engine;
- `decisions.yaml` possui consumidor real (V0.4: `open_decisions`, CLI `decision`, `doctor`):
  `model` (alias → Jev) e `thresholds.minimum_confidence`; Jev desabilitado por padrão.
  `escalation_order` continua declarativo até o V5.

### Validações atuais

A fundação já valida:

- schema via Pydantic;
- campos extras proibidos;
- YAML inválido;
- chaves duplicadas;
- model → provider;
- role → model;
- modes declarados;
- ordem conceitual de decisão;
- risco default válido;
- provider habilitado durante model resolution;
- `memory.yaml`: backend `mem0` exige seção `mem0` (URL http(s), nome da env var da API key, timeout); valores de chave são rejeitados;
- `decisions.yaml` (V0.4): `model` existe em `models.yaml`; `model` exige `thresholds`; `minimum_confidence` em 0..1;
- `providers.yaml` (V0.4): campos de conexão opcionais (`base_url` http(s), `api_key_env` nome de env var, `timeout_seconds`); valores de chave rejeitados.

---

## 10. Conceitos separados

Os seguintes conceitos são arquiteturalmente distintos:

```text
Role
RequestSource
Provider
Model
```

### Role

Representa responsabilidade de agente.

Ainda não possui runtime próprio.

### RequestSource

Representa de onde veio uma solicitação.

Vive no domínio de request.

### Provider

Representa backend de inferência/decisão.

Vive na camada `providers/`.

### Model

Representa um alias lógico configurado, ligado a um provider e ao `model_id` externo.

Essa separação deve ser preservada.

---

## 11. Princípios arquiteturais obrigatórios

### 11.1 Workflow governa agentes

Nenhum provider ou modelo controla sozinho o processo.

### 11.2 Determinismo primeiro

Ordem conceitual:

```text
Deterministic Rules
→ Jev
→ Reasoning LLM
→ Human
```

O V0.4 implementa apenas o segundo degrau (Jev), como camada isolada. Jev é
probabilístico: mesmo `confidence = 1.0` não é prova nem regra determinística, e
nenhuma decisão do Jev sobrescreve uma regra determinística. A combinação dos degraus
pertence ao V5.

### 11.3 Provider agnostic

O core não depende diretamente de:

- OpenAI;
- Anthropic;
- NVIDIA;
- Jev;
- Mem0.

### 11.4 Baixo acoplamento

Configuração específica permanece fora do core.

### 11.5 Simplicidade incremental

Não criar abstrações sem consumidor real.

### 11.6 Auditabilidade

Toda execução relevante deverá futuramente preservar evidências suficientes para reconstruir:

- solicitação;
- contexto;
- provider/model;
- decisões;
- gates;
- alterações;
- resultado.

---

## 12. Target architecture

A direção arquitetural permanece:

```text
engineering/
├── orchestrator/
│   ├── core/
│   ├── providers/
│   ├── agents/
│   ├── context/
│   ├── memory/
│   ├── decisions/
│   ├── review/
│   ├── gates/
│   ├── git/
│   ├── tools/
│   ├── prompts/
│   ├── pipelines/
│   ├── delivery/
│   ├── observability/
│   ├── storage/
│   └── utils/
│
├── config/
├── skills/
├── specialties/
├── guidelines/
├── policies/
├── prompts/
├── schemas/
├── pipelines/
├── environments/
├── infrastructure/
├── templates/
├── docs/
├── runs/
├── scripts/
└── tests/
```

Essa árvore é arquitetura alvo, não backlog automático.

Um diretório somente deve nascer quando houver:

- responsabilidade concreta;
- consumidor real;
- comportamento testável;
- versão do roadmap que o justifique.

---

## 13. Boundaries futuros

### `memory/`

Implementado no V0.3 (Mem0 self-hosted). Evoluções futuras — ingestão automática,
retenção, relevância, uso em contexto — pertencem a versões posteriores (V1.x+).

### `decisions/`

Implementado no V0.4 (Jev, fallback sinalizado, threshold, telemetria). O Decision Policy
Engine (combinação dos degraus, auto accept, LLM review, human escalation, sampling,
agreement) entra em:

```text
V5 — Decisions
```

### `context/`

Context Engineering entra a partir da família:

```text
V1.x — Context Engineering
```

### `agents/`

Runtime de roles e specialty routing entra em:

```text
V2.x — Agent Execution
```

### `gates/`

Validações determinísticas entram em:

```text
V3.x — Deterministic Quality
```

### `review/`

Review estruturado entra em:

```text
V4.x — Review System
```

### `git/`

Controle de repository, diff, branch, worktree e integration entra em:

```text
V7.x — Git Integration
```

### `storage/`

Persistência completa de runs e artifacts entra principalmente em:

```text
V8.x — Run Artifacts
```

### `delivery/`

Build, release, deploy, smoke e rollback entram entre:

```text
V10 — Release
V11 — Deployment
```

### `observability/`

Health, logs, metrics e validação pós-deploy entram em:

```text
V12 — Observability
```

---

## 14. Ordem oficial de implementação

A ordem atual é definida pelo roadmap:

```text
V0    Foundation
V0.1  Modes
V0.2  Providers
V0.3  Mem0
V0.4  Jev
V1    Global Library
V1.x  Context Engineering
V2    Agent Execution
V3    Gates
V4    Review
V5    Decisions
V6    State Machine
V7    Git
V8    Run Artifacts
V9    Risk
V10   Release
V11   Deploy
V12   Observability
V13   Autonomous Loop
V14   MCP/API/IDE
V15   Hardening
```

Essa ordem substitui sequências anteriores presentes em versões antigas da documentação arquitetural.

---

## 15. Próxima versão

O V0.4 — Decision Foundation está COMPLETE (ver `engineering/docs/sprints/sprint-v0.4.md`;
prova live 5/5 contra `jev-1.13.0` com `JEV_API_KEY`).

A próxima versão é:

```text
V1 — Global Library
```

A Global Library ainda não está implementada.

---

## 16. Contratos atuais e futuros

Contratos atualmente implementados:

```text
LLMProvider
DecisionProvider
MemoryProvider
```

Contracts futuros, quando houver consumidor real:

```text
Gate
Tool
DeploymentProvider
```

Essas interfaces não devem ser criadas apenas por antecipação.

Cada contract deve surgir junto do primeiro caso de uso real.

---

## 17. Precedência de fontes

A precedência conceitual continua:

```text
Policies / explicit invariants
        ↓
ADRs
        ↓
Task / Sprint contract
        ↓
Project guidelines
        ↓
Skills / specialties
        ↓
Repository context
        ↓
Mem0 / previous runs
```

Para versionamento e sequência de entrega:

```text
AI-Engineering-Harness-Roadmap.md
```

é a fonte autoritativa.

Memória nunca substitui fonte oficial.

---

## 18. Segurança

Princípios obrigatórios:

- secrets não devem ser persistidos em logs;
- não registrar `.env`;
- não registrar tokens;
- nenhuma API key em YAML;
- subprocess sem shell quando possível;
- paths validados;
- configuração inválida falha cedo;
- provider errors não devem vazar prompts;
- erros e telemetria de decisão não contêm pergunta, subject, API key nem header `Authorization`;
- ausência de evidência crítica não deve ser tratada como sucesso.

Hardening completo entra posteriormente.

---

## 19. Testabilidade

Toda nova capacidade deve possuir:

- type hints;
- testes;
- erro previsível;
- configuração validável;
- possibilidade de uso com fake quando envolver serviço externo;
- testes offline sempre que possível.

O V0.2 já introduziu contract tests para providers.

Adapters concretos futuros devem respeitar esses contracts.

---

## 20. Stack atual

### Core

```text
Python 3.12+
Typer
Pydantic v2
PyYAML
Rich
pytest
```

### Tooling de qualidade

```text
ruff
mypy
pytest
```

Não existem SDKs reais de providers instalados. O adapter Mem0 (V0.3) usa a API REST do
servidor self-hosted e o adapter Jev (V0.4) usa a API HTTP documentada da TypeSafe
(`POST /v1/systemone`), ambos via biblioteca padrão (`urllib`); nenhuma dependência nova
foi adicionada.

### Infraestrutura de memória (externa, opcional)

```text
Mem0 self-hosted REST server (FastAPI) + PostgreSQL/pgvector (Docker Compose do Mem0)
```

---

## 21. Integrações previstas

Implementada:

```text
Mem0 self-hosted (V0.3, via REST; infraestrutura Docker do próprio Mem0)
Jev / TypeSafe System One (V0.4, via HTTP; SaaS api.typesafe.ai; opt-in)
```

Ainda não implementadas:

```text
OpenAI
Anthropic Claude
NVIDIA
Git orchestration
```

A ausência dessas integrações no V0.4 é intencional.

---

## 22. Decisões arquiteturais consolidadas

### Dois provider contracts pequenos

Existem:

```text
LLMProvider
DecisionProvider
```

em vez de uma interface genérica de IA.

### Protocol em vez de ABC obrigatório

Adapters satisfazem contracts estruturalmente.

Mypy e contract tests complementam a validação.

### Registry tipado

Um registry mantém mapas separados por tipo de provider.

### Sem factory/bootstrap prematuro

Ainda não há adapters concretos suficientes para justificar essa camada. O V0.4 introduziu
apenas `build_decision_adapter` (um `kind`: jev) no passo de composição de decisões.

### DecisionProvider evoluído de forma aditiva (V0.4)

Campos novos opcionais (`kind`, `subject`, `ordered`, `descriptions`; `probability`,
`probabilities`, `score`, `resolved_model`, `input_tokens`). Requests/results do V0.2
continuam válidos. `choice ∈ options` é garantido no adapter e no `DecisionService`.

### Fallback é valor, não ação (V0.4)

`DecisionOutcome` sinaliza `fallback_required` com motivo tipado; nenhum LLM ou humano é
acionado pelo Harness até o V5.

### Alias lógico separado do model id externo

Configuração pode referenciar modelos semanticamente sem acoplar o core ao identificador do vendor.

### Fakes reutilizáveis

Fake providers vivem no package e não são registrados automaticamente.

---

## 23. Dívidas técnicas conhecidas

As seguintes dívidas foram identificadas no V0.2:

- registration valida existência de métodos, não assinatura completa em runtime;
- ~~`DecisionResult.choice ∈ options` é garantido principalmente por contract tests~~
  (resolvido no V0.4: validado no adapter e no `DecisionService`);
- contracts atuais são síncronos;
- ~~`ProviderEntry.kind` ainda não possui consumidor real~~ (V0.4: `build_decision_adapter`).

Esses pontos não impediram o V0.3.

Identificadas no V0.3:

- a safe ingestion policy é heurística (regex): reduz, mas não elimina, o risco de secrets
  em formatos desconhecidos;
- a busca não filtra por metadata além do scope;
- `created_at`/`updated_at` dependem do formato retornado pelo backend.

Identificadas no V0.4:

- transporte HTTP duplicado entre `memory/mem0.py` e `providers/jev.py` (~40 linhas);
- `minimum_confidence` padrão (0.70) não calibrado; alias `jev-latest` pode mudar sob o threshold;
- telemetria só em log/objeto (sem persistência: Run Artifacts, V8);
- sem retry/backoff para 429/529 (política do V5).

Não devem ser resolvidos preventivamente sem necessidade real.

---

## 24. Critérios arquiteturais para novas versões

Cada versão deve:

1. introduzir apenas capacidades necessárias;
2. possuir testes;
3. manter baixo acoplamento;
4. evitar abstrações sem consumidor real;
5. produzir contracts estruturados quando necessário;
6. manter auditabilidade;
7. atualizar documentação quando decisões arquiteturais mudarem;
8. não alterar silenciosamente a arquitetura;
9. respeitar a ordem oficial do roadmap;
10. parar ao atingir os critérios de saída da versão atual.

---

## 25. Estado arquitetural consolidado

O estado atual pode ser resumido como:

```text
Project Foundation
        ↓
Typed Configuration
        ↓
Mode Foundation
        ↓
EngineeringRequest
        ↓
Admission
        ↓
Provider Abstraction
        ↓
Model Resolution
        ↓
Provider Registry
        ↓
Fake Providers
        ↓
Memory Foundation (Mem0 self-hosted, scopes, lineage, safe ingestion)
        ↓
Decision Foundation (Jev, typed decisions, threshold, fallback contract, telemetry)
        ↓
Ready for Global Library (V1)
```

Ainda não existe provider externo real de inferência generativa.

A memória operacional existe, mas é operada apenas explicitamente e nunca é source of truth.

Ainda não existe Context Engineering.

O decision provider real (Jev) existe como camada probabilística isolada; não há Decision
Policy Engine e nenhum fallback é executado automaticamente.

Ainda não existe agent execution.

Ainda não existe autonomia.

Essas capacidades serão adicionadas progressivamente conforme o roadmap.

---

## 26. Regra final

A estrutura deste documento representa duas coisas distintas:

### Current architecture

O que está efetivamente implementado e testado hoje.

### Target architecture

A direção que permite evoluir o Harness até se tornar um engineering control plane completo.

Nunca confundir arquitetura alvo com implementação atual.

A regra permanece:

> preparar para evolução sem antecipar complexidade.
