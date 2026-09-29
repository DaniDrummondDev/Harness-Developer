# AI Engineering Harness — Requisitos Funcionais e Não Funcionais

## 1. Objetivo

Este documento define os requisitos funcionais e não funcionais do AI Engineering Harness.

O Harness deve ser uma plataforma Python reutilizável para orquestração de engenharia de software assistida por LLMs, com gerenciamento de contexto, memória, decisões, validações, especialistas, ciclo de desenvolvimento, release e deploy.

---

# 2. Requisitos Funcionais

## RF-001 — Configuração de projeto

O sistema deve permitir configurar cada projeto de forma declarativa.

A configuração deve incluir, quando aplicável:

- nome do projeto;
- raiz do projeto;
- repositórios;
- stack;
- providers;
- modelos;
- políticas;
- guidelines;
- skills;
- specialties;
- gates;
- memória;
- pipelines;
- ambientes;
- risco;
- release;
- deploy.

---

## RF-002 — Provider abstraction

O sistema deve abstrair providers de IA por interfaces.

Deve ser possível configurar, no mínimo:

- OpenAI;
- Anthropic Claude;
- NVIDIA;
- Jev/TypeSafe.

A substituição de modelo ou provider não deve exigir alteração do core.

---

## RF-003 — Agent roles

O sistema deve suportar papéis configuráveis de agentes, incluindo:

- Architect;
- Implementer;
- Reviewer;
- Test Engineer;
- Validator;
- Release Engineer;
- Deployment Engineer.

Papéis devem ser desacoplados de providers.

---

## RF-004 — Specialties

O sistema deve permitir associar especialidades aos agentes.

Exemplos:

- architecture;
- python;
- php-laravel;
- testing;
- database;
- security;
- frontend;
- infrastructure;
- observability;
- deployment;
- AI/RAG.

Especialidades devem poder fornecer:

- profile;
- rules;
- checklist;
- referências;
- ferramentas permitidas.

---

## RF-005 — Skills

O sistema deve suportar skills reutilizáveis.

Uma skill deve definir como executar bem um tipo específico de trabalho.

O Context Engine deve conseguir selecionar skills relevantes automaticamente.

---

## RF-006 — Guidelines

O sistema deve suportar guidelines específicas do projeto.

Guidelines devem representar convenções, padrões e expectativas locais.

---

## RF-007 — Policies

O sistema deve suportar policies obrigatórias e não negociáveis.

Policies devem ter precedência sobre memória e recomendações probabilísticas.

---

## RF-008 — ADR awareness

O sistema deve indexar e recuperar ADRs relevantes para uma tarefa.

ADRs devem ser tratados como source of truth arquitetural.

---

## RF-009 — Sprint e Task Contracts

O sistema deve suportar documentos estruturados de sprint e task.

Tasks devem poder definir:

- objetivo;
- contexto;
- dependências;
- findings;
- decisions;
- constraints;
- invariants;
- implementation scope;
- forbidden scope;
- acceptance criteria;
- required tests;
- required evidence;
- exit criteria;
- next states.

---

## RF-010 — Context Candidate Discovery

O sistema deve descobrir automaticamente candidatos de contexto.

Fontes incluem:

- docs;
- ADRs;
- policies;
- guidelines;
- skills;
- specialties;
- source code;
- Git;
- previous runs;
- Mem0;
- releases;
- findings.

---

## RF-011 — Context Classification

Cada item de contexto deve poder ser classificado como:

- REQUIRED;
- HIGH_VALUE;
- OPTIONAL;
- EXCLUDED.

Classificações obrigatórias podem ser determinísticas.

Classificações semânticas podem usar Jev ou LLM.

---

## RF-012 — Context Scoring

O sistema deve poder atribuir relevância a candidatos de contexto.

Jev poderá ser utilizado para:

- relevância;
- classificação;
- seleção;
- scoring;
- roteamento.

---

## RF-013 — Context Budget

O sistema deve limitar o contexto fornecido aos modelos.

O orçamento deve ser configurável e permitir limites por categoria.

Exemplos:

- task;
- policies;
- architecture;
- source code;
- memory;
- history;
- reserve.

---

## RF-014 — Context Escalation

O sistema deve poder escalar o planejamento de contexto para uma LLM de raciocínio mais forte quando houver:

- tarefa arquitetural;
- alto risco;
- múltiplos domínios;
- baixa confiança;
- ambiguidade;
- excesso de candidatos relevantes.

---

## RF-015 — Context Audit Trail

Cada item incluído no contexto deve registrar, quando possível:

- origem;
- tipo;
- razão;
- score;
- selecionador;
- timestamp;
- lineage.

---

## RF-016 — Mem0 self-hosted

O sistema deve integrar Mem0 self-hosted como memória de longo prazo.

O adapter de memória deve ser desacoplado do core.

---

## RF-017 — Memory ingestion

O sistema deve poder persistir memórias aprovadas de:

- task results;
- decisions;
- findings;
- remediations;
- releases;
- incidents;
- implementation notes.

---

## RF-018 — Memory retrieval

O sistema deve recuperar memórias relevantes para a tarefa atual.

Memórias recuperadas devem passar por filtragem antes de entrar no contexto final.

---

## RF-019 — Memory precedence

Memória nunca deve sobrescrever:

- policies;
- ADRs;
- documentação oficial;
- task contract;
- Git como evidência factual.

---

## RF-020 — Memory security

O sistema deve impedir ou filtrar armazenamento de:

- secrets;
- tokens;
- API keys;
- passwords;
- `.env`;
- credenciais;
- dados sensíveis proibidos por política.

---

## RF-021 — Claude execution

O sistema deve poder executar Claude de forma não interativa.

Deve capturar:

- input;
- stdout;
- stderr;
- exit code;
- structured output;
- duração;
- modelo/configuração.

---

## RF-022 — OpenAI reviewer/architect

O sistema deve permitir uso de OpenAI para:

- arquitetura;
- planning;
- revisão;
- análise de contexto;
- escalation;
- remediation planning.

---

## RF-023 — NVIDIA provider

O sistema deve permitir configurar NVIDIA como provider adicional sem alterar o core.

---

## RF-024 — Jev decision provider

O sistema deve integrar Jev como provider de decisão probabilística estruturada.

Deve suportar ao menos:

- choice;
- score;
- probability/confidence;
- routing;
- severity;
- context relevance;
- next-state candidate.

---

## RF-025 — Deterministic decision engine

O sistema deve possuir decisões determinísticas para condições objetivas.

Exemplos:

- tests failed;
- forbidden path changed;
- command failed;
- security gate failed;
- health check failed.

---

## RF-026 — Escalation policy

O sistema deve decidir entre:

- automatic continue;
- Jev;
- reasoning LLM;
- human review.

A decisão deve depender de:

- risco;
- confidence;
- tipo de tarefa;
- policies;
- finding;
- estado do workflow.

---

## RF-027 — Quality gates

O sistema deve suportar gates configuráveis.

Exemplos:

- tests;
- lint;
- static analysis;
- architecture tests;
- security checks;
- contract checks;
- Git scope;
- migration safety;
- build validation.

---

## RF-028 — Gate execution

Gates devem poder executar comandos declarativos configurados por projeto.

---

## RF-029 — Structured findings

Reviewers devem emitir findings estruturados com:

- tipo;
- severidade;
- evidência;
- origem;
- recomendação;
- necessidade de decisão;
- status.

---

## RF-030 — Scope drift detection

O sistema deve detectar alterações além do escopo permitido.

Pode usar:

- regras determinísticas;
- Jev;
- reviewer LLM.

---

## RF-031 — Test specialization

O sistema deve suportar agente especializado em testes, capaz de derivar testes dos requisitos e invariantes sem assumir que a implementação está correta.

---

## RF-032 — State machine

O sistema deve controlar o workflow através de state machine explícita.

Estados mínimos esperados:

- PLANNED;
- CONTEXT_BUILDING;
- READY;
- IMPLEMENTING;
- VERIFYING;
- REVIEWING;
- REMEDIATION;
- BLOCKED;
- HUMAN_REVIEW;
- DONE.

Estados adicionais devem suportar integration/release/deploy.

---

## RF-033 — Automatic remediation

Quando permitido por política e risco, o sistema deve gerar e executar remediation automaticamente.

---

## RF-034 — Retry limits

Retries automáticos devem possuir limites configuráveis.

Ao exceder o limite, o workflow deve escalar.

---

## RF-035 — Human review

O sistema deve conseguir interromper o fluxo e solicitar intervenção humana.

Deve fornecer:

- motivo;
- evidência;
- alternativas;
- impacto;
- decisão requerida.

---

## RF-036 — Git integration

O sistema deve integrar Git para:

- status;
- diff;
- history;
- branches;
- commits;
- worktrees;
- escopo de alterações.

---

## RF-037 — Worktree isolation

O sistema deve suportar Git worktrees para execução isolada de tarefas.

---

## RF-038 — Run artifacts

Cada run deve gerar artefatos persistentes.

Exemplos:

- manifest;
- context;
- prompt;
- events;
- stdout;
- stderr;
- diff;
- gates;
- decisions;
- review;
- result.

---

## RF-039 — Run lineage

Deve ser possível relacionar:

- project;
- sprint;
- task;
- run;
- commit;
- decision;
- release.

---

## RF-040 — Risk classification

O sistema deve classificar tasks/releases em níveis de risco.

Níveis sugeridos:

- LOW;
- MEDIUM;
- HIGH;
- CRITICAL.

---

## RF-041 — Risk-aware workflow

O nível de risco deve alterar:

- gates;
- reviewer requirements;
- human approvals;
- deploy policy;
- rollback requirements;
- sampling.

---

## RF-042 — Development pipeline

O sistema deve suportar pipeline de desenvolvimento.

---

## RF-043 — Integration pipeline

O sistema deve suportar integração e verificação antes de release.

---

## RF-044 — Release pipeline

O sistema deve suportar:

- build;
- artifacts;
- versioning;
- release candidate;
- release notes;
- pre-release checks.

---

## RF-045 — Deployment pipeline

O sistema deve suportar deploy configurável por ambiente.

---

## RF-046 — Environment configuration

Deve suportar:

- local;
- test;
- staging;
- production.

---

## RF-047 — Pre-deploy validation

Antes de deploy devem poder ser exigidos:

- build válido;
- testes;
- migrations verificadas;
- secrets/config verificados;
- backup policy;
- rollback plan;
- approvals.

---

## RF-048 — Smoke tests

Após deploy, o sistema deve executar smoke tests configuráveis.

---

## RF-049 — Health checks

O sistema deve validar health endpoints ou comandos equivalentes.

---

## RF-050 — Observability

O sistema deve poder consultar sinais como:

- logs;
- metrics;
- health;
- error rate;
- queue health;
- latency.

---

## RF-051 — Rollback

O sistema deve suportar rollback quando seguro e configurado.

---

## RF-052 — Release verification

Um deploy só deve ser marcado como RELEASED após verificações pós-deploy.

---

## RF-053 — Sampling de decisões

Decisões automáticas de alta confiança devem poder ser amostradas para revisão adicional.

Objetivo: medir qualidade real do decision provider.

---

## RF-054 — Decision telemetry

O sistema deve registrar:

- provider;
- decision;
- confidence;
- escalation;
- final outcome;
- agreement/disagreement posterior.

---

## RF-055 — Context telemetry

O sistema deve registrar métricas como:

- selected context;
- unused context;
- context misses;
- relevance scores;
- context size;
- escalation rate.

---

## RF-056 — CLI

O Harness deve fornecer CLI para operação.

Comandos serão definidos incrementalmente.

---

## RF-057 — Doctor

O sistema deve verificar ambiente, configuração e dependências através de comando `doctor`.

---

## RF-058 — Extensibility

Novos providers, gates, memory backends, tools e deployment adapters devem poder ser adicionados sem alteração extensa do core.

---

# 3. Requisitos Não Funcionais

## RNF-001 — Linguagem

O core do Harness deve ser implementado em Python 3.12 ou superior.

---

## RNF-002 — Baixo acoplamento

Providers externos devem ser acessados através de interfaces/adapters.

---

## RNF-003 — Portabilidade

A pasta do Harness deve poder ser copiada para um novo projeto e configurada sem alteração estrutural do código.

---

## RNF-004 — Configuração declarativa

Configuração específica do projeto deve permanecer fora do core.

---

## RNF-005 — Validação de configuração

Configurações devem ser validadas com modelos tipados.

---

## RNF-006 — Fail closed

Para invariantes críticos de segurança, autorização, integridade ou deploy, ausência de evidência deve resultar em bloqueio, não aprovação implícita.

---

## RNF-007 — Auditabilidade

Ações automáticas devem possuir trilha de auditoria.

---

## RNF-008 — Reprodutibilidade

Uma run deve preservar dados suficientes para reconstruir seu contexto e decisões relevantes.

---

## RNF-009 — Observabilidade

O Harness deve produzir logs estruturados e métricas operacionais.

---

## RNF-010 — Segurança de secrets

Secrets nunca devem ser persistidos em runs, prompts ou memória sem autorização explícita.

---

## RNF-011 — Least privilege

Agents e ferramentas devem receber somente permissões necessárias para a etapa atual.

---

## RNF-012 — Resiliência

Falha de provider externo deve ser tratada explicitamente.

O sistema deve suportar retry controlado e fallback quando permitido.

---

## RNF-013 — Idempotência

Operações que podem ser repetidas devem possuir mecanismos de idempotência quando necessário.

---

## RNF-014 — Performance

O sistema deve preferir regras determinísticas e providers de decisão baratos antes de LLMs mais caras quando isso não reduzir segurança ou qualidade.

---

## RNF-015 — Controle de custo

O sistema deve registrar consumo/custo quando disponível.

---

## RNF-016 — Context efficiency

O sistema deve evitar envio de contexto desnecessário.

---

## RNF-017 — Testabilidade

Componentes centrais devem possuir interfaces que permitam testes sem chamadas reais a providers.

---

## RNF-018 — Type safety

Código Python deve utilizar type hints e validação estruturada.

---

## RNF-019 — Simplicidade incremental

O projeto deve evitar abstrações sem uso real.

Cada versão deve implementar apenas capacidades necessárias ao estágio atual.

---

## RNF-020 — Provider neutrality

O sistema não deve depender semanticamente de um único LLM/vendor.

---

## RNF-021 — Data ownership

Artefatos, memória e histórico devem permanecer sob controle do usuário/projeto sempre que possível.

---

## RNF-022 — Self-hosted memory

A memória de longo prazo deve suportar operação self-hosted.

---

## RNF-023 — Human agency

Decisões de alto impacto devem poder exigir intervenção humana.

---

## RNF-024 — No silent architecture changes

Agentes não devem alterar arquitetura, policies ou ADRs unilateralmente sem fluxo explícito de decisão.

---

## RNF-025 — Deployment safety

Deploy de produção deve possuir gates mais rigorosos que desenvolvimento local.

---

## RNF-026 — Rollback readiness

Mudanças de alto risco devem exigir estratégia de rollback antes do deploy.

---

## RNF-027 — Backward compatibility

Quando configurado como requisito do projeto, contratos públicos e migrations devem preservar compatibilidade ou exigir decisão explícita.

---

## RNF-028 — Versionamento

Schemas, contracts, prompts, policies e configurações críticas devem ser versionáveis.

---

## RNF-029 — Lineage

Memórias e decisões devem possuir ligação com suas fontes quando tecnicamente viável.

---

## RNF-030 — Deterministic precedence

Quando regra determinística conflitar com recomendação probabilística, a regra determinística prevalece.

---

# 4. Fora de Escopo Inicial

A primeira versão do projeto não precisa entregar todo o ciclo completo.

Podem ficar para fases posteriores:

- dashboard web;
- execução distribuída;
- scheduler avançado;
- múltiplos workers;
- Kubernetes;
- marketplace de skills;
- auto-tuning de modelos;
- aprendizado de políticas;
- execução multi-host;
- gestão corporativa multi-user.

O roadmap deve preservar a arquitetura necessária para evoluir sem antecipar complexidade.
