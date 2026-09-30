# Sprint V1.4 — LLM Context Escalation

**Status: V1.4 — LLM Context Escalation COMPLETE** (depois do budget, gatilhos
determinísticos decidem se a seleção de contexto precisa de um modelo de raciocínio; só
então o planner — alias lógico → `ModelResolver` → `LLMProvider` — recebe metadata segura e
propõe um `ContextPlan`, validado deterministicamente antes de existir; REQUIRED nunca
removido, EXCLUDED nunca selecionado, classificação nunca alterada, overflow nunca
escondido; qualquer falha mantém o resultado do V1.3; offline com provider de teste,
provider-agnostic, independente do CWD, sem chamada LLM desnecessária).

## Objetivo

```text
EngineeringRequest
        ↓
Discovery (V1.1) → Classification (V1.2) → Budget (V1.3)
        ↓
Escalation evaluation (V1.4, determinística)
        ├── não necessária ──> NOT_REQUIRED: resultado determinístico do budget, 0 chamadas LLM
        └── necessária ─────> LLM Context Planner ──> ContextPlan validado (PLANNED)
                                   └── qualquer falha ──> FAILED + resultado do budget
```

Responde "esta tarefa precisa de raciocínio adicional para planejar o contexto?" e, só
quando precisa, "qual contexto priorizar ou reorganizar dentro das restrições existentes?".
Não renderiza prompt, não executa agente, não mede precisão/recall (V1.5).

## Baseline

| Item | Valor |
|---|---|
| Branch / HEAD | `main` / `55332e4` ("feat(context): implement V1.3 deterministic context budgeting") |
| Working tree | limpa |
| Package | `1.3.0` → `1.4.0` |
| pytest | 956 passed, 6 skipped (Mem0/Jev live opt-in) |
| ruff / mypy | limpo / limpo (49 arquivos) |
| doctor | PASS (12 pass, 0 warn, 0 fail) |

Auditoria (estado real, não relatórios anteriores):

- `LLMProvider.complete(LLMRequest(model, prompt)) -> LLMResult(provider, model, text)`:
  sem structured output, sem timeout no contrato, sem system prompt;
- **nenhum adapter LLM real** (OpenAI/Anthropic/NVIDIA desabilitados e sem módulo); só
  `FakeLLMProvider` (eco do prompt) e o adapter de decisão Jev;
- `ModelResolver.llm(alias)` + `ProviderRegistry` já existem (V0.2);
- `EngineeringRequest.intent` ∈ {plan, implement, review, unclassified}: único sinal tipado
  de tarefa arquitetural (`plan` = Architect);
- `risks.yaml` só declara níveis/default; a requisição **não tem risco** → não há fonte
  confiável para "alto risco";
- conflitos observáveis: `metadata["merge_conflicts"]` do merge do discovery (V1.2) e
  `LimitConflict` do budget;
- confiança: `Evidence.DECISION_LOW_CONFIDENCE` (Jev respondeu abaixo do threshold);
  `NO_DECISION_LAYER` aparece em **todo** request enquanto Jev está desabilitado;
- medição real (este repositório, `--intent plan`): 38 candidatos — 7 REQUIRED, 9
  HIGH_VALUE (1 specialty), 22 OPTIONAL; budget SUCCESS 52 922 / 80 000.

Guards anteriores ajustados conscientemente:

- `test_context_discovery::test_context_does_not_know_interfaces_providers_decisions_or_network`:
  `context/escalation/planner.py` (e só ele) pode importar `providers.base`,
  `providers.registry` e `providers.resolution` (contrato LLM + composição), nunca um
  adapter, service ou rede;
- `test_earlier_context_stages_never_import_later_ones`: discovery, classification e budget
  não importam `context.escalation`;
- `test_doctor::test_valid_environment_passes`: novo check `escalation`.

## Arquitetura

```text
cli.py  context plan ─┐                                  doctor.py  check "escalation"
  _discover → _classify → build_budgeter().budget()      (estrutural: gatilhos, alias,
  _planner_for_context → open_context_planner(config)     provider/kind; nunca abre adapter)
                       ↓
context/escalation/planner.py   build_escalation(config, planner=…) · ContextEscalation.escalate
   ├── evaluator.py    EscalationEvaluator      (determinístico, ContextBudgetResult → decisão)
   ├── planning.py     harness_constraints · prepare_input (allow-list + safety) · render_prompt
   ├── ContextPlanner  LLMProvider.complete(LLMRequest(model=<model_id>, prompt))
   ├── validation.py   parse_response (JSON estrito) · validate_plan (normaliza + invariantes)
   ├── invariants.py   PlanningRole · plan_violations (reaplica o budget) · plan_size
   └── models.py       EscalationReason … ContextPlan · ContextEscalationResult (revalida o plano)
```

Dependências: `escalation → budget.models, classification.models, context.models,
context.files (is_secret_name), memory.safety, config, providers.base/registry/resolution
(só planner.py)`. Nenhum estágio anterior importa `escalation`.

### Contratos

```text
ContextEscalationDecision   required · reasons[] · evidence[EscalationEvidence] · evaluated
EscalationEvidence          reason · detail · observed · threshold · candidate_ids[]
ContextPlan                 selected_candidate_ids (ordem de prioridade) · rationale ·
                            added[] · dropped[] · used · usable ·
                            unresolved_constraints[UnresolvedConstraint] · suggestions[]
UnresolvedConstraint        kind (required_overflow | required_unavailable | source_conflict |
                            limit_conflict | withheld | planner_reported) · detail · candidate_ids[]
PlannerCall                 model_alias · provider · model_id · duration_ms ·
                            prompt_characters · response_characters
ContextEscalationResult     budget (V1.3, intacto) · escalation · status · constraints ·
                            plan? · failure_kind? · failure? · call? · llm_calls (0|1) · warnings
PlanStatus                  NOT_REQUIRED | PLANNED | FAILED
PlanningFailure             planner_unavailable | unsafe_input | provider_error | invalid_output
```

Invariantes no modelo (nenhum caminho de código constrói um resultado inválido):
NOT_REQUIRED ⇔ escalation não requerida; plano ⇔ PLANNED; falha (tipo + detalhe) ⇔ FAILED;
`call` ⇔ `llm_calls == 1`, e só PLANNED/provider_error/invalid_output chamam a LLM;
constraints só com escalation; o plano reporta **todas** as constraints do Harness,
inalteradas, e passa por `plan_violations` contra o budget.

Saída exigida da LLM (`PlannerResponse`, `extra="forbid"`, `strict=True`):

```json
{"selected_candidate_ids": ["..."], "rationale": "...",
 "unresolved_constraints": ["..."], "suggestions": ["..."]}
```

## Decisões técnicas

1. **Escalar é decisão determinística.** O avaliador lê só dados do V1.0–V1.3; a LLM nunca
   decide se deve ser chamada. Sem gatilho → nenhuma chamada (testado).
2. **Só gatilhos com dado real** (tabela abaixo). *Alto risco* não foi implementado: sem
   fonte de risco na requisição/config (Risk Engine é V9) — simular seria inventar.
3. **Quatro thresholds**, cada um desativável (`[]`/`null`); problemas objetivos
   (overflow, unavailable, conflito de fonte) sempre escalam.
4. **Baixa confiança ≠ fallback de configuração.** Conta só `decision_low_confidence`; o
   fallback `no_decision_layer` ocorre em todo request com Jev desabilitado e escalaria
   tudo — viola "determinístico por padrão".
5. **Provider via alias.** `context.yaml escalation.model` (alias de `models.yaml`,
   validado entre arquivos) → `ModelResolver` → `LLMProvider`; nenhum nome de vendor no
   código. Sem adapter real (V2.x), o valor enviado é `null` e o doctor explica o efeito.
   `build_llm_adapter` existe e falha fechado (`ProviderNotFoundError`), simétrico a
   `build_decision_adapter`; nenhuma infraestrutura V2 antecipada.
6. **Só metadata, por allow-list** (`ContextPlanningInput`): nenhum conteúdo de candidato
   sai. Decisão consciente: o V1.3 registrou que conteúdo selecionado não passa por
   varredura de secrets; não enviar conteúdo elimina esse risco no envio externo sem criar
   um framework de redação.
7. **Structured output sem recurso de vendor**: o contrato só devolve texto; o prompt exige
   um objeto JSON e `PlannerResponse` o valida estritamente (chaves exatas, tipos estritos,
   tamanhos limitados). Tolera-se apenas um fence ``` envolvendo o objeto; sem extração de
   prosa nem reparo.
8. **Omissão de REQUIRED rejeita o plano** (não é re-adicionada em silêncio). Exceção
   explícita: REQUIRED **retido por segurança** — a LLM não o viu, então o Harness o insere
   (registrado como constraint `withheld`).
9. **Normalização mínima e determinística**: REQUIRED primeiro (ordem do planner preservada
   dentro de cada grupo). Uma lista única `selected_candidate_ids` é a ordem de prioridade —
   evita duas listas (seleção + ordem) inconsistentes.
10. **O plano reorganiza, não compra espaço**: `plan_violations` reaplica o V1.3 (REQUIRED
    antes, itens inteiros, usable, categorias, `max_*`); só itens com tamanho medido são
    selecionáveis. Truncation/chunking/sumarização viram `suggestions`, nunca executadas.
11. **Validação duas vezes**: `validate_plan` rejeita; `ContextEscalationResult` revalida.
12. **Fallback = V1.3**, carregado sempre no resultado. Nunca outra LLM, Jev ou humano
    automático. Falha é explícita: status + `failure_kind` + `failure` + warning.
13. **Três status** (NOT_REQUIRED, PLANNED, FAILED). "Não resolvido" é
    `unresolved_constraints` do plano, não um estado paralelo.
14. **Fake genérico preservado**: o provider roteirizado (`ScriptedLLMProvider`) vive em
    `tests/escalation_helpers.py`; `providers/fake.py` não conhece ContextPlan.
15. **Log em INFO** (tamanho do plano ou tipo de falha; nunca prompt ou saída): o JSON já
    carrega os warnings, a CLI continua silenciosa por padrão.

### Gatilhos implementados (reais)

```text
architectural_task            SUPPORTED   request.intent ∈ architectural_intents ([plan])
multiple_domains              SUPPORTED   specialties REQUIRED/HIGH_VALUE ≥ min_specialties (3)
                                          (hoje derivadas do perfil do projeto; por tarefa só com Jev)
low_confidence                SUPPORTED   evidência decision_low_confidence ≥ min_low_confidence (3)
                                          (só existe com Jev habilitado)
too_many_relevant_candidates  SUPPORTED   HIGH_VALUE > max_high_value (12)
source_conflict               PARTIAL     metadata `merge_conflicts` em candidato não EXCLUDED;
                                          sem detector semântico (proibido pelo escopo)
required_overflow             SUPPORTED   budget usage.overflow > 0
required_unavailable          SUPPORTED   REQUIRED em not_selected (content_unavailable)
high_risk                     NOT SUPPORTED  sem fonte de risco (V9)
```

## Estrutura de pastas

```text
engineering/
├── config/context.yaml                    # + seção escalation (enabled, model: null, triggers)
├── config/models.yaml                     # + exemplo comentado context_planner
├── orchestrator/
│   ├── config.py                          # + EscalationTriggers, EscalationSection, ref. cruzada
│   ├── cli.py                             # + context plan
│   ├── doctor.py                          # + check_escalation
│   └── context/escalation/                # NOVO (V1.4)
│       ├── __init__.py
│       ├── models.py  invariants.py  evaluator.py  planning.py  validation.py  planner.py
└── tests/
    ├── escalation_helpers.py              # ScriptedLLMProvider, plan_json, budget_of, escalate
    ├── unit/test_context_escalation_evaluator.py
    ├── unit/test_context_escalation_plan.py
    ├── unit/test_context_escalation_config_doctor.py
    └── integration/test_context_escalation_pipeline.py
```

## Fluxos principais

### Quando a LLM é chamada / não é chamada

Chamada **somente** se: `escalation.enabled` ∧ ≥ 1 gatilho ∧ planner aberto (modelo
configurado, provider habilitado, adapter registrado) ∧ instrução e prompt passam na
verificação de segurança. **Nunca** chamada quando: nenhum gatilho (`NOT_REQUIRED`,
`llm_calls: 0`); escalation desabilitada; sem planner (`planner_unavailable`); input
inseguro (`unsafe_input`).

### Segurança (o que sai, o que é retido, o que falha)

| | |
|---|---|
| **Enviado** | request: intent, mode, source, instruction; budget: status, unit, truncation, total, reserve, usable, used, remaining, overflow, category_limits, max_*; escalation_reasons; por candidato: id, kind, title, classification, selected_by, evidence, confidence, category, size, budget_reason, selected_by_budget, role, conflicts; constraints do Harness (só ids visíveis); contagem de retidos |
| **Nunca enviado** | conteúdo de qualquer candidato, excerpts de memória, descrições da biblioteca, provenance, request_id, created_at, origin_ref |
| **Retido (withheld)** | candidato cujo id/título/path/conflicts casam regras de `memory.safety` ou cujo path do projeto tem nome de secret (`.env*`, chaves, credentials: `is_secret_name`) → constraint `withheld` com nomes das regras; REQUIRED retido é mantido pelo Harness |
| **Detalhe substituído** | constraint cujo `detail` casa uma regra → "(detail withheld: failed the safety check)" |
| **Falha da escalation** | instrução com aparência de secret, ou prompt final bloqueado → `FAILED unsafe_input`, 0 chamadas; mensagens citam regras, nunca o texto |

### Provider failure

`ProviderError` (timeout, 5xx, auth, qualquer erro traduzido pelo adapter) →
`FAILED provider_error`, `llm_calls: 1`, `call.response_characters: null`, `budget`
intacto, warning "planning failed (provider_error): …; the deterministic budget result
stands", `summary.selection_source: deterministic_budget`. Uma exceção de vendor não
traduzida é violação do contrato do adapter (bug) e propaga.

### Exemplo real — este repositório, provider roteirizado (único LLM disponível)

```text
request   "redesign the context budget in orchestrator/context/budget/budgeter.py" --intent plan
classes   REQUIRED 7 · HIGH_VALUE 9 · OPTIONAL 22 (Jev desabilitado)
budget    SUCCESS · 52 922 / 80 000 · 25 selecionados
reasons   [architectural_task]
prompt    17 359 caracteres · 38 candidatos enviados · 0 retidos · passa em memory.safety
plan      PLANNED · 16 selecionados (7 REQUIRED + 9 HIGH_VALUE) · used 25 431 / 80 000
          added [] · dropped 9 (OPTIONAL docs + specialties "always") · suggestions
          ["summarise sprint docs"] (registrada, não executada)
call      context_planner → scripted-llm / planner-v1 · llm_calls 1
```

Com a configuração enviada (`model: null`), o mesmo comando real produz
`FAILED planner_unavailable`, `llm_calls: 0`, a seleção do budget intacta e exit 3.

### Sem escalation (prova)

```text
$ harness context plan "fix rounding in orchestrator/context/budget/budgeter.py"
summary: escalation_required false · reasons [] · plan_status NOT_REQUIRED · llm_calls 0 ·
         budget_status SUCCESS · selected_count 25 · selection_source deterministic_budget
exit 0
```

Testes: `test_simple_request_does_not_escalate_and_calls_no_llm` (unit) e
`test_simple_task_with_small_context_never_calls_the_llm` (e2e) verificam
`ScriptedLLMProvider.requests == []`.

### Debug

- `harness context plan "..." | jq .summary` — escalou? por quê? quem planejou? o que ficou aberto?
- `jq .escalation.evidence` — valor observado, threshold e candidatos de cada gatilho.
- `jq '.failure_kind, .failure'` — por que o plano falhou; `jq .plan.added, .plan.dropped` —
  diferença para o budget.
- `--log-level INFO` — uma linha por plano/falha (sem prompt nem saída).
- `harness doctor` — gatilhos e modelo planner em vigor.

### Como manter / onde modificar

- Thresholds → `config/context.yaml` `escalation.triggers`.
- Novo gatilho → `EscalationReason` + método em `evaluator.py` (+ campo em
  `EscalationTriggers` se tiver threshold) + testes em `test_context_escalation_evaluator.py`.
- O que o planner vê → `planning.py` (`ContextPlanningInput`, `prepare_input`,
  `_INSTRUCTIONS`); o que pode responder → `PlannerResponse`; o que todo plano respeita →
  `plan_violations`.
- Adapter LLM real (V2.x) → módulo em `providers/`, kind em `LLM_ADAPTER_KINDS`, ramo em
  `build_llm_adapter`, alias em `models.yaml`, `escalation.model`.

## Testes

| Arquivo | Cobre |
|---|---|
| `unit/test_context_escalation_evaluator.py` (16) | request simples não escala; intent arquitetural; múltiplas specialties; muitos HIGH_VALUE; low confidence (e `no_decision_layer` não conta); source conflict (e EXCLUDED não conta); REQUIRED_OVERFLOW; REQUIRED_UNAVAILABLE; múltiplos gatilhos registrados em ordem; desabilitado; invariantes da decisão; provider não chamado sem gatilho |
| `unit/test_context_escalation_plan.py` (37) | plano válido + metadata da chamada; budget/classificação intactos; normalização REQUIRED-first determinística; troca dentro dos limites; constraints/suggestions do planner; fence; REQUIRED omitido; EXCLUDED; id desconhecido; duplicata; budget excedido; 8 saídas malformadas/fora do schema (inclui campo `classification`); REQUIRED indisponível; não medido; overflow (constraint mantida; nada adicionado); provider failure (timeout, 503, erro genérico); sem planner; invariantes do resultado; prompt com invariantes; só metadata (sem conteúdo, chaves exatas, ids inalterados); instrução secreta não enviada; `.env` retido; título com token retido; REQUIRED retido mantido |
| `unit/test_context_escalation_config_doctor.py` (18) | config enviada; alias desconhecido; triggers inválidos; desativação; composição (sem modelo, provider desabilitado, sem adapter, adapter registrado); doctor PASS/disabled/FAIL (jev)/PASS (desabilitado)/WARN (sem adapter, sem abrir adapter) |
| `integration/test_context_escalation_pipeline.py` (7) | e2e com REQUIRED policy/instruction/source, HIGH_VALUE guideline/código, OPTIONAL doc/memória, EXCLUDED ADR/lock, gatilho → plano válido (REQUIRED primeiro, EXCLUDED fora, budget respeitado, 1 chamada); simples sem chamada; overflow planejado mas não resolvido; provider failure preserva o budget; independente do CWD; CLI sem gatilho (exit 0, 0 chamadas) e com gatilho sem planner (exit 3) |

Resultados finais: ver "Critério de saída".

## Riscos

- **Planner inoperante na prática** até existir adapter LLM (V2.x): toda escalation real
  termina `FAILED planner_unavailable` (explícito, exit 3). Mitigação: doctor e summary
  dizem isso; o resultado determinístico continua disponível.
- **Pouca semântica no input**: sem conteúdo, o planner decide por ids/títulos/tamanhos/
  classes. Pode propor planos pouco melhores que o budget.
- **Heurística de secrets** (regex do V0.3): reduz, não elimina, vazamento via títulos/ids.
  Conteúdo nunca sai, o que limita o impacto.
- **Gatilho arquitetural depende do intent declarado**: requests `unclassified` nunca
  disparam; um intent errado escala (ou não) indevidamente.
- **Thresholds não calibrados** (3/12/3).
- **Onde pode quebrar**: mudança em `BudgetedItem`/`ContextBudgetResult` (invariantes
  reaplicam o budget — `plan_violations` precisa seguir o budgeter); novo `CandidateKind`
  (categorias/contagens em `invariants.py`); adapter que não traduz exceções de vendor.

## Melhorias futuras

- Adapter LLM real + teste de contrato (V2.x) e teste live opt-in do planner.
- Excerpts seguros (com redação) para candidatos específicos quando o planner precisar.
- Fonte de risco (V9) → gatilho `high_risk`.
- Telemetria de escalations e concordância plano × budget (V1.5).

## Dívidas

- Sem adapter LLM real; planner roda só com provider injetado.
- `LLMProvider` sem structured output/timeout no contrato (JSON exigido pelo prompt).
- `source_conflict` limitado a conflitos de metadata do merge.
- `multiple_domains` reflete o perfil do projeto, não a tarefa, sem Jev.
- Conteúdo selecionado continua sem varredura de secrets (não é enviado a lugar nenhum até
  a renderização de prompt do V2).

## Critério de saída

```text
EngineeringRequest → Discovery → Classification → Budget → Escalation Evaluation
   → [not needed] deterministic result   OR   [needed] LLM ContextPlan (validado)
```

| Critério | Evidência |
|---|---|
| provider-agnostic | só `LLMProvider` via alias/`ModelResolver`; guard de imports |
| estruturado | `ContextEscalationDecision`, `ContextPlan`, `ContextEscalationResult` Pydantic estritos |
| auditável | evidência por gatilho, `PlannerCall`, `added`/`dropped`, constraints, warnings |
| validado deterministicamente | `PlannerResponse` + `validate_plan` + revalidação no modelo |
| seguro | allow-list, sem conteúdo, `memory.safety` + `is_secret_name`, prompt verificado |
| offline com fake | `ScriptedLLMProvider`; nenhum teste depende de rede/chave |
| independente do CWD | `test_plan_is_independent_of_cwd` |
| REQUIRED preservado / EXCLUDED nunca / sem reclassificação | testes unit + e2e + invariantes |
| sem LLM desnecessária | testes com `requests == []` |

Quality gates (comandos oficiais, `engineering/`): `pytest` 1034 passed, 6 skipped ·
`ruff check .` limpo · `mypy` limpo (56 arquivos) · `python -m orchestrator doctor` PASS
(13 pass, 0 warn, 0 fail).

**V1.4 COMPLETE.** Próxima etapa: **V1.5 — Context Telemetry** (não iniciada).
