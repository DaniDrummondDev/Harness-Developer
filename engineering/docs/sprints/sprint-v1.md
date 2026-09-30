# Sprint V1 — Global Library

**Status: V1 — Global Library COMPLETE** (critério de saída do roadmap comprovado offline:
um projeto declara `stack`/`capabilities` e herda, sem cópia local, os artefatos globais
aplicáveis; pytest, ruff e mypy verdes).

## Objetivo

Criar a biblioteca global reutilizável do Harness (roadmap V1):

```text
Project profile (project.yaml: stack, capabilities)
        ↓
Global Library (skills, guidelines, policies, rules, specialties)
        ↓
deterministic resolution
        ↓
artefatos aplicáveis, tipados, com força normativa e motivo
```

sem Context Engine (V1.1+), sem Jev/LLM na seleção, sem agent runtime e sem gates.

## Baseline

| Item | Valor |
|---|---|
| Branch / HEAD | `main` / `d4c422f` ("Add unit tests for Mem0 memory provider and CLI interactions") |
| Working tree | limpa |
| Python / package | 3.12 / `0.4.0` (venv `engineering/.venv`) |
| pytest | 521 passed, 6 skipped (Mem0/Jev live opt-in) |
| ruff | limpo |
| mypy | limpo, 30 arquivos |
| Global Library | inexistente; `project.yaml` só com `stack: [python]`; `context.yaml` apenas toggle declarativo |

Contradições bloqueantes: nenhuma. Ponto resolvido por decisão (ver D1): RNF-003 diz que a
pasta do Harness é copiável para cada projeto, enquanto o V1 exige herdar conhecimento
"sem duplicar arquivos localmente". Ambos valem porque a raiz da biblioteca é a
*instalação* do Harness, e não a raiz de configuração do projeto.

## Arquitetura

```text
cli.py (library inspect | resolve)              doctor.py (check "library", offline)
        │                                                │
        └──────────── library/library.py ────────────────┘
                      GlobalLibrary.load(root) → index → references
                      artifacts() / by_type() / get() / resolve(profile)
                                   │
                      library/loader.py
                      resolve_library_root · discover · read · front matter · validate
                                   │
                      library/models.py
                      ArtifactType · Authority · AppliesTo · ArtifactMetadata
                      SpecialtyMetadata · Artifact · ProjectProfile · Match
                                   │
          utils/yaml_loader.py (safe YAML, extraído de config.py) · utils/files.py
```

`library/` não importa CLI, doctor, providers, memory, decisions, rede ou subprocess; `core/`
não importa `library/`; só `cli.py` e `doctor.py` a consomem
(`tests/unit/test_library_isolation.py`). A única dependência em `config` é
`default_harness_root()` (localização da instalação).

### Contratos

| Contrato | Papel |
|---|---|
| `ArtifactType` | `policy`, `guideline`, `rule`, `skill`, `specialty` |
| `Authority` / `AUTHORITY_BY_TYPE` | policy → `mandatory`; guideline, rule → `recommended`; skill, specialty → `knowledge` |
| `PRECEDENCE` | mandatory (0) < recommended (1) < knowledge (2): ordem da saída |
| `ArtifactMetadata` | `version: 1`, `id`, `type`, `name`, `description`, `tags`, `applies_to` (extra proibido) |
| `SpecialtyMetadata` | + `skills`, `rules` (referências tipadas, validadas) |
| `AppliesTo` | `always: true` **xor** `stacks`/`capabilities`; `reasons(profile)` |
| `Artifact` | metadata + body (texto inerte) + `source` relativo; `key = <type>/<id>` |
| `ProjectProfile` | `stack`, `capabilities` normalizados (ordenados, sem duplicatas) |
| `Match` | artefato + motivos (`always`, `stack:<x>`, `capability:<x>`) |
| `GlobalLibrary` | `load`, `artifacts`, `by_type`, `get`, `resolve` |
| Erros | `LibraryError` → `LibraryStructureError`, `ArtifactParseError`, `ArtifactValidationError`, `ArtifactNotFoundError` (com `path`) |

## Decisões técnicas

- **D1 — A biblioteca pertence à instalação.** `resolve_library_root`: explícito →
  `$HARNESS_LIBRARY_ROOT` → diretório de instalação (`default_harness_root()`). Nunca
  `--root`/`$HARNESS_ROOT`. Um consumidor aponta `--root` para o seu `config/` e herda a
  biblioteca (provado por `test_module_library_resolve_from_foreign_cwd`, cujo root não
  contém nenhum artefato). Alternativa rejeitada: biblioteca sob a raiz de config — exigiria
  cópia por projeto.
- **D2 — Layout da arquitetura alvo** (`engineering/{policies,guidelines,rules,skills,specialties}/`),
  um diretório plano por tipo; `rules/` acrescentado à árvore alvo. Alternativa rejeitada:
  `engineering/library/<tipo>/` — divergiria da arquitetura alvo sem ganho.
- **D3 — Markdown + front matter YAML**: legível, versionável em Git, validável com
  Pydantic, sem banco nem formato novo. Schema `version: 1` (mesma convenção dos YAMLs).
- **D4 — `Authority` derivada do tipo**, não declarável (campo `authority:` é rejeitado).
  Garante que guideline nunca tenha força de policy e já entrega a ordem de precedência que
  o Context Engine usará. Rules ficam em `recommended`: são convenções concretas e
  verificáveis; torná-las obrigatórias é papel de uma policy (ou dos gates no V3).
- **D5 — IDs únicos por tipo**; identidade global `<type>/<id>`. O roadmap usa o mesmo nome
  em tipos diferentes (`testing` é skill, guideline e specialty).
- **D6 — Aplicabilidade explícita**: sem default implícito; `always` não combina com
  matchers. Todas as policies entregues são `always: true` (fail closed: uma policy não
  depende de o projeto lembrar de declarar uma capability).
- **D7 — `capabilities` em `project.yaml`** (opcional, retrocompatível): único campo novo,
  consumido pela resolução (ex.: `api` → skill/specialty `api`, rules de controllers).
  "Tipo de projeto" não foi adicionado: sem consumidor distinto de `capabilities`.
- **D8 — Resolução = igualdade exata de strings**, sem aliases (`mysql` casa porque o
  artefato `database` lista `mysql`), sem Jev, sem LLM. Ordem: authority, tipo, id.
- **D9 — Referências de specialties são validadas, não expandidas.** Expansão/roteamento é
  Specialty Routing (V2.4).
- **D10 — Fail fast em ordem estável** (tipo, nome de arquivo): o mesmo erro sempre.
- **D11 — Segurança do loader**: só os cinco diretórios conhecidos; cada diretório e
  arquivo precisa resolver dentro do diretório esperado (symlink para fora ou `../` →
  erro); apenas `*.md` regulares (dotfiles ignorados, qualquer outra entrada é erro);
  limite de 256 KiB checado antes da leitura; UTF-8; YAML via SafeLoader com chaves
  duplicadas rejeitadas (tags `!!python/...` falham sem executar nada); body nunca
  interpretado.
- **D12 — CLI mínima**: `library inspect [--type]` e `library resolve [--stack] [--capability]`,
  JSON em stdout. `doctor` ganhou um check offline em vez de um comando `validate`.
- **D13 — `utils/yaml_loader.py`** extraído de `config.py` (agora com dois consumidores);
  comportamento da config inalterado (testes de chave duplicada seguem verdes).
- **D14 — Versão `1.0.0`** seguindo o mapeamento Vx.y → x.y.0 já usado (V0.4 = 0.4.0).

## Estrutura de pastas

```text
engineering/
├── orchestrator/library/{__init__,models,loader,library}.py   # novo
├── orchestrator/utils/yaml_loader.py                          # novo (extraído)
├── policies/     secrets, security, git, breaking-changes, deploy
├── guidelines/   coding, architecture, testing, documentation, review
├── rules/        thin-controllers, explicit-authorization,
│                 validation-at-boundaries, avoid-unnecessary-abstractions
├── skills/       python, laravel, testing, database, security, api, docker
├── specialties/  architecture, python, php-laravel, testing, database,
│                 security, api, infrastructure
└── tests/
    ├── library_helpers.py
    ├── unit/test_library_loader.py        # loading, parsing, validação, path safety, root
    ├── unit/test_library_resolution.py    # resolução, semântica, conteúdo entregue
    ├── unit/test_library_cli_doctor.py    # CLI e check do doctor
    └── unit/test_library_isolation.py     # boundaries (AST)
```

Alterados: `orchestrator/{config,doctor,cli,__init__}.py`, `core/exceptions.py`,
`config/project.yaml`, `pyproject.toml` (descrição), `tests/conftest.py` (fixture
`library_root`), `tests/unit/{test_doctor,test_config}.py`,
`tests/integration/test_module_entrypoint.py`, docs.

## Fluxos principais

```text
harness library resolve                          (perfil de project.yaml sob --root)
  load_config(--root) → ProjectProfile(stack, capabilities)
  resolve_library_root() → GlobalLibrary.load(root)
     para cada tipo (ordem fixa): diretório existe e está dentro da raiz
       para cada entrada ordenada: *.md regular dentro do diretório, ≤ 256 KiB, UTF-8
         front matter '---' → YAML seguro → version == 1 → type válido == diretório
         → ArtifactMetadata/SpecialtyMetadata → body não vazio → Artifact
     índice (type, id) sem duplicatas → referências de specialties existem
  library.resolve(profile) → Match[] (authority → tipo → id) → JSON
```

Exemplo (projeto Laravel do enunciado, `--stack php --stack laravel --stack mysql
--stack redis --stack docker --capability api`): 5 policies e 5 guidelines (`always`),
rules `thin-controllers`/`explicit-authorization` (`stack:laravel`, `capability:api`) e as
duas universais, skills `laravel`, `database` (`stack:mysql`), `docker`, `api`, `testing`,
`security`, specialties `php-laravel`, `database`, `infrastructure`, `api`, `architecture`,
`security`, `testing`. Nenhum item Python. `redis` e `php` não casam nada (nenhum
artefato os declara): sem falso positivo.

### Operação e debug

- `harness doctor` → linha `library` com contagem por tipo, ou o arquivo e o motivo do erro.
- `harness library inspect --type policy` → metadata JSON (sem body).
- `harness library resolve --stack <x>` → o que casa e por quê (`reasons`).
- Erro sempre prefixado pelo caminho do arquivo; ordem estável.
- Autoria: criar `<tipo-dir>/<id>.md` com o front matter do README; rodar `doctor`.

## Testes

| Gate | Resultado |
|---|---|
| pytest | **633 passed, 6 skipped** (6 = testes live Mem0/Jev opt-in; +112 testes V1) |
| ruff check . | All checks passed |
| mypy (strict) | Success: no issues found in 35 source files |
| `python -m orchestrator doctor` | PASS (9 pass, 0 warn, 0 fail); `library`: 29 artifacts |

Cobertura V1: biblioteca válida com todos os tipos; biblioteca vazia; ordem estável
independente da criação; mesmo id em tipos diferentes; front matter ausente/não fechado/
vazio/lista/YAML inválido/chave duplicada; CRLF+BOM; UTF-8 inválido; arquivo ilegível;
arquivo grande; versão de schema inválida (2, 0, `'1'`, `true`, ausente); tipo inválido;
tipo ≠ diretório; id ausente/malformado (`../etc`, `a/b`, maiúsculas); id duplicado; campos
extras (`provider`, `model`, `role`, `authority`); `applies_to` ausente/vazio/combinado/
duplicado; body vazio; referência inexistente ou de tipo errado; symlink de arquivo e de
diretório para fora; `../` via symlink; tag YAML `!!python` não executa; diretório ausente;
arquivo não-md; subdiretório; resolução por stack, stack desconhecida, perfil vazio,
matches parciais não casam, múltiplas stacks/capabilities, todos os motivos, determinismo
sob todas as permutações; policy vs guideline distintos com mesmo id; ordem por precedência;
conteúdo entregue cobre o roadmap, policies universais, exemplo Laravel, perfil deste
projeto, conteúdo sem secrets (regras de `memory/safety.py`); independência de cwd (unit
e subprocess); CLI inspect/resolve e códigos de saída; doctor PASS/FAIL/WARN/env.

## Riscos

- **Vocabulário não controlado**: `postgres` ≠ `postgresql`; um typo silencia um match.
  Mitigação atual: `library resolve` mostra exatamente o que casou e por quê.
- **Conteúdo desatualizado**: artefatos são conhecimento curado; revisão é humana (Git).
- **Wheel sem biblioteca**: instalação não editável precisa de `$HARNESS_LIBRARY_ROOT`
  (sem ele, `doctor` falha — fail closed, não silencioso).
- **Autoridade de rules**: tratadas como `recommended`; se uma rule precisar ser
  obrigatória, hoje isso só se expressa por uma policy (texto).

## Melhorias futuras

- V1.1: usar `GlobalLibrary` como fonte de candidatos do Context Candidate Discovery.
- Composição Global + conhecimento local do projeto (o loader já é agnóstico de raiz;
  falta a regra de sobreposição/precedência — decisão de produto).
- Aviso no `doctor`/`resolve` para entradas de `stack`/`capabilities` que nada casam.
- Relatório de todos os erros de uma vez (hoje fail fast).
- Expansão de referências de specialties no Specialty Routing (V2.4).
- Empacotar a biblioteca como package data quando houver distribuição por wheel.

## Dívidas

Listadas em `docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md` §23 ("Identificadas no V1").
Nenhuma impede o critério de saída.

Próxima versão: **V1.1 — Context Candidate Discovery** (não iniciada).
