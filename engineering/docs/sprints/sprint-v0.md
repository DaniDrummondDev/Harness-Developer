# Sprint V0 — Project Foundation

## Objetivo

Criar a fundação verificável do AI Engineering Harness: package Python, CLI, configuração
declarativa validada, logging, helpers de subprocess/filesystem, `doctor`, templates base e
testes — sem nenhuma integração externa e sem antecipar V0.1+.

## Arquitetura

Camadas com dependência em sentido único: `cli → doctor → config → utils → core`.
Detalhes e mapa do sistema: [`../architecture.md`](../architecture.md).

## Decisões técnicas

- `engineering/` é a harness root portátil (RNF-003); docs oficiais permanecem em `/docs`.
- Resolução da root: `--root` > `$HARNESS_ROOT` > diretório do package; nunca o cwd.
- 10 arquivos YAML obrigatórios, `version: 1`, `extra="forbid"`, chaves duplicadas rejeitadas.
- Validação em 3 estágios com erros distintos: parse → schema → referências cruzadas/paths.
- Subprocess sempre sem shell; resultado estruturado; non-zero é dado, não exceção (salvo `check=True`).
- Logs em stderr, nível WARNING por padrão; nunca registra argv completo, env ou output.
- `doctor`: PASS/WARN/FAIL, pior status vence, exit 1 somente com FAIL; check que quebra = FAIL.
- Git é WARN no V0 (nenhuma operação Git ainda).
- Sem Jinja2 e sem interfaces/registries até existir consumidor.
- Lista de configs segue o roadmap (inclui `modes.yaml`), não a árvore arquitetural.

## Estrutura de pastas

```text
engineering/
├── orchestrator/{__init__,__main__,cli,config,doctor}.py
├── orchestrator/core/exceptions.py
├── orchestrator/utils/{shell,files,logging}.py
├── config/*.yaml (10)
├── templates/{README,adr,sprint,task}.md
├── docs/{architecture.md, sprints/sprint-v0.md}
├── tests/{conftest.py, unit/, integration/}
├── pyproject.toml, README.md, .gitignore
```

## Fluxos principais

1. `python -m orchestrator` → identidade + help (exit 0).
2. `python -m orchestrator doctor` → checks → tabela Rich em stdout → exit 0/1.
3. `load_config(root)` → `HarnessConfig` imutável ou `ConfigError` tipado com path e campo.

Testes: `pytest` (77), `ruff check .`, `mypy` (strict). Debug: `--log-level DEBUG`.

## Riscos

- Schemas preparatórios (providers/models/memory/...) serão revistos em V0.2+/V0.3; `version`
  existe para tornar essa evolução explícita.
- Instalação não-editable exige `--root`/`HARNESS_ROOT`.
- Testes de subprocess dependem de `sys.executable` e de permissões POSIX (`chmod`).
- `doctor` não valida versões mínimas de dependências Python (delegado ao `pyproject.toml`).

## Melhorias futuras

- Conflitos documentais (lista de configs e numeração de versões entre roadmap e doc 03)
  devem ser resolvidos por decisão humana/ADR.
- ADR formal para a decisão "engineering/ como harness root".
- CI executando `pytest`, `ruff` e `mypy`.
