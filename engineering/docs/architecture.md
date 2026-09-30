# Architecture — as built (V1.3)

Target architecture: [`../../docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md`](../../docs/03-ARCHITECTURE-AND-FOLDER-STRUCTURE.md).
This file records **what exists now** and the decisions taken to get here. Modules from
the target tree are created only when a version needs them.

## System map

| Module | Responsibility | Depends on |
|---|---|---|
| `orchestrator/__main__.py` | `python -m orchestrator` entry point | `cli` |
| `orchestrator/cli.py` | Typer app: root command (identity + help), global options (`--root`, `--log-level`, `--version`), `doctor`, `intake`, **V0.3** `memory` (health/add/search/update/delete) , **V0.4** `decision` (classify/route/severity/relevance/health) , **V1** `library` (inspect/resolve), **V1.1** `context discover`, **V1.2** `context classify` and **V1.3** `context budget` commands, rendering | `doctor`, `config`, `intake`, `core.admission`, `memory.service`, `decisions.service`, `library.*`, `context.discovery`, `context.classification.classifier`, `context.budget.budgeter`, `utils.logging` |
| `orchestrator/library/models.py` | **V1** Global Library contracts: `ArtifactType`, `Authority` (fixed per type), `PRECEDENCE`, `DIRECTORY_BY_TYPE`, `AppliesTo`, `ArtifactMetadata`/`SpecialtyMetadata` (schema v1), `Artifact`, `ProjectProfile`, `Match` | — (Pydantic only) |
| `orchestrator/library/loader.py` | **V1** `resolve_library_root` (explicit > `$HARNESS_LIBRARY_ROOT` > installation dir); discover → read → parse (front matter) → validate, with path-escape, size and file-type guards | `library.models`, `config` (`default_harness_root` only), `utils.files`, `utils.yaml_loader`, `core.exceptions` |
| `orchestrator/library/library.py` | **V1** `GlobalLibrary`: index (duplicate ids), reference checks, `artifacts`/`by_type`/`get`, deterministic `resolve(profile)` | `library.loader`, `library.models`, `core.exceptions` |
| `orchestrator/context/models.py` | **V1.1** `CandidateKind` (merge/output order), `ReferenceStore`, `CandidateReference`, `Provenance`, `ContextCandidate` (no classification/score fields), `SourceStatus`, `SourceReport`, `ContextDiscoveryResult`, `UNSUPPORTED_SOURCES` | `core.request` |
| `orchestrator/context/files.py` | **V1.1** `ProjectFiles`: configured-path containment (fatal), bounded sorted walks (pruning, no symlinked dirs, secret names, size limit), 8 KiB Markdown head for titles | `core.exceptions` |
| `orchestrator/context/discoverers.py` | **V1.1** `LibraryDiscoverer`, `InstructionsDiscoverer`, `AdrDiscoverer`, `DocumentationDiscoverer`, `RepositoryHintsDiscoverer` (+ `extract_hints`), `MemoryDiscoverer` (via `MemorySearcher` protocol), `UnconsultedSource` | `context.files/models`, `library`, `memory.models`, `core` |
| `orchestrator/context/discovery.py` | **V1.1** `ContextCandidateDiscovery` (run, merge by canonical resource, sort), `build_discovery(config, library, memory=...)`, `check_discovery_paths`; **V1.2** metadata-preserving merge (`merge_conflicts`) | `config`, `context.*`, `library`, `core` |
| `orchestrator/context/classification/models.py` | **V1.2** `ContextClass`, `SelectedBy`, `Evidence`, `ContextClassification` (+ invariants), `ClassifiedContextCandidate`, `ContextClassificationResult` (ordered, counts) | `context.models`, `core.request` |
| `orchestrator/context/classification/deterministic.py` | **V1.2** `ClassificationRule`, `DEFAULT_RULES` (ordered, first match wins), `DeterministicClassifier` | `classification.models`, `context.models`, `library.models` (`Authority`) |
| `orchestrator/context/classification/probabilistic.py` | **V1.2** `Decider` protocol, `decision_subject` (minimal safe input), `ProbabilisticClassifier` (outcome → class/fallback, per-run stop on provider failure, `max_decisions`) | `classification.models`, `decisions.models`, `providers.base`, `memory.safety` |
| `orchestrator/context/classification/classifier.py` | **V1.2** `ContextClassifier` (deterministic → decider → fallback), `build_classifier(config, decider=...)` | `config`, `classification.*`, `context.models` |
| `orchestrator/context/budget/models.py` | **V1.3** `BudgetCategory` (+ `CATEGORY_BY_KIND`), `BudgetStatus`, `BudgetReason`, `BudgetedItem` (wraps the classified candidate), `LimitConflict`, `BudgetUsage`, `ContextBudgetResult` (+ invariants: REQUIRED never left out for budget, EXCLUDED never selected, usage/status derived) | `config` (`BudgetSection`), `classification.models`, `context.models`, `core.request` |
| `orchestrator/context/budget/content.py` | **V1.3** `ContentLoader` protocol, `ContextContentLoader`: reference → safe text (project file via `ProjectFiles.check_file` + bounded read + binary/UTF-8 checks; library body via `GlobalLibrary.get`; memory excerpt) | `context.files`, `context.models`, `library`, `core.exceptions` |
| `orchestrator/context/budget/budgeter.py` | **V1.3** `ContextBudgeter` (REQUIRED → HIGH_VALUE → OPTIONAL, whole items, first fit; EXCLUDED never), `priority_key`, `build_budgeter(config, library)` | `config`, `budget.*`, `classification.models`, `context.discovery` (`project_files`), `context.models`, `library` |
| `orchestrator/utils/yaml_loader.py` | **V1** (extracted from `config.py`) safe YAML parsing that rejects duplicate keys; shared by config and library | — (PyYAML only) |
| `orchestrator/doctor.py` | Deterministic checks, aggregation (worst status wins), exit code; **V0.3** opt-in `memory` check; **V0.4** opt-in `decisions` check | `config`, `utils.shell`, `memory.service`, `decisions.service` |
| `orchestrator/config.py` | Harness-root resolution, YAML parsing, Pydantic schemas, cross-file checks, `HarnessConfig` (incl. `enabled_modes`) | `utils.files`, `core.exceptions`, `core.request` |
| `orchestrator/intake.py` | **V0.1** Normalization: raw strings from any origin → `EngineeringRequest` | `core.request`, `core.exceptions` |
| `orchestrator/core/request.py` | **V0.1** Domain contracts: `ExecutionMode`, `RequestSource`, `Intent`, `WorkflowState`, `SOURCES_BY_MODE`, `EngineeringRequest`, `AdmittedRequest` | — (Pydantic only) |
| `orchestrator/core/admission.py` | **V0.1** Core entry point: `admit()` — initial transition rule (→ `PLANNED`) | `core.request`, `core.exceptions` |
| `orchestrator/core/exceptions.py` | `HarnessError` hierarchy (incl. **V0.2** `ProviderError`, **V0.3** `MemoryStoreError` subtrees; **V0.4** `Decision*Error` under `ProviderCallError`, `InvalidDecisionRequestError`) | — |
| `orchestrator/providers/base.py` | **V0.2** Contracts: `LLMProvider`, `DecisionProvider` (Protocols), `LLMRequest/Result`, `DecisionRequest/Result`; **V0.4** `DecisionKind`, additive request/result fields (kind, subject, ordered, descriptions / probability, probabilities, score, resolved_model, input_tokens) | — (Pydantic only) |
| `orchestrator/providers/jev.py` | **V0.4** `JevDecisionProvider` (TypeSafe System One HTTP, stdlib urllib) + `JevHttpTransport`; only module that knows Jev | `providers.base`, `core.exceptions` |
| `orchestrator/decisions/models.py` | **V0.4** `DecisionOutcome`, `DecisionStatus`, `FallbackReason`, `DecisionTelemetry`, `DecisionHealth` | `providers.base` |
| `orchestrator/decisions/service.py` | **V0.4** `DecisionService` (request build → provider → boundary validation → threshold → outcome + telemetry), `open_decisions(config)` composition, `build_decision_adapter` | `config`, `providers.*`, `decisions.models`, `core.exceptions` |
| `orchestrator/providers/registry.py` | **V0.2** `ProviderRegistry`: provider id → adapter, typed per contract | `providers.base`, `core.exceptions` |
| `orchestrator/providers/resolution.py` | **V0.2** `ModelResolver`: alias → provider → `model_id` → adapter; `ResolvedModel` | `providers.registry`, `config` (types only), `core.exceptions` |
| `orchestrator/providers/fake.py` | **V0.2** `FakeLLMProvider`, `FakeDecisionProvider` (offline, deterministic, test-only) | `providers.base`, `core.exceptions` |
| `orchestrator/memory/models.py` | **V0.3** `ScopeKind`, `MemoryScope` (+ `namespace`), `SourceType`, `MemorySource` (lineage), `NewMemory`, `MemoryRecord`, `MemoryQuery`, `MemoryHit`, `MemoryHealth` | — (Pydantic only) |
| `orchestrator/memory/base.py` | **V0.3** `MemoryProvider` contract (Protocol): health, add, search, update, delete | `memory.models` |
| `orchestrator/memory/safety.py` | **V0.3** Safe ingestion policy: deterministic ALLOW/BLOCK rules, `ensure_safe` | `core.exceptions` |
| `orchestrator/memory/service.py` | **V0.3** `MemoryService` (validation → policy → provider) and `open_memory(config)` composition | `config`, `memory.*`, `core.exceptions` |
| `orchestrator/memory/mem0.py` | **V0.3** `Mem0MemoryProvider` (REST, stdlib urllib) + `HttpTransport`; only module that knows Mem0 | `memory.models`, `core.exceptions` |
| `orchestrator/memory/fake.py` | **V0.3** `FakeMemoryProvider` (offline, deterministic, test-only) | `memory.models`, `core.exceptions` |
| `orchestrator/utils/shell.py` | `run_command` → `CommandResult` (no shell, typed errors) | `core.exceptions` |
| `orchestrator/utils/files.py` | Path resolution and existence/read helpers | `core.exceptions` |
| `orchestrator/utils/logging.py` | Central logging config (stderr, WARNING default) | — |

Dependencies point one way: `cli → (doctor | intake) → config → utils → core` and
`providers.resolution → (providers.registry → providers.base) + config`. No module imports a
vendor SDK (guarded by `tests/unit/test_provider_isolation.py`). `core/` knows nothing about
CLI, YAML, Typer, `config` or `providers`; `providers/` knows nothing about CLI, intake,
requests or YAML parsing. Since V0.4 the CLI and `doctor` reach providers only through
`decisions.service.open_decisions`; only `decisions/service.py` imports `providers/jev.py`
(guarded by `tests/unit/test_decision_config.py`), and `decisions/` never imports an LLM.
`memory/` knows nothing about CLI, intake, requests or inference providers; only
`memory/service.py` imports the Mem0 adapter, and only `cli.py`/`doctor.py` open memory
(guarded by `tests/unit/test_memory_isolation.py`). `library/` (V1) knows nothing about
CLI, providers, memory, decisions, network or subprocesses; `core/` does not import it and
only `cli.py`/`doctor.py` and, since V1.1, `context/` consume it (guarded by
`tests/unit/test_library_isolation.py`). `context/` (V1.1) never imports CLI, doctor,
providers, decisions, the memory service/adapters, network or subprocesses; it
searches memory only through the `MemorySearcher` protocol, so opening memory stays with
`cli.py`/`doctor.py` (guarded by `tests/unit/test_context_discovery.py`). V1.2: only
`context/classification/probabilistic.py` imports the decision layer's *contracts*
(`decisions.models`, `providers.base`) and reaches Jev through the `Decider` protocol;
`open_decisions` stays in `cli.py` (same guard). V1.3: `context/budget/` follows the
same rules (no CLI, doctor, providers, decisions, network); earlier stages never import
later ones (discovery ↛ classification/budget, classification ↛ budget), and the budget
reads the library only to get an artifact body (guards in `test_context_discovery.py`,
`test_library_isolation.py`).

## Main flows

**Configuration load**

```text
resolve_harness_root(--root | $HARNESS_ROOT | package dir)   -> HarnessPathError
  └─ for each of the 10 required files:
       parse YAML (safe, duplicate keys rejected)              -> ConfigFileNotFoundError / ConfigParseError
       validate against its versioned, extra="forbid" model   -> ConfigValidationError
  └─ cross-file references (models→providers, roles→models,
     decisions.model→models)                                 -> ConfigValidationError
  └─ resolve project.root against harness root; must exist   -> ConfigValidationError
  └─ HarnessConfig (frozen)
```

**Doctor**

```text
python → harness_root → [permissions, config_files, config_valid, structure, memory*, decisions**, context****] → library*** → git → [git_repository]
**** context (V1.1): only when context.enabled — validates discovery paths (escape = FAIL), never discovers
     + classification (V1.2): structural strategy report; WARN if probabilistic without decisions.model; no call
     + budget (V1.3): structural budget report; WARN if a category limit >= usable; never loads content
                         (only if root found)                                                                          (only if git + config ok)
*** library (V1): always, offline, independent of the harness root — load errors FAIL, empty library WARN
* memory: only when memory.yaml has enabled: true — healthy PASS, unavailable WARN, misconfigured FAIL
** decisions: only when the decisions.model's provider is enabled — GET /v1/models (no inference):
   healthy PASS, unavailable WARN, missing/rejected key FAIL
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

Adapters are registered by the caller. Since V0.4 the one composition step that builds a
concrete adapter from `kind` is `decisions.service.build_decision_adapter` (`kind: jev`);
tests register fakes directly.

**Memory (V0.3)**

```text
harness memory add|search|update|delete|health  (explicit operator commands only)
        │
open_memory(config) ── memory disabled / $MEM0_API_KEY unset ──> MemoryConfigurationError
        │  memory.yaml (base_url, api_key_env, timeout) + environment
        ↓
MemoryService(provider, project)
  1. parse/validate: scope `<kind>[:<key>]`, source `<type>:<id>`, content ≤ 8000 chars
                                                      ──> InvalidMemoryInputError
  2. safe ingestion (add/update): ensure_safe(content, source.id)
                                                      ──> UnsafeMemoryContentError (nothing sent)
  3. MemoryProvider
        ↓
Mem0MemoryProvider ── HTTP (X-API-Key) ──> Mem0 self-hosted REST ──> pgvector
  scope   → Mem0 user_id = "<project>/<kind>[/<key>]"   (exact-match isolation)
  lineage → metadata harness_{schema,project,scope,scope_key,source_type,source_id}
  infer: false (stored verbatim)
  401/403 → MemoryConfigurationError · 404(id) → MemoryNotFoundError
  5xx/connection/timeout → MemoryUnavailableError · other → MemoryStoreError
```

Memory never overrides official docs, ADRs, policies, task/sprint contracts or Git; nothing
in the Harness reads memory to make a decision yet (Context Engineering, V1.x).

**Decision (V0.4)**

```text
harness decision classify|route|severity|relevance  (or any caller of DecisionService)
        │
open_decisions(config) ── decisions.model unset ─────────────> ProviderNotEnabledError
        │  ModelResolver.resolve(alias) ── jev disabled ──────> ProviderNotEnabledError
        │  build_decision_adapter(kind) ── $JEV_API_KEY ─> DecisionAuthenticationError
        │  ProviderRegistry.register_decision → resolver.decision(alias)
        ↓
DecisionService.decide(question, options, kind, subject, ordered, descriptions)
  1. DecisionRequest(model=model_id, ...)          ── invalid ──> InvalidDecisionRequestError
  2. JevDecisionProvider.decide ── POST /v1/systemone (Bearer) ──> api.typesafe.ai
       unordered → Choice question · ordered → Score question (score/(n-1) → 0..1)
       401/403 → DecisionAuthenticationError ─────────────────────> raised (+ telemetry "error")
       422/other → ProviderCallError ─────────────────────────────> raised (+ telemetry "error")
       timeout → DecisionTimeoutError ────────────┐
       429/529/5xx/unreachable → DecisionUnavailableError ┤──> FALLBACK_REQUIRED(timeout|unavailable)
       malformed / choice ∉ options → DecisionInvalidResponseError ┘──> FALLBACK_REQUIRED(invalid_response)
  3. boundary validation (every adapter): choice ∈ options, identity echoed,
     probabilities cover the options, score only if ordered ──> FALLBACK_REQUIRED(invalid_response)
  4. confidence < thresholds.minimum_confidence ────────────────> FALLBACK_REQUIRED(low_confidence) + result
  5. else DECIDED
  └─ DecisionTelemetry → JSON log line (orchestrator.decisions.telemetry, INFO) + on the outcome
```

The fallback is a value, never an action: nothing calls an LLM or a human in V0.4.

**Global Library (V1)**

```text
resolve_library_root(explicit | $HARNESS_LIBRARY_ROOT | installation dir)   -> LibraryStructureError
  (never --root / $HARNESS_ROOT: consumers share the installation's library)
GlobalLibrary.load(root)
  └─ for type in policy, guideline, rule, skill, specialty:           (fixed order)
       <root>/<type dir>/ must exist (may be empty), resolve inside root   -> LibraryStructureError
       for entry in sorted(dir): skip dotfiles; must be a regular *.md
         resolving inside its type dir (no symlink escape)                 -> LibraryStructureError
         size ≤ 256 KiB, UTF-8                                             -> ArtifactParseError
         '---' YAML front matter '---' (safe loader, no duplicate keys)    -> ArtifactParseError
         version == 1; type valid and == directory type                    -> ArtifactValidationError
         ArtifactMetadata / SpecialtyMetadata (extra keys forbidden)       -> ArtifactValidationError
         non-empty body (inert text)                                       -> ArtifactValidationError
  └─ index by (type, id): duplicates                                       -> ArtifactValidationError
  └─ specialty skills/rules references exist with that type                -> ArtifactValidationError
library.resolve(ProjectProfile(stack, capabilities))   # from project.yaml
  applies_to.always → "always"; stacks ∩ profile.stack → "stack:<x>"; capabilities ∩ … → "capability:<x>"
  → Match(artifact, reasons), ordered by authority (mandatory > recommended > knowledge), type, id
```

`harness library inspect [--type]` and `harness library resolve [--stack …] [--capability …]`
print these as JSON. Nothing selects, ranks or budgets knowledge for a prompt yet (V1.2+).

**Context Candidate Discovery (V1.1)**

```text
harness context discover "<instruction>" [--intent] [--ref]
  load_config → normalize_request(source=cli) → admit()          (same path as intake)
  GlobalLibrary.load(resolve_library_root())
  memory.enabled ? open_memory(config) (failure → reason, not an error) : none
  build_discovery(config, library, memory=…)
    context.enabled false ─────────────────────────────────────> ContextDiscoveryError
    every configured path resolves inside project root, else ──> ContextDiscoveryError
  ContextCandidateDiscovery.discover(request), fixed order:
    library           GlobalLibrary.resolve(ProjectProfile(stack, capabilities))
    instructions      instruction_files that exist
    adrs              walk adr_paths (*.md; README/index/template skipped; status, number)
    documentation     walk documentation_paths (.md .markdown .rst .txt .adoc)
    repository_hints  extract_hints(instruction, origin_ref):
                        path → project root, then each source root (dir → direct files)
                        file name → exact match in a bounded walk of source_roots
                        outside project / excluded dir / secret name → rejected (warning)
    memory            MemorySearcher.search(instruction, project scope, memory_results)
                        MemoryStoreError → UNAVAILABLE + warning; disabled → SKIPPED
  merge by canonical resource (resolved file / memory id): one candidate, all provenance,
    kind = first in CandidateKind order
  sort (kind order, id) → ContextDiscoveryResult(request, candidates, sources, unsupported)
```

No classification, score, budget, content loading, LLM or Jev in discovery.

**Context Classification (V1.2)**

```text
harness context classify "<instruction>" [--intent] [--ref]
  (same discovery as above) → ContextDiscoveryResult
  classification.probabilistic ? open_decisions(config) (failure → reason, not an error) : none
  build_classifier(config, decider=…) → ContextClassifier.classify(discovery)
    each candidate → DeterministicClassifier: DEFAULT_RULES in order, first match decides,
                     other matches → also_matched; memory never REQUIRED
    unresolved only:
      decider available → ProbabilisticClassifier, per candidate:
        provider stopped earlier ───────────> FALLBACK decision_unavailable
        calls ≥ max_decisions ──────────────> FALLBACK decision_limit_reached (+ warning)
        subject blocked by memory.safety ───> FALLBACK unsafe_decision_input (+ warning)
        DecisionService.decide(CONTEXT_RELEVANCE, options EXCLUDED<OPTIONAL<HIGH_VALUE, ordered)
          DECIDED ────────────────────────> PROBABILISTIC class, confidence, relevance=score
          low_confidence ─────────────────> FALLBACK + suggestion (not applied)
          invalid_response ───────────────> FALLBACK + warning (run continues)
          unavailable/timeout/raised error > FALLBACK + warning; provider stopped for the run
      no decider → FALLBACK no_decision_layer (+ one warning with the reason)
  ContextClassificationResult.build: every candidate (EXCLUDED kept), order (class, kind, id),
    counts, decisions (by selected_by), warnings (discovery + classification)
```

No budget, truncation, prompt selection or LLM here (budget: V1.3, below).

**Context Budget (V1.3)**

```text
harness context budget "<instruction>" [--intent] [--ref] [--content]
  (same discovery + classification as above; the library is loaded once and shared)
  build_budgeter(config, library): context.yaml budget + ContextContentLoader(ProjectFiles, library)
  ContextBudgeter.budget(classification), candidates sorted by priority_key:
    (class, deterministic < probabilistic < fallback, -confidence if probabilistic, kind, id)
    1. every REQUIRED: load
         no content (missing/binary/non-UTF-8/secret/too large/outside) ─> not_selected
                                     content_unavailable → status REQUIRED_UNAVAILABLE
         else ─> selected `required` (never limited by categories or max_*)
       REQUIRED usage > usable ─────> status REQUIRED_OVERFLOW (all REQUIRED kept)
       REQUIRED usage > category/max_* limit ─> `conflicts` (+ warning), kept
    2. HIGH_VALUE, then OPTIONAL, one by one (first fit, whole items):
         overflow ─> required_overflow · max_adrs/max_files/max_memories ─> *_reached
         (both before loading) · load failed ─> content_unavailable · size > usable or
         category limit ─> item_too_large · > usable remainder ─> total_budget_exhausted ·
         > category remainder ─> category_budget_exhausted · else selected within_budget
    3. EXCLUDED ─> excluded_by_classification (never loaded)
  ContextBudgetResult.build: usage (total, reserve, usable, used, remaining, overflow,
    by_category, files, adrs, memories) and status derived and validated
  CLI: JSON without item text unless --content; exit 0 SUCCESS, 3 otherwise
```

No Jev, no LLM, no reclassification, no truncation, no prompt rendering.

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

## Decisions (V0.3)

Rationale and alternatives: [`sprints/sprint-v0.3.md`](sprints/sprint-v0.3.md).

1. **`MemoryProvider` is its own contract** in `memory/`, not a provider in `providers/`:
   memory stores context; it neither infers nor decides.
2. **Mem0 via its self-hosted REST server**, called with stdlib `urllib` (no new
   dependency, no SDK). The `mem0ai` `MemoryClient` targets the hosted platform API, and
   embedding the library in-process would pull its LLM/embedder stack into the Harness.
3. **Safety and project binding live in `MemoryService`**, enforced once for every
   backend; adapters are pure translation layers.
4. **BLOCK or ALLOW, never REDACT.** A masked secret has no value in memory.
5. **Lineage is mandatory** (`<source_type>:<id>`, types from RF-017). Untraceable memory
   is not stored.
6. **Strict scope isolation**: one Mem0 `user_id` namespace per exact scope; search never
   crosses scopes, and the adapter re-checks the scope of every result.
7. **`infer: false`**: Harness memories are stored verbatim; no LLM rewrites them.
8. **Memory disabled by default**; `doctor` checks it only when enabled (unavailable = WARN).
9. **No automatic ingestion**: only explicit `harness memory` commands write.

## Decisions (V0.4)

Rationale and alternatives: [`sprints/sprint-v0.4.md`](sprints/sprint-v0.4.md).

1. **Evolve `DecisionProvider`, don't duplicate it.** New request/result fields are
   optional, so V0.2 call sites and fakes stay valid; no second decision contract.
2. **Jev over its documented HTTP API with stdlib urllib**, not the `typesafe-sdk`: one
   endpoint needed, zero new dependencies, and an injectable transport for offline tests
   (same choice as Mem0 in V0.3).
3. **Unordered options → Jev Choice; ordered options → Jev Score.** `score` exists only
   where Jev computes one (probability-weighted position), normalized by `n − 1` to 0..1.
   A Score answer has no `choice`: the Harness takes the most probable level (lower level
   wins ties).
4. **Three distinct metrics.** `confidence` = Jev's distribution concentration;
   `probability` = mass on the choice; `score` = ordinal position. None is derived from
   another by the Harness.
5. **`choice ∈ options` enforced twice**: in the adapter and, for every adapter, in
   `DecisionService`. A violation is never accepted.
6. **Fallback is a typed outcome, not an action.** Unavailable/timeout/invalid/low
   confidence → `FALLBACK_REQUIRED` + reason. Auth failures and rejected requests are
   raised: configuration bugs must not be silently routed to another layer.
7. **One threshold** (`minimum_confidence`); graded thresholds (auto/review/human) are
   V5.2. The default 0.70 is a starting value, not a calibration.
8. **Telemetry = typed record + one JSON log line**; it never contains the question,
   subject, descriptions or credentials.
9. **No retries in the adapter.** One call, one outcome; retry policy belongs to V5.
10. **Jev disabled by default**; `doctor` checks it only when enabled, without inference.

## Decisions (V1)

Rationale and alternatives: [`sprints/sprint-v1.md`](sprints/sprint-v1.md).

1. **The library belongs to the installation, not to the project.** Its root is resolved
   independently of `--root`/`$HARNESS_ROOT`; a consumer project declares only its profile.
2. **Target-tree layout**: `policies/ guidelines/ rules/ skills/ specialties/` directly
   under `engineering/` (`rules/` added); one flat directory per type.
3. **Markdown + YAML front matter**, schema `version: 1`, unknown keys rejected.
4. **Authority is derived from the type**, never declared: policy = mandatory, guideline
   and rule = recommended, skill and specialty = knowledge. It orders resolved output.
5. **Ids are unique per type**; the library-wide identity is `<type>/<id>`.
6. **Applicability is explicit**: `always: true` xor `stacks`/`capabilities`.
7. **Resolution = exact matching** against `project.yaml` `stack` + new optional
   `capabilities`; no aliases, no Jev, no LLM.
8. **Specialty references are validated, not expanded** by resolution.
9. **Fail fast, stable order**: the first error in (type, filename) order stops the load.

## Decisions (V1.1)

Rationale and alternatives: [`sprints/sprint-v1.1.md`](sprints/sprint-v1.1.md).

1. **Discovery is not classification**: candidates have no class, relevance or budget
   field; library authority and memory backend scores are metadata, not decisions.
2. **The request is the subject, not a candidate**; the result echoes it.
3. **Only sources with a real store**: library, instruction files, ADRs, docs, repository
   hints, memory. Task/sprint contracts, Git, runs, releases, findings are listed as
   unsupported, never simulated.
4. **References, not content**: store + project/library-relative path or memory id.
5. **Dedup by canonical resource** (resolved path / memory id), never by title; one
   candidate keeps every provenance; kind by `CandidateKind` priority.
6. **Explicit roots only**, relative and contained; unsafe configuration is fatal,
   missing or failing sources are warnings.
7. **Library via `GlobalLibrary.resolve`**, profile-based (not text-based).
8. **Memory through a protocol** (`MemorySearcher`), project scope, read-only, opt-in.
9. **`context.enabled` now gates discovery** (shipped `true`).

## Decisions (V1.2)

Rationale and alternatives: [`sprints/sprint-v1.2.md`](sprints/sprint-v1.2.md).

1. **Composition, not mutation**: `ClassifiedContextCandidate(candidate, classification)`.
2. **Deterministic first by construction**: resolved candidates never reach the decider.
3. **Ordered rule table, first match wins**; rule id = `Evidence` value (stable).
   Negative structural state (`superseded_adr`, `generated_artifact`) precedes explicit
   references: a named superseded ADR or generated file stays EXCLUDED, with the reference
   in `also_matched`.
4. **Jev cannot answer REQUIRED** (options EXCLUDED/OPTIONAL/HIGH_VALUE, ordered →
   `relevance` score); REQUIRED needs objective evidence.
5. **Threshold reused** from decisions.yaml (`minimum_confidence`), not duplicated.
6. **Conservative fallback = OPTIONAL**, always with structured evidence; failures are
   warnings, and an unavailable provider is not called again in the run.
7. **One decision per candidate** (no batch contract), bounded by `max_decisions`.
8. **No reasoning-LLM fallback**: no LLM runtime exists (V2.x); not simulated.
9. **Dedup keeps all metadata** (conflicts recorded) and `Provenance.match` makes
   explicit references structured.

## Decisions (V1.3)

Rationale and alternatives: [`sprints/sprint-v1.3.md`](sprints/sprint-v1.3.md).

1. **Characters, not tokens**: `len` of the loaded text (code points); no tokenizer,
   provider-neutral, exact. Bytes (`stat`) are a safety bound, never the measure.
2. **One reserve** (`usable = total − reserve`), not a model of every future prompt part.
3. **Classification is the authority**: priority is class first; within a class only
   signals V1.2 produced (selector, probabilistic confidence), then kind, then id.
4. **Whole items, first fit**: never truncated; a skipped item does not stop the scan.
5. **REQUIRED is never dropped**: over `usable` → `REQUIRED_OVERFLOW`; unloadable →
   `REQUIRED_UNAVAILABLE`; over a category/max_* limit → recorded `conflicts`.
   Invariants live in the models, not only in the engine.
6. **Six categories** (library, instructions, adrs, documentation, source_code, memory),
   one per real source family; the library is one bucket (authority is already in the class).
7. **Lazy, safe materialization** (`ContextContentLoader`): reuses `ProjectFiles` rules and
   the already-loaded library body; memory uses its excerpt (no `MemoryProvider` change).
8. **Budget decision is a separate layer**: items wrap the classified candidate; the
   classification reason is never overwritten; every candidate lands in exactly one list.
9. **CLI exit 3** for REQUIRED_OVERFLOW / REQUIRED_UNAVAILABLE (escalation needed; the
   JSON is still printed), mirroring `decision`'s fallback exit code.

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
- New memory backend → module in `memory/` implementing `MemoryProvider`, a
  `Test<Backend>(MemoryProviderContract)` subclass, a `backend` literal + section in
  `config.py`, and a branch in `open_memory`. `MemoryService` and callers do not change.
- New safe-ingestion rule → `RULES` in `memory/safety.py` + positive/negative examples in
  `tests/unit/test_memory_safety.py`.
- New scope or lineage type → `ScopeKind` / `SourceType` in `memory/models.py` (additive);
  renaming a value breaks stored metadata.
- Mem0 API change → `memory/mem0.py` and `tests/mem0_emulator.py` only.
- Jev API change → `providers/jev.py` and `tests/jev_emulator.py` only.
- New decision adapter → module in `providers/` implementing `DecisionProvider`, a
  `Test<Adapter>(DecisionProviderContract)` subclass, and a `kind` branch in
  `decisions.service.build_decision_adapter`. `DecisionService` and callers do not change.
- Decision threshold values → `config/decisions.yaml`; a new threshold field →
  `DecisionThresholds` in `config.py` + its consumer (V5.2 policy engine).
- New decision kind → `DecisionKind` in `providers/base.py` (additive) + CLI preset if needed.
- Pin the Jev version → `config/models.yaml` `model_id` (e.g. `jev-1.13.0`).
- New library artifact → one `.md` file in the type directory (`skills/`, ...); run
  `harness library inspect` / `doctor`. No code change.
- New artifact metadata field → `ArtifactMetadata` (or a type-specific subclass) in
  `library/models.py` + a consumer + tests; removing/renaming a field needs schema `version: 2`.
- New artifact type → `ArtifactType`, `AUTHORITY_BY_TYPE`, `DIRECTORY_BY_TYPE` (and
  `METADATA_MODEL_BY_TYPE` if it has its own fields) + the directory.
- New matching criterion → `AppliesTo` (field + `reasons`) and, if the project declares
  it, `ProjectSection` in `config.py` and `ProjectProfile`.
- New candidate source (e.g. Git in V7, runs in V8) → a `CandidateKind` value (its
  position = merge/output priority), a discoverer class in `context/discoverers.py`
  returning `Discovered`, wiring in `build_discovery`, and removal from
  `UNSUPPORTED_SOURCES`. Only when the source really exists.
- Discovery roots/limits → `config/context.yaml`; a new option → `DiscoverySection` + its
  consumer. Built-in excluded dirs / secret names → `context/files.py`.
- Hint extraction rules → `extract_hints` in `context/discoverers.py` (+ parametrized tests).
- New classification rule → `Evidence` member (`classification/models.py`, add it to
  `DETERMINISTIC_EVIDENCE`), a `ClassificationRule` at its precedence position in
  `DEFAULT_RULES` (`classification/deterministic.py`) + tests in
  `test_context_classification_rules.py`.
- Jev question/rubric/input allowlist → `QUESTION`, `DESCRIPTIONS`, `SAFE_METADATA` in
  `classification/probabilistic.py`. Fallback class → `FALLBACK_CLASS` (models.py).
- Classification options → `ClassificationSection` in `config.py` + `config/context.yaml`.
- Budget sizes/limits → `config/context.yaml` `budget`; a new limit → `BudgetSection` /
  `CategoryLimits` in `config.py` + its check in `budget/budgeter.py` + a `BudgetReason`.
- New budget category → `BudgetCategory` + `CATEGORY_BY_KIND` (`budget/models.py`) + a
  `CategoryLimits` field (a test keeps them equal).
- New candidate store → a branch in `ContextContentLoader.load` (`budget/content.py`).
- Selection order inside a class → `priority_key` (`budget/budgeter.py`).
