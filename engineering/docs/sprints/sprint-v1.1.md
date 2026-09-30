# Sprint V1.1 — Context Candidate Discovery

**Status: V1.1 — Context Candidate Discovery COMPLETE** (dado um `EngineeringRequest`
válido, o Harness produz um `ContextDiscoveryResult` tipado, determinístico, auditável,
seguro, offline com fakes e independente do CWD, sem classificação, budget, LLM ou Jev).

## Objetivo

```text
EngineeringRequest
        ↓
Context Candidate Discovery
        ↓
Global Library · instructions · ADRs · docs · repository hints · memory
        ↓
ContextDiscoveryResult (candidates + sources + warnings + unsupported sources)
```

Responde "quais fontes existem que *podem* ser relevantes?". Não responde quais são
melhores, o que entra no prompt nem quanto cabe (V1.2–V1.3).

## Baseline

| Item | Valor |
|---|---|
| Branch / HEAD | `main` / `f905ea4` ("Add specialties and tests for the Global Library", V1) |
| Working tree | limpa |
| Package | `1.0.0` |
| pytest | 633 passed, 6 skipped (Mem0/Jev live opt-in) |
| ruff / mypy | limpo / limpo (35 arquivos) |
| doctor | PASS (9 pass) |
| Contexto | `context.yaml` só com toggle `enabled: false` sem consumidor; nenhum `context/` |
| Fontes reais | Global Library (V1), `MemoryService` (V0.3), arquivos do projeto. Sem ADRs no repo (`docs/adr` inexistente; só template), sem store de task/sprint contracts, sem Git (V7), runs/releases/findings (V8+) |

Contradições bloqueantes: nenhuma. Dois guards anteriores foram ajustados conscientemente:

- `test_library_isolation`: `context/` passa a consumir a Global Library (fonte de candidatos
  exigida pelo V1.1);
- `test_doctor::test_valid_environment_passes`: novo check `context`.

O guard do V0.3 "só CLI/doctor abrem memória" foi **preservado**: `context/` busca memória
por um protocolo (`MemorySearcher`) e nunca importa `memory.service`.

## Arquitetura

```text
cli.py  context discover ──┐                   doctor.py  check "context" (só caminhos)
  normalize_request/admit  │                        │
  GlobalLibrary.load       │                        │
  open_memory (opcional)   │                        │
                           ↓                        ↓
             context/discovery.py   build_discovery · check_discovery_paths
                                    ContextCandidateDiscovery (merge · sort)
                           ↓
             context/discoverers.py LibraryDiscoverer · InstructionsDiscoverer
                                    AdrDiscoverer · DocumentationDiscoverer
                                    RepositoryHintsDiscoverer · MemoryDiscoverer
                                    UnconsultedSource
                           ↓
             context/files.py       ProjectFiles (contenção, walks limitados, exclusões)
             context/models.py      ContextCandidate · CandidateReference · Provenance
                                    SourceReport · ContextDiscoveryResult
```

Dependências: `context → core, config, library, memory.models`. Nunca `cli`, `doctor`,
`providers`, `decisions` (sem Jev), `memory.service/mem0/fake`, rede ou subprocess (guard
AST em `test_context_discovery.py`). `core/`, `library/` e `memory/` não importam `context/`.

### Contratos

| Contrato | Conteúdo |
|---|---|
| `CandidateKind` | `policy, guideline, rule, skill, specialty, instructions, adr, doc, source, memory` (ordem = prioridade de merge e de saída) |
| `ReferenceStore` | `project` · `library` · `memory` |
| `CandidateReference` | `store` + `path` relativo (ou id de memória) |
| `Provenance` | `discoverer` + `reason` |
| `ContextCandidate` | `id`, `kind`, `title`, `reference`, `provenance` (≥1), `metadata` — sem classe, relevância, score ou tokens (campos extras rejeitados) |
| `SourceReport` | `discoverer`, `status` (`ok` · `skipped` · `unavailable`), `candidates`, `warnings` |
| `ContextDiscoveryResult` | `request` (o próprio `EngineeringRequest`), `candidates`, `sources`, `unsupported_sources`; `.warnings` |
| `CandidateDiscoverer` (Protocol) | `name` + `discover(request) -> Discovered` |
| `MemorySearcher` (Protocol) | `project` + `search(text, scope, limit)` — satisfeito por `MemoryService` |
| Erro | `ContextDiscoveryError` (fatal): contexto desabilitado, caminho configurado fora do projeto |

## Decisões técnicas

- **D1 — Discovery ≠ classification.** Nenhum campo de classe/relevância/budget. A
  `authority` da biblioteca, o `status` de ADR e o `backend_score` de memória são
  *metadata* de proveniência, nunca decisão. Sem Jev, sem LLM.
- **D2 — Request como sujeito.** A task/requisição não vira candidato: é sempre parte do
  trabalho e é ecoada em `result.request` (mesmo objeto, sem duplicar campos).
- **D3 — Só fontes reais.** Library, instruction files, ADRs, docs, repository hints e
  memória. Task/sprint contracts, Git, previous runs, releases e findings aparecem em
  `unsupported_sources`; nada é simulado. Sprint records em `engineering/docs/sprints/`
  são descobertos como *documentação* (é o que eles são hoje).
- **D4 — Identidade estável** por `kind` + caminho relativo ao projeto (arquivos),
  `<type>/<id>` (biblioteca) e `memory/<id>`. Nunca por índice ou título.
- **D5 — Deduplicação por recurso canônico** (arquivo com symlinks resolvidos; id de
  memória): um recurso = um candidato com **todas as proveniências** (ex.:
  `docs/03-...md` via `documentation` + `repository_hints`; neste repo a instalação vive
  dentro do projeto, então `engineering/policies/secrets.md` citado na requisição funde com
  `policy/secrets`). O `kind` vencedor é o primeiro em `CandidateKind`; a metadata do
  perdedor é descartada, a proveniência não.
- **D6 — Referências, não conteúdo.** Só `stat` e os primeiros 8 KiB de Markdown (título,
  status de ADR). Exceção documentada: memória leva excerpt ≤ 280 chars porque
  `MemoryProvider` não tem get-by-id.
- **D7 — Biblioteca por perfil**, via `GlobalLibrary.resolve(ProjectProfile)` (sem
  reparse, sem casar texto da requisição — isso é classificação).
- **D8 — Repository hints conservadores.** Só o que a requisição (ou `--ref`) nomeia:
  caminhos (relativos à raiz do projeto, depois a cada `source_root`), diretórios (arquivos
  diretos), nomes de arquivo exatos (walk limitado dos `source_roots`). Heurística de nome:
  radical ≥ 2 caracteres e extensão iniciando por letra (`e.g.`, `1.2` não são arquivos).
  URLs ignoradas; `file.py:42` → `file.py`.
- **D9 — Memória opt-in, só leitura, scope de projeto.** `memory.enabled: false` →
  `skipped`; habilitada mas não abrível (ex.: sem `$MEM0_API_KEY`) → `unavailable` com o
  motivo; falha de busca → `unavailable`; zero hits → `ok` + warning. Discovery continua.
- **D10 — Fatal vs warning.** Fatal: config inválida, contexto desabilitado, caminho
  configurado escapando (inclusive via symlink). Warning: raiz opcional ausente, hint não
  encontrado/rejeitado, arquivo grande, limite de walk, memória indisponível.
- **D11 — `context.enabled` ganha consumidor** e passa a `true` no config entregue
  (fail closed quando `false`, como memória).
- **D12 — Configuração mínima** (`context.yaml` → `discovery`): caminhos relativos
  normalizados e validados sintaticamente no Pydantic, contenção verificada em runtime;
  limites (`max_files`, `max_file_bytes`) são de operabilidade, não budget; opções de
  V1.2/V1.3 rejeitadas como campos extras.
- **D13 — CLI fina**: `context discover` reutiliza `normalize_request` + `admit` (mesmo
  caminho do `intake`). `doctor` só valida caminhos; nunca faz walk (testado).
- **D14 — Versão `1.1.0`.**

## Estrutura de pastas

```text
engineering/orchestrator/context/{__init__,models,files,discoverers,discovery}.py   # novo
engineering/tests/unit/test_context_files.py        # contratos + filesystem seguro
engineering/tests/unit/test_context_discoverers.py  # cada discoverer isolado
engineering/tests/unit/test_context_discovery.py    # agregação, dedup, composição, config,
                                                    # doctor, CLI, guards de arquitetura
engineering/docs/sprints/sprint-v1.1.md
```

Alterados: `orchestrator/{config,cli,doctor,__init__}.py`, `core/exceptions.py`,
`config/context.yaml`, `pyproject.toml`, `tests/unit/{test_doctor,test_library_isolation}.py`,
`tests/integration/test_module_entrypoint.py`, docs.

## Fluxos principais

### Segurança do filesystem

- raiz do projeto canonicalizada; todo caminho configurado precisa resolver dentro dela;
- caminhos da configuração: relativos POSIX, sem `..`, `/`, `~`, `\`, `:`;
- hints: normalizados e resolvidos; fora do projeto → rejeitados com warning;
- walks: ordenados, depth-first, sem seguir diretórios symlink; arquivo symlink só se o
  alvo estiver no projeto; entradas ocultas e diretórios excluídos podados (`.git`,
  `.venv`, `venv`, `node_modules`, `vendor`, `__pycache__`, caches, `build`, `dist`,
  `site-packages`, IDEs + `exclude_dirs`);
- nomes de secrets (`.env*`, `*.pem|key|p12|pfx|jks|keystore`, `id_rsa*`, `.npmrc`,
  `.pypirc`, `.netrc`, `.pgpass`, `credentials*`, `secrets.{yaml,json,toml}`) nunca viram
  candidatos, nem citados explicitamente;
- no máximo `max_files` arquivos por walk; arquivos > `max_file_bytes` ignorados sem leitura;
- sem `eval`/`exec`/shell (guard AST).

### Exemplo real (este repositório)

```bash
python -m orchestrator context discover \
  "Refactor engineering/orchestrator/library/loader.py and cli.py following docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md" \
  --intent implement --ref T-42
```

36 candidatos: 19 da biblioteca (5 policies, 5 guidelines, 2 rules, 3 skills,
4 specialties para `stack: [python]`), `instructions/CLAUDE.md`, 14 docs e 2 sources.
Trechos:

```json
{"id": "policy/secrets", "kind": "policy",
 "reference": {"store": "library", "path": "policies/secrets.md"},
 "provenance": [{"discoverer": "library", "reason": "applies to the project profile: always"}]}
{"id": "doc/docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md", "kind": "doc",
 "provenance": [{"discoverer": "documentation", "reason": "under documentation path 'docs'"},
                {"discoverer": "repository_hints",
                 "reason": "named in the request: 'docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md'"}]}
{"id": "source/engineering/orchestrator/cli.py", "kind": "source",
 "provenance": [{"discoverer": "repository_hints", "reason": "named in the request: 'cli.py'"}]}
```

Fontes: `library ok 19`, `instructions ok 1`, `adrs ok 0` (warning `'docs/adr' does not
exist`), `documentation ok 14`, `repository_hints ok 3`, `memory skipped` (memória
desabilitada). Hints inseguros (`../../etc/passwd`, `.venv/pyvenv.cfg`) aparecem como
warnings de rejeição.

### Debug

- `harness context discover "..." | jq '.sources'` → o que cada fonte fez e por quê;
- `jq '.candidates[] | {id, provenance}'` → por que cada candidato está lá;
- `harness doctor` → caminhos de discovery válidos/ausentes sem executar discovery.

## Testes

| Gate | Resultado |
|---|---|
| pytest | **736 passed, 6 skipped** (+103 do V1.1; 6 = live Mem0/Jev opt-in) |
| ruff check . | All checks passed |
| mypy (strict) | Success: no issues found in 40 source files |
| `python -m orchestrator doctor` | PASS (10 pass, 0 warn, 0 fail) |

Cobertura: contrato (imutabilidade, serialização, ausência de campos de classificação,
proveniência obrigatória, kinds suportados); filesystem (escape fatal via symlink,
canonicalização, ordenação independente da criação, poda de ocultos/excluídos/secrets,
symlink de diretório não seguido, symlink de arquivo para fora, limite de tamanho, limite de
arquivos, leitura limitada do cabeçalho, diretório ilegível); library (todos os tipos,
perfil, ordem, reuso de `resolve`); instructions/docs/ADRs (roots válidas, ausentes,
arquivos ignorados, status/número, README de ADR ignorado); hints (extração, path
explícito, relativo a source root, nome em vários lugares, diretório, `origin_ref`,
inexistente, `..`, absoluto, excluído, secret, symlink para fora, sem hints, sem match);
memória com fake (hit → candidato, só scope de projeto, zero hits, backend indisponível,
query inválida, nunca escreve); agregação (dedup documentação+ADR, biblioteca+arquivo pelo
caminho canônico, título igual não funde, duplicata do mesmo discoverer, ordenação, nomes
únicos); composição (end-to-end, determinismo, CWD, desabilitado, escape, memória
habilitada/indisponível/fora do ar); config (defaults, caminhos inseguros, opções futuras
rejeitadas, normalização); doctor (PASS com ausentes, FAIL em escape, pulado se
desabilitado, nunca faz walk); CLI (JSON, desabilitado, memória sem chave, request
inválida); guards AST; subprocess de CWD alheio.

## Riscos

- **Recall de hints léxicos**: requisições que descrevem código sem nomear arquivos não
  geram candidatos `source` (esperado; recall semântico não é deste escopo).
- **Volume de documentação**: todo arquivo sob `documentation_paths` vira candidato; em
  projetos com muita doc, a lista cresce (filtrar é V1.2/V1.3).
- **Excerpt de memória** é conteúdo (pequeno) no candidato; memória continua marcada
  `source_of_truth: false`.
- **Heurística de nomes de secret** reduz, mas não elimina, o risco de referenciar um
  arquivo sensível com nome incomum (não há leitura de conteúdo em discovery).

## Melhorias futuras

- V1.2: classificar `ContextDiscoveryResult` (determinístico → Jev → LLM).
- `get(id)` no `MemoryProvider` para dispensar o excerpt.
- Hints por símbolo/módulo via índice de código (quando existir consumidor).
- Discoverers de Git (V7), runs/releases/findings (V8+) e task/sprint contracts (V6/V13).
- Cache de walks entre requisições se o custo aparecer.

## Dívidas

Listadas em `docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md` §23 ("Identificadas no V1.1").
Nenhuma impede o critério de saída.

Próxima versão: **V1.2 — Context Classification** (não iniciada).
