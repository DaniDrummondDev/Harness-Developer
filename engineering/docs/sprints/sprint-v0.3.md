# Sprint V0.3 — Memory Foundation

**Status: COMPLETE** (critério de saída comprovado contra Mem0 self-hosted real; ver "Prova de integração").

## Objetivo

Integrar Mem0 self-hosted como memória operacional de longo prazo (roadmap V0.3), com baixo
acoplamento, segurança e auditabilidade, provando `gravar → reiniciar → recuperar` sem
transformar memória em source of truth.

## Baseline

| Item | Valor |
|---|---|
| Branch / HEAD | `main` / `13de6fc` ("first commit", contém V0–V0.2) |
| Working tree | `docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md` modificado (atualização pós-V0.2 do autor, preservada) |
| Python / package | 3.12.3 / `0.2.0` |
| pytest | 235 passed |
| ruff | limpo |
| mypy (gate do projeto, `orchestrator/`) | limpo, 19 arquivos |
| `mypy .` (inclui testes) | 1 erro pré-existente em `tests/unit/test_config.py:48` (índice `str` em `dict[ExecutionMode, ...]`) — corrigido |
| Memória | `memory.yaml` só estrutural; sem `orchestrator/memory/`; nenhum código Mem0 |
| Infra | Mem0 self-hosted já em execução (`~/projects/mem0/server`, compose `mem0-dev`: API :8888, pgvector :8432, dashboard :3000; mem0ai 2.2.1) |

## Escopo

Dentro: `MemoryProvider`, modelos tipados, scopes, lineage, safe ingestion policy, adapter
Mem0 (health/add/search/update/delete), `FakeMemoryProvider`, `memory.yaml` tipado com
consumidor real, comandos `memory`, check opcional no `doctor`, contract/unit/integration
tests, documentação.

Fora: ingestão automática, retenção/relevância, uso de memória em contexto (V1.x), Jev
(V0.4), agentes (V2), state machine (V6), MCP/HTTP (V14), dashboards/infra de produção.

## Arquitetura

```text
harness memory health|add|search|update|delete         doctor (memory.enabled only)
                 └──────────────┬──────────────────────────────┘
                     open_memory(config)          memory.yaml + $MEM0_API_KEY
                                ↓
                        MemoryService(provider, project)
                          1. validação tipada         → InvalidMemoryInputError
                          2. safe ingestion (add/update) → UnsafeMemoryContentError
                                ↓
                        MemoryProvider (Protocol)
                     ┌──────────┴──────────┐
          Mem0MemoryProvider         FakeMemoryProvider (testes)
                     ↓ HTTP + X-API-Key
          Mem0 self-hosted REST → Postgres/pgvector
```

Dependências: `cli`/`doctor` → `memory.service` → (`config`, `memory.mem0`, `memory.safety`,
`memory.models`, `memory.base`) → `core.exceptions`. `core/` não importa `memory/`;
`memory/` não importa CLI, intake, `EngineeringRequest` nem `providers/`; só `service.py`
importa o adapter Mem0; só CLI e `doctor` abrem a memória (testado).

## Implementação

| Elemento | Onde | Nota |
|---|---|---|
| `MemoryProvider` | `memory/base.py` | Protocol: `backend_id`, `health`, `add`, `search`, `update`, `delete` |
| Modelos | `memory/models.py` | `ScopeKind`, `MemoryScope`, `SourceType`, `MemorySource`, `NewMemory`, `MemoryRecord`, `MemoryQuery`, `MemoryHit`, `HealthStatus`, `MemoryHealth` — frozen, `extra="forbid"` |
| Safe ingestion | `memory/safety.py` | `evaluate()` → ALLOW/BLOCK + nomes de regras; `ensure_safe()` |
| Serviço + composição | `memory/service.py` | `MemoryService`, `open_memory(config, environ)` |
| Adapter Mem0 | `memory/mem0.py` | `Mem0MemoryProvider`, `HttpTransport` (stdlib `urllib`) |
| Fake | `memory/fake.py` | determinístico, busca lexical, `unavailable=True` |
| Erros | `core/exceptions.py` | `MemoryStoreError` + 5 subclasses |
| Config | `config.py`, `config/memory.yaml` | `Mem0Section`, `MemorySection.backend: Literal["mem0"]` |
| CLI | `cli.py` | grupo `memory` |
| Doctor | `doctor.py` | `check_memory`, `memory_opener` injetável |

### Contract `MemoryProvider`

| Operação | Entrada | Saída | Regras |
|---|---|---|---|
| `health()` | — | `MemoryHealth(status, detail)` | nunca lança; `healthy` / `unavailable` / `misconfigured` |
| `add` | `NewMemory(content, scope, source)` | `MemoryRecord` | conteúdo, scope e lineage fazem round-trip |
| `search` | `MemoryQuery(scope, text, limit 1–50)` | `tuple[MemoryHit, ...]` | somente o scope exato; mais relevante primeiro |
| `update` | `memory_id`, `content` | `MemoryRecord` | muda só o conteúdo; id/scope/lineage preservados |
| `delete` | `memory_id` | — | id desconhecido, apagado ou malformado → `MemoryNotFoundError` |

Demais falhas: subclasses de `MemoryStoreError`; mensagens nunca contêm conteúdo nem credenciais.
Adapters **não** aplicam a policy: `MemoryService` aplica uma vez, antes de qualquer backend.

### Adapter Mem0

Verificado no código-fonte do servidor (`mem0/server/main.py`, commit `94c3fe9f`, mem0ai 2.2.1)
e sondado ao vivo antes da implementação.

| Harness | Mem0 REST |
|---|---|
| `health` | `GET /memories?user_id=harness-healthcheck&top_k=1` (auth + consulta ao datastore) |
| `add` | `POST /memories {messages:[{role:user,content}], user_id:<namespace>, metadata, infer:false}` + `GET /memories/{id}` |
| `search` | `POST /search {query, filters:{user_id:<namespace>}, top_k}` |
| `update` | `PUT /memories/{id} {text}` + `GET /memories/{id}` |
| `delete` | `DELETE /memories/{id}` |
| scope | `user_id = "<project>/<kind>[/<key>]"` |
| lineage | metadata `harness_schema/project/scope/scope_key/source_type/source_id` |

Tradução de erros: 401/403 → `MemoryConfigurationError` (cita `$MEM0_API_KEY`, nunca a chave);
404 em id → `MemoryNotFoundError`; 5xx/conexão/timeout → `MemoryUnavailableError` (com o
`code` sanitizado do servidor, ex. `provider_auth_failed`); outros 4xx/corpo inesperado →
`MemoryStoreError`. Ids não-UUID → `MemoryNotFoundError` sem requisição. Resultados sem
metadata Harness ou de outro scope são descartados (defesa em profundidade).

### Scopes

`project` (sem chave) e `task|run|agent|release:<chave>`; chaves `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`;
todo scope pertence ao projeto de `project.yaml`. Namespace único por scope exato; busca nunca
atravessa scopes (contract test para os 5 tipos + chave diferente + projeto diferente, e teste real).

### Safe ingestion

Veredito **ALLOW** ou **BLOCK** (sem REDACT: segredo mascarado não tem valor operacional e
máscara parcial ainda vaza estrutura). Regras: `private_key`, `authorization_header`,
`bearer_token`, `openai_style_key` (inclui `sk-ant-`, `sk-proj-`), `github_token`,
`aws_access_key`, `slack_token`, `google_api_key`, `nvidia_api_key`, `jwt`, `url_credentials`,
`env_secret_assignment` (variáveis MAIÚSCULAS), `yaml_secret_value`, `quoted_secret_literal`.
Valores placeholder (`<...>`, `${...}`, `changeme`, `***`...), referências (`os.environ[...]`)
e números puros não bloqueiam. Aplicada a conteúdo e `source.id`, antes de qualquer envio;
o erro lista regras, nunca o trecho.

### Lineage

Obrigatório em toda escrita: `MemorySource(type, id)`, tipos de RF-017 (`task_result`,
`decision`, `finding`, `remediation`, `release`, `incident`, `implementation_note`).
Não há tipo "conversa"/"livre": memória sem origem rastreável não é gravada.

## Decisões técnicas

- **Contract próprio em `memory/`**, não em `providers/`. Alternativa: `MemoryProvider` junto de
  LLM/Decision. Impacto: responsabilidades separadas; `providers/` inalterado.
- **REST do servidor self-hosted via `urllib`.** Alternativas: `mem0ai.MemoryClient` (API da
  plataforma hospedada, rotas incompatíveis); `mem0ai.Memory` in-process (traz LLM/embedder
  e credenciais para o Harness); `httpx` (nova dependência sem necessidade). Impacto: zero
  dependências novas; detalhes de Mem0 confinados a `mem0.py`.
- **Transport injetável** (`Callable[[method, path, body], (status, json)]`): o adapter real
  roda offline contra `tests/mem0_emulator.py` na mesma contract suite do fake.
- **`MemoryService` concentra policy e projeto.** Alternativa: cada adapter aplicar a policy.
  Impacto: uma única barreira, testada independentemente do backend.
- **Health consulta o datastore**, não só autenticação. Comprovou valor: o servidor respondia
  200 em rotas sem banco enquanto o vector store estava inacessível (ver findings).
- **`infer: false`**: conteúdo gravado literalmente; nenhuma LLM reescreve memórias do Harness.
- **Memória desabilitada por padrão**; `doctor` só consulta com `enabled: true`
  (unavailable = WARN, misconfigured/sem chave = FAIL).
- **Sem ingestão automática**: somente `harness memory add|update`.
- **Sem infraestrutura própria (compose) no Harness.** O servidor self-hosted oficial do Mem0 é
  construído a partir do repositório do Mem0; duplicar o compose criaria drift. Documentado
  o setup e a armadilha de senha.
- **Schema `memory.yaml` mantém `version: 1`**: extensão compatível (seção nova opcional;
  `backend` mais estrito). O arquivo distribuído continua válido e desabilitado.
- **Versão do package `0.2.0` → `0.3.0`.**

## Estrutura de pastas

```text
engineering/orchestrator/
├── core/exceptions.py      # + MemoryStoreError e subclasses
├── cli.py                  # + grupo memory
├── doctor.py               # + check_memory (opt-in)
├── config.py               # + Mem0Section, MemorySection tipada
└── memory/                 # novo
    ├── __init__.py
    ├── base.py             # MemoryProvider
    ├── models.py           # scope, lineage, records, queries, health
    ├── safety.py           # safe ingestion policy
    ├── service.py          # MemoryService, open_memory
    ├── mem0.py             # adapter Mem0 self-hosted
    └── fake.py             # FakeMemoryProvider
engineering/tests/
├── mem0_emulator.py        # emulação offline das rotas Mem0 (Transport)
├── contract/test_memory_provider_contract.py
├── integration/test_mem0_persistence.py   # opt-in, servidor real
└── unit/test_memory_{safety,service,cli_doctor,isolation}.py, test_mem0_adapter.py
```

## Fluxos principais

1. `memory add "<texto>" --scope task:T-1 --source task_result:T-1` → validação → policy →
   Mem0 → JSON do registro (id, conteúdo, scope, source, timestamps).
2. `memory search "<consulta>" --scope task:T-1` → somente memórias daquele scope.
3. Conteúdo com segredo → `error: content blocked by the safe ingestion policy (matched rules: ...)`, exit 1, nada enviado.
4. Memória desabilitada / `$MEM0_API_KEY` ausente → `MemoryConfigurationError`, exit 1, sem rede.
5. `memory health` / `doctor` → healthy (PASS) · unavailable (WARN) · misconfigured (FAIL).

## Testes

| Suite | Testes | Cobertura |
|---|---|---|
| `contract/test_memory_provider_contract.py` | 34 (17 × 2 backends) | add/search/update/delete, health, 5 scopes + isolamento, limite, id desconhecido/malformado, indisponibilidade, erros sem conteúdo — Fake e Mem0 adapter (emulado) |
| `unit/test_memory_safety.py` | 34 | 17 positivos (bloqueio), 14 negativos (texto técnico legítimo), determinismo, mensagens sem segredo |
| `unit/test_memory_service.py` | 32 | namespaces, validação de scope/source, CRUD via serviço, policy antes do provider (inclusive lineage), entradas inválidas, `open_memory` |
| `unit/test_mem0_adapter.py` | 16 | formato exato das requisições, `infer:false`, filtros, descarte de itens estranhos, tradução de 401/403/404/400/500/502, chave nunca exposta, ids não-UUID, transport HTTP real (URL inválida, conexão recusada) |
| `unit/test_memory_cli_doctor.py` | 23 | `memory.yaml` válido/inválido (backend, seção, URL, env var, `api_key` proibido, campos extras), CLI CRUD/health/erros/segredo, `doctor` skip/PASS/WARN/FAIL |
| `unit/test_memory_isolation.py` | 5 | dependências, só `service.py` conhece Mem0, só CLI/doctor abrem memória, fake fora da produção |
| `integration/test_mem0_persistence.py` | 1 (opt-in) | servidor real, 6 processos distintos |

Totais: 380 coletados; offline: **379 passed, 1 skipped** (integração real opt-in); com
`HARNESS_MEM0_INTEGRATION=1`: integração **1 passed** (9,0 s). 235 testes V0–V0.2 preservados
(1 ajuste só de tipagem em `test_config.py`). `ruff check .` limpo; `mypy` (26 arquivos) e
`mypy .` (51 arquivos) limpos.

## Prova de integração

`tests/integration/test_mem0_persistence.py` (opt-in): processo A grava, B busca (novo processo),
isolamento verificado em outro scope, C atualiza, D busca o conteúdo novo, E apaga, F confirma
remoção — cada passo é um `python -m orchestrator` separado; nada sobrevive em memória Python.

Evidência manual adicional (2026-09-29), com **reinício do container do servidor Mem0** entre escrita
e leitura:

```text
[processo A] add  → id 29a5aa0b-6897-411d-9e12-63dc53a93e17, scope run:evidence-1790722343,
                    source implementation_note:V0.3
docker restart mem0-dev-mem0-1 (22:52:27Z)
[processo B] search → mesmo id, score 0.643, conteúdo e lineage idênticos
[processo C] search em outro scope → []
[processo D] add com DB_PASSWORD=... → bloqueado (env_secret_assignment), nada enviado
[processo E] delete → {"deleted": "29a5aa0b-..."}
[processo F] search → []
```

Reprodução:

```bash
export MEM0_API_KEY=<chave m0sk_ do servidor>  HARNESS_MEM0_INTEGRATION=1
cd engineering && pytest -m mem0 -v tests/integration/test_mem0_persistence.py
```

## Critérios de saída

Gravar memória → reiniciar → recuperar, sem source of truth — **atendido** (teste real e
evidência acima). Memória não é lida por nenhum componente de decisão; a precedência oficial
não foi alterada.

## Riscos

- Policy heurística: formatos de segredo desconhecidos podem passar; texto incomum pode ser
  bloqueado (fail closed, corrigível reescrevendo).
- Scores de busca são específicos do backend (Mem0: embeddings + BM25; fake: lexical); só são
  comparáveis dentro de uma mesma lista.
- A disponibilidade depende do servidor Mem0 e do provedor de embeddings configurado **nele**
  (erros aparecem como `unavailable` com `code` do servidor).
- Mem0 2.2.1 quebra com senha Postgres contendo `/ : @ ? #` (bug upstream; documentado).
- Chamadas síncronas com timeout configurável; sem retry (V15.1).

## Melhorias futuras

- Filtro de busca por metadata (ex.: `source_type`) quando houver consumidor (Context Engine).
- Retenção/expiração (`expiration_date` do Mem0) e políticas de ingestão automática (V1.x+).
- Retry/backoff e circuit breaking no transport (V15.1).
- Regras de safe ingestion adicionais conforme novos formatos de credenciais surgirem.
- Contribuir upstream a correção do URI não escapado do pgvector no Mem0.
