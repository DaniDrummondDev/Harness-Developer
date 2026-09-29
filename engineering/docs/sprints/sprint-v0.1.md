# Sprint V0.1 — Mode Foundation

**Status: COMPLETE** (exit criterion met; see "Critérios de saída").

## Objetivo

Formalizar os dois modos de operação (Interactive e Autonomous) e permitir que o core receba
uma requisição normalizada independentemente da origem — sem providers, LLM, memória, state
machine completa ou integrações externas (roadmap, V0.1).

## Escopo

Dentro: `EngineeringRequest`, `ExecutionMode`, `RequestSource`, `Intent`, normalização de
entrada, regra de transição inicial, consumidor real de `modes.yaml`, comando CLI que prova o
fluxo, testes e documentação.

Fora (versões posteriores): provider abstraction (V0.2), Mem0 (V0.3), Jev/classificação
(V0.4), Context Engineering (V1.x), execução de agentes (V2), state machine (V6), seleção
autônoma de tasks / loop (V13), MCP/HTTP (V14).

## Arquitetura

```text
raw input ──> intake.normalize_request() ──> EngineeringRequest ──> core.admission.admit()
 (CLI hoje)      (fora do core)                (core/request.py)       ──> AdmittedRequest(PLANNED)
```

Dependências: `cli → intake → core`, `cli → config → core`. O core não importa CLI, YAML
nem `config`; `admit()` recebe o conjunto de modos habilitados como dado.
Mapa completo: [`../architecture.md`](../architecture.md).

## Implementação

| Elemento | Onde | Nota |
|---|---|---|
| `ExecutionMode` | `core/request.py` | `interactive`, `autonomous` |
| `RequestSource` | `core/request.py` | 5 interativas + 5 autônomas, todas nomeadas no roadmap |
| `SOURCES_BY_MODE` / `mode_for_source` | `core/request.py` | partição imutável fonte → modo |
| `Intent` | `core/request.py` | `plan`, `implement`, `review`, `unclassified` |
| `WorkflowState` | `core/request.py` | só `planned` (estado inicial) |
| `EngineeringRequest` | `core/request.py` | frozen, `extra="forbid"`, `schema_version: 1` |
| `AdmittedRequest` | `core/request.py` | request + estado inicial |
| `admit()` / `INITIAL_STATE` | `core/admission.py` | regra de transição inicial |
| `normalize_request()` | `intake.py` | normalizador único para todas as origens |
| `RequestError`, `InvalidRequestError`, `ModeNotEnabledError` | `core/exceptions.py` | com consumidores (intake, admission, CLI) |
| `ModesFile` / `HarnessConfig.enabled_modes` | `config.py` | chaves tipadas, ambos os modos obrigatórios |
| `harness intake` | `cli.py` | `intake "<instrução>" [--intent] [--ref]` → JSON |

### `EngineeringRequest`

| Campo | Tipo | Regra |
|---|---|---|
| `schema_version` | `Literal[1]` | versão do contrato serializado |
| `request_id` | UUID | gerado localmente (UUID4) na criação; fornecido só ao reidratar |
| `created_at` | datetime com timezone | UTC por padrão; naive é rejeitado |
| `mode` | `ExecutionMode` | obrigatório |
| `source` | `RequestSource` | obrigatório; deve pertencer ao `mode` |
| `intent` | `Intent` | padrão `unclassified` |
| `instruction` | str | stripped, não vazio |
| `origin_ref` | str \| None | ≤ 200 chars; obrigatório em Autonomous |

### Invariantes (implementadas e testadas)

1. `source ∈ SOURCES_BY_MODE[mode]` — as 50 combinações cruzadas inválidas são testadas.
2. `instruction` não pode ser vazia/só espaços.
3. Autonomous exige `origin_ref` (rastreabilidade do artefato que originou o trabalho).
4. Autonomous exige `intent` classificado (fail closed, RNF-006).
5. `created_at` com timezone; `request_id` UUID; campos extras rejeitados; objeto imutável.
6. `modes.yaml` declara todos os `ExecutionMode`; nomes desconhecidos são rejeitados.
7. Admissão: request de modo desabilitado é recusado; ambos os modos entram em `PLANNED`.

## Decisões técnicas

- **Normalizador genérico, não adapters por fonte.** Só a CLI é consumidor real hoje; um
  adapter por origem seria abstração sem consumidor. Alternativa: `CliAdapter`, `McpAdapter`...
  Impacto: MCP/HTTP (V14) chamam a mesma função; parsers específicos entram quando um payload exigir.
- **Modo derivado da fonte, mas armazenado.** Cada fonte pertence a um único modo, então a
  normalização deriva o modo; ele continua explícito no contrato (conceito de domínio) e é
  validado contra a fonte. Alternativa: `autonomous: bool` ou só `source`. Impacto: regras
  futuras por modo leem `mode`, não inferem da fonte.
- **Intent declarado ou `unclassified`.** Não há taxonomia oficial; os três valores espelham
  papéis/verbos documentados (Architect/plan, Implementer/`task run`, Reviewer/`task review`).
  Alternativa: taxonomia ampla ou default "implement". Impacto: V0.4 pode classificar
  `unclassified` sem mudar o contrato.
- **Estado inicial único `PLANNED`**, idêntico para os dois modos (primeiro estado de RF-032/V6).
  Alternativa: nenhum estado. Impacto: V6 estende `WorkflowState` e adiciona transições.
- **`modes.yaml` passa a governar admissão.** `enabled` agora tem efeito; Autonomous permanece
  `false` até existir state machine/loop. Schema continua `version: 1`: a forma não mudou, só
  ficou mais estrita (ambos os modos obrigatórios; o arquivo distribuído já cumpria).
- **Sem `metadata`.** Nenhuma origem atual precisa de dados além dos campos tipados; um
  dicionário livre viraria depósito de campos de domínio. Entra quando MCP/HTTP exigirem.
- **Sem campo de projeto.** O Harness opera um projeto por `config/`; multi-projeto é futuro.
- **CLI `intake`, não `interactive`.** `harness interactive` é reservado ao V14 (e um teste do
  V0 garante que ainda não existe). Erros de domínio → exit 1 em stderr; uso → exit 2.
- **Versão do package `0.0.1` → `0.1.0`** para refletir V0.1.

## Estrutura de pastas

```text
engineering/orchestrator/
├── intake.py              # novo: normalização
└── core/
    ├── admission.py       # novo: admit(), INITIAL_STATE
    ├── request.py         # novo: contratos de domínio
    └── exceptions.py      # + RequestError, InvalidRequestError, ModeNotEnabledError
engineering/tests/unit/
├── test_request.py        # novo
├── test_intake.py         # novo
└── test_admission.py      # novo
```

## Fluxos principais

1. `harness intake "add health endpoint" --intent implement --ref T-1` → carrega config →
   normaliza (`source=cli`, `mode=interactive`) → `admit` → JSON `{request, state: "planned"}`, exit 0.
2. Entrada inválida (fonte/intent/modo desconhecido, instrução vazia, combinação inválida) →
   `InvalidRequestError` → `error: ...` em stderr, exit 1.
3. Modo desabilitado em `modes.yaml` → `ModeNotEnabledError` → exit 1.
4. Autonomous (programático, ex.: `normalize_request(source="task", intent="implement",
   origin_ref="T-3", ...)`) → mesmo contrato, mesmo `admit`.

Testes: `pytest` (181; 77 do V0 preservados), `ruff check .`, `mypy` (strict).
Debug: `harness intake ...` mostra o request normalizado; mensagens de erro listam cada campo inválido.

## Critérios de saída

O core recebe uma requisição normalizada independentemente da origem — **atendido**:
`admit()` aceita qualquer `EngineeringRequest`, interativo ou autônomo, pelo mesmo caminho.

## Riscos

- `created_at` e `request_id` não são determinísticos; testes comparam campos, não o JSON inteiro.
- Nenhum produtor autônomo real existe; o caminho autônomo é provado por testes, e Autonomous
  está desabilitado por configuração.
- `Intent` pequeno pode precisar crescer; adicionar valores é compatível, renomear não.
- Instruções não têm limite de tamanho (sem requisito documentado).

## Melhorias futuras

- Limite de tamanho para `instruction` quando houver requisito (ex.: HTTP API).
- `metadata` tipada quando MCP/HTTP trouxerem dados de cliente/sessão.
- Persistência do `AdmittedRequest` como `request.json` (V8).
- Pasta `tests/contract/` citada no doc 03 não existe (ver findings do relatório V0.1).
