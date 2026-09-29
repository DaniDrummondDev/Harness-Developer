# Architecture — as built (V0.2)

Target architecture: [`../../docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md`](../../docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md).
This file records **what exists now** and the decisions taken to get here. Modules from
the target tree are created only when a version needs them.

## System map

| Module | Responsibility | Depends on |
|---|---|---|
| `orchestrator/__main__.py` | `python -m orchestrator` entry point | `cli` |
| `orchestrator/cli.py` | Typer app: root command (identity + help), global options (`--root`, `--log-level`, `--version`), `doctor` and `intake` commands, rendering | `doctor`, `config`, `intake`, `core.admission`, `utils.logging` |
| `orchestrator/doctor.py` | Deterministic checks, aggregation (worst status wins), exit code | `config`, `utils.shell` |
| `orchestrator/config.py` | Harness-root resolution, YAML parsing, Pydantic schemas, cross-file checks, `HarnessConfig` (incl. `enabled_modes`) | `utils.files`, `core.exceptions`, `core.request` |
| `orchestrator/intake.py` | **V0.1** Normalization: raw strings from any origin → `EngineeringRequest` | `core.request`, `core.exceptions` |
| `orchestrator/core/request.py` | **V0.1** Domain contracts: `ExecutionMode`, `RequestSource`, `Intent`, `WorkflowState`, `SOURCES_BY_MODE`, `EngineeringRequest`, `AdmittedRequest` | — (Pydantic only) |
| `orchestrator/core/admission.py` | **V0.1** Core entry point: `admit()` — initial transition rule (→ `PLANNED`) | `core.request`, `core.exceptions` |
| `orchestrator/core/exceptions.py` | `HarnessError` hierarchy (incl. **V0.2** `ProviderError` subtree) | — |
| `orchestrator/providers/base.py` | **V0.2** Contracts: `LLMProvider`, `DecisionProvider` (Protocols), `LLMRequest/Result`, `DecisionRequest/Result` | — (Pydantic only) |
| `orchestrator/providers/registry.py` | **V0.2** `ProviderRegistry`: provider id → adapter, typed per contract | `providers.base`, `core.exceptions` |
| `orchestrator/providers/resolution.py` | **V0.2** `ModelResolver`: alias → provider → `model_id` → adapter; `ResolvedModel` | `providers.registry`, `config` (types only), `core.exceptions` |
| `orchestrator/providers/fake.py` | **V0.2** `FakeLLMProvider`, `FakeDecisionProvider` (offline, deterministic, test-only) | `providers.base`, `core.exceptions` |
| `orchestrator/utils/shell.py` | `run_command` → `CommandResult` (no shell, typed errors) | `core.exceptions` |
| `orchestrator/utils/files.py` | Path resolution and existence/read helpers | `core.exceptions` |
| `orchestrator/utils/logging.py` | Central logging config (stderr, WARNING default) | — |

Dependencies point one way: `cli → (doctor | intake) → config → utils → core` and
`providers.resolution → (providers.registry → providers.base) + config`. No module imports a
vendor SDK (guarded by `tests/unit/test_provider_isolation.py`). `core/` knows nothing about
CLI, YAML, Typer, `config` or `providers`; `providers/` knows nothing about CLI, intake,
requests or YAML parsing. Nothing in the CLI or `doctor` uses providers yet.

## Main flows

**Configuration load**

```text
resolve_harness_root(--root | $HARNESS_ROOT | package dir)   -> HarnessPathError
  └─ for each of the 10 required files:
       parse YAML (safe, duplicate keys rejected)              -> ConfigFileNotFoundError / ConfigParseError
       validate against its versioned, extra="forbid" model   -> ConfigValidationError
  └─ cross-file references (models→providers, roles→models)  -> ConfigValidationError
  └─ resolve project.root against harness root; must exist   -> ConfigValidationError
  └─ HarnessConfig (frozen)
```

**Doctor**

```text
python → harness_root → [permissions, config_files, config_valid, structure] → git → [git_repository]
                         (only if root found)                                       (only if git + config ok)
aggregate: worst of PASS < WARN < FAIL; exit 1 iff FAIL; empty report = FAIL; crashed check = FAIL
```

**Request intake (V0.1)**

```text
Interactive input (CLI today; MCP / Claude Code / Codex / HTTP API later) ─┐
                                                                           ├→ intake.normalize_request()
Autonomous input (roadmap / sprint / task / previous run / state; V6+)  ───┘        │  InvalidRequestError
                                                                                    ↓
                                                                          EngineeringRequest
                                                                                    ↓
                                               core.admission.admit(request, config.enabled_modes)
                                                                                    │  ModeNotEnabledError
                                                                                    ↓
                                                                AdmittedRequest(state=PLANNED)
```

`harness intake "<instruction>" [--intent] [--ref]` exercises this path with
`source=cli` and prints the `AdmittedRequest` as JSON. Nothing is executed.

**Provider resolution (V0.2)**

```text
providers.yaml + models.yaml ──load_config()──> HarnessConfig.providers / .models
                                                        │
                    ModelResolver(models, providers, registry)
                                                        │ .llm(alias) / .decision(alias)
  alias not declared ─────────────────────── ModelNotFoundError
  provider not declared ──────────────────── ProviderNotFoundError
  provider enabled: false ────────────────── ProviderNotEnabledError   (fail closed)
                                                        ↓
                          ResolvedModel(alias, provider, model_id)
                                                        │
            ProviderRegistry.llm(provider) / .decision(provider)
  no adapter registered ──────────────────── ProviderNotFoundError
  adapter is the other contract ──────────── ProviderTypeMismatchError
                                                        ↓
     LLMProvider.complete(LLMRequest(model=model_id, prompt))   -> LLMResult
     DecisionProvider.decide(DecisionRequest(model=model_id, question, options)) -> DecisionResult
  adapter/vendor failure ─────────────────── ProviderCallError (vendor exception chained)
```

Adapters are registered by the caller (today: tests, with the fakes). No factory builds
adapters from `kind` yet: there is no concrete adapter to build.

## Decisions (V0)

1. **`engineering/` is the portable harness root.** It holds the package, `config/`,
   templates, tests and `pyproject.toml`, matching the target tree and RNF-003. The official
   product docs stay at the repository's top-level `docs/`.
2. **Harness root is never derived from the cwd.** Precedence: `--root` > `$HARNESS_ROOT`
   > the directory containing the package. A wheel (non-editable) install must pass a root.
3. **All ten config files are required and versioned (`version: 1`), unknown keys rejected.**
   Fail fast over silent defaults. Defaults exist only where they are safe (e.g. `enabled: false`).
4. **Config files for future capabilities are declarative only.** Providers, memory, context,
   pipelines are validated structurally; nothing connects to anything.
5. **Decision layers are provider-agnostic** (`deterministic → probabilistic → reasoning →
   human`); the vendor (e.g. Jev) is bound later through `providers.yaml`. Invariants
   enforced now: deterministic first (RNF-030), human last (RNF-023), no repeats.
6. **Git is WARN, not FAIL, in `doctor`.** V0 performs no Git operations; Git becomes
   mandatory with Git Integration.
7. **No Jinja2 yet.** Templates are plain Markdown; there is no rendering consumer in V0.
8. **No interfaces/registries** (`LLMProvider`, `Gate`, `Tool`, ...) until a consumer exists.

## Decisions (V0.1)

Rationale and alternatives: [`sprints/sprint-v0.1.md`](sprints/sprint-v0.1.md).

1. **One contract, one core path.** Both modes produce the same `EngineeringRequest` and go
   through the same `admit()`; there is no per-mode orchestrator or branch.
2. **Mode ≠ source ≠ provider.** Mode is who started the work, source is where it came
   from; each source belongs to exactly one mode (`SOURCES_BY_MODE`), enforced by the model.
   Providers do not appear in the request.
3. **Intent is declared, never inferred.** Four values (`plan`, `implement`, `review`,
   `unclassified`); classification is the decision layer's job (V0.4+).
4. **Normalization lives outside `core/`** (`intake.py`), as a single generic function, not
   one adapter per source.
5. **`modes.yaml` gates admission.** Its keys are `ExecutionMode`, both modes must be
   declared, and a request of a disabled mode is refused (fail closed). Autonomous stays
   disabled in the shipped config.
6. **Only the initial state exists** (`WorkflowState.PLANNED`); the state machine is V6.

## Decisions (V0.2)

Rationale and alternatives: [`sprints/sprint-v0.2.md`](sprints/sprint-v0.2.md).

1. **Two small contracts, not one provider interface.** `LLMProvider.complete` and
   `DecisionProvider.decide`; Jev is not forced into the LLM shape.
2. **Structural contracts (`Protocol`, runtime-checkable).** Adapters do not inherit from
   Harness classes; the registry verifies the shape at registration.
3. **One registry, two typed maps.** Provider ids are unique across contracts; duplicates
   raise; a lookup under the wrong contract raises `ProviderTypeMismatchError`.
4. **Alias ≠ provider model id.** Code uses the `models.yaml` key; `model_id` goes to the
   vendor. Switching provider/model is a config change.
5. **`enabled` now has effect.** Resolving a model of a disabled provider fails closed.
6. **No factory/bootstrap, no vendor modules, no CLI/doctor changes.** Nothing concrete to
   build or diagnose yet; adding them now would be abstraction without a consumer.
7. **Errors translated at the adapter boundary** into `ProviderCallError`; messages carry
   the provider id, never prompts, outputs or secrets.

## Where to change things

- New CLI command → `cli.py` (`@app.command()`), logic in its own module.
- New config file/field → model in `config.py`, `CONFIG_FILES`, `HarnessConfig`, default YAML, tests.
- New doctor check → function in `doctor.py`, call from `run_doctor`, test in `test_doctor.py`.
- Structured/JSON logs → replace formatter/handler in `utils/logging.py` only.
- New request source → `RequestSource` + `SOURCES_BY_MODE` in `core/request.py`; tests in
  `test_request.py` enforce the partition.
- New intent → `Intent` in `core/request.py` (serialized value: breaking change only if renamed).
- New interface (MCP/HTTP) → call `intake.normalize_request()` then `admission.admit()`;
  add a source-specific parser in `intake.py` only if its payload needs one.
- New request field → `EngineeringRequest`; a removed/renamed field bumps `REQUEST_SCHEMA_VERSION`.
- New vendor adapter → new module in `providers/` implementing `LLMProvider` or
  `DecisionProvider`; translate vendor errors to `ProviderCallError`; add a
  `Test<Adapter>(LLMProviderContract)` subclass in `tests/contract/`. No core change.
- New provider capability (e.g. structured output) → a new field on the request/result or
  a new small contract in `providers/base.py`, only when a consumer needs it; update
  the contract suites.
- Switch provider/model for an alias → `config/models.yaml` only.
