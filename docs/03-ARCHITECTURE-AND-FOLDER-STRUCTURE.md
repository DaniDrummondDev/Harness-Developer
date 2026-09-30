# AI Engineering Harness — Arquitetura e Estrutura de Pastas

## 1. Objetivo

Este documento descreve a arquitetura atual e a estrutura de pastas do AI Engineering Harness após a conclusão do **V1.4 — LLM Context Escalation** (sobre o V1.3 — Context Budget, o V1.2 — Context Classification, o V1.1 — Context Candidate Discovery e o V1 — Global Library).

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
V1   — Global Library           COMPLETE
V1.1 — Context Candidate Discovery COMPLETE
V1.2 — Context Classification  COMPLETE
V1.3 — Context Budget          COMPLETE
V1.4 — LLM Context Escalation  COMPLETE
```

Próxima versão: **V1.5 — Context Telemetry** (não iniciada).

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
- Global Library (V1): skills, guidelines, policies, rules e specialties versionados
  (Markdown + front matter YAML, schema `version: 1`), pertencentes à instalação do Harness
  e herdados — não copiados — pelos projetos consumidores;
- `GlobalLibrary` (load → parse → validate → index → resolve), `Authority` fixa por tipo
  (policy = mandatory > guideline/rule = recommended > skill/specialty = knowledge);
- resolução determinística contra o perfil do projeto (`project.yaml` → `stack` e o novo
  campo opcional `capabilities`), com motivo por item;
- comandos `library` (inspect/resolve) e check offline `library` no `doctor`;
- Context Candidate Discovery (V1.1): `EngineeringRequest` → `ContextDiscoveryResult` com
  candidatos tipados, determinísticos e com proveniência, vindos da Global Library,
  instruction files, ADRs, documentação, arquivos citados na requisição e memória (opt-in);
- comando `context discover` e check `context` no `doctor` (só valida caminhos);
- Context Classification (V1.2): `ContextDiscoveryResult` → `ContextClassificationResult`,
  cada candidato com exatamente uma classe (REQUIRED/HIGH_VALUE/OPTIONAL/EXCLUDED), quem
  decidiu (`deterministic`/`probabilistic`/`fallback`) e evidência estruturada; regras
  determinísticas primeiro, Jev (via `DecisionService`) para o restante quando habilitado,
  fallback conservador OPTIONAL;
- comando `context classify` e check estrutural `classification` no `doctor`;
- Context Budget (V1.3): `ContextClassificationResult` → `ContextBudgetResult`, seleção
  determinística de itens inteiros num orçamento em **caracteres** (total − reserve,
  limites por categoria, `max_files`/`max_adrs`/`max_memories`): todo REQUIRED, depois
  HIGH_VALUE, depois OPTIONAL, EXCLUDED nunca; REQUIRED que não cabe vira status explícito
  (`REQUIRED_OVERFLOW` / `REQUIRED_UNAVAILABLE`), nunca é removido; cada candidato com
  motivo estruturado de entrada/saída; materialização lazy e segura do conteúdo;
- comando `context budget` e check estrutural `budget` no `doctor`;
- LLM Context Escalation (V1.4): `ContextBudgetResult` → `ContextEscalationResult`;
  gatilhos **determinísticos** (intent arquitetural declarado, múltiplas specialties
  relevantes, decisões abaixo do threshold, excesso de HIGH_VALUE, conflito de metadata
  registrado pelo merge, `REQUIRED_OVERFLOW`, `REQUIRED_UNAVAILABLE`) decidem se a seleção
  precisa de um modelo de raciocínio; só então o planner (alias lógico → `ModelResolver` →
  `LLMProvider`) recebe metadata segura (nunca conteúdo) e propõe um `ContextPlan`, validado
  deterministicamente (REQUIRED mantido, EXCLUDED nunca, ids conhecidos, sem
  reclassificação, budget reaplicado); qualquer falha mantém o resultado do V1.3;
- comando `context plan` e check estrutural `escalation` no `doctor`;
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
- adapter LLM real para o planner de contexto (a escalation do V1.4 roda com provider de
  teste; sem adapter, uma escalation termina `FAILED planner_unavailable` com o resultado
  determinístico); gatilho de alto risco (sem fonte de risco até o V9);
- telemetria de contexto (V1.5), truncation parcial, sumarização, chunking semântico,
  renderização de prompt/context package; classificação via reasoning LLM;
- descoberta de task/sprint contracts, Git, previous runs, releases e findings (sem store real);
- composição Global Library + conhecimento específico do projeto;
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

## 5. Estrutura real após o V1.4

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
│   ├── library/              # V1
│   │   ├── __init__.py
│   │   ├── models.py         # ArtifactType, Authority, AppliesTo, metadata, ProjectProfile, Match
│   │   ├── loader.py         # resolve_library_root; discover/read/parse/validate
│   │   └── library.py        # GlobalLibrary: index, by_type, get, resolve
│   │
│   ├── context/              # V1.1: discovery; V1.2: classification; V1.3: budget; V1.4: escalation
│   │   ├── __init__.py
│   │   ├── models.py         # CandidateKind, ContextCandidate, Provenance(match), ContextDiscoveryResult
│   │   ├── files.py          # ProjectFiles: roots contidas, walks limitados, exclusões
│   │   ├── discoverers.py    # library, instructions, adrs, documentation, repository_hints, memory
│   │   ├── discovery.py      # ContextCandidateDiscovery (merge/sort), build_discovery
│   │   ├── classification/   # V1.2
│   │   │   ├── __init__.py
│   │   │   ├── models.py         # ContextClass, SelectedBy, Evidence, ContextClassification, result
│   │   │   ├── deterministic.py  # ClassificationRule table, DeterministicClassifier
│   │   │   ├── probabilistic.py  # Decider protocol, ProbabilisticClassifier (Jev via DecisionService)
│   │   │   └── classifier.py     # ContextClassifier, build_classifier
│   │   ├── budget/           # V1.3
│   │   │   ├── __init__.py
│   │   │   ├── models.py         # BudgetCategory, BudgetStatus, BudgetReason, BudgetedItem, result
│   │   │   ├── content.py        # ContentLoader protocol, ContextContentLoader (referência → texto seguro)
│   │   │   └── budgeter.py       # ContextBudgeter (política de seleção), priority_key, build_budgeter
│   │   └── escalation/       # V1.4
│   │       ├── __init__.py
│   │       ├── models.py         # EscalationReason, ContextEscalationDecision, ContextPlan, result
│   │       ├── invariants.py     # PlanningRole, plan_violations (invariantes de qualquer plano)
│   │       ├── evaluator.py      # EscalationEvaluator (gatilhos determinísticos)
│   │       ├── planning.py       # ContextPlanningInput (allow-list segura), constraints, prompt
│   │       ├── validation.py     # PlannerResponse (schema estrito), validate_plan
│   │       └── planner.py        # ContextPlanner (LLMProvider), ContextEscalation, composição
│   │
│   └── utils/
│       ├── files.py
│       ├── logging.py
│       ├── shell.py
│       └── yaml_loader.py    # V1: safe YAML (duplicate keys rejected), config + library
│
├── policies/                 # V1 Global Library (conteúdo; um .md por artefato)
├── guidelines/
├── rules/
├── skills/
├── specialties/
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
│       ├── sprint-v0.4.md
│       ├── sprint-v1.md
│       ├── sprint-v1.1.md
│       ├── sprint-v1.2.md
│       └── sprint-v1.3.md
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

A árvore acima representa o estado funcional pós-V1.4.

Diretórios futuros devem ser adicionados somente quando a versão correspondente os exigir.

---

## 6. Regras de organização atuais

### `orchestrator/`

Contém o core Python genérico do Harness.

Não deve conter configuração específica de um projeto consumidor.

### `orchestrator/cli.py`

Responsável pela interface CLI atual.

A CLI existente suporta os comandos já implementados pelo projeto: `doctor`, `intake`, o grupo `memory` (V0.3), o grupo `decision` (V0.4: classify, route, severity, relevance, health), o grupo `library` (V1: inspect, resolve) e o grupo `context` (V1.1: discover; V1.2: classify; V1.3: budget — exit 3 em
`REQUIRED_OVERFLOW`/`REQUIRED_UNAVAILABLE`; V1.4: plan — exit 3 quando a escalation falha
ou resta constraint não resolvida).

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

Check `library` (V1): sempre executado e sempre offline. Carrega a Global Library
(independente da raiz do Harness) e retorna FAIL em erro de estrutura, parsing, schema,
ID duplicado ou referência inexistente; WARN se a biblioteca estiver vazia.

Check `context` (V1.1): executado quando `context.enabled`; apenas valida os caminhos de
discovery configurados (FAIL se algum resolver fora do projeto; caminhos opcionais ausentes
aparecem no detalhe do PASS). Nunca executa discovery (que exige uma requisição).

Check `classification` (V1.2): executado junto com `context`; estrutural e offline. Informa a
estratégia que `context classify` usará (regras determinísticas; modelo de decisão quando
`classification.probabilistic` e o provider estão habilitados; fallback OPTIONAL). WARN se
`probabilistic: true` sem `decisions.model`. Nunca classifica nem chama o provider.

Check `budget` (V1.3): executado junto com `context`; estrutural e offline. Informa o
orçamento que `context budget` aplicará (unidade, total, reserve, usable, limites por
categoria e de itens); WARN se um limite de categoria for ≥ usable (nunca restringe). Nunca
materializa conteúdo, seleciona, lê o repositório nem chama provider (invariantes inválidas
já falham em `config_valid`).

Check `escalation` (V1.4): executado junto com `context`; estrutural e offline. Informa os
gatilhos e o modelo planner que `context plan` usará. PASS quando desabilitado, sem modelo
ou com provider desabilitado (escalations mantêm o resultado determinístico); FAIL quando o
alias aponta para um provider só de decisão (jev); WARN quando o provider está habilitado
mas não há adapter LLM (V2.x). Nunca abre adapter, chama provider ou planeja.

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

### `orchestrator/library/`

Implementado no V1.

Responsável por:

- contratos dos cinco tipos de artefato (`ArtifactType`) e da sua força normativa
  (`Authority`, derivada do tipo e nunca declarada pelo autor);
- localização da biblioteca (`resolve_library_root`: argumento explícito →
  `$HARNESS_LIBRARY_ROOT` → diretório de instalação do Harness), **independente** de
  `--root`/`$HARNESS_ROOT`, para que um projeto consumidor herde a biblioteca sem copiá-la;
- discover → read → parse (front matter YAML seguro) → validate por arquivo, com proteção
  contra symlinks que saem do diretório esperado, arquivos inesperados e arquivos grandes;
- `GlobalLibrary`: índice por `(tipo, id)`, IDs duplicados, referências de specialties,
  `artifacts`/`by_type`/`get` e `resolve(ProjectProfile)` determinístico.

Não conhece CLI, providers, Jev, Mem0, rede ou subprocessos (teste de isolamento). O core
(`core/`) não importa `library/`; CLI, `doctor` e (desde o V1.1) `context/` a consomem
(V1.2: `classification/deterministic.py` lê o vocabulário `Authority`; V1.3:
`budget/content.py` obtém o corpo já carregado de um artefato via `GlobalLibrary.get`).
Não seleciona, classifica nem orça contexto.

### `orchestrator/context/`

V1.1: Context Candidate Discovery. V1.2: Context Classification (`context/classification/`).
V1.3: Context Budget (`context/budget/`). V1.4: LLM Context Escalation
(`context/escalation/`). Cada estágio consome o resultado do anterior e
nunca importa um estágio posterior (guard de arquitetura).

```text
EngineeringRequest
  → ContextCandidateDiscovery.discover()
      library → instructions → adrs → documentation → repository_hints → memory
  → merge por recurso canônico → ordenação (kind, id)
  → ContextDiscoveryResult(request, candidates, sources, unsupported_sources)
```

Responsável por:

- contrato `ContextCandidate` (id estável, `kind`, título, `reference` store+path,
  `provenance`, `metadata`), sem classificação, score ou budget;
- discoverers apenas para fontes reais: Global Library (via `GlobalLibrary.resolve`),
  instruction files, ADRs, documentação, arquivos citados na requisição (paths/nomes) e
  memória (via protocolo `MemorySearcher`, somente scope de projeto, opt-in);
- acesso seguro ao filesystem (`ProjectFiles`): caminhos relativos contidos no projeto,
  sem seguir diretórios symlink, exclusões fixas e configuráveis, nomes de secrets
  bloqueados, limite de arquivos por walk e de tamanho, leitura só do início de Markdown;
- deduplicação por recurso canônico (arquivo resolvido / id de memória) preservando todas
  as proveniências e (V1.2) toda a metadata: chaves de ambos os lados; em conflito vale o
  valor do kind vencedor e o valor descartado fica em `metadata["merge_conflicts"]`;
- `Provenance.match` (V1.2): como um hint da requisição casou (`path`, `file_name`,
  `ambiguous_file_name`, `directory`), para a classificação não interpretar texto livre.

A requisição é o sujeito da descoberta, não um candidato. Erros fatais
(`ContextDiscoveryError`): contexto desabilitado ou caminho configurado fora do projeto.
Fontes ausentes, vazias ou indisponíveis geram warnings. Não importa CLI, doctor,
providers, decisions (sem Jev), serviço/adapters de memória, rede ou subprocessos.
Fontes ainda não suportadas: task/sprint contracts, Git, previous runs, releases, findings.

Context Classification (V1.2):

```text
ContextDiscoveryResult
  → DeterministicClassifier     tabela ordenada de regras; a primeira que casa decide
  → não resolvidos apenas:
      ProbabilisticClassifier  Decider (DecisionService/Jev), 1 decisão por candidato,
                               opções ordenadas EXCLUDED < OPTIONAL < HIGH_VALUE (nunca REQUIRED),
                               threshold = decisions.yaml minimum_confidence
      ou fallback              OPTIONAL + evidência estruturada + warning
  → ContextClassificationResult(request, candidates, counts, decisions, warnings,
                                decision_provider)   ordenado por classe, kind, id
```

Precedência estrutural: candidato resolvido deterministicamente nunca é enviado ao Jev; o
modelo rejeita memória REQUIRED, decisão probabilística REQUIRED e fallback ≠ OPTIONAL.
EXCLUDED permanece no resultado. Só `classification/probabilistic.py` importa contratos da
camada de decisão (`decisions.models`, `providers.base`) — nunca adapter, service ou rede;
a composição (`open_decisions`) fica na CLI. A classificação não orça nem seleciona.
Regras e fallback: `engineering/docs/sprints/sprint-v1.2.md`.

Context Budget (V1.3):

```text
ContextClassificationResult
  → ordenação por prioridade: classe → deterministic < probabilistic (confidence ↓) < fallback
                              → kind → id
  → 1. todo REQUIRED: materializa; sempre selecionado (nunca limitado por categoria/max_*)
        sem conteúdo carregável → not_selected content_unavailable → REQUIRED_UNAVAILABLE
        soma > usable → REQUIRED_OVERFLOW (todos mantidos; nada mais é considerado)
        soma > limite de categoria/max_* → `conflicts` (mantidos)
  → 2. HIGH_VALUE, depois OPTIONAL, item inteiro, first fit (um item grande não bloqueia
        os seguintes): limites de contagem (antes de carregar) → carga → item_too_large →
        total_budget_exhausted → category_budget_exhausted → within_budget
  → 3. EXCLUDED: nunca carregado, nunca selecionado, mantido para auditoria
  → ContextBudgetResult(request, status, limits, usage, selected, not_selected, excluded,
                        conflicts, warnings)
```

Unidade: **caracteres** (code points Unicode do texto carregado, `len`), nunca tokens —
provider-neutral e exata; bytes de `stat` são só limite de segurança. `usable = total −
reserve`; a reserve preserva espaço para tudo que não é contexto (system prompt, task,
output, metadata de tools). Truncation: `whole_item` (nunca corta). Categorias: `library`,
`instructions`, `adrs`, `documentation`, `source_code`, `memory`. `max_files` conta arquivos
do projeto; `max_adrs` ADRs (também arquivos); `max_memories` excerpts de memória.

`ContextContentLoader` materializa referência → texto seguro: arquivo do projeto via
`ProjectFiles.check_file` (mesmas regras do discovery: contido após resolver symlinks, sem
diretórios excluídos, sem nomes de secrets, ≤ `max_file_bytes`), leitura limitada, NUL →
binário, UTF-8 estrito; artefato da biblioteca via corpo já carregado (sem reparse); memória
via excerpt (sem alterar `MemoryProvider`). Sem Jev, LLM, reclassificação ou renderização de
prompt. Política e exemplos: `engineering/docs/sprints/sprint-v1.3.md`.

LLM Context Escalation (V1.4):

```text
ContextBudgetResult (mantido intacto)
  → EscalationEvaluator (determinístico; context.yaml escalation.triggers)
       sem gatilho → NOT_REQUIRED, 0 chamadas LLM
  → harness_constraints (overflow, unavailable, conflitos de fonte/limite)
  → sem planner → FAILED planner_unavailable (0 chamadas)
  → ContextPlanningInput: allow-list de metadata (nunca conteúdo); candidato inseguro
       (memory.safety / nome de secret) → withheld + constraint; instrução ou prompt
       inseguro → FAILED unsafe_input (0 chamadas)
  → LLMProvider.complete (alias → ModelResolver → provider → model id)
       ProviderError → FAILED provider_error (1 chamada)
  → parse (um objeto JSON, schema estrito) → validate_plan → plan_violations
       inválido → FAILED invalid_output (1 chamada) · válido → PLANNED + ContextPlan
  → ContextEscalationResult(budget, escalation, status, constraints, plan, failure, call)
```

O plano não reclassifica, não remove REQUIRED, não seleciona EXCLUDED/indisponível/não
medido, não esconde overflow e não é prompt; truncation/chunking sugeridos pelo planner são
registrados como `suggestions`, nunca executados. Fallback = resultado do V1.3 (nunca outra
LLM, Jev ou humano automático). Só `escalation/planner.py` importa o contrato LLM e sua
composição (`providers.base/registry/resolution`); nenhum estágio anterior importa
`escalation/`. Gatilhos, schema e segurança: `engineering/docs/sprints/sprint-v1.4.md`.

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
- `context.yaml` possui consumidor real (V1.1 discovery, V1.2 classification, V1.3 budget,
  V1.4 escalation);
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
- `providers.yaml` (V0.4): campos de conexão opcionais (`base_url` http(s), `api_key_env` nome de env var, `timeout_seconds`); valores de chave rejeitados;
- `project.yaml` (V1): `capabilities` opcional (default `[]`, retrocompatível), ids em minúsculas como `stack`; ambos formam o `ProjectProfile` consumido pela resolução da Global Library.

- `context.yaml` (V1.1): `enabled` passa a ter consumidor (habilita `context discover`);
  seção `discovery` com `instruction_files`, `documentation_paths`, `adr_paths`,
  `source_roots` (caminhos relativos POSIX, sem `..`, `/`, `~`, normalizados),
  `exclude_dirs` (nomes), `max_files`, `max_file_bytes`, `memory_results` (limitados);
  campos extras (ex.: budget) rejeitados.
- `context.yaml` (V1.2): seção `classification` com `probabilistic` (bool, default true) e
  `max_decisions` (1..500, default 50). O threshold não é duplicado: vem de
  `decisions.yaml` `thresholds.minimum_confidence`. Campos extras rejeitados.
- `context.yaml` (V1.3): seção `budget` com `unit` (`characters`, único valor),
  `truncation` (`whole_item`, único valor), `total` (≥ 1, default 100000), `reserve`
  (≥ 0 e < `total`, default 20000), `categories` (caracteres por categoria, ≥ 0 ou ausente;
  categorias desconhecidas rejeitadas), `max_files` (20), `max_adrs` (5), `max_memories`
  (5), todos ≥ 0. Campos extras rejeitados.
- `context.yaml` (V1.4): seção `escalation` com `enabled` (default true), `model` (alias de
  `models.yaml` ou null — referência validada entre arquivos) e `triggers`:
  `architectural_intents` (intents únicos, nunca `unclassified`; default `[plan]`),
  `min_specialties` (≥ 2 ou null), `max_high_value` (≥ 1 ou null), `min_low_confidence`
  (≥ 1 ou null). Campos extras rejeitados.

A Global Library não é configuração: seus artefatos são validados pelo próprio loader
(`orchestrator/library/`), com schema versionado próprio (`version: 1`).

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
├── skills/          # existe desde o V1
├── specialties/     # existe desde o V1
├── guidelines/      # existe desde o V1
├── policies/        # existe desde o V1
├── rules/           # existe desde o V1 (adicionado à arquitetura alvo)
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

O V1.1 criou `context/` com Context Candidate Discovery; a `GlobalLibrary` é uma de suas
fontes (via `resolve`) e a `Authority` de cada artefato segue como metadata do candidato,
insumo para a precedência `Policies > ADRs > Task > Project guidelines >
Skills/specialties > ... > Memory`. O V1.2 criou `context/classification/`, que aplica essa
precedência (policy aplicável → REQUIRED; memória nunca REQUIRED) e produz
`ContextClassificationResult`. O V1.3 criou `context/budget/`, que o consome e produz
`ContextBudgetResult` (seleção determinística, REQUIRED nunca removido). O V1.4 criou
`context/escalation/`, que avalia gatilhos determinísticos sobre esse resultado e, só quando
necessário, obtém um `ContextPlan` validado via `LLMProvider`; telemetry (V1.5) consumirá
esses resultados.

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

O V1.4 — LLM Context Escalation está COMPLETE (ver
`engineering/docs/sprints/sprint-v1.4.md`).

A próxima versão é:

```text
V1.5 — Context Telemetry
```

O V1.5 ainda não foi iniciado.

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

### Global Library pertence à instalação (V1)

A raiz da biblioteca é resolvida independentemente da raiz de configuração; o projeto
declara apenas seu perfil (`stack`, `capabilities`) e herda o conhecimento aplicável.

### Força normativa derivada do tipo (V1)

`Authority` vem do tipo do artefato (policy = mandatory; guideline e rule = recommended;
skill e specialty = knowledge) e não pode ser declarada no arquivo: um guideline nunca
assume força de policy. Memória e decisões probabilísticas não participam da biblioteca.

### Resolução determinística e explícita (V1)

`applies_to` é `always: true` ou `stacks`/`capabilities`; o match é por igualdade exata
de strings, sem aliases, Jev ou LLM. Referências de specialties são validadas, não expandidas.

### Discovery não é classification (V1.1)

`ContextCandidate` não tem campo de classe, relevância ou budget. Proveniência e metadata
(autoridade, status de ADR, lineage de memória) ficam disponíveis para o V1.2 decidir.
A requisição é o sujeito, não um candidato.

### Identidade e deduplicação por recurso canônico (V1.1)

Ids estáveis (`policy/secrets`, `adr/<path>`, `doc/<path>`, `source/<path>`,
`memory/<id>`); o mesmo recurso (arquivo resolvido ou id de memória) encontrado por vários
discoverers vira um único candidato com todas as proveniências; o `kind` segue a ordem de
prioridade de `CandidateKind`. Título nunca participa da identidade.

### Classification compõe, não muta (V1.2)

`ClassifiedContextCandidate` envolve o `ContextCandidate` original (composição); a classe,
`selected_by` e a `Evidence` estruturada (id estável da regra ou motivo do fallback) ficam em
`ContextClassification`. Invariantes no modelo: memória nunca REQUIRED; a camada
probabilística nunca produz REQUIRED; fallback é sempre OPTIONAL.

### Determinístico primeiro, por construção (V1.2)

Só candidatos sem regra determinística chegam ao `Decider`; nenhuma resposta probabilística
pode rebaixar ou promover uma decisão determinística. Provider indisponível interrompe as
chamadas no run e vira fallback visível (warning), nunca classificação silenciosa.

### Budget em caracteres, com reserve (V1.3)

A unidade é caracteres (code points do texto carregado): exata, determinística e sem
tokenizer de vendor. `usable = total − reserve`; um único reserve preserva espaço para o que
não é contexto. Nenhum número depende do limite máximo de um modelo.

### Classificação é a autoridade do budget (V1.3)

A prioridade é a classe; dentro dela, apenas sinais já produzidos pelo V1.2 (determinístico
antes de probabilístico, confidence) e depois kind e id. O budget não reclassifica, não
chama Jev nem LLM; a decisão de budget é uma camada separada que envolve o candidato
classificado sem sobrescrever o motivo da classificação.

### REQUIRED nunca é removido (V1.3)

REQUIRED acima do usable → `REQUIRED_OVERFLOW`; sem conteúdo carregável →
`REQUIRED_UNAVAILABLE`; acima de limite de categoria/`max_*` → `conflicts`. Invariantes no
modelo: nenhum caminho de código consegue construir um REQUIRED descartado por orçamento.

### Itens inteiros, first fit (V1.3)

Nada é truncado; um item que não cabe é pulado e a varredura continua. Sem sumarização ou
chunking semântico.

### Escalar é decisão determinística (V1.4)

Gatilhos leem apenas dados já produzidos (intent declarado, classes, evidência de decisão,
metadata de merge, status/uso do budget) contra thresholds do `context.yaml`; a LLM nunca
decide se deve ser chamada. Sem gatilho, nenhuma chamada. Alto risco não é gatilho (sem
fonte de risco até o V9); fallback `no_decision_layer` é configuração, não incerteza.

### Plano validado, nunca confiado (V1.4)

A saída do planner é um único objeto JSON com schema estrito (sem campos extras, sem
classificação), depois invariantes determinísticas (`plan_violations`): REQUIRED completo e
primeiro, nada EXCLUDED/indisponível/não medido, ids conhecidos, budget reaplicado com as
regras do V1.3. O próprio `ContextEscalationResult` revalida o plano. Falha → resultado do
V1.3 + falha explícita.

### Só metadata segura sai para o provider (V1.4)

`ContextPlanningInput` é uma allow-list (nunca conteúdo de candidato); candidatos com
metadata ou nome de arquivo com aparência de secret são retidos e registrados; instrução ou
prompt inseguro cancela a chamada. Reusa `memory.safety` e `is_secret_name`.

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

Identificadas no V1:

- o wheel empacota só `orchestrator/`; instalação não editável exige `$HARNESS_LIBRARY_ROOT`
  (mesma limitação já existente para `config/` e `--root`);
- vocabulário de `stack`/`capabilities` não é controlado: um typo (`postgres` vs
  `postgresql`) não casa e não gera aviso;
- a carga para no primeiro erro (não lista todos os problemas de uma vez);
- referências de specialties não são expandidas pela resolução (routing de specialties: V2.4);
- sem composição Global + conhecimento local do projeto (loader já é agnóstico de raiz).

Identificadas no V1.1:

- `MemoryProvider` não possui get-by-id: candidatos de memória carregam um excerpt
  (≤ 280 caracteres); carregar a memória completa depois exigirá esse método;
- hints de repositório são léxicos: nomes sem extensão, símbolos (`GlobalLibrary`) e
  módulos em notação de ponto não são reconhecidos;
- a busca de memória usa a instrução inteira como query e só o scope de projeto
  (`origin_ref` é texto livre, não identifica task/run com segurança);
- walks são refeitos a cada requisição (sem cache/índice);
- ~~o merge descarta a metadata do candidato de menor prioridade~~ (resolvido no V1.2:
  metadata unida; conflitos registrados em `merge_conflicts`).

Identificadas no V1.2:

- sem Jev habilitado, tudo o que não tem regra determinística vira OPTIONAL (documentação,
  ADRs aceitos, conhecimento `always`, memória): classificação correta, porém pouco seletiva;
- uma chamada de decisão por candidato não resolvido (sem contrato de batch no
  `DecisionProvider`); `max_decisions` limita custo/latência;
- a regra de artefatos gerados usa uma lista fixa de nomes/sufixos (lock files, `.min.js`,
  `.map`);
- o fallback via reasoning LLM (roadmap) não existe: não há runtime LLM real (V2.x);
- `minimum_confidence` é compartilhado com as demais decisões (não há threshold específico
  de classificação; não calibrado).

Identificadas no V1.3:

- defaults do budget (100000/20000 caracteres, limites por categoria) são pontos de partida
  conservadores, não calibrados (calibração depende da telemetria do V1.5);
- caracteres ≠ tokens: a relação varia por idioma, código e tokenizer; a reserve absorve a
  diferença, mas não há garantia de encaixe numa janela específica;
- first fit por prioridade não é ótimo (não maximiza uso do orçamento; pode escolher um item
  menor posterior depois de pular um maior anterior) — é intencional e auditável;
- itens ainda elegíveis são lidos para medir mesmo com o orçamento quase cheio (limitado por
  `max_file_bytes` e pelo número de candidatos);
- conteúdo selecionado não passa por varredura de secrets (só nomes de arquivos de secrets
  são bloqueados, como no discovery);
- arquivo binário citado explicitamente vira REQUIRED no V1.2 e, portanto,
  `REQUIRED_UNAVAILABLE` no V1.3 (correto, mas bloqueia o pacote até escalation).
- ~~conteúdo selecionado não passa por varredura de secrets~~ para envio externo (V1.4:
  nenhum conteúdo é enviado ao planner; metadata é verificada). O conteúdo selecionado em si
  continua sem varredura até existir renderização de prompt (V2).

Identificadas no V1.4:

- não há adapter LLM real: o planner só roda com provider injetado (testes); com a
  configuração padrão toda escalation termina `FAILED planner_unavailable`;
- o planner vê apenas metadata (ids, títulos, tamanhos, classes), não conteúdo nem
  excerpts: decide com pouca semântica; enviar excerpts exigirá política de redação;
- `LLMProvider` não tem structured output nativo nem timeout no contrato: o JSON é exigido
  pelo prompt e validado estritamente; timeout depende do adapter;
- `architectural_task` depende do intent declarado (`--intent plan`); requests
  `unclassified` nunca disparam esse gatilho;
- `multiple_domains` conta specialties REQUIRED/HIGH_VALUE, que hoje vêm do perfil do
  projeto (stack/capabilities) e não do texto da tarefa, salvo com Jev habilitado;
- `source_conflict` cobre só conflitos de metadata registrados no merge; conflito semântico
  entre documentos não é detectado;
- thresholds (3/12/3) não calibrados (dependem da telemetria do V1.5);
- a varredura de secrets é heurística (mesmas limitações do V0.3).

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
Global Library (skills, guidelines, policies, rules, specialties; deterministic resolution)
        ↓
Context Candidate Discovery (request → typed, deduplicated candidates with provenance)
        ↓
Context Classification (REQUIRED / HIGH_VALUE / OPTIONAL / EXCLUDED; deterministic → Jev → fallback)
        ↓
Context Budget (characters, reserve, category/item limits; REQUIRED never dropped)
        ↓
LLM Context Escalation (deterministic triggers; validated ContextPlan via LLMProvider; fallback = budget)
        ↓
Ready for Context Telemetry (V1.5)
```

O Harness já lista, classifica e seleciona, para uma requisição, o contexto que cabe num
orçamento determinístico, com o motivo de entrada/saída de cada item, e decide
deterministicamente quando essa seleção precisa de um planner LLM, cujo plano só é aceito
após validação; nada ainda injeta contexto em prompts.

Ainda não existe provider externo real de inferência generativa.

A memória operacional existe, mas é operada apenas explicitamente e nunca é source of truth.

Context Engineering existe até a escalation (V1.1–V1.4); pacote de contexto renderizado,
telemetria de contexto e adapter LLM real ainda não.

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
