# AI Engineering Harness — Visão do Projeto

## 1. Propósito

O AI Engineering Harness é uma plataforma de orquestração de engenharia de software orientada por agentes e LLMs, criada para acompanhar o ciclo de vida completo de um projeto: da concepção e arquitetura ao desenvolvimento, validação, release, deploy, observabilidade e recuperação.

O Harness não deve ser apenas uma ferramenta para executar prompts ou chamar modelos. Ele deve funcionar como um **control plane de engenharia**, capaz de coordenar agentes especializados, contexto, memória, decisões, validações determinísticas e escalonamento humano.

A meta é reduzir trabalho manual repetitivo, eliminar fluxos de copy/paste entre LLMs, aumentar consistência técnica, preservar decisões arquiteturais e reduzir falhas evitáveis.

O sistema deve operar de forma autônoma dentro de limites explícitos, chamando intervenção humana quando houver decisões arquiteturais, ambiguidades relevantes, riscos elevados, mudanças destrutivas ou conflitos que não devam ser resolvidos automaticamente.

---

## 2. Problema que o projeto resolve

O fluxo tradicional de desenvolvimento assistido por IA possui vários problemas recorrentes:

- prompts copiados e colados manualmente;
- contexto perdido entre sessões;
- decisões arquiteturais não carregadas no momento correto;
- excesso de contexto irrelevante;
- LLM implementadora avaliando o próprio trabalho;
- ausência de trilha de auditoria;
- pouca separação entre decisão probabilística e validação determinística;
- falta de coordenação entre arquitetura, implementação, testes, revisão e deploy;
- dependência excessiva da memória de conversas individuais;
- dificuldade em reproduzir por que determinada decisão foi tomada;
- ausência de critérios objetivos para avanço, remediation ou escalonamento humano.

O Harness deve transformar esse fluxo em um processo governado, observável e reproduzível.

---

## 3. Visão de alto nível

O fluxo desejado é:

```text
IDEA / REQUIREMENT
        ↓
Architecture / ADR / Roadmap
        ↓
Sprint / Task Contract
        ↓
Context Engineering
        ↓
Agent Routing
        ↓
Implementation
        ↓
Deterministic Gates
        ↓
Semantic Review / Decisions
        ↓
State Machine
        ↓
Integration
        ↓
Release
        ↓
Deploy
        ↓
Observe
        ↓
PASS / REMEDIATION / ROLLBACK / HUMAN REVIEW
```

O Harness deve controlar o workflow. Os agentes e LLMs são componentes plugáveis e não devem governar sozinhos o processo.

---

## 4. Princípios centrais

### 4.1 Workflow governa agentes

Nenhuma LLM deve ser tratada como autoridade única. O Harness define estados, políticas, limites e critérios de avanço.

### 4.2 Determinismo primeiro

Sempre que uma decisão puder ser tomada de forma determinística, ela não deve depender de uma LLM.

Exemplos:

- teste falhou;
- lint falhou;
- arquivo proibido foi alterado;
- migration destrutiva detectada;
- comando retornou exit code diferente de zero;
- health check falhou.

### 4.3 LLMs com papéis especializados

Os modelos devem atuar em funções diferentes:

- **OpenAI**: arquitetura, planejamento, revisão de alto nível, análise de contexto complexo e escalonamento;
- **Claude**: implementação, exploração de repositório, refatoração, testes e execução de tarefas;
- **NVIDIA / Kimi-k3 modelos compatíveis**: capacidade adicional de inferência, classificação, execução ou especialização conforme configuração;
- **Jev**: classificação, scoring, routing, decisões estruturadas e probabilidade/confiança.

Nenhum provider deve ser hardcoded na arquitetura.

### 4.4 Provider-agnostic

O sistema deve operar com interfaces e adapters.

Modelos, providers e parâmetros devem ser configuráveis, permitindo substituição sem alterar o core.

### 4.5 Memória não substitui verdade oficial

A memória de longo prazo via Mem0 auxilia recuperação de contexto, mas não substitui:

- ADRs;
- documentação oficial;
- políticas;
- Git;
- contratos de sprint/task;
- artefatos aprovados.

Quando houver conflito, a fonte oficial vence.

### 4.6 Context Engineering é capacidade de primeira classe

O sistema deve decidir automaticamente:

- qual contexto carregar;
- quanto contexto carregar;
- qual contexto excluir;
- quais skills/guidelines/policies são relevantes;
- quais memórias devem ser recuperadas;
- quais ADRs e arquivos de código precisam ser incluídos;
- quando escalar planejamento de contexto para uma LLM mais capaz.

### 4.7 Auditabilidade

Cada execução deve preservar evidências suficientes para responder:

- o que foi solicitado;
- qual contexto foi carregado;
- quais agentes foram utilizados;
- quais decisões foram tomadas;
- qual modelo tomou cada decisão;
- quais gates passaram ou falharam;
- quais arquivos foram alterados;
- por que houve avanço, remediation, bloqueio ou rollback.

---

## 5. Papéis do sistema

### Architect

Responsável por:

- arquitetura;
- trade-offs;
- ADRs;
- boundaries;
- roadmap;
- definição de sprint;
- análise de mudanças de alto impacto.

Normalmente operado por LLM de raciocínio forte ou humano + LLM.

### Implementer

Responsável por:

- implementação;
- refatoração;
- exploração de código;
- criação e manutenção de testes;
- execução local;
- relatório técnico estruturado.

### Reviewer

Responsável por:

- revisar diff;
- avaliar aderência ao contrato;
- identificar scope drift;
- avaliar riscos;
- validar consistência arquitetural.

### Test Engineer

Responsável por derivar testes a partir de requisitos, invariantes e critérios de aceitação, sem assumir que a implementação está correta.

### Validator

Responsável por gates determinísticos.

### Release / Deployment Engineer

Responsável por:

- build;
- release candidate;
- migrations;
- deploy;
- smoke tests;
- rollback;
- verificação pós-deploy.

---

## 6. Especialidades

Papéis e especialidades são conceitos diferentes.

Exemplos de especialidades:

- architecture;
- php-laravel;
- python;
- testing;
- database;
- security;
- frontend;
- infrastructure;
- observability;
- deployment;
- AI/RAG;
- APIs;
- distributed-systems.

Um agente deve ser construído pela composição:

```text
Role
+
Specialties
+
Policies
+
Guidelines
+
Task Contract
+
Relevant Context
```

---

## 7. Fontes de contexto

O Context Engine deve trabalhar com:

- task atual;
- sprint atual;
- project instructions;
- CLAUDE.md / AGENTS.md;
- policies;
- guidelines;
- skills;
- specialties;
- ADRs;
- arquitetura;
- roadmap;
- source code;
- Git diff/history;
- previous runs;
- findings;
- releases anteriores;
- Mem0;
- metadata do projeto.

O sistema deve distinguir:

- REQUIRED;
- HIGH_VALUE;
- OPTIONAL;
- EXCLUDED.

---

## 8. Memória de longo prazo

Mem0 será utilizado em modo self-hosted para memória operacional de longo prazo.

Exemplos de conteúdo adequado:

- decisões operacionais;
- implementações relevantes;
- problemas recorrentes;
- findings históricos;
- remediations;
- relações entre módulos;
- incidentes;
- resultados de releases;
- contexto que ajude tarefas futuras.

Memórias devem possuir metadata e lineage para fonte original quando possível.

O sistema deve evitar armazenar:

- secrets;
- credenciais;
- `.env`;
- tokens;
- conteúdo sensível sem necessidade;
- grandes dumps de stdout;
- código completo sem necessidade.

---

## 9. Camada de decisão

A hierarquia desejada é:

```text
1. Deterministic Rules
2. Jev
3. Reasoning LLM
4. Human
```

Jev deve ser usado principalmente para:

- classification;
- relevance scoring;
- routing;
- severity;
- scope drift;
- next-state candidate;
- context selection;
- confidence estimation.

Jev nunca deve ser tratado como determinístico.

---

## 10. Estados esperados

Exemplos de estados:

- PLANNED
- CONTEXT_BUILDING
- READY
- IMPLEMENTING
- VERIFYING
- REVIEWING
- REMEDIATION
- BLOCKED
- HUMAN_REVIEW
- READY_FOR_INTEGRATION
- INTEGRATING
- READY_FOR_RELEASE
- RELEASING
- DEPLOYING
- OBSERVING
- RELEASED
- ROLLBACK_REQUIRED
- ROLLED_BACK
- FAILED

---

## 11. Gestão de risco

O sistema deve suportar níveis como:

- LOW
- MEDIUM
- HIGH
- CRITICAL

O nível de risco deve influenciar:

- necessidade de reviewer;
- quantidade de gates;
- necessidade de aprovação humana;
- política de deploy;
- necessidade de backup;
- necessidade de rollback preparado;
- sampling adicional.

---

## 12. Objetivo de autonomia

O objetivo final é permitir que o Harness conduza grande parte do projeto de forma autônoma, incluindo:

- leitura de tarefas;
- montagem de contexto;
- escolha de especialistas;
- execução;
- testes;
- revisão;
- remediation;
- avanço de sprint;
- build;
- release;
- deploy;
- verificação pós-deploy.

A autonomia deve ser limitada por políticas e gates.

O sistema deve chamar um humano quando necessário, especialmente em:

- mudanças arquiteturais;
- requisitos ambíguos;
- mudanças destrutivas;
- breaking changes;
- riscos de segurança;
- mudanças de produto;
- decisões financeiras ou operacionais críticas;
- situações sem evidência suficiente.

---

## 13. Stack alvo

### Core

- Python 3.12+
- Typer
- Pydantic
- PyYAML
- Rich
- Jinja2
- pytest

### Providers / IA

- OpenAI
- Anthropic Claude
- NVIDIA / providers compatíveis
- Jev / TypeSafe AI

### Memória

- Mem0 self-hosted
- PostgreSQL + pgvector quando aplicável à stack self-hosted

### Infraestrutura

- Docker / Docker Compose
- Git
- CLI tools
- CI/CD configurável por projeto

---

## 14. Critério de sucesso

O Harness será considerado bem-sucedido quando conseguir reduzir significativamente:

- copy/paste manual entre agentes;
- contexto perdido;
- decisões inconsistentes;
- regressões detectáveis;
- retrabalho;
- intervenção humana em tarefas de baixo risco;
- falhas de deploy evitáveis.

E aumentar:

- rastreabilidade;
- consistência;
- qualidade;
- previsibilidade;
- reutilização;
- observabilidade;
- segurança;
- confiança no processo de engenharia.
