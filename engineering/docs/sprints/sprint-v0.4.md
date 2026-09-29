# Sprint V0.4 — Decision Foundation

**Status: V0.4 — Decision Foundation COMPLETE** (critério de saída comprovado contra a API
real do Jev, `jev-1.13.0`, com `JEV_API_KEY`; ver "Prova de integração").

## Objetivo

Integrar Jev (TypeSafe System One) como `DecisionProvider` probabilístico real (roadmap V0.4):

```text
DecisionRequest → DecisionService → JevDecisionProvider → Jev → answer
    → choice / score / probability / confidence → DecisionOutcome auditável
```

sem implementar o Decision Policy Engine (V5), sem Context Engine (V1.x) e sem fallback
automático para LLM.

## Baseline

| Item | Valor |
|---|---|
| Branch / HEAD | `main` / `13de6fc` ("first commit", contém V0–V0.2) |
| Working tree | V0.3 inteiro **não commitado** (11 arquivos modificados, 10 novos: `orchestrator/memory/`, testes e docs de memória) — preservado, V0.4 construído por cima |
| Python / package | 3.12.3 / `0.3.0` (venv `engineering/.venv`) |
| pytest | 379 passed, 1 skipped (Mem0 live opt-in) |
| ruff | limpo |
| mypy | limpo, 51 arquivos |
| Decisões | `DecisionProvider`/`DecisionRequest`/`DecisionResult`/`FakeDecisionProvider` (V0.2); `decisions.yaml` só com `escalation_order`; `jev` declarado e desabilitado; `models.yaml` vazio |
| Jev | sem SDK instalado; nenhuma credencial TypeSafe no ambiente |

## Escopo

Dentro: adapter Jev real; evolução aditiva do contract de decisão; typed decisions
(classification, routing, severity, context relevance); score; probability/confidence;
threshold configurável; fallback contract; telemetria mínima; composição por config; CLI
`decision`; check opt-in no `doctor`; contract/unit/integration tests; prova live opt-in.

Fora (verificado): Global Library, skills/guidelines/policies runtime, Context Engine
(discovery, classification pipeline, budget, plan), OpenAI/Anthropic/NVIDIA reais, agent
runtime, gates, review, Decision Policy Engine, auto-accept, LLM/human escalation,
sampling, agreement, calibração, state machine, Git, run artifacts, MCP/HTTP API.

## Integração Jev (estudo da documentação oficial)

Fonte: docs.typesafe.ai (`/api`, `/sdk/python`, `/primitives/{choice,score,noul}`,
`/confidence`, `/models`), lidas em 2026-09-29.

| Item | Valor verificado |
|---|---|
| API usada | HTTP `POST https://api.typesafe.ai/v1/systemone` (avaliação); `GET /v1/models` (listagem, usada como health check sem inferência) |
| SDK | `typesafe-sdk` (PyPI) existe; **não usado** (ver Decisões técnicas) |
| Modelo | `jev-latest` (alias) → `jev-1.13.0`; a resposta reporta a versão exata em `model` |
| Autenticação | `Authorization: Bearer <key>` (formato da API, inalterado). No Harness o valor vem apenas do ambiente, da variável canônica `JEV_API_KEY` (`providers.yaml` → `api_key_env`) |
| Request | `{model, state, questions: {<id>: {type: choice|score|noul, instructions, criteria}}}`; ids de pergunta não são enviados ao modelo |
| Choice | `criteria: {option: description|null}` (≤ 255) → `{type, choice, probabilities{option: p}, confidence}` |
| Score | `criteria: [levels]` (2..10, ordenados) → `{type, score (0..n−1, média ponderada), legend, probabilities{"0": p}, confidence}` |
| Noul | sim/não → `{type, noul}`; **sem confidence** (não usado no V0.4) |
| Confidence | 0..1, derivada da concentração da distribuição (Choice/Score) — não é a probabilidade da escolha |
| Usage | `{input_tokens, output_tokens}` (cobrança por input token) |
| Erros | 401 chave inválida/ausente · 422 body inválido · 429 rate limit · 529 overloaded |
| Limites conhecidos | 64k tokens/request (32k state + maior pergunta); rate limits dinâmicos; texto apenas; inglês é o idioma mais preciso; alias `jev-latest` muda sem aviso |

## Arquitetura

```text
cli.py (decision classify|route|severity|relevance|health)      doctor.py (check "decisions")
        │                                                               │
        └──────────────── decisions/service.py ─────────────────────────┘
                          open_decisions(config)  ── composição (lê env: API key)
                          DecisionService.decide  ── validação de boundary, threshold,
                                 │                   outcome, telemetria
               providers/resolution.py (alias → provider → model_id, enabled)
               providers/registry.py   (DecisionProvider tipado)
                                 │
               providers/base.py   DecisionProvider / DecisionRequest / DecisionResult
               providers/jev.py    JevDecisionProvider (único módulo que conhece TypeSafe)
               providers/fake.py   FakeDecisionProvider (evoluído)
```

`core/` não importa `decisions/` nem `providers/`. Só `decisions/service.py` importa
`providers/jev.py`. `decisions/` nunca importa `LLMProvider` (testes de isolamento).

## Implementação

### DecisionProvider — reuso e evolução

Reutilizado; nenhum segundo contract. Evolução **aditiva** (todos os campos novos são
opcionais; requests/results do V0.2 continuam válidos):

- `DecisionRequest`: `kind: DecisionKind` (default `classification`), `subject` (conteúdo
  julgado; vira o `state` do Jev), `ordered` (opções do menor ao maior → Score),
  `descriptions` (rubrica por opção; chaves devem ser opções);
- `DecisionResult`: `kind`, `probability`, `probabilities`, `score`, `resolved_model`,
  `input_tokens`; validação: `choice ∈ probabilities` e soma ≈ 1 (±0.02).

Razão: o contract V0.2 não tinha onde colocar o conteúdo julgado, a ordinalidade, nem as
métricas reais do Jev. Nada do V5 foi misturado (sem layer, escalation, policy).

### Typed decisions

`DecisionKind` = `classification | routing | severity | context_relevance`. É rótulo de
auditoria/telemetria; não altera como o provider decide. Os vocabulários (bug/feature,
low..critical, ...) são dados do chamador — existem só como presets da CLI.

### Adapter Jev (`providers/jev.py`)

- unordered → pergunta **Choice**; ordered → pergunta **Score**; `state = subject or question`;
- envia apenas `model`, `state`, `questions` (nada além do necessário à decisão);
- valida a resposta (modelos Pydantic internos, campos desconhecidos ignorados):
  choice ∈ options, `probabilities` cobre exatamente as opções/níveis, score em 0..n−1,
  confidence/probabilidades em 0..1 e soma ≈ 1 → senão `DecisionInvalidResponseError`;
- status: 401/403 → `DecisionAuthenticationError`; 429/529/5xx/unreachable →
  `DecisionUnavailableError`; timeout → `DecisionTimeoutError`; 422/outros → `ProviderCallError`;
- sem retries; `ping()` = `GET /v1/models`.

### Choice / Score / Confidence

| Métrica | Faixa | Significado | Origem | Ausência |
|---|---|---|---|---|
| `choice` | ∈ options | opção escolhida | Choice: `choice`; Score: nível de maior probabilidade (empate → nível menor) | nunca ausente |
| `confidence` | 0..1 | concentração da distribuição (1 = toda massa numa opção) | `answer.confidence` do Jev, sem transformação | obrigatório |
| `probability` | 0..1 | probabilidade da opção escolhida | `probabilities[choice]` | `None` = provider não reportou |
| `probabilities` | 0..1, Σ≈1 | distribuição completa | Choice: por opção; Score: nível `"i"` → `options[i]` | `{}` = não reportado |
| `score` | 0..1 | posição ordinal ponderada; 0 = primeira opção, 1 = última | `answer.score / (n − 1)` (normalização documentada pela TypeSafe) | `None` = decisão não ordenada |

`score` e `confidence` nunca são confundidos nem derivados um do outro pelo Harness.

### Thresholds

`decisions.yaml`: `thresholds.minimum_confidence` (0..1, obrigatório quando `model` está
definido). Declarativo; o único consumidor é o `DecisionService`, que apenas **sinaliza**
`low_confidence`. Faixas graduadas (auto/review/human) são V5.2. Default 0.70: valor
inicial não calibrado (a doc da TypeSafe recomenda calibrar por domínio e risco).

### Fallback contract

| Situação | Resultado |
|---|---|
| decisão válida e confiante | `DECIDED` |
| confidence < mínimo | `FALLBACK_REQUIRED` / `low_confidence` (result mantido para auditoria; `outcome.choice = None`) |
| indisponível / 429 / 529 / 5xx | `FALLBACK_REQUIRED` / `unavailable` |
| timeout | `FALLBACK_REQUIRED` / `timeout` |
| resposta malformada / choice ∉ options / contrato violado | `FALLBACK_REQUIRED` / `invalid_response` |
| chave ausente/rejeitada, 422 | **levanta** exceção (bug de config/request não é roteado silenciosamente) |

Nenhum LLM, humano ou retry é executado (teste `test_fallback_never_calls_an_llm`).
CLI: exit 0 decided, 3 fallback required, 1 erro.

### Telemetria

`DecisionTelemetry` (anexada ao outcome e emitida como uma linha JSON no logger
`orchestrator.decisions.telemetry`, nível INFO): timestamp, provider, model_alias, model,
resolved_model, kind, option_count, status (`decided|fallback_required|error`), choice,
confidence, probability, score, minimum_confidence, fallback_required, fallback_reason,
error_category, duration_ms, input_tokens. Nunca contém pergunta, subject, descriptions,
API key ou header (teste dedicado).

### Configuração

- `decisions.yaml`: `model: decision`, `thresholds.minimum_confidence: 0.70`;
- `models.yaml`: `decision: {provider: jev, model_id: jev-latest}`;
- `providers.yaml`: `jev: {kind: jev, enabled: false, base_url, api_key_env: JEV_API_KEY, timeout_seconds: 15}`;
- `ProviderEntry` ganhou campos opcionais vendor-neutros `base_url`, `api_key_env`, `timeout_seconds`;
- cross-reference `decisions.model → models.yaml` na carga (fail fast).

### Registry / Model resolution

Reutilizados sem mudança: `open_decisions` cria um `ProviderRegistry`, resolve o alias via
`ModelResolver` (enabled check), registra o adapter construído por `build_decision_adapter`
(`kind: jev`) e o obtém tipado via `resolver.decision(alias)`. Unicidade de id, type
mismatch, provider desconhecido e desabilitado continuam cobertos pelos testes do V0.2.

## Decisões técnicas

1. **HTTP + urllib em vez do `typesafe-sdk`.** Um endpoint basta; zero dependências novas;
   transport injetável para testes offline; mesmo padrão do Mem0. Trade-off: sem o retry
   automático do SDK para 429/529 — desejado (sem retry storms; política é V5).
2. **Choice para opções não ordenadas, Score para ordenadas.** Score é a única fonte real
   de `score` no Jev; inventar um score a partir de Choice criaria semântica fictícia.
3. **Noul não usado.** Não tem confidence e não é "escolher uma de N".
4. **Validação dupla de `choice ∈ options`** (adapter + service): o service é a garantia
   para qualquer adapter, inclusive fakes e futuros vendors.
5. **Auth/422 levantam em vez de fallback**: erros de configuração precisam ser corrigidos.
6. **Status `error` só na telemetria**: um `DecisionOutcome` nunca é `error` (validador).
7. **Jev desabilitado por padrão**; doctor só checa se habilitado, sem inferência.
8. **Mudança de testes V0.2 intencional**: 3 fixtures que substituíam `models.yaml` passaram
   a declarar `decisions.yaml` sem `model` (o cross-reference novo é fail-fast), e o teste de
   campos de `DecisionRequest` foi atualizado para o contract evoluído.

## Estrutura de pastas

```text
orchestrator/
├── providers/jev.py            NOVO  adapter Jev
├── providers/base.py           MOD   DecisionKind + campos aditivos
├── providers/fake.py           MOD   choice/score/fail_as no fake
├── decisions/__init__.py       NOVO
├── decisions/models.py         NOVO  outcome, fallback, telemetry, health
├── decisions/service.py        NOVO  DecisionService, open_decisions
├── config.py                   MOD   ProviderEntry conexão, DecisionThresholds, cross-ref
├── core/exceptions.py          MOD   Decision*Error, InvalidDecisionRequestError
├── cli.py                      MOD   grupo `decision`
├── doctor.py                   MOD   check opt-in `decisions`
└── __init__.py                 MOD   0.4.0
config/{decisions,models,providers}.yaml   MOD
tests/jev_emulator.py                      NOVO
tests/contract/test_decision_provider_contract.py   MOD (expandido; Fake + Jev)
tests/unit/test_jev_adapter.py             NOVO
tests/unit/test_decision_service.py        NOVO
tests/unit/test_decision_config.py         NOVO
tests/unit/test_decision_cli_doctor.py     NOVO
tests/integration/test_jev_live.py         NOVO (opt-in)
tests/unit/{test_provider_contracts,test_model_resolution,test_config}.py   MOD
```

## Fluxos principais

Ver `docs/architecture.md` → "Decision (V0.4)".

## Testes

| Suite | Cobertura |
|---|---|
| contract (Fake + Jev via emulador) | estrutura, identidade, kind, choice ∈ options, métricas 0..1, distribuição, score só ordenado, erro tipado, timeout, malformed, choice inválida nunca aceita |
| `test_jev_adapter.py` | mapeamento request (choice/score/state/descriptions/model), mapeamento response (probability, confidence, score normalizado, empate, resolved_model, tokens), 10 respostas malformadas, 4 scores inválidos, 7 status HTTP, chave vazia, ping; **transport real** contra servidor HTTP local: header `Bearer`, JSON, timeout, conexão recusada, URL não-http |
| `test_decision_service.py` | decided, 4 kinds, threshold no limite, low confidence, unavailable/timeout/invalid, 6 violações de contrato no boundary, auth levanta, 422 levanta, nenhum LLM chamado/sem retry, input inválido sem chamada, invariantes do outcome, telemetria (campos, duração, sem segredos), health |
| `test_decision_config.py` | config shipped, sem segredos no YAML, threshold 0/0.5/0.7/1 válidos, −0.01/1.01/texto/ausente/campo extra inválidos, 11 configs inválidas (provider/model/campos), composição, fail closed sem rede, chave ausente, env customizada, kind sem adapter, isolamento de imports |
| `test_decision_cli_doctor.py` | classify/route/severity/relevance, exit codes 0/3/1, health, doctor skip/PASS/WARN/FAIL |
| regressão V0–V0.3 | inalterada, verde |

Resultado final: **521 passed, 6 skipped** (5 Jev live + 1 Mem0 live, opt-in); ruff limpo;
mypy limpo (61 arquivos).

## Prova de integração

Teste: `tests/integration/test_jev_live.py` (marker `jev`; classification, routing, severity,
context relevance in-process + um processo CLI completo). Valida invariantes, não semântica.

```bash
export JEV_API_KEY=...          # console.typesafe.ai
HARNESS_JEV_INTEGRATION=1 .venv/bin/python -m pytest -m jev -v -s tests/integration/test_jev_live.py
```

**Estado: PASS — 5/5.** Executado pelo operador na própria shell (a sessão de
implementação não herdava a variável e não lê o arquivo da chave), com `JEV_API_KEY`
carregada do arquivo local fora do repositório e `HARNESS_JEV_INTEGRATION=1`:

| Teste | Status | Choice | Confidence | Probability | Score | Modelo |
|---|---|---|---|---|---|---|
| classification ("Fix failing authentication test") | decided | `bug` | 1.0 | 1.0 | — | `jev-1.13.0` |
| routing ("Review pull request #42 for security problems...") | decided | `reviewer` | 1.0 | 1.0 | — | `jev-1.13.0` |
| severity ("Production checkout returns HTTP 500...") | decided | `critical` | 1.0 | 1.0 | 1.0 | `jev-1.13.0` |
| context_relevance (ADR-007 × "Add a discount field") | **fallback_required** (`low_confidence`) | `high_value` | 0.55 | 0.66 | — | `jev-1.13.0` |
| CLI end-to-end (`python -m orchestrator decision classify`) | decided | `bug` | 1.0 | — | — | `jev-1.13.0` |

O que isso comprova ao vivo: autenticação Bearer com `JEV_API_KEY`; integração real;
mapeamento da resposta estruturada (Choice e Score); `choice ∈ options`; confidence,
probability e score (normalizado, severity → 1.0 = última opção); `resolved_model` do alias
`jev-latest`; **fallback contract** — 0.55 < `minimum_confidence` 0.70 devolve
`fallback_required/low_confidence` com o result preservado para auditoria e nenhuma
chamada adicional; CLI completa em processo separado.

Observações:
- três decisões com confidence 1.0 continuam **probabilísticas**: é a crença do modelo em
  casos claros, não prova nem regra determinística;
- context relevance ter caído abaixo do threshold é coerente com um julgamento
  genuinamente graduado (probabilidade dividida entre `required` e `high_value`) e é
  exatamente o caso que o V5 deverá escalar.

Evidência complementar (pré-credencial, placeholder inválido, não é segredo):
`GET /v1/models` e `POST /v1/systemone` → `DecisionAuthenticationError: credentials rejected
(HTTP 401); check $JEV_API_KEY` — auth sanitizada, sem vazamento.

## Critérios de saída

| Critério | Estado |
|---|---|
| DecisionProvider reutilizado/evoluído | PASS |
| adapter Jev real, desacoplado do core | PASS |
| typed decisions; choice validado; score; probability/confidence; metadata provider/model | PASS |
| thresholds configuráveis e validados | PASS |
| fallback contract; sem LLM automático | PASS |
| telemetria mínima | PASS |
| classification / routing / severity comprovados (offline + live) | PASS |
| context relevance suportável sem Context Engine (offline + live) | PASS |
| FakeDecisionProvider funcional; contract tests; offline | PASS |
| Jev live integration (5/5, `jev-1.13.0`) | PASS |
| fallback contract comprovado ao vivo (`low_confidence`) | PASS |
| `JEV_API_KEY` único nome canônico (nome antigo removido, sem fallback) | PASS |
| sem API key no repositório; V0–V0.3 verdes; pytest/ruff/mypy | PASS |
| documentação; sprint-v0.4 | PASS |
| nenhum V1+ antecipado | PASS |

## Riscos

- **Jev é probabilístico**: confidence alta (inclusive 1.0) não é prova; nunca usar como regra.
- Threshold 0.70 não calibrado; `jev-latest` pode mudar o modelo sob o threshold → fixar
  versão (`jev-1.13.0`) antes de calibrar.
- Rate limits do Jev são dinâmicos; sem retry, picos viram `fallback_required(unavailable)`.
- Conteúdo enviado ao Jev (subject/question) sai do processo: o chamador não deve enviar
  segredos (não há safe-ingestion para decisões no V0.4).
- Semântica do Score: um score 0.5 entre níveis é média ponderada, não "meio severo".

## Onde pode quebrar / como debugar

- Mudança na API TypeSafe → `providers/jev.py` + `tests/jev_emulator.py`; o erro aparece
  como `invalid_response` com o campo violado.
- `decision health` separa `misconfigured` (chave) de `unavailable` (rede/429/5xx).
- `--log-level INFO` mostra a telemetria de cada decisão.

## Melhorias futuras

- Extrair transporte HTTP comum (Mem0/Jev) quando surgir o terceiro adapter HTTP.
- Safe-ingestion (reusar `memory/safety.py`) antes de enviar subject a provider externo.
- Retry com backoff/`retry-after` para 429/529 como política explícita (V5).
- Persistir telemetria em run artifacts (V8); calibração/agreement (V5.3).
- Perguntas múltiplas por request (fan-out) quando o Context Engine precisar (V1.x).
