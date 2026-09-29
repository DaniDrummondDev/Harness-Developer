# Sprint V0.2 — Provider Abstraction

**Status: COMPLETE** (critério de saída atendido; ver "Critérios de saída").

## Objetivo

Definir uma abstração de providers que permita trocar provider/model sem alterar o core
(roadmap, V0.2): `LLMProvider`, `DecisionProvider`, provider registry, configuração por
YAML, resolução de provider/model e adapters fake — sem nenhuma integração real.

## Escopo

Dentro: contracts tipados mínimos, registry, resolução alias → provider → model id →
adapter, efeito real de `providers.yaml`/`models.yaml`, fakes determinísticos, erros de
provider, suítes de contrato reutilizáveis, testes e documentação.

Fora (versões posteriores): Mem0/`MemoryProvider` (V0.3), Jev real, thresholds, telemetria
de decisão (V0.4), Context Engineering (V1.x), Claude runner, OpenAI/NVIDIA reais, roles
em runtime, prompt rendering (V2.x), retries/timeouts/fallback (V15.1), custo (V15.2).

## Arquitetura

```text
HarnessConfig.models / .providers   (validados por load_config; YAML nunca é lido aqui)
          ↓
ModelResolver.llm(alias) | .decision(alias)
          ↓  ModelNotFoundError | ProviderNotFoundError | ProviderNotEnabledError
ResolvedModel(alias, provider, model_id)
          ↓
ProviderRegistry.llm(provider) | .decision(provider)
          ↓  ProviderNotFoundError | ProviderTypeMismatchError
LLMProvider.complete(LLMRequest)        DecisionProvider.decide(DecisionRequest)
          ↓                                        ↓
FakeLLMProvider → LLMResult             FakeDecisionProvider → DecisionResult
          (falhas: ProviderCallError, exceção do vendor encadeada em __cause__)
```

Dependências: `providers.resolution → providers.registry → providers.base`; `resolution`
usa os tipos `ModelEntry`/`ProviderEntry` de `config`. `core/` não importa `providers/`;
`providers/` não importa CLI, intake, `EngineeringRequest`, Typer nem YAML (testado em
`tests/unit/test_provider_isolation.py`). Mapa completo: [`../architecture.md`](../architecture.md).

## Implementação

| Elemento | Onde | Nota |
|---|---|---|
| `LLMProvider` | `providers/base.py` | Protocol: `provider_id`, `complete(LLMRequest) -> LLMResult` |
| `DecisionProvider` | `providers/base.py` | Protocol: `provider_id`, `decide(DecisionRequest) -> DecisionResult` |
| `LLMRequest` / `LLMResult` | `providers/base.py` | `model`, `prompt` / `provider`, `model`, `text` |
| `DecisionRequest` / `DecisionResult` | `providers/base.py` | `model`, `question`, `options` (≥2, únicas) / `provider`, `model`, `choice`, `confidence ∈ [0,1]` |
| `ProviderRegistry` | `providers/registry.py` | `register_llm`, `register_decision`, `llm`, `decision`, `provider_ids` |
| `ModelResolver` / `ResolvedModel` | `providers/resolution.py` | `resolve`, `llm`, `decision` |
| `FakeLLMProvider` / `FakeDecisionProvider` | `providers/fake.py` | determinísticos, `fail_with`, `.requests` |
| `ProviderError` + 6 subclasses | `core/exceptions.py` | ver "Erros" |
| Suítes de contrato | `tests/contract/` | `LLMProviderContract`, `DecisionProviderContract` |

### Erros

| Erro | Quando |
|---|---|
| `ProviderRegistrationError` | id duplicado (em qualquer contrato), id vazio, objeto não implementa o contrato |
| `ProviderNotFoundError` | provider não declarado em `providers.yaml` ou sem adapter registrado |
| `ProviderNotEnabledError` | provider declarado com `enabled: false` (fail closed) |
| `ProviderTypeMismatchError` | id registrado no outro contrato (LLM ↔ decision) |
| `ModelNotFoundError` | alias ausente em `models.yaml` |
| `ProviderCallError` | falha na chamada; tradução de exceções do vendor; carrega `provider_id`, nunca prompt/output |

### Invariantes (implementadas e testadas)

1. Resultados ecoam `provider == adapter.provider_id` e `model == request.model`.
2. `DecisionResult.choice ∈ request.options`; `confidence` é probabilidade em [0, 1].
3. Nenhuma exceção de vendor atravessa o adapter; toda falha é `ProviderError`.
4. Registro nunca sobrescreve silenciosamente; lookup nunca devolve o contrato errado.
5. Modelo de provider desabilitado não é resolvível.
6. Nenhum SDK de vendor importado; nenhum acesso à rede; nenhuma API key lida.

## Decisões técnicas

- **Dois contracts pequenos, não uma interface única.** Alternativa: `AIProvider` com
  `complete/decide/...`. Impacto: Jev (V0.4) implementa só `decide`; embeddings, tools etc.
  entram como contracts novos quando houver consumidor.
- **`Protocol` runtime-checkable, não ABC.** Adapters não herdam de classes do Harness
  (isolamento de vendor); o registry verifica a forma no registro. Limitação: `isinstance`
  verifica presença de membros, não assinaturas — mypy e as suítes de contrato cobrem o resto.
- **Um registry com dois mapas tipados.** Alternativa: dois registries ou `Registry[T]`
  genérico. Impacto: ids únicos entre contratos e `ProviderTypeMismatchError` explícito sem
  `cast`/`Any`.
- **O adapter carrega seu `provider_id`**, igual à chave em `providers.yaml`; vários
  providers podem ter o mesmo `kind` (ex.: endpoints compatíveis com OpenAI).
- **Alias lógico ≠ `model_id` do vendor.** O schema já separava (chave vs `model_id`);
  mantido sem bump de `version`. Alternativa: renomear para `model:` (quebra de schema sem
  ganho). Impacto: o código usa o alias; trocar provider/model é edição em `models.yaml`.
- **`enabled` passa a ter efeito na resolução** (fail closed, RNF-006).
- **Resolver retorna `(provider, ResolvedModel)`** em vez de um objeto "binding". Menos
  tipos; o chamador monta o request com `model.model_id`.
- **Sem factory/bootstrap.** Não existe adapter concreto para construir a partir de `kind`;
  o chamador registra adapters. Entra com o primeiro adapter real.
- **Sem módulos `openai.py`/`anthropic.py`/`nvidia.py`/`jev.py`**, nem SDKs instalados.
- **Chamadas síncronas**, como o resto do código; async só se um adapter real exigir.
- **Fakes dentro do package** (`providers/fake.py`), não em `tests/`: são adapters reais dos
  contracts, reutilizáveis por suítes futuras. Nada os registra automaticamente.
- **Sem mudanças na CLI e no `doctor`.** Não há consumidor de inferência; o `doctor` já
  valida providers/models via `config_valid` e não deve checar conectividade.
- **`models.yaml` continua vazio e providers desabilitados.** Escolher modelos concretos de
  vendor é decisão de produto sem consumidor nesta versão (ver findings).
- **Versão do package `0.1.0` → `0.2.0`**, seguindo a convenção do V0.1.

## Estrutura de pastas

```text
engineering/orchestrator/
├── core/exceptions.py      # + ProviderError e subclasses
└── providers/              # novo
    ├── __init__.py
    ├── base.py             # contracts
    ├── registry.py         # ProviderRegistry
    ├── resolution.py       # ModelResolver, ResolvedModel
    └── fake.py             # FakeLLMProvider, FakeDecisionProvider
engineering/tests/
├── contract/               # novo: suítes reutilizáveis por adapter
│   ├── test_llm_provider_contract.py
│   └── test_decision_provider_contract.py
└── unit/
    ├── test_provider_contracts.py
    ├── test_provider_registry.py
    ├── test_model_resolution.py
    └── test_provider_isolation.py
```

## Fluxos principais

1. Código com alias `strong_reasoning` → `resolver.llm(...)` → adapter de `alpha` →
   `LLMResult(provider="alpha", model="<model_id>")`. Mudar `models.yaml` para `beta` altera o
   resultado sem alterar o código (`test_switching_provider_and_model_needs_only_configuration`).
2. Alias de decisão → `resolver.decision(...)` → `DecisionResult(choice, confidence)`.
3. Falhas de configuração → `ConfigValidationError` no `load_config` (provider inexistente,
   campo extra como `api_key`, `model_id` ausente/vazio).
4. Falhas de runtime → erros tipados listados acima, cada um com mensagem que diz o que corrigir.

Testes: `pytest` (235; 181 do V0/V0.1 preservados sem alteração + 54 novos), `ruff check .`,
`mypy` (strict, 19 arquivos).
Debug: as mensagens de erro nomeiam alias, provider e o que está declarado/registrado;
`fake.requests` mostra exatamente o que o adapter recebeu.

**Novo adapter real (futuro):** implementar o Protocol num módulo em `providers/`, traduzir
exceções do SDK para `ProviderCallError`, criar `Test<Adapter>(LLMProviderContract)` em
`tests/contract/` e registrar o adapter na composição. Nenhuma mudança no core.

## Critérios de saída

Trocar provider/model não exige alteração do core — **atendido**: o código chamador depende
apenas do alias e dos contracts; a troca é feita em `models.yaml` (provado por teste).

## Riscos

- `runtime_checkable` só verifica presença de membros; um adapter com assinatura errada
  passaria no registro (mitigado por mypy strict e pelas suítes de contrato).
- `choice ∈ options` é regra de contrato verificada por teste, não em runtime; um adapter real
  defeituoso só seria pego pela suíte de contrato.
- Contracts síncronos: adapters HTTP reais podem pedir async/timeout — mudança de contrato
  a decidir em V2/V0.4.
- `ProviderEntry.kind` ainda não tem consumidor; seu papel (seleção de adapter) só se
  concretiza com a primeira factory.
- `fake.py` é importável em produção; nada o registra, mas não há barreira técnica.

## Melhorias futuras

- Composição config → adapters (seleção por `kind`) quando existir o primeiro adapter real.
- Check de `doctor` para modelos que apontam para providers desabilitados/sem adapter,
  quando houver adapters reais.
- Timeout/retry/fallback na boundary do adapter (V15.1); metadata de uso/custo (V15.2).
- Validação runtime opcional de `DecisionResult` contra o request (wrapper no resolver).
- Referência de credenciais por nome de variável de ambiente, com o primeiro adapter real.
