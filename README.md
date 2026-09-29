# AI Engineering Harness

> Control plane de engenharia de software orientado por agentes e LLMs — o workflow governa os agentes, não o contrário.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Status](https://img.shields.io/badge/status-V0%20Project%20Foundation-orange)

## O que é

O **AI Engineering Harness** é uma plataforma de orquestração que acompanha o ciclo de vida completo de um projeto de software: concepção, arquitetura, desenvolvimento, validação, release, deploy, observabilidade e recuperação.

Ele não é um wrapper de prompts. É um **control plane de engenharia** que coordena agentes especializados, contexto, memória, decisões, validações determinísticas e escalonamento humano.

### Problema que resolve

O desenvolvimento assistido por IA costuma sofrer com:

- prompts copiados e colados manualmente entre LLMs;
- contexto perdido entre sessões e decisões arquiteturais esquecidas;
- a mesma LLM que implementa avaliando o próprio trabalho;
- ausência de trilha de auditoria e de critérios objetivos para avançar ou escalar.

O Harness transforma esse fluxo em um processo **governado, observável e reproduzível**.

### Fluxo alvo

```text
Idea → Architecture/ADR → Sprint/Task Contract → Context Engineering → Agent Routing
     → Implementation → Deterministic Gates → Review/Decisions → State Machine
     → Integration → Release → Deploy → Observe → PASS / REMEDIATION / ROLLBACK / HUMAN REVIEW
```

### Princípios

- **Workflow governa agentes:** nenhuma LLM é autoridade única.
- **Determinismo primeiro:** o que pode ser validado por regra (testes, lint, exit codes) não depende de LLM.
- **Hierarquia de decisão:** regras determinísticas → decisão probabilística (Jev) → LLM de raciocínio → humano.
- **Provider-agnostic:** OpenAI, Anthropic Claude, NVIDIA e Jev entram via adapters configuráveis, sem nada hardcoded no core.
- **Memória não é fonte de verdade:** ADRs, policies, documentação oficial e Git prevalecem sobre a memória (Mem0).
- **Auditabilidade:** cada execução registra o que foi pedido, o contexto usado, as decisões tomadas e o motivo.

## Status atual

O projeto está na versão **V0 — Project Foundation**, que entrega:

- CLI (`python -m orchestrator` / `harness`);
- configuração declarativa em YAML validada com Pydantic;
- comando `doctor` para diagnóstico do ambiente;
- helpers de logging, subprocess e filesystem;
- testes automatizados.

Integrações com providers de IA, memória, Context Engine, gates e state machine ainda **não** foram implementadas. Elas chegam nas próximas versões (veja o [roadmap](docs/AI-Engineering-Harness-Roadmap.md)).

## Requisitos

- Python **3.12+**
- Git (opcional no V0; o `doctor` apenas emite aviso)
- Nenhuma API key, serviço externo ou acesso à rede é necessário

## Instalação

```bash
git clone <url-do-repositorio>
cd <repositorio>/engineering

python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Com [uv](https://github.com/astral-sh/uv):

```bash
cd engineering
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Uso

```bash
python -m orchestrator            # identidade + ajuda
python -m orchestrator --help
python -m orchestrator --version
python -m orchestrator doctor     # verifica ambiente e configuração
harness doctor                    # mesmo comando, via console script
```

O `doctor` retorna exit code `0` quando nenhum check falha (avisos são permitidos) e `1` quando há pelo menos uma falha.

A raiz do harness (pasta que contém `config/`) é resolvida nesta ordem: `--root PATH` → variável `HARNESS_ROOT` → diretório do package. O diretório atual nunca é usado:

```bash
python -m orchestrator --root /caminho/para/engineering doctor
HARNESS_ROOT=/caminho/para/engineering harness doctor
python -m orchestrator --log-level DEBUG doctor   # logs vão para stderr
```

## Testes e qualidade

Execute a partir de `engineering/`, com o venv ativo:

```bash
pytest          # suíte completa (unit + integration)
pytest -v tests/unit/test_config.py   # um arquivo específico
ruff check .    # lint
mypy            # type checking estrito
```

Os testes não dependem de APIs externas. Cada teste usa uma cópia isolada da configuração em diretório temporário.

## Estrutura do repositório

```text
.
├── docs/                    # documentação oficial: visão, requisitos, arquitetura, roadmap
└── engineering/             # harness (pasta portátil)
    ├── orchestrator/        # core Python (CLI, config, doctor, utils)
    ├── config/              # configuração declarativa do projeto (*.yaml)
    ├── templates/           # templates Markdown (ADR, sprint, task)
    ├── docs/                # arquitetura "as built" e registros de sprint
    ├── tests/               # testes unitários e de integração
    └── pyproject.toml
```

## Documentação

- [Visão do projeto](docs/01-PROJECT-VISION.md)
- [Requisitos funcionais e não funcionais](docs/02-FUNCTIONAL-NONFUNCTIONAL-REQUIREMENTS.md)
- [Arquitetura e estrutura de pastas](docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md)
- [Roadmap de implementação](docs/AI-Engineering-Harness-Roadmap.md)
- [Guia técnico do harness](engineering/README.md)
- [Arquitetura as-built (V0)](engineering/docs/architecture.md)

## Stack

**Core:** Python 3.12+, Typer, Pydantic v2, PyYAML, Rich, pytest.
**Previsto:** OpenAI, Anthropic Claude, NVIDIA, Jev/TypeSafe, Mem0 self-hosted, Docker.
