# Sprint V1.3 — Context Budget

**Status: V1.3 — Context Budget COMPLETE** (dado o contexto descoberto e classificado,
seleção determinística de itens inteiros num orçamento em caracteres — total, reserve,
limites por categoria, `max_files`/`max_adrs`/`max_memories` — respeitando
REQUIRED > HIGH_VALUE > OPTIONAL > EXCLUDED; REQUIRED nunca removido, overflow explícito;
motivo estruturado de entrada/saída para cada candidato; materialização lazy e segura;
offline, provider-neutral, independente do CWD, sem Jev, sem LLM, sem renderização de prompt).

## Objetivo

```text
EngineeringRequest
        ↓
Context Candidate Discovery (V1.1)
        ↓
Context Classification (V1.2)
        ↓
Context Budget (V1.3)
   REQUIRED (sempre) → HIGH_VALUE → OPTIONAL (first fit, itens inteiros) · EXCLUDED nunca
        ↓
ContextBudgetResult: selected · not_selected · excluded · usage · status
```

Responde "dado o contexto já classificado, o que cabe no orçamento e o que fica de fora —
e por quê?". Não responde "uma LLM deve redesenhar o plano de contexto?" (V1.4) nem mede
precisão/recall (V1.5).

## Baseline

| Item | Valor |
|---|---|
| Branch / HEAD | `main` / `323cbe2` ("fix(context): correct V1.2 classification precedence") |
| Working tree | limpa |
| Package | `1.2.0` → `1.3.0` |
| pytest | 847 passed, 6 skipped (Mem0/Jev live opt-in) |
| ruff / mypy | limpo / limpo (45 arquivos) |
| doctor | PASS (11 pass) |
| Contrato de entrada | `ContextClassificationResult` (V1.2): candidatos por referência (`CandidateReference` store+path), memória com excerpt ≤ 280 chars, biblioteca já carregada em memória (`Artifact.body`) |

Medição real antes do design (este repositório, requisição de exemplo abaixo): REQUIRED
≈ 48,5k caracteres, HIGH_VALUE ≈ 47k, OPTIONAL ≈ 242k (quase tudo documentação). Os
defaults foram escolhidos a partir desses números.

Guards anteriores ajustados conscientemente:

- `test_library_isolation::test_only_interfaces_and_context_discovery_consume_the_library`:
  `context/budget/content.py` (corpo do artefato via `GlobalLibrary.get`) e
  `context/budget/budgeter.py` (composição) passam a consumir a biblioteca;
- `test_doctor::test_valid_environment_passes`: novo check `budget`;
- novo guard `test_earlier_context_stages_never_import_later_ones` (discovery ↛
  classification/budget; classification ↛ budget).

## Arquitetura

```text
cli.py  context budget ─┐                          doctor.py  check "budget" (estrutural)
  _discover → _classify  │ (biblioteca carregada uma vez e compartilhada)
                         ↓
  context/budget/budgeter.py   build_budgeter(config, library) · ContextBudgeter · priority_key
          │ ContentLoader (protocol)
          ↓
  context/budget/content.py    ContextContentLoader
          │ project → ProjectFiles.check_file (V1.1) + leitura limitada + binário/UTF-8
          │ library → GlobalLibrary.get(type, id).body (sem reparse)
          │ memory  → metadata["excerpt"]
          ↓
  context/budget/models.py     BudgetCategory · BudgetStatus · BudgetReason · BudgetedItem
                               LimitConflict · BudgetUsage · ContextBudgetResult
config.py                      CategoryLimits · BudgetSection (ContextSection.budget)
```

Dependências novas: `budget → config, context.models, context.files, context.discovery
(project_files), classification.models, library, core`. Nunca `cli`, `doctor`,
`providers`, `decisions`, serviço/adapters de memória, rede ou subprocessos (guard). V1.1 e
V1.2 não conhecem o budget.

### Contratos

| Contrato | Campos | Invariantes |
|---|---|---|
| `BudgetSection` (config) | `unit` (`characters`), `truncation` (`whole_item`), `total`, `reserve`, `categories`, `max_files`, `max_adrs`, `max_memories`; `usable` | `total ≥ 1`; `0 ≤ reserve < total`; limites `≥ 0`; extras rejeitados |
| `CategoryLimits` (config) | `library`, `instructions`, `adrs`, `documentation`, `source_code`, `memory` (caracteres ou `None`) | `≥ 0`; categoria desconhecida rejeitada; campos == `BudgetCategory` (teste) |
| `BudgetStatus` | `SUCCESS`, `REQUIRED_OVERFLOW`, `REQUIRED_UNAVAILABLE` | derivado e validado |
| `BudgetReason` | 11 motivos (tabela abaixo) | por lista: selected / not_selected / excluded |
| `BudgetedItem` | `classified` (V1.2, intacto), `category`, `reason`, `size`, `included_size`, `detail`, `content` | REQUIRED só `required` ou `content_unavailable`; EXCLUDED ⇔ `excluded_by_classification`; selecionado ⇒ conteúdo e `len(content) == size == included_size`; não selecionado ⇒ sem conteúdo; `detail` ⇔ `content_unavailable`; categoria == kind |
| `LimitConflict` | `limit` (`category`/`max_files`/`max_adrs`/`max_memories`), `category?`, `configured`, `required` | `required > configured`; categoria ⇔ `limit == category` |
| `BudgetUsage` | `total`, `reserve`, `usable`, `used`, `remaining`, `overflow`, `by_category`, `files`, `adrs`, `memories` | derivado dos selecionados e validado |
| `ContextBudgetResult` | `request`, `status`, `limits`, `usage`, `selected`, `not_selected`, `excluded`, `conflicts`, `warnings` | cada candidato em exatamente uma lista, com motivo da lista; usage e status coerentes |

## Decisões técnicas

1. **Unidade: caracteres** = code points Unicode do texto carregado (`len`). Exata,
   determinística e sem tokenizer (nenhum acoplamento a OpenAI/Anthropic/NVIDIA/Jev).
   `stat().st_size` (bytes) nunca é usado como medida — só como limite de segurança
   (`max_file_bytes`, o mesmo do discovery). Alternativa rejeitada: tokens estimados
   (falsa precisão; dependeria de um tokenizer de vendor ou de uma heurística).
2. **Reserve único**: `usable = total − reserve`. Não modela cada parte futura do prompt.
3. **Defaults conservadores**: `total 100000`, `reserve 20000` (20%) → `usable 80000`
   (≈ 20k tokens pela regra de bolso de ~4 chars/token — só documentação, nunca calculado):
   bem abaixo de qualquer janela atual, de propósito (critério "sem depender do limite
   máximo do modelo"). Categorias: `library 20000` (todos os artefatos aplicáveis deste
   repositório ≈ 15k), `adrs 15000`, `documentation 25000` (docs são os maiores e quase
   sempre OPTIONAL: evita que inundem o orçamento), `source_code 40000`, `memory 2000`
   (5 excerpts × 280 = 1400), `instructions` sem limite (sempre REQUIRED hoje).
   `max_files 20`, `max_adrs 5`, `max_memories 5` (= `memory_results`).
4. **Classificação é a autoridade**: a prioridade é a classe. Dentro da classe, só sinais
   já produzidos pelo V1.2: determinístico < probabilístico (confidence ↓) < fallback, depois
   kind (autoridade da biblioteca primeiro … memória por último), depois id. Confidence nunca
   cruza classes (HIGH_VALUE 0.99 vem depois de todo REQUIRED). Confidence de um fallback
   (sugestão de baixa confiança não aceita) não é usada.
5. **Itens inteiros, first fit** (`truncation: whole_item`): nunca corta código/documentação;
   um item que não cabe é pulado e a varredura continua (um item menor posterior pode entrar).
   Alternativa rejeitada: truncation por prefixo (destrói semântica; exigiria política por tipo).
6. **REQUIRED nunca é removido**. REQUIRED acima do usable → `REQUIRED_OVERFLOW` (todos
   mantidos em `selected`, nada mais é considerado); REQUIRED sem conteúdo carregável →
   `REQUIRED_UNAVAILABLE`; REQUIRED acima de um limite de categoria ou `max_*` → mantido e
   registrado em `conflicts` (+ warning). Precedência: segurança da classificação >
   conveniência do orçamento. As invariantes estão no **modelo**, não só no motor.
7. **REQUIRED conta no uso**: consome o total, a categoria e os contadores, deixando menos
   espaço para o resto (ex.: 12 arquivos REQUIRED com `max_files 10` → todos entram, conflito
   registrado, nenhum HIGH_VALUE de arquivo entra).
8. **Categorias = famílias reais de fonte** (6), uma por grupo de `CandidateKind`. A
   biblioteca é um único bucket: autoridade (policy vs skill) já está na classe.
9. **`max_files` conta arquivos do projeto** (instructions, ADRs, docs, source); artefatos da
   biblioteca são limitados pela categoria `library`. `max_adrs` é verificado antes de
   `max_files` (motivo mais específico).
10. **Materialização lazy e segura** (`ContextContentLoader`): só itens ainda elegíveis são
    lidos (EXCLUDED, overflow e limites de contagem nunca carregam). Arquivos do projeto
    reutilizam `ProjectFiles.check_file` (mesmas regras do discovery), leitura limitada a
    `max_file_bytes + 1` (arquivo que cresceu é rejeitado), NUL → binário, UTF-8 estrito,
    BOM removido. Biblioteca: corpo já carregado e validado (sem segundo parser; referência
    tem de bater com `artifact.source`). Memória: excerpt (sem alterar `MemoryProvider`).
11. **Decisão de budget é outra camada**: `BudgetedItem` envolve o
    `ClassifiedContextCandidate`; o motivo da classificação nunca é sobrescrito.
12. **CLI fina**: `context budget` = discover + classify + budget; JSON sem o texto dos itens
    por padrão (`--content` inclui); exit 0 em SUCCESS, **3** em REQUIRED_OVERFLOW /
    REQUIRED_UNAVAILABLE (mesmo significado do exit 3 de `decision`: resultado que exige
    escalation), 1 em erro do Harness.
13. **Doctor estrutural**: relata o orçamento; WARN se um limite de categoria ≥ usable
    (nunca restringe); nunca carrega conteúdo, seleciona ou chama provider.
14. **Sem `budget.enabled`**: `context.enabled` já controla o pipeline e o comando é
    explícito; uma flag sem consumidor seria configuração morta.

## Estrutura de pastas

```text
engineering/orchestrator/context/budget/
    __init__.py · models.py · content.py · budgeter.py
engineering/orchestrator/config.py             # CategoryLimits, BudgetSection
engineering/orchestrator/cli.py                # context budget; _discover/_classify compartilhados
engineering/orchestrator/doctor.py             # check_budget
engineering/config/context.yaml                # seção budget
engineering/tests/budget_helpers.py            # builders, FakeLoader
engineering/tests/unit/test_context_budget.py            # política de seleção
engineering/tests/unit/test_context_budget_models.py     # contratos, config, doctor
engineering/tests/unit/test_context_budget_content.py    # materialização e segurança
engineering/tests/integration/test_context_budget_pipeline.py  # ponta a ponta + CLI
```

## Fluxos principais

### Política final implementada

```text
REQUIRED    → sempre selecionado (reason required), conteúdo carregado; nunca limitado por
              categoria/max_*; soma > usable → REQUIRED_OVERFLOW; sem conteúdo →
              not_selected content_unavailable → REQUIRED_UNAVAILABLE
HIGH_VALUE  → depois de todo REQUIRED; em ordem de prioridade, item inteiro, first fit;
              within_budget ou motivo estruturado de saída
OPTIONAL    → depois de todo HIGH_VALUE; mesma regra (fallback OPTIONAL tratado como
              qualquer OPTIONAL, nunca promovido)
EXCLUDED    → nunca carregado, nunca selecionado; mantido em `excluded` para auditoria
```

### Motivos estruturados

| Lista | `reason` | Quando |
|---|---|---|
| selected | `required` | classe REQUIRED com conteúdo |
| selected | `within_budget` | HIGH_VALUE/OPTIONAL que cabe em todos os limites |
| not_selected | `content_unavailable` (+ `detail`) | inexistente, binário, não UTF-8, nome de secret, diretório excluído, fora do projeto, grande demais |
| not_selected | `required_overflow` | não considerado: REQUIRED já excede o usable |
| not_selected | `max_adrs_reached` / `max_files_reached` / `max_memories_reached` | limite de contagem atingido (verificado antes de carregar) |
| not_selected | `item_too_large` | maior que o usable ou que o limite da sua categoria |
| not_selected | `total_budget_exhausted` | não cabe no restante do usable |
| not_selected | `category_budget_exhausted` | não cabe no restante da categoria |
| excluded | `excluded_by_classification` | classe EXCLUDED |

### REQUIRED > usable

`usable = 20000`, REQUIRED somando `27000`: todos os REQUIRED ficam em `selected` (nenhum
truncado ou removido), `usage.used = 27000`, `usage.overflow = 7000`, `usage.remaining = 0`,
`status = REQUIRED_OVERFLOW`; todo HIGH_VALUE/OPTIONAL vai para `not_selected` com
`required_overflow` sem ser carregado; warning `budget: REQUIRED context (27000 characters)
exceeds the usable budget (20000) by 7000; ...`; a CLI imprime o JSON e sai com 3. O mesmo
vale para um único REQUIRED maior que o usable. O resultado **não** é um pacote de contexto
válido: o chamador deve escalar (V1.4 / humano — não implementado aqui).

### Exemplo real — este repositório (Jev desabilitado)

`harness --root engineering context budget "Implement V1.3 budget in
engineering/orchestrator/context/ following docs/AI-Engineering-Harness-Roadmap.md and fix
cli.py" --intent implement`, executado a partir de `/tmp`, config padrão:

```text
status SUCCESS · total 100000 − reserve 20000 = usable 80000 · used 79883 · remaining 117
by_category library 15516 · instructions 3705 · documentation 22420 · source_code 38242
selected 26 · not_selected 16 · excluded 0 · conflicts 0

selected     REQUIRED   required   policy/{breaking-changes,deploy,git,secrets,security},
                                   instructions/CLAUDE.md (3705),
                                   doc/docs/AI-Engineering-Harness-Roadmap.md (17001),
                                   source/engineering/orchestrator/cli.py (24120)
selected     HIGH_VALUE within     5 guidelines, 2 rules, skill/python, specialty/python,
                                   context/__init__.py (626), discovery.py (8595), models.py (4901)
selected     OPTIONAL   within     skill/{security,testing}, specialty/{architecture,security,
                                   testing}, doc/README.md (5419)
not_selected HIGH_VALUE category_budget_exhausted  discoverers.py (17217), files.py (7003)
not_selected OPTIONAL   item_too_large             docs/03 (43256), engineering/README.md (26250),
                                                   engineering/docs/architecture.md (36512)
not_selected OPTIONAL   total_budget_exhausted     docs/01, docs/02, docs/README.md (493),
                                                   8 sprint docs
```

`source_code` tem limite 40000: `cli.py` REQUIRED (24120) já ocupa a maior parte, então
`discoverers.py` e `files.py` ficam de fora por categoria, enquanto `discovery.py` e
`models.py` entram. Os documentos grandes (> limite de 25000 da documentação) são
`item_too_large`. O repositório não tem ADRs nem lock files, por isso EXCLUDED = 0.

### Exemplo com todas as classes (teste `test_mixed_scenario_...`)

Projeto temporário com tamanhos exatos; `total 1160 − reserve 200 = usable 960`; memória
fake habilitada; sem camada de decisão (não resolvidos → OPTIONAL fallback). Requisição
`fix rounding in src/billing/invoice.py for the whole src/billing/ package; see
docs/adr/0001-cents.md`:

```text
selected     REQUIRED   required                 policy/secrets 100 · policy/security 100 ·
                                                 instructions/AGENTS.md 200 ·
                                                 source/src/billing/invoice.py 300
selected     HIGH_VALUE within_budget            guideline/testing 100 · source/.../rates.py 150
not_selected HIGH_VALUE total_budget_exhausted   source/.../tax.py 400
not_selected OPTIONAL   total_budget_exhausted   doc/docs/overview.md 300 · memory/fake-000001 29
excluded     EXCLUDED   excluded_by_classification  adr/docs/adr/0001-cents.md (superseded_adr),
                                                    source/src/billing/uv.lock (generated_artifact)
usage: used 950 · remaining 10 · files 3 · status SUCCESS
```

### Debug

- `harness context budget "..." | jq '[.selected[], .not_selected[], .excluded[]] | .[] |
  [.classified.classification.classification, .reason, .size, .classified.candidate.id]'`
  responde "entrou ou não, e por quê" para cada candidato.
- `.usage` e `.conflicts` explicam os totais; `.warnings` traz discovery, classification e
  `budget:`.
- `harness doctor` (check `budget`) mostra o orçamento em vigor.
- Um item "inesperadamente fora": veja `reason`; `size` é `null` quando nunca foi carregado
  (excluded, overflow, limite de contagem, conteúdo indisponível).

### Como manter / onde modificar

- Valores: `config/context.yaml` `budget`. Novo limite: `BudgetSection`/`CategoryLimits`
  (`config.py`) + verificação em `ContextBudgeter._consider` + um `BudgetReason`.
- Nova categoria: `BudgetCategory` + `CATEGORY_BY_KIND` + campo em `CategoryLimits`.
- Novo store de candidato: um ramo em `ContextContentLoader.load`.
- Ordem dentro de uma classe: `priority_key`.
- Truncation futura: novo valor em `BudgetSection.truncation` + relaxar a invariante
  `included_size == size` de `BudgetedItem` só para esse modo.

## Testes

+109 testes (847 → 956; 6 skipped live opt-in). Todos offline.

- **política** (`test_context_budget.py`, 33): REQUIRED cabe / exatamente o orçamento /
  overflow total / um único REQUIRED > usable (sem truncation) / não limitado por
  `max_files`, categoria, `max_adrs` (conflitos) / policies e instruction preservadas /
  REQUIRED sem conteúdo → REQUIRED_UNAVAILABLE (precede overflow); HIGH_VALUE antes de
  OPTIONAL independentemente de kind/id; ordem determinística; item grande não bloqueia os
  seguintes; `item_too_large`; OPTIONAL só com sobra; fallback tratado como OPTIONAL e não
  promovido; EXCLUDED nunca carregado e auditável; reserve; categoria; REQUIRED conta na
  categoria; `max_files` (não conta biblioteca, verificado antes de carregar); `max_adrs`
  antes de `max_files`; `max_memories`; limites zero; memória não desaloja REQUIRED;
  conteúdo indisponível OPTIONAL não interrompe; determinístico → probabilístico por
  confidence → id; confidence não cruza classes; probabilístico antes de fallback;
  resultado idêntico com entrada em outra ordem; cada candidato uma vez com os dois motivos.
- **contratos/config/doctor** (`test_context_budget_models.py`, 43): vocabulário exato,
  categorias == config, sem novas classes; invariantes de `BudgetedItem`/`LimitConflict`;
  usage derivado; round-trip JSON; resultados inconsistentes rejeitados; imutabilidade;
  config padrão, defaults, 13 configs inválidas (total 0, reserve negativa/igual/maior,
  categoria negativa/desconhecida, `max_*` negativos, `unit: tokens`, `truncation: head`,
  `enabled`, extras); limites zero válidos; doctor PASS/WARN, estrutural (nunca carrega),
  ausente com context desabilitado.
- **materialização** (`test_context_budget_content.py`, 24): arquivo normal (BOM, code
  points), inexistente, path traversal (3 formas), symlink para fora / dentro, 6 nomes de
  secret (nunca abertos), diretório excluído, binário, não UTF-8, arquivo grande (nunca
  aberto), arquivo que cresce após o check, CWD estrangeiro, corpo da biblioteca (sem front
  matter), artefato ausente, referência divergente, sem `artifact_id`, excerpt de memória.
- **ponta a ponta** (`tests/integration/test_context_budget_pipeline.py`, 8): cenário misto
  obrigatório (todas as classes, REQUIRED todos, HIGH_VALUE parcial, OPTIONAL fora,
  EXCLUDED nunca, uso exato 950/960), overflow obrigatório (nenhum REQUIRED removido, nada
  carregado além), espaço sobrando (tudo menos EXCLUDED, em ordem), determinismo + CWD
  estrangeiro; CLI SUCCESS (resumo sem conteúdo), `--content` (JSON validável), overflow
  exit 3, config inválida exit 1.
- **guard** (`test_context_discovery.py`): estágios anteriores não importam posteriores.

Gates finais: pytest 956 passed / 6 skipped; ruff limpo; mypy strict limpo (49 arquivos);
doctor PASS (12 pass).

## Riscos

- **Caracteres ≠ tokens**: a razão varia por idioma, código e tokenizer. A reserve absorve a
  diferença, mas não há garantia de encaixe numa janela específica de modelo.
- **Defaults não calibrados**: pontos de partida conservadores; a calibração depende da
  telemetria (V1.5).
- **First fit não é ótimo**: pode escolher um item menor posterior depois de pular um maior
  anterior; intencional, previsível e auditável.
- **Binário citado explicitamente** vira REQUIRED no V1.2 e, portanto, `REQUIRED_UNAVAILABLE`
  aqui: correto pela invariante, mas bloqueia o pacote até escalation.
- **Sem Jev, muitos OPTIONAL por fallback** (documentação): o orçamento os descarta por
  espaço, não por relevância.
- **Onde pode quebrar**: um novo `CandidateKind` sem entrada em `CATEGORY_BY_KIND` (teste
  cobre); um novo `ReferenceStore` sem ramo no loader (vira `content_unavailable`); mudança no
  metadata `artifact_id`/`excerpt` do discovery.

## Melhorias futuras

- Varredura de secrets no conteúdo selecionado (hoje só nomes de arquivo são bloqueados).
- Curto-circuito quando o restante é 0 (evita ler itens que certamente não cabem).
- Truncation controlada por tipo (ex.: prefixo de logs), somente com política explícita.
- Unidade em tokens via abstração provider-neutral, se a telemetria mostrar necessidade.
- Pacote de contexto renderizado (V2+) e escalation da seleção (V1.4).

## Dívidas

- defaults do budget não calibrados;
- itens ainda elegíveis são lidos para medir mesmo com o orçamento quase cheio (limitado por
  `max_file_bytes` e pelo número de candidatos);
- conteúdo selecionado não passa por varredura de secrets;
- memória entra só como excerpt (≤ 280 caracteres): `MemoryProvider` não tem get-by-id
  (dívida do V1.1, inalterada).

## Critério de saída

`EngineeringRequest → Discovery → Classification → Budget → contexto selecionado
determinístico`, respeitando REQUIRED > HIGH_VALUE > OPTIONAL > EXCLUDED, com budget total,
reserve, limites por categoria, `max_files`, `max_memories`, `max_adrs`, política explícita
de truncation (`whole_item`: skip, nunca corte), overflow explícito para REQUIRED, resultado
determinístico e auditável (motivo da classificação + motivo do budget por candidato),
materialização segura, portável (CWD), testes offline e sem depender do limite máximo do
modelo.

**V1.3 COMPLETE.** Próxima etapa: **V1.4 — LLM Context Escalation** (não iniciada).
