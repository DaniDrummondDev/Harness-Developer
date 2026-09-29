# AI Engineering Harness — Arquitetura e Estrutura de Pastas

## 1. Objetivo

Este documento descreve a arquitetura atual e a estrutura de pastas do AI Engineering Harness após a conclusão do **V0 — Project Foundation**.

Ele possui dois objetivos complementares:

1. documentar com precisão o que existe hoje no repositório;
2. preservar a direção arquitetural necessária para as próximas versões sem antecipar implementação.

A estrutura deve continuar permitindo evolução incremental, mantendo separação entre:

- core Python;
- configuração;
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
V0 — Project Foundation
Status: COMPLETE
```

O V0 entregou:

- package Python funcional;
- CLI base com Typer;
- configuração declarativa em YAML;
- validação com Pydantic;
- logging;
- subprocess helper;
- filesystem helper;
- comando `doctor`;
- templates iniciais;
- testes unitários, integração e contrato;
- documentação arquitetural interna da implementação.

O V0 não implementa:

- modos Interactive/Autonomous completos;
- abstração real de providers;
- OpenAI;
- Anthropic;
- NVIDIA;
- Jev;
- Mem0;
- Context Engine;
- agent execution;
- gates framework;
- review system;
- state machine;
- Git orchestration;
- run artifacts completos;
- risk engine;
- release;
- deploy;
- observabilidade externa;
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

## 5. Estrutura real após o V0

A estrutura atualmente implementada é:

```text
engineering/
├── orchestrator/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── doctor.py
│   │
│   ├── core/
│   │   └── exceptions.py
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
│       └── sprint-v0.md
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

Observação:

A árvore acima representa o estado funcional do V0.

Diretórios e módulos futuros devem ser adicionados somente quando a versão correspondente os exigir.

---

## 6. Regras de organização atuais

### `orchestrator/`

Contém o core Python genérico do Harness.

Não deve conter configuração específica de um projeto consumidor.

### `orchestrator/cli.py`

Responsável pela interface CLI atual.

No V0 suporta:

```text
python -m orchestrator
python -m orchestrator --help
python -m orchestrator doctor
```

A CLI deve permanecer fina.

Ela coordena serviços, mas não deve concentrar regras de domínio.

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

O comportamento não deve depender do current working directory.

### `orchestrator/doctor.py`

Responsável por diagnósticos determinísticos da fundação local.

Resultados possíveis:

```text
PASS
WARN
FAIL
```

O `doctor` não deve exigir integrações externas ainda não pertencentes à versão atual.

### `orchestrator/core/exceptions.py`

Define erros tipados do Harness.

A hierarquia deve permanecer pequena e evoluir somente quando consumidores reais exigirem distinções adicionais.

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

Esse módulo será reutilizado futuramente por gates e ferramentas.

### `orchestrator/utils/files.py`

Contém apenas operações de filesystem realmente utilizadas pelo core.

Evitar transformar esse módulo em uma biblioteca genérica sem necessidade.

### `orchestrator/utils/logging.py`

Centraliza configuração de logging.

Princípios:

- logger do Harness separado do output principal da CLI;
- logs em stderr;
- não registrar secrets;
- evitar argumentos, ambiente ou outputs sensíveis;
- preparado para structured logging futuro.

---

## 7. Configuração declarativa

O V0 possui os seguintes arquivos:

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

- `providers.yaml` existe, mas providers reais ainda não estão implementados;
- `memory.yaml` existe, mas Mem0 ainda não está integrado;
- `context.yaml` existe, mas Context Engine ainda não existe;
- `modes.yaml` prepara V0.1;
- `decisions.yaml` prepara V0.4 e versões posteriores.

### Regras de validação atuais

A fundação já valida:

- schema via Pydantic;
- campos extras proibidos;
- YAML inválido;
- chaves duplicadas;
- referências de modelos para providers declarados;
- referências de roles para modelos declarados;
- ordem conceitual de decisão;
- risco default válido.

Essas regras devem continuar evoluindo junto com a implementação real.

---

## 8. Princípios arquiteturais obrigatórios

### 8.1 Workflow governa agentes

Nenhum provider ou modelo deve controlar sozinho o processo.

O Harness controla:

- estados;
- políticas;
- limites;
- gates;
- decisões;
- escalonamento.

### 8.2 Determinismo primeiro

Sempre que uma condição puder ser decidida objetivamente, use regra ou gate determinístico antes de decisões probabilísticas.

Ordem alvo:

```text
Deterministic Rules
→ Jev
→ Reasoning LLM
→ Human
```

### 8.3 Provider agnostic

O core não pode depender semanticamente de:

- OpenAI;
- Anthropic;
- NVIDIA;
- Jev;
- Mem0.

Integrações futuras entram por adapters/contracts.

### 8.4 Baixo acoplamento

Configuração específica permanece fora do core.

Módulos devem depender de contracts estáveis, não de implementações concretas.

### 8.5 Simplicidade incremental

Não criar abstrações sem consumidor real.

Evitar antecipar:

- interfaces;
- registries;
- factories;
- plugin systems;
- pipelines;
- state machines.

A arquitetura deve comportar evolução futura sem implementar funcionalidades antes da hora.

### 8.6 Auditabilidade

Toda execução relevante deverá futuramente preservar evidências suficientes para reconstruir:

- solicitação;
- contexto;
- modelo;
- decisões;
- gates;
- alterações;
- resultado.

O V0 prepara a base, mas não implementa ainda o modelo completo de run artifacts.

---

## 9. Target architecture

A direção arquitetural continua sendo:

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

Essa árvore é **arquitetura alvo**, não backlog automático de diretórios.

Um diretório somente deve nascer quando houver:

- responsabilidade concreta;
- consumidor real;
- comportamento testável;
- versão do roadmap que o justifique.

---

## 10. Boundaries futuros

### `providers/`

Adapters para serviços externos.

Entrará a partir de:

```text
V0.2 — Provider Abstraction
```

### `memory/`

Memória de longo prazo.

Primeira implementação:

```text
Mem0 self-hosted
```

Entrará em:

```text
V0.3 — Memory Foundation
```

### `decisions/`

Camada de decisão probabilística e política de escalonamento.

Primeira integração real:

```text
Jev / TypeSafe
```

Entrará inicialmente em:

```text
V0.4 — Decision Foundation
```

e será expandida nas versões de Decision Layer.

### `context/`

Context Engineering.

Responsabilidades alvo:

```text
request/task
→ candidate discovery
→ deterministic inclusion
→ Jev scoring
→ optional LLM escalation
→ budget
→ final context package
```

Entra a partir da família:

```text
V1.x — Context Engineering
```

### `agents/`

Roles e specialty routing.

Entra a partir de:

```text
V2.x — Agent Execution
```

### `gates/`

Validações determinísticas e semi-determinísticas.

Entra a partir de:

```text
V3.x — Deterministic Quality
```

### `review/`

Review estruturado, findings e reviewers especializados.

Entra a partir de:

```text
V4.x — Review System
```

### `git/`

Controle de repository, diff, branch, worktree e integration.

Entra a partir de:

```text
V7.x — Git Integration
```

### `storage/`

Persistência de runs, state e artifacts.

Entra principalmente em:

```text
V8.x — Run Artifacts
```

### `delivery/`

Build, release, deploy, smoke e rollback.

Entra entre:

```text
V10 — Release
V11 — Deployment
```

### `observability/`

Health, logs, metrics e validação pós-deploy.

Entra em:

```text
V12 — Observability
```

---

## 11. Ordem oficial de implementação

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

## 12. Próxima versão

Após o fechamento do V0, a próxima versão é:

```text
V0.1 — Mode Foundation
```

Objetivo:

Formalizar os dois modos de entrada sem implementar ainda a state machine completa.

### Interactive Mode

Entrada iniciada por humano.

Fontes futuras:

- CLI;
- MCP;
- Claude Code;
- Codex;
- HTTP API.

### Autonomous Mode

Entrada iniciada pelo workflow persistido.

Fontes futuras:

- roadmap;
- sprint;
- task pendente;
- run anterior;
- estado persistido.

### Elementos previstos

- `EngineeringRequest`;
- `ExecutionMode`;
- `RequestSource`;
- `Intent`;
- normalização de entrada;
- regras de transição inicial.

O V0.1 deve continuar provider-agnostic.

Não deve ainda integrar:

- OpenAI;
- Anthropic;
- NVIDIA;
- Jev;
- Mem0.

---

## 13. Contratos futuros

O sistema deverá evoluir, quando houver consumidor real, para contracts equivalentes a:

```python
class LLMProvider:
    ...

class DecisionProvider:
    ...

class MemoryProvider:
    ...

class Gate:
    ...

class Tool:
    ...

class DeploymentProvider:
    ...
```

Essas interfaces não devem ser criadas apenas por antecipação.

A introdução de cada contract precisa ocorrer junto do primeiro caso de uso real.

---

## 14. Precedência de fontes

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

Para **versionamento e sequência de entrega**, acrescenta-se:

```text
AI-Engineering-Harness-Roadmap.md
```

como fonte autoritativa.

Memória nunca substitui fonte oficial.

---

## 15. Segurança

Princípios obrigatórios desde o V0:

- secrets não devem ser persistidos em logs;
- não registrar `.env`;
- não registrar tokens;
- subprocess sem shell quando possível;
- paths validados;
- configuração inválida falha cedo;
- ausência de evidência crítica não deve ser tratada como sucesso.

Hardening completo entra somente em versões posteriores.

---

## 16. Testabilidade

Toda nova capacidade deve possuir:

- type hints;
- testes;
- erro previsível;
- configuração validável;
- possibilidade de uso com fakes quando envolver serviços externos.

Chamadas reais a providers não devem ser necessárias para testes unitários.

---

## 17. Stack atual

### Core

```text
Python 3.12+
Typer
Pydantic v2
PyYAML
Rich
pytest
```

### Tooling atual de qualidade

```text
ruff
mypy
pytest
```

Jinja2 não foi incluído no V0 porque ainda não possui consumidor real.

---

## 18. Integrações previstas

Ainda não implementadas:

```text
OpenAI
Anthropic Claude
NVIDIA
Jev / TypeSafe
Mem0 self-hosted
Git orchestration
Docker-based infrastructure
```

A ausência dessas integrações no V0 é intencional.

---

## 19. Critérios arquiteturais para novas versões

Cada versão deve:

1. introduzir apenas capacidades necessárias;
2. possuir testes;
3. manter baixo acoplamento;
4. evitar abstrações sem consumidor real;
5. produzir contratos estruturados quando necessário;
6. manter auditabilidade;
7. atualizar documentação quando decisões arquiteturais mudarem;
8. não alterar silenciosamente a arquitetura;
9. respeitar a ordem oficial do roadmap;
10. parar ao atingir os critérios de saída da versão atual.

---

## 20. Estado arquitetural consolidado

O projeto possui agora uma fundação funcional e testada.

O estado pode ser resumido como:

```text
Project Foundation
        ↓
Typed Configuration
        ↓
CLI
        ↓
Doctor
        ↓
Filesystem / Subprocess / Logging
        ↓
Tests
        ↓
Ready for Mode Foundation
```

Ainda não existe orchestration real de agentes.

Ainda não existe Context Engineering.

Ainda não existe memória operacional.

Ainda não existe decision provider.

Ainda não existe autonomia.

Essas capacidades serão adicionadas progressivamente de acordo com o roadmap.

---

## 21. Regra final

A estrutura deste documento representa duas coisas distintas:

### Current architecture

O que está efetivamente implementado e testado hoje.

### Target architecture

A direção que permite evoluir o Harness até se tornar um control plane de engenharia completo.

Nunca confundir arquitetura alvo com implementação atual.

A regra permanece:

> preparar para evolução sem antecipar complexidade.
