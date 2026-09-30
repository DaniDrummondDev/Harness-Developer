# Sprint V1.2 — Context Classification

**Status: V1.2 — Context Classification COMPLETE** (cada candidato descoberto recebe
exatamente uma classe — REQUIRED / HIGH_VALUE / OPTIONAL / EXCLUDED — com `selected_by`,
evidência estruturada e motivo; determinístico quando há evidência objetiva, Jev quando
habilitado, fallback conservador caso contrário; tipado, auditável, offline com fakes,
independente do CWD, sem budget e sem seleção de prompt).

## Objetivo

```text
EngineeringRequest
        ↓
Context Candidate Discovery (V1.1)
        ↓
Context Classification (V1.2)
   deterministic rules → Jev (DecisionService) → conservative fallback
        ↓
ContextClassificationResult: REQUIRED · HIGH_VALUE · OPTIONAL · EXCLUDED
```

Responde "qual a importância contextual deste candidato para esta requisição?". Não
responde quanto cabe nem o que entra no prompt (V1.3 — Context Budget e seguintes).

## Baseline

| Item | Valor |
|---|---|
| Branch / HEAD | `main` / `9b062cd` ("Add unit tests for context discovery and project file access", V1.1) |
| Working tree | limpa |
| Package | `1.1.0` → `1.2.0` |
| pytest | 736 passed, 6 skipped (Mem0/Jev live opt-in) |
| ruff / mypy | limpo / limpo (40 arquivos) |
| doctor | PASS (10 pass) |
| Decisão | `DecisionService` (V0.4) com threshold `minimum_confidence` 0.70, `DecisionKind.CONTEXT_RELEVANCE`, fallback sinalizado; Jev **desabilitado** no `providers.yaml` padrão; `DecisionProvider` responde uma pergunta por chamada (sem batch) |
| LLM | nenhum runtime real (OpenAI/Anthropic/NVIDIA são V2.x) |

Guards anteriores ajustados conscientemente:

- `test_context_discovery::test_context_does_not_know_...`: `context/` continuava proibido
  de importar `decisions`/`providers`. Agora **apenas** `classification/probabilistic.py`
  pode importar os *contratos* `decisions.models` e `providers.base` (nunca adapter,
  service, registry ou rede) — o guard verifica exatamente isso;
- `test_library_isolation`: `classification/deterministic.py` lê o enum `Authority`;
- `test_doctor::test_valid_environment_passes`: novo check `classification`.

### Auditoria da dívida do V1.1 (metadata no dedup)

`_merge` mantinha só a metadata do kind vencedor. Evidência relevante para classificar:

| Evidência | Onde vivia | Perdida antes? |
|---|---|---|
| referência explícita na requisição | proveniência `repository_hints` | não (proveniência era preservada), mas só como texto livre em `reason` |
| status de ADR | metadata do kind `adr` (vencedor sobre `doc`) | não na prática; sim se um kind de menor prioridade a tivesse |
| authority/applies da biblioteca | metadata do kind da biblioteca (sempre vencedor) | não |
| chaves só do perdedor (ex.: `size_bytes` de um hint sobre arquivo da biblioteca) | metadata do perdedor | **sim** |

Correções: (1) merge une as metadatas; em conflito mantém o valor do kind vencedor e
registra o descartado em `metadata["merge_conflicts"]` (nunca silencioso); (2)
`Provenance.match` (`path` | `file_name` | `ambiguous_file_name` | `directory`) torna a
referência explícita estruturada, sem parsear texto. Testes de regressão em
`test_context_discovery.py` e `test_context_classification.py`.

## Arquitetura

```text
cli.py  context classify ─┐                    doctor.py  check "classification" (estrutural)
  _discover (= discover)  │
  open_decisions (opcional; falha → motivo)
                          ↓
  context/classification/classifier.py   build_classifier · ContextClassifier
          │ 1. deterministic.py           DEFAULT_RULES (ordenadas) · DeterministicClassifier
          │ 2. probabilistic.py           Decider (protocol) · ProbabilisticClassifier
          │                               └─ DecisionService (V0.4) → JevDecisionProvider
          │ 3. fallback                   OPTIONAL + Evidence
          ↓
  context/classification/models.py       ContextClass · SelectedBy · Evidence
                                         ContextClassification · ClassifiedContextCandidate
                                         ContextClassificationResult
```

Dependências novas: `classification → context.models, core.request, config,
library.models (Authority), memory.safety (evaluate), decisions.models, providers.base`.
Nunca `cli`, `doctor`, `decisions.service`, `providers.jev/registry/fake`, rede. Discovery
(V1.1) continua sem conhecer classificação.

### Contratos

| Contrato | Campos | Invariantes |
|---|---|---|
| `ContextClass` | REQUIRED, HIGH_VALUE, OPTIONAL, EXCLUDED | ordem = prioridade; sem outros níveis |
| `SelectedBy` | deterministic, probabilistic, fallback | — |
| `Evidence` | 12 ids de regra + `decision_provider_judgement` + 6 motivos de fallback | id de regra = valor estável |
| `ContextClassification` | `classification`, `selected_by`, `evidence`, `reason`, `also_matched`, `confidence?`, `relevance?`, `suggestion?`, `provider?`, `model?` | determinístico sem métricas; probabilístico nunca REQUIRED e com provider+confidence; fallback sempre OPTIONAL; `also_matched` só determinístico |
| `ClassifiedContextCandidate` | `candidate` (V1.1, intacto), `classification` | memória nunca REQUIRED |
| `ContextClassificationResult` | `request`, `candidates`, `counts`, `decisions`, `warnings`, `decision_provider` | counts/decisions derivados e validados; ordem (classe, kind, id) validada |

`relevance` = score da decisão ordenada (0 = EXCLUDED … 1 = HIGH_VALUE) — o campo
"relevance" do critério de saída do roadmap; para decisões determinísticas a relevância é
a própria regra (`evidence`/`reason`).

## Decisões técnicas

1. **Composição**: o candidato do V1.1 é envolvido, nunca copiado nem mutado.
2. **Determinístico primeiro, por construção**: só candidatos sem regra chegam ao
   `Decider`. "Policy REQUIRED + Jev diz OPTIONAL" é impossível (a policy nunca é enviada)
   e, além disso, o modelo rejeita REQUIRED vindo da camada probabilística.
3. **Tabela ordenada de regras, primeira vence** (não `if/elif` central, nem uma classe por
   regra): `ClassificationRule(id, classification, description, applies)`. Regras que
   também casaram ficam em `also_matched` (ex.: ADR superseded e citado → EXCLUDED por
   `superseded_adr`, com `explicit_document_reference` em `also_matched`).
3a. **Negative structural state takes precedence over explicit reference** (correção
   pré-commit do V1.2): `superseded_adr` e `generated_artifact` são avaliadas antes das
   regras de referência explícita. Uma referência explícita aumenta relevância, mas não
   ressuscita um ADR superseded/deprecated/rejected/obsolete nem transforma um lock file,
   bundle minificado ou source map em REQUIRED. A referência continua auditável em
   `also_matched`. Só `applicable_policy` vem antes (artefato de biblioteca, nunca alvo
   dessas exclusões). A versão inicial do V1.2 tinha a ordem inversa (explícito > exclusão),
   o que promovia contexto obsoleto a REQUIRED.
4. **Authority vem da metadata** do candidato (`authority`, `applies`), não do diretório.
5. **Jev só escolhe entre EXCLUDED < OPTIONAL < HIGH_VALUE** (decisão ordenada →
   `relevance`); REQUIRED exige evidência objetiva.
6. **Threshold reutilizado**: `decisions.yaml` `thresholds.minimum_confidence` (aplicado
   pelo `DecisionService`). Nenhum threshold duplicado em `context.yaml`.
7. **Fallback conservador = OPTIONAL**: não promove (nada vira HIGH_VALUE por falha), não
   descarta (nada vira EXCLUDED por falha); sempre com `Evidence` específica.
8. **Uma decisão por candidato**: o contrato `DecisionProvider` não tem batch; cada decisão
   é auditável isoladamente. `max_decisions` (50) limita custo/latência por run.
9. **Falha do provider é visível e interrompe o run**: `unavailable`/`timeout`/erro
   levantado (credencial, 422) → fallback + warning, e o provider não é chamado de novo
   no mesmo run. `invalid_response` → fallback + warning, o run continua.
10. **Input mínimo e seguro**: requisição (≤ 600 chars), kind, título, referência,
    proveniências e allowlist de metadata (`description`, `tags`, `applies`, `status`,
    `lineage`, `excerpt`). Nenhum conteúdo de arquivo. Se `memory.safety.evaluate`
    bloquearia o texto, nada é enviado (`unsafe_decision_input`).
11. **Sem fallback LLM**: não há runtime LLM real; o design aceita uma camada futura
    (V1.4/V2.x) sem mudar contratos. Nada foi simulado.
12. **Doctor estrutural**: informa a estratégia; nunca classifica nem chama o provider.
13. **CLI fina**: `context classify` = discover + classify, JSON, exit 0 (camada de decisão
    indisponível é warning).

## Estrutura de pastas

```text
engineering/orchestrator/context/models.py            # + ReferenceMatch, Provenance.match, MERGE_CONFLICTS_KEY
engineering/orchestrator/context/discoverers.py       # repository_hints registra match
engineering/orchestrator/context/discovery.py         # merge preserva metadata
engineering/orchestrator/context/classification/
    __init__.py · models.py · deterministic.py · probabilistic.py · classifier.py
engineering/orchestrator/config.py                    # ClassificationSection
engineering/orchestrator/cli.py                       # context classify
engineering/orchestrator/doctor.py                    # check_classification
engineering/config/context.yaml                       # classification: probabilistic, max_decisions
engineering/tests/classification_helpers.py           # builders + ScriptedDecisionProvider
engineering/tests/unit/test_context_classification_models.py
engineering/tests/unit/test_context_classification_rules.py
engineering/tests/unit/test_context_classification.py
```

## Fluxos principais

### Regras determinísticas implementadas (ordem = precedência)

```text
#  rule / evidence              class       condição (sobre o modelo do V1.1)
1  applicable_policy            REQUIRED    metadata authority == mandatory
2  superseded_adr               EXCLUDED    kind adr + status superseded|deprecated|rejected|obsolete
3  generated_artifact           EXCLUDED    arquivo de projeto: lock file, .min.js/.css, .map
4  explicit_source_reference    REQUIRED    kind source + proveniência match path|file_name
5  explicit_document_reference  REQUIRED    kind instructions|adr|doc + match path|file_name
6  explicit_library_reference   REQUIRED    kind de biblioteca + match path|file_name
7  project_instruction          REQUIRED    kind instructions (discovery.instruction_files)
8  applicable_guideline         HIGH_VALUE  kind guideline + authority recommended
9  applicable_library_rule      HIGH_VALUE  kind rule + authority recommended
10 matching_stack               HIGH_VALUE  authority knowledge + applies stack:*
11 matching_capability          HIGH_VALUE  authority knowledge + applies capability:*
12 named_directory_entry        HIGH_VALUE  proveniência match directory
-- sem regra → Jev (se habilitado) → senão fallback OPTIONAL
```

Precedência: estado estrutural negativo (2–3) > referência explícita (4–6). Portanto
`ADR superseded + citado → EXCLUDED` e `artefato gerado + citado → EXCLUDED`; arquivo
normal ou ADR ativo citado → REQUIRED.

Por que `project_instruction` é REQUIRED: o kind só existe para arquivos que o usuário
declarou em `discovery.instruction_files`; não é inferido pelo nome `CLAUDE.md`.

Deliberadamente **não** determinístico: documentação só por estar em `docs/`, ADR aceito
ou proposto não citado, skill/specialty `always`, memória, nome de arquivo ambíguo.

### Quando Jev é chamado

Somente para candidatos sem regra, e somente se `context.classification.probabilistic`
(padrão `true`) **e** `open_decisions(config)` funcionar (modelo configurado, provider
`enabled: true`, `$JEV_API_KEY` presente). No shipped config Jev está desabilitado: o
motivo aparece em `warnings` e os candidatos sem regra vão para o fallback.

### Fallback

| Situação | Classe | `evidence` | Warning |
|---|---|---|---|
| sem camada de decisão (desabilitada/indisponível) | OPTIONAL | `no_decision_layer` | 1 por run, com o motivo |
| `max_decisions` atingido | OPTIONAL | `decision_limit_reached` | 1 por run |
| input com aparência de segredo | OPTIONAL | `unsafe_decision_input` | por candidato (regras, nunca o texto) |
| confiança < `minimum_confidence` | OPTIONAL (+ `suggestion`, `confidence`) | `decision_low_confidence` | não (resultado esperado) |
| resposta inválida / choice fora das opções | OPTIONAL | `decision_invalid_response` | por candidato |
| unavailable / timeout / erro levantado | OPTIONAL; provider parado no run | `decision_unavailable` | sim + contagem dos não enviados |

### Exemplo real — este repositório (Jev desabilitado)

`harness --root engineering context classify "Implement V1.2 classification in
engineering/orchestrator/context/ following docs/AI-Engineering-Harness-Roadmap.md and fix
cli.py" --intent implement`, executado a partir de `/tmp`:

```text
counts    REQUIRED 8 · HIGH_VALUE 14 · OPTIONAL 19 · EXCLUDED 0
decisions deterministic 22 · probabilistic 0 · fallback 19

REQUIRED   applicable_policy            policy/{breaking-changes,deploy,git,secrets,security}
REQUIRED   project_instruction          instructions/CLAUDE.md
REQUIRED   explicit_document_reference  doc/docs/AI-Engineering-Harness-Roadmap.md
REQUIRED   explicit_source_reference    source/engineering/orchestrator/cli.py
HIGH_VALUE applicable_guideline         guideline/{architecture,coding,documentation,review,testing}
HIGH_VALUE applicable_library_rule      rule/{avoid-unnecessary-abstractions,validation-at-boundaries}
HIGH_VALUE matching_stack               skill/python, specialty/python
HIGH_VALUE named_directory_entry        source/engineering/orchestrator/context/{__init__,discoverers,discovery,files,models}.py
OPTIONAL   no_decision_layer            skill/{security,testing}, specialty/{architecture,security,testing},
                                        14 docs (README, docs/01..03, sprints...)
warnings: adrs: 'docs/adr' does not exist · memory: disabled ·
          classification: 19 candidate(s) ... fallback (OPTIONAL): decision layer unavailable:
          model 'decision' uses provider 'jev', which is disabled in providers.yaml
```

O repositório não tem ADRs nem lock files, por isso EXCLUDED = 0 aqui.

### Exemplo com as quatro classes (teste `test_end_to_end_all_four_classes`)

Projeto temporário (AGENTS.md, docs/overview.md, ADR-0001 superseded, ADR-0002 accepted,
`src/billing/{invoice.py,tax.py,uv.lock}`; biblioteca com policy, guideline, skill python e
skill `always`), requisição `fix rounding in src/billing/ per docs/adr/0001-cents.md`,
Jev substituído por `ScriptedDecisionProvider` atrás do `DecisionService` real:

```text
REQUIRED   policy/secrets                    applicable_policy            deterministic
REQUIRED   instructions/AGENTS.md            project_instruction          deterministic
HIGH_VALUE guideline/testing                 applicable_guideline         deterministic
HIGH_VALUE skill/python                      matching_stack               deterministic
HIGH_VALUE source/src/billing/invoice.py     named_directory_entry        deterministic
HIGH_VALUE source/src/billing/tax.py         named_directory_entry        deterministic
HIGH_VALUE adr/docs/adr/0002-banker.md       decision_provider_judgement  probabilistic (0.88)
OPTIONAL   skill/debugging                   decision_provider_judgement  probabilistic (0.75)
EXCLUDED   adr/docs/adr/0001-cents.md        superseded_adr               deterministic (also_matched: explicit_document_reference)
EXCLUDED   doc/docs/overview.md              decision_provider_judgement  probabilistic (0.80)
EXCLUDED   source/src/billing/uv.lock        generated_artifact           deterministic
```

counts: REQUIRED 2 · HIGH_VALUE 5 · OPTIONAL 1 · EXCLUDED 3. 8 determinísticas,
3 probabilísticas (fake), 0 fallback; threshold 0.70. O ADR-0001 é citado na requisição,
mas superseded: fica EXCLUDED e a citação aparece em `also_matched`.

### Debug

- `harness context classify "..." | jq '.candidates[] | [.classification.classification,
  .classification.evidence, .candidate.id]'` mostra por que cada item recebeu sua classe.
- `harness doctor` (check `classification`) mostra qual estratégia será usada.
- `--log-level INFO` imprime a telemetria de cada decisão Jev (sem subject/pergunta).
- Regra inesperada: veja `also_matched` e a ordem em `DEFAULT_RULES`.

## Testes

+111 testes (736 → 847; 6 skipped live opt-in). Todos offline (fakes, `JevEmulator`).

- **models** (`test_context_classification_models.py`): quatro classes exatas, vocabulário
  `selected_by`, invariantes (determinístico sem métricas, probabilístico nunca REQUIRED,
  fallback sempre OPTIONAL, memória nunca REQUIRED, `also_matched`), confidence 0..1,
  ordenação/contagens, rejeição de counts/ordem inconsistentes, round-trip JSON, estabilidade.
- **rules** (`test_context_classification_rules.py`): cada regra positiva/negativa,
  precedência (superseded/deprecated/rejected/obsolete e artefatos gerados citados
  explicitamente continuam EXCLUDED com a referência em `also_matched`; arquivo normal e ADR
  ativo citados continuam REQUIRED; ordem da tabela verificada), authority lida da metadata, memória nunca
  REQUIRED mesmo com metadata enganosa, fonte desconhecida não quebra, tabela única, e a
  Global Library real para um projeto Python.
- **classificação** (`test_context_classification.py`): Jev fake HIGH_VALUE/OPTIONAL/
  EXCLUDED com confidence/relevance/provider; request mínimo (sem REQUIRED, ordenado,
  sem score do backend, truncado); low confidence; choice inválida; Decider "rogue" que
  diz REQUIRED; unavailable/timeout/erro de credencial (1 chamada, warnings);
  `max_decisions`; input sensível não enviado; precedência (determinísticos nunca enviados;
  memória não supera policy); agregação mista, candidatos intactos, EXCLUDED visível,
  execuções idênticas; config (shipped, defaults, extras rejeitados); `build_classifier`;
  end-to-end com as quatro classes; **regressão do dedup** (ADR por 3 discoverers mantém
  status e referência explícita); CWD estrangeiro; CLI offline, CLI com Jev emulado,
  erros da CLI; doctor (desabilitado, `probabilistic: false`, sem modelo → WARN, habilitado
  sem abrir a camada de decisão).
- **V1.1 ajustados**: `match` nos hints; merge de metadata e conflito registrado.

Gates finais: pytest 847 passed / 6 skipped; ruff limpo; mypy strict limpo (45 arquivos);
doctor PASS (11 pass).

## Riscos

- **Sem Jev, a classificação é pouco seletiva**: tudo sem regra vira OPTIONAL (no
  exemplo real, 19 de 41). Correto e conservador, mas o V1.3 receberá muitos OPTIONAL.
- **Custo/latência com Jev**: até `max_decisions` chamadas sequenciais por run.
- **Heurísticas determinísticas**: lista fixa de artefatos gerados; status de ADR por
  prefixo; `named_directory_entry` assume que o diretório citado é relevante.
- **Threshold não calibrado** e compartilhado com as demais decisões.
- **Onde pode quebrar**: mudança no formato de `applies`/`authority` da biblioteca (as
  regras leem essas chaves); um novo `CandidateKind` cai no Jev/fallback até ganhar regra.

## Melhorias futuras

- Threshold específico de classificação, somente se a calibração (V5.2) mostrar necessidade.
- Batch de decisões se o contrato `DecisionProvider` ganhar suporte.
- Escalation para LLM de raciocínio quando houver runtime (V1.4 / V2.x).
- Regras de ADR por escopo/módulo quando ADRs tiverem metadata de escopo.

## Dívidas

- fallback via reasoning LLM (roadmap) não implementado: não existe runtime LLM real;
- uma chamada Jev por candidato (sem batch no contrato);
- lista de artefatos gerados fixa no código;
- `minimum_confidence` compartilhado e não calibrado.

## Critério de saída

Cada item possui `source` (`candidate.reference` + `provenance`), `type`
(`candidate.kind`), `classification`, `relevance` (score Jev quando probabilístico; regra
quando determinístico), `reason` + `evidence` estruturada e `selected_by`. Tipado,
determinístico quando possível, Jev quando necessário, provider-agnostic (`Decider`),
auditável, seguro, offline, independente do CWD, sem budget e sem seleção final.

**V1.2 COMPLETE.** Próxima etapa: **V1.3 — Context Budget** (não iniciada).
