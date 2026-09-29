# AI Engineering Harness — Roadmap de Implementação

## 1. Objetivo

Este roadmap define a implementação incremental do AI Engineering Harness, considerando desde o início dois modos de operação:

- **Interactive Mode** — iniciado por uma solicitação humana via Claude Code, Codex, CLI, MCP ou API.
- **Autonomous Mode** — iniciado e conduzido pela state machine a partir do estado do projeto, roadmap, sprint e tasks pendentes.

Ambos os modos compartilham o mesmo core:

- Context Engine
- Memory
- Agent Routing
- Provider Abstraction
- Decision Engine
- Deterministic Gates
- Review
- State Machine
- Git Integration
- Delivery
- Observability

A estratégia é evoluir por versões pequenas, verificáveis e auditáveis, evitando autonomia ampla antes de existirem contexto, gates, memória, decisões e políticas suficientes.

---

## 2. Princípios

### 2.1 Incrementalidade
Cada versão adiciona uma capacidade clara e testável.

### 2.2 Determinismo primeiro
Sempre que possível:

```text
código
→ regra
→ gate
```

antes de:

```text
Jev
→ LLM
→ humano
```

### 2.3 Baixo acoplamento
OpenAI, Anthropic, NVIDIA, Jev e Mem0 entram via adapters.

### 2.4 Source of Truth
Documentação oficial, ADRs, policies, task contracts e Git têm precedência sobre memória e decisões probabilísticas.

### 2.5 Auditabilidade
Toda execução relevante gera artefatos estruturados.

### 2.6 Autonomia controlada
O Harness opera autonomamente apenas dentro de limites explícitos.

---

# 3. Fases

## V0 — Project Foundation

### Objetivo
Criar a base estrutural correta do projeto.

### Implementar
- estrutura inicial de diretórios;
- `pyproject.toml`;
- CLI base;
- config loader;
- validação Pydantic;
- logging;
- subprocess helper;
- filesystem helper;
- `doctor`;
- testes unitários iniciais;
- README;
- documentação arquitetural inicial.

### Configurações iniciais
- `project.yaml`
- `providers.yaml`
- `models.yaml`
- `agents.yaml`
- `modes.yaml`
- `context.yaml`
- `memory.yaml`
- `decisions.yaml`
- `risks.yaml`
- `pipelines.yaml`

### Critérios de saída
- `python -m orchestrator` funciona;
- `python -m orchestrator doctor` funciona;
- configs inválidas falham corretamente;
- estrutura do projeto é validada;
- testes passam;
- nenhuma integração externa real é obrigatória.

---

## V0.1 — Mode Foundation

### Objetivo
Formalizar os dois modos de operação.

### Interactive Mode
Entrada iniciada por humano.

Fontes futuras:
- CLI;
- MCP;
- Claude Code;
- Codex;
- HTTP API.

### Autonomous Mode
Entrada iniciada pela state machine.

Fontes:
- roadmap;
- sprint;
- task pendente;
- run anterior;
- estado persistido.

### Criar
- `EngineeringRequest`;
- `ExecutionMode`;
- `RequestSource`;
- `Intent`;
- normalização de entrada;
- regras de transição inicial.

### Critério de saída
O core recebe uma requisição normalizada independentemente da origem.

---

## V0.2 — Provider Abstraction

### Objetivo
Definir abstração de providers sem acoplamento.

### Providers previstos
- OpenAI;
- Anthropic;
- NVIDIA;
- Jev.

### Implementar
- `LLMProvider`;
- `DecisionProvider`;
- provider registry;
- configuração por YAML;
- resolução de provider/model;
- adapters fake para testes.

### Não implementar ainda
- prompting complexo;
- closed loop;
- state machine completa.

### Critério de saída
Trocar provider/model não exige alteração do core.

---

## V0.3 — Memory Foundation

### Objetivo
Integrar Mem0 self-hosted como memória de longo prazo.

### Implementar
- `MemoryProvider`;
- adapter Mem0;
- health/connectivity;
- add/search/update/delete;
- metadata;
- namespaces/scopes;
- safe ingestion policy;
- blacklist de secrets;
- lineage básico;
- testes com fake provider.

### Escopos
- project;
- task;
- run;
- agent;
- release.

### Critério de saída
O Harness consegue:

```text
gravar memória
→ reiniciar
→ recuperar memória
```

sem transformar memória em source of truth.

---

## V0.4 — Decision Foundation

### Objetivo
Integrar Jev como decision provider probabilístico.

### Implementar
- connectivity;
- typed decisions;
- score;
- choice;
- probability/confidence;
- provider telemetry;
- fallback contract;
- thresholds configuráveis.

### Primeiro uso
- classification;
- routing;
- context relevance;
- severity.

### Critério de saída
O Harness chama Jev e retorna uma decisão estruturada auditável.

---

# 4. Context Engineering

## V1 — Global Library

### Objetivo
Criar biblioteca reutilizável global.

### Estrutura
- skills;
- guidelines;
- policies;
- rules;
- specialties.

### Exemplos iniciais

#### Skills
- python;
- laravel;
- testing;
- database;
- security;
- API;
- Docker.

#### Guidelines
- coding;
- architecture;
- testing;
- documentation;
- review.

#### Policies
- secrets;
- security;
- Git;
- breaking changes;
- deploy.

#### Rules
- thin controllers;
- explicit authorization;
- validation at boundaries;
- avoid unnecessary abstractions.

### Critério de saída
O projeto pode declarar sua stack e herdar conhecimento global sem duplicar arquivos localmente.

---

## V1.1 — Context Candidate Discovery

### Objetivo
Descobrir automaticamente fontes de contexto relevantes.

### Fontes
- task;
- sprint;
- project instructions;
- policies;
- guidelines;
- skills;
- specialties;
- ADRs;
- docs;
- repository;
- Git;
- Mem0;
- previous runs;
- releases.

### Critério de saída
Dada uma task, o Harness gera uma lista estruturada de candidatos.

---

## V1.2 — Context Classification

### Objetivo
Classificar candidatos.

### Classes
- REQUIRED;
- HIGH_VALUE;
- OPTIONAL;
- EXCLUDED.

### Estratégias
- deterministic;
- Jev;
- fallback LLM.

### Critério de saída
Cada item possui:
- source;
- type;
- classification;
- relevance;
- reason;
- selected_by.

---

## V1.3 — Context Budget

### Objetivo
Controlar quantidade de contexto.

### Implementar
- token/character budget;
- limite por categoria;
- prioridade;
- truncation policy;
- reserve;
- max files;
- max memories;
- max ADRs.

### Critério de saída
O Harness produz contexto menor e relevante sem depender do limite máximo do modelo.

---

## V1.4 — LLM Context Escalation

### Objetivo
Usar LLM forte quando seleção de contexto for complexa.

### Escalar quando
- task arquitetural;
- múltiplos domínios;
- alto risco;
- baixa confiança;
- muitos candidatos relevantes;
- conflito entre fontes.

### Critério de saída
O Harness produz `ContextPlan` estruturado via LLM.

---

## V1.5 — Context Telemetry

### Objetivo
Medir qualidade do contexto.

### Registrar
- itens selecionados;
- itens descartados;
- scores;
- context misses;
- unused context;
- tamanho;
- escalations;
- provider agreement.

### Critério de saída
É possível avaliar precisão e recall contextual por run.

---

# 5. Agent Execution

## V2 — Claude Runner

### Objetivo
Executar Claude de forma não interativa.

### Implementar
- input estruturado;
- prompt renderer;
- subprocess execution;
- stdout/stderr;
- exit code;
- timeout;
- structured result;
- run artifacts;
- provider metadata.

### Critério de saída
O Harness executa uma task simples via Claude sem copy/paste.

---

## V2.1 — OpenAI Architect / Reviewer

### Objetivo
Integrar OpenAI como camada de raciocínio forte.

### Usos
- arquitetura;
- planning;
- context escalation;
- review;
- remediation planning.

### Critério de saída
OpenAI e Claude operam como roles diferentes sem acoplamento.

---

## V2.2 — NVIDIA Provider

### Objetivo
Adicionar provider NVIDIA.

### Requisitos
- mesmo contrato;
- configuração declarativa;
- sem alterar core.

### Critério de saída
Provider pode ser usado em qualquer role compatível.

---

## V2.3 — Agent Roles

### Objetivo
Formalizar roles.

### Roles
- Architect;
- Implementer;
- Reviewer;
- Test Engineer;
- Validator;
- Release Engineer;
- Deployment Engineer.

### Critério de saída
Role é desacoplada de provider.

---

## V2.4 — Specialty Routing

### Objetivo
Associar specialties dinamicamente.

### Exemplo

```text
Role: Implementer
Specialties:
- php-laravel
- database
- testing
```

### Routing
Pode usar:
- task metadata;
- deterministic rules;
- Jev;
- LLM escalation.

---

# 6. Deterministic Quality

## V3 — Gate Framework

### Objetivo
Criar sistema genérico de gates.

### Implementar
- Gate interface;
- command gates;
- aggregation;
- severity;
- required/optional;
- evidence;
- exit behavior.

---

## V3.1 — Core Gates

### Gates iniciais
- tests;
- lint;
- static analysis;
- Git status;
- Git scope;
- build.

---

## V3.2 — Architecture / Security / Contract Gates

### Implementar
- architecture tests;
- security checks;
- public contract checks;
- migration safety;
- forbidden path rules.

---

## V3.3 — Gate Policies

### Objetivo
Tornar gates dependentes de:
- stack;
- task type;
- risk;
- environment.

---

# 7. Review System

## V4 — Structured Review

### Objetivo
Criar review formal e auditável.

### Implementar
- findings;
- severity;
- evidence;
- scope drift;
- architectural drift;
- remediation suggestion;
- review result.

---

## V4.1 — Specialist Reviewers

### Exemplos
- architecture reviewer;
- security reviewer;
- database reviewer;
- testing reviewer;
- deployment reviewer.

---

## V4.2 — Independent Test Engineer

### Objetivo
Criar testes derivados de requisitos e invariantes.

O Test Engineer não deve assumir que a implementação está correta.

---

# 8. Decision Layer

## V5 — Decision Policy Engine

### Objetivo
Combinar decisões determinísticas, Jev, LLM e humano.

### Ordem

```text
Deterministic
→ Jev
→ Reasoning LLM
→ Human
```

---

## V5.1 — Jev Decision Routing

### Usos
- scope drift;
- severity;
- routing;
- next-state candidate;
- context relevance;
- review requirement.

---

## V5.2 — Confidence Thresholds

### Implementar
- auto accept;
- LLM review;
- human review;
- configurable thresholds.

---

## V5.3 — Sampling

### Objetivo
Auditar parte das decisões automáticas de alta confiança.

### Medir
- Jev/LLM agreement;
- false acceptance;
- false escalation;
- confidence calibration.

---

# 9. Workflow State

## V6 — State Machine

### Estados
- PLANNED;
- CONTEXT_BUILDING;
- READY;
- IMPLEMENTING;
- VERIFYING;
- REVIEWING;
- REMEDIATION;
- BLOCKED;
- HUMAN_REVIEW;
- READY_FOR_INTEGRATION;
- INTEGRATING;
- READY_FOR_RELEASE;
- RELEASING;
- DEPLOYING;
- OBSERVING;
- RELEASED;
- ROLLBACK_REQUIRED;
- ROLLED_BACK;
- FAILED.

---

## V6.1 — Interactive Flow

```text
Human Request
→ Intake
→ Context
→ Execution
→ Validation
→ Review
→ Response
```

O Harness retorna controle ao humano ao final da unidade atual.

---

## V6.2 — Autonomous Flow

```text
State Machine
→ Next Task
→ Context
→ Execution
→ Validation
→ Review
→ Decision
→ Next State
```

Continua automaticamente até condição de parada.

---

## V6.3 — Human Escalation

### Parar quando
- architecture decision;
- missing requirement;
- critical risk;
- destructive operation;
- unresolved ambiguity;
- retry limit exceeded;
- security issue;
- production approval required.

---

# 10. Git Integration

## V7 — Repository Control

### Implementar
- status;
- diff;
- history;
- branch;
- commit metadata;
- repository state.

---

## V7.1 — Worktree Isolation

### Objetivo
Executar tasks em worktrees isolados.

---

## V7.2 — Change Scope

### Implementar
- allowed paths;
- forbidden paths;
- unexpected changes;
- diff summary.

---

## V7.3 — Integration

### Implementar
- merge readiness;
- integration checks;
- conflict handling;
- rollback of failed integration.

---

# 11. Run Artifacts

## V8 — Execution Persistence

### Cada run deve armazenar

```text
manifest.json
request.json
context.json
prompt.md
events.jsonl
stdout.log
stderr.log
diff.patch
gates.json
decisions.json
review.json
result.json
```

---

## V8.1 — Lineage

### Relacionar
- project;
- sprint;
- task;
- run;
- commit;
- memory;
- decision;
- release.

---

# 12. Risk Engine

## V9 — Risk Classification

### Níveis
- LOW;
- MEDIUM;
- HIGH;
- CRITICAL.

---

## V9.1 — Risk-aware Policies

### Risco deve controlar
- reviewers;
- gates;
- retries;
- human approval;
- deployment;
- rollback;
- sampling.

---

# 13. Release

## V10 — Build and Release

### Implementar
- build;
- artifacts;
- version;
- release candidate;
- changelog/release notes;
- release gates.

---

## V10.1 — Pre-release Validation

### Exigir quando aplicável
- green tests;
- security;
- migrations;
- contracts;
- config validation;
- rollback plan.

---

# 14. Deployment

## V11 — Environment Model

### Ambientes
- local;
- test;
- staging;
- production.

---

## V11.1 — Deployment Adapters

### Objetivo
Deploy provider-agnostic.

Possíveis adapters futuros:
- SSH;
- Docker Compose;
- CI/CD;
- cloud provider;
- Kubernetes.

---

## V11.2 — Staging Deployment

### Implementar
- deploy;
- health;
- smoke;
- logs;
- metrics.

---

## V11.3 — Production Deployment

### Implementar
- approval policy;
- backup verification;
- migration execution;
- deploy;
- post-deploy validation.

---

# 15. Post-Deploy

## V12 — Observability

### Integrar
- health;
- logs;
- metrics;
- queue health;
- error rate;
- latency;
- alerts.

---

## V12.1 — Release Verification

Deploy só é RELEASED após validação.

---

## V12.2 — Rollback

### Acionar quando configurado
- health failure;
- smoke failure;
- error rate spike;
- migration issue;
- critical alert.

---

# 16. Autonomous Engineering Loop

## V13 — Controlled Autonomous Loop

### Objetivo
Permitir execução contínua do projeto.

### Fluxo

```text
Roadmap
→ Sprint
→ Task
→ Context
→ Implement
→ Validate
→ Review
→ Decide
→ Remediate if needed
→ Integrate
→ Next Task
```

---

## V13.1 — Autonomous Sprint Progression

O Harness deve:
- identificar próxima task;
- respeitar dependencies;
- verificar exit criteria;
- criar run;
- executar;
- decidir próximo estado.

---

## V13.2 — Autonomous Remediation

Permitida apenas dentro de limites.

---

## V13.3 — Human Checkpoints

Humano deve ser chamado para decisões que não devem ser automatizadas.

---

# 17. Interface Layer

## V14 — CLI

Comandos previstos:

```text
harness doctor
harness status
harness interactive
harness autonomous
harness task run
harness task review
harness memory search
harness context inspect
harness decisions inspect
```

---

## V14.1 — MCP Server

### Objetivo
Permitir Claude Code e Codex consumirem o Harness.

### Tools previstas
- `plan_task`
- `get_context`
- `search_memory`
- `get_policy`
- `get_skill`
- `get_adr`
- `evaluate_result`
- `report_result`
- `request_decision`

---

## V14.2 — HTTP API

### Objetivo
Expor o Harness a:
- IDE;
- dashboard;
- external automation;
- CI;
- future clients.

---

## V14.3 — Native Integrations

### Possibilidades
- Claude Code hooks;
- Codex App Server;
- IDE integrations.

---

# 18. Hardening

## V15 — Security Hardening

### Implementar
- least privilege;
- secret redaction;
- command allowlists;
- sandbox policies;
- permission boundaries;
- audit log integrity.

---

## V15.1 — Reliability

### Implementar
- retries;
- timeouts;
- fallback;
- provider outages;
- circuit breaking quando necessário.

---

## V15.2 — Cost Control

### Medir
- tokens;
- provider cost;
- decision cost;
- memory cost;
- execution duration.

---

# 19. Future Capabilities

Após estabilidade real:
- dashboard web;
- multi-project control plane;
- distributed workers;
- remote execution;
- team collaboration;
- policy learning;
- adaptive routing;
- automatic model selection;
- evaluation datasets;
- benchmark suite;
- plugin ecosystem;
- marketplace de skills;
- CI/CD integrations;
- multi-host execution.

---

# 20. Ordem Recomendada de Implementação

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

---

# 21. Primeiro Milestone Real

```text
User request
→ Interactive Intake
→ Context Candidate Discovery
→ Global Library
→ Mem0 retrieval
→ Jev classification
→ Context Package
→ Claude execution
→ deterministic validation
→ structured result
```

Sem ainda avançar tasks autonomamente.

---

# 22. Segundo Milestone Real

```text
Task
→ Claude
→ Gates
→ Jev
→ OpenAI reviewer
→ remediation
→ final PASS
```

Sem copy/paste manual.

---

# 23. Terceiro Milestone Real

```text
Sprint
→ autonomous task selection
→ execution
→ validation
→ review
→ decision
→ next task
```

com human escalation.

---

# 24. Critério de Maturidade

O Harness estará maduro quando:

- o mesmo core atender Interactive e Autonomous Mode;
- contexto for selecionado automaticamente;
- memória for persistente e governada;
- providers puderem ser trocados;
- decisões forem auditáveis;
- gates impedirem avanço incorreto;
- tarefas de baixo risco fluírem sem intervenção;
- decisões críticas forem escaladas;
- release e deploy forem governados;
- rollback e post-deploy forem verificáveis.
