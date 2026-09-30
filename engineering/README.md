# AI Engineering Harness — `engineering/`

Engineering control plane for LLM-assisted software delivery. The Harness governs the
workflow; LLMs and other providers are pluggable components, never the sole authority.

**Current version: V1.2 — Context Classification.** It provides only:

- CLI (`python -m orchestrator` / `harness`)
- declarative configuration (`config/*.yaml`) with typed validation (Pydantic v2)
- `doctor` command (deterministic environment and foundation checks)
- logging, subprocess and filesystem helpers
- error model and unit tests
- **V0.1:** Interactive/Autonomous modes, the normalized `EngineeringRequest` contract,
  input normalization and request admission (`intake` command)
- **V0.2:** `LLMProvider` / `DecisionProvider` contracts, provider registry, model
  resolution from `models.yaml`/`providers.yaml`, deterministic offline fake adapters
- **V0.3:** long-term operational memory on Mem0 self-hosted: `MemoryProvider` contract,
  Mem0 REST adapter, scopes (project/task/run/agent/release), lineage, safe ingestion
  policy, `memory` commands and an opt-in `doctor` check
- **V0.4:** probabilistic decisions with Jev (TypeSafe): `JevDecisionProvider` adapter,
  typed decisions (choice, score, probability, confidence), configurable confidence
  threshold, fallback contract (signalled, never executed), decision telemetry,
  `decision` commands and an opt-in `doctor` check
- **V1:** the Global Library — versioned skills, guidelines, policies, rules and
  specialties owned by the Harness installation, validated on load and resolved
  deterministically against the project's declared `stack`/`capabilities`; `library`
  commands and an offline `doctor` check
- **V1.1:** Context Candidate Discovery — given a request, a typed, deduplicated and
  deterministic list of sources that *may* be relevant (library artifacts, instruction
  files, ADRs, docs, files the request names, memory hits), each with provenance;
  `context discover` and a `context` doctor check
- **V1.2:** Context Classification — every discovered candidate gets exactly one of
  REQUIRED / HIGH_VALUE / OPTIONAL / EXCLUDED, with who decided (deterministic rule,
  Jev, or conservative fallback) and structured evidence; `context classify` and a
  structural `classification` doctor check. Nothing is budgeted or selected yet

Memory is auxiliary context, **never a source of truth** (docs, ADRs, policies, task
contracts and Git win), and nothing writes it automatically. **Jev is probabilistic**:
even a confidence of 1.0 is a model's belief, never a rule; deterministic rules always
come first, and the Harness only *signals* that a decision needs a fallback. No
generative inference provider (OpenAI, Anthropic, NVIDIA), context budget or selection, agent, gate or state-machine capability exists yet; `intake` normalizes and admits a request but
executes nothing. See the official docs in [`../docs/`](../docs/) (vision, requirements,
architecture, roadmap).

## Requirements

- Python 3.12+
- Git (optional in V0; `doctor` warns if it is missing)
- No network access, API keys or external services are needed for the core, the tests
  or `doctor`. Only the optional memory feature needs a running Mem0 server (see Memory),
  and only real decisions need a TypeSafe API key (see Decisions).

## Setup

```bash
cd engineering
python3.12 -m venv .venv            # or: uv venv --python 3.12 .venv
.venv/bin/pip install -e ".[dev]"   # or: uv pip install --python .venv/bin/python -e ".[dev]"
source .venv/bin/activate
```

The editable install makes `orchestrator` importable from any directory.

## Usage

```bash
python -m orchestrator              # identity + help
python -m orchestrator --help
python -m orchestrator --version
python -m orchestrator doctor       # exit 0 = no FAIL (WARN allowed), 1 = at least one FAIL
python -m orchestrator --root /path/to/harness doctor
python -m orchestrator --log-level DEBUG doctor   # logs go to stderr
harness doctor                      # same, via console script

# V0.1: normalize an interactive CLI request and admit it (prints JSON, executes nothing)
python -m orchestrator intake "add a health endpoint" --intent implement --ref T-1
```

`intake` exit codes: 0 admitted; 1 invalid request, disabled mode or invalid config
(`error: ...` on stderr); 2 usage error. `--intent` is one of `plan`, `implement`,
`review`, `unclassified` (default — intent is never guessed).

### Modes and requests (V0.1)

Every entry point is normalized into one `EngineeringRequest` (`orchestrator/core/request.py`)
and admitted by the core in state `planned` (`orchestrator/core/admission.py`):

| Mode | Started by | Sources |
|---|---|---|
| `interactive` | a human (or a tool acting for one) | `cli`, `mcp`, `claude_code`, `codex`, `http_api` |
| `autonomous` | the workflow, from persisted state | `roadmap`, `sprint`, `task`, `previous_run`, `persisted_state` |

Only `cli` has a real interface today. Autonomous requests must carry `origin_ref` and a
classified intent, and are refused while `autonomous.enabled` is `false` in `modes.yaml`.

### Memory (V0.3)

Explicit operations on long-term memory. Output is JSON; exit 1 with `error: ...` on any
failure (memory disabled, missing key, unsafe content, unknown id, backend down).

```bash
export MEM0_API_KEY=m0sk_...          # a key accepted by YOUR self-hosted server
python -m orchestrator memory health  # exit 0 only when healthy
python -m orchestrator memory add "Deploys run on Tuesdays" \
    --scope release:v1.0.0 --source release:v1.0.0
python -m orchestrator memory search "when do deploys run" --scope release:v1.0.0 --limit 5
python -m orchestrator memory update <id> "Deploys run on Wednesdays"
python -m orchestrator memory delete <id>
```

- **Scopes** (`--scope`): `project`, `task:<id>`, `run:<id>`, `agent:<id>`, `release:<id>`.
  Every memory also belongs to the project in `project.yaml`. A search sees **only** its
  exact scope.
- **Lineage** (`--source`, required): `<type>:<id>` with type one of `task_result`,
  `decision`, `finding`, `remediation`, `release`, `incident`, `implementation_note`.
- **Safe ingestion**: before anything is sent, content (and the source id) is checked for
  secrets — API keys/tokens of known formats, private keys, authorization headers,
  credentials in URLs, secret-named `.env`/YAML/quoted assignments. A match **blocks** the
  whole write (no redaction); the error names the rule, never the secret.
- Content is stored verbatim (`infer: false`), at most 8000 characters.

**Backend setup.** The Harness talks to the official Mem0 self-hosted REST server
(`server/` of the Mem0 repository: FastAPI + Postgres/pgvector, verified with mem0ai 2.2.1).
Run it following its README (`make bootstrap`), create an API key in its dashboard
(API Keys) and export it as `MEM0_API_KEY`. Then set `memory.enabled: true` in
`config/memory.yaml` (`base_url` defaults to `http://localhost:8888`). The server's own
LLM/embedder keys stay in the server's `.env`. Known pitfall: with mem0ai 2.2.1 the
server's `POSTGRES_PASSWORD` must not contain URI-reserved characters (`/ : @ ? #`); the
server builds an unescaped Postgres URI and every memory call then fails with HTTP 502
(`memory health` reports `unavailable`). Use e.g. `openssl rand -hex 32`.

Live proof (opt-in, needs the server): `HARNESS_MEM0_INTEGRATION=1 pytest -m mem0 -v`.

### Decisions (V0.4)

One probabilistic decision per command, answered by Jev. Output is a `DecisionOutcome`
as JSON. Exit codes: **0** decided, **3** fallback required, **1** Harness error (not
configured, provider disabled, missing/rejected key, invalid input), 2 usage error.

```bash
export JEV_API_KEY=...        # from console.typesafe.ai; never put it in YAML
# once: set providers.jev.enabled: true in config/providers.yaml
python -m orchestrator decision health      # auth + connectivity, no inference
python -m orchestrator decision classify "Fix failing authentication test"
python -m orchestrator decision route "Review PR #42 for security issues" \
    -o architect -o implementer -o reviewer
python -m orchestrator decision severity "Checkout returns 500 for every customer"
python -m orchestrator decision relevance "ADR-007: money is integer cents" \
    --task "Add a discount field to invoices"
python -m orchestrator --log-level INFO decision classify "..."   # + telemetry JSON on stderr
```

Each command has preset options (e.g. `bug/feature/refactor`, `low..critical`) that
`-o/--option` replaces and a preset question that `-q/--question` replaces. The presets
are CLI conveniences, not Harness enums.

| Field | Meaning |
|---|---|
| `result.choice` | one of the options; **validated by the Harness**, never trusted from the provider |
| `result.confidence` | 0..1, how concentrated the distribution is (Jev's own measure) |
| `result.probability` / `probabilities` | 0..1 probability of the choice / of every option |
| `result.score` | ordered decisions only (`severity`): 0 = first option, 1 = last option |
| `result.resolved_model` | exact model version that answered (e.g. `jev-1.13.0`) |
| `status` / `fallback_reason` | `decided`, or `fallback_required` + `low_confidence`, `unavailable`, `timeout`, `invalid_response` |

Configuration: `decisions.yaml` → `model` (alias, default `decision`) and
`thresholds.minimum_confidence` (default 0.70, uncalibrated: tune it on your data);
`models.yaml` → `decision: {provider: jev, model_id: jev-latest}`; `providers.yaml` →
`jev: {enabled, base_url, api_key_env, timeout_seconds}`. A below-threshold answer is
returned for audit, but its choice is not accepted. The Harness never calls an LLM or a
human as a fallback in V0.4 (Decision Policy Engine: V5).

Live proof (opt-in, costs tokens):
`HARNESS_JEV_INTEGRATION=1 JEV_API_KEY=... pytest -m jev -v -s`.

### Global Library (V1)

Reusable engineering knowledge that ships with the Harness and is **inherited, not
copied**, by every project. A project only declares its profile in `config/project.yaml`:

```yaml
project:
  stack: [php, laravel, mysql, redis, docker]   # technologies
  capabilities: [api]                          # what it has/does (optional)
```

```bash
python -m orchestrator library inspect                 # every artifact (metadata JSON)
python -m orchestrator library inspect --type policy   # one type
python -m orchestrator library resolve                 # what applies to project.yaml, and why
python -m orchestrator library resolve --stack laravel --stack mysql --capability api
```

Exit codes: 0 ok; 1 invalid library or config (`error: ...` on stderr); 2 usage error.

| Type | Directory | Authority | Meaning |
|---|---|---|---|
| policy | `policies/` | mandatory | non-negotiable; nothing below overrides it |
| guideline | `guidelines/` | recommended | convention / expected practice |
| rule | `rules/` | recommended | one concrete, verifiable instruction |
| skill | `skills/` | knowledge | how to do a kind of work well |
| specialty | `specialties/` | knowledge | a domain; references skills and rules |

Authority comes from the type (it cannot be declared) and orders the output: policies
first. **Artifact format** — one Markdown file per artifact with YAML front matter:

```markdown
---
version: 1                  # schema version (only 1)
id: laravel                 # ^[a-z][a-z0-9_-]*$, unique per type
type: skill                 # must match the directory
name: Laravel
description: How to implement features in Laravel ...
tags: [php, web]            # optional classifiers
applies_to:                 # exactly one form:
  stacks: [laravel]         #   stacks and/or capabilities (exact match), or
  # always: true            #   every project
# specialties only:  skills: [laravel, database]   rules: [thin-controllers]
---
Markdown body (inert text; never executed or rendered).
```

The library is loaded from `$HARNESS_LIBRARY_ROOT` if set, else from the Harness
installation (this `engineering/` folder) — **never** from `--root`/`$HARNESS_ROOT`, so a
consumer project with its own `config/` still uses the one shared library. Loading fails
fast on: missing type directory, unexpected file or subdirectory, symlink leaving its
directory, file > 256 KiB, non-UTF-8, missing/invalid front matter, duplicate YAML key,
unsupported `version`, invalid or mismatched `type`, unknown field, missing `id`,
duplicate id, empty body, unknown specialty reference. Resolution is exact string
matching (no aliases, Jev or LLM); choosing what enters a prompt is V1.1+.

### Context Candidate Discovery (V1.1)

Answers *"which sources exist that could matter for this request?"* — not which are
best, not what enters a prompt, not how much fits (V1.2+). No LLM, no Jev.

```bash
python -m orchestrator context discover "fix rounding in billing/invoice.py" \
    --intent implement --ref T-12            # ContextDiscoveryResult as JSON
```

Exit codes: 0 result printed (warnings are inside the JSON); 1 invalid request, config or
library, `context.enabled: false`, or a discovery path escaping the project; 2 usage error.

| Discoverer | Finds | Candidate id |
|---|---|---|
| `library` | Global Library artifacts applying to `project.yaml` (via `GlobalLibrary.resolve`) | `policy/secrets`, `skill/laravel` |
| `instructions` | existing `instruction_files` (CLAUDE.md, AGENTS.md, ...) | `instructions/CLAUDE.md` |
| `adrs` | Markdown ADRs under `adr_paths` (+ `status`, `number`) | `adr/docs/adr/0001-x.md` |
| `documentation` | `.md/.rst/.txt/.adoc` under `documentation_paths` | `doc/docs/guide.md` |
| `repository_hints` | files the request/`--ref` names: paths (project root or `source_roots`), a directory's direct files, exact file names under `source_roots` | `source/src/billing/invoice.py` |
| `memory` | project-scope memory hits (only when `memory.enabled`; failures are warnings) | `memory/<id>` |

Each candidate has `id`, `kind`, `title`, `reference` (`store` project/library/memory +
relative `path`), `provenance` (discoverer + reason) and kind-specific `metadata`
(authority, ADR status, size, memory lineage...). No content is loaded, except the first
8 KiB of Markdown files for the title and a ≤280-char memory excerpt. The same resource
found by several discoverers is **one** candidate with several provenance entries.
Output order: policies, guidelines, rules, skills, specialties, instructions, ADRs, docs,
source, memory; then id. The request itself is echoed as `request` (it is the subject,
not a candidate). Not supported yet (listed as `unsupported_sources`): task/sprint
contracts, Git, previous runs, releases, findings.

Safety: configured paths are relative (no `/`, `~`, `..`), resolved and required to stay
inside the project; symlinked directories are not followed; `.git`, virtualenvs,
`node_modules`, `vendor`, caches, `build`/`dist`, hidden entries and `exclude_dirs` are
pruned; secret-looking files (`.env*`, keys, credentials) are never candidates; walks stop
at `max_files`; files over `max_file_bytes` are skipped unread.

Duplicates keep every provenance entry and all metadata; if two sources disagree on a
metadata value, the winning kind's value is kept and the dropped one is listed under
`metadata.merge_conflicts`. `repository_hints` provenance carries `match` (`path`,
`file_name`, `ambiguous_file_name`, `directory`).

### Context Classification (V1.2)

Answers *"how important is each candidate for this request?"* — not how much fits or
what enters the prompt (V1.3+).

```bash
python -m orchestrator context classify "fix rounding in src/billing/ per docs/adr/0001.md"
# discover + classify: ContextClassificationResult as JSON (counts, decisions, warnings)
```

Exit codes as for `context discover`; an unavailable decision layer is a warning, not an error.

| Class | Meaning |
|---|---|
| `REQUIRED` | must be available for a correct/safe execution |
| `HIGH_VALUE` | strongly related; very likely improves the work |
| `OPTIONAL` | possibly useful; also the conservative fallback |
| `EXCLUDED` | not to be considered (kept in the output for audit) |

Order of decision: **deterministic rules** (first match wins, never overridden) →
**Jev** for candidates no rule resolves (only when `context.classification.probabilistic`
and the decision provider is enabled; options EXCLUDED/OPTIONAL/HIGH_VALUE — it can never
answer REQUIRED; accepted at `decisions.yaml` `minimum_confidence`) → **fallback OPTIONAL**
(no decision layer, low confidence, invalid answer, provider down — the provider is not
called again in that run —, `max_decisions` reached, or secret-looking input, which is never
sent). Memory is never REQUIRED.

| Rule (`evidence`) | Class |
|---|---|
| `applicable_policy` (authority mandatory) | REQUIRED |
| `superseded_adr` (status superseded/deprecated/rejected/obsolete) | EXCLUDED |
| `generated_artifact` (lock file, `.min.js/.css`, `.map`) | EXCLUDED |
| `explicit_source_reference` / `explicit_document_reference` / `explicit_library_reference` (request names the path or a unique file name) | REQUIRED |
| `project_instruction` (configured instruction file) | REQUIRED |
| `applicable_guideline` / `applicable_library_rule` (authority recommended) | HIGH_VALUE |
| `matching_stack` / `matching_capability` (skill/specialty applying via the profile) | HIGH_VALUE |
| `named_directory_entry` (file in a directory the request names) | HIGH_VALUE |

Rules are listed in precedence order (first match decides). A negative structural state
beats an explicit reference: naming a superseded ADR or a lock file keeps it EXCLUDED,
with the reference recorded in `also_matched`.

Each output item is `{candidate, classification}`; `classification` has `classification`,
`selected_by` (`deterministic`/`probabilistic`/`fallback`), `evidence`, `reason`,
`also_matched`, and for Jev `confidence`, `relevance` (ordered score), `provider`, `model`
(`suggestion` when a low-confidence answer was not accepted). Items are ordered by class,
kind, id — stability only, not a selection.

### Harness root resolution

The harness root is the folder containing `config/`. It is resolved **without depending on
the current working directory**:

1. `--root PATH`
2. `$HARNESS_ROOT`
3. the directory that contains the `orchestrator/` package (this `engineering/` folder,
   which works for source checkouts and editable installs)

If the chosen directory has no `config/`, the command fails with a clear message. A
non-editable (wheel) install must use `--root` or `$HARNESS_ROOT`, and
`$HARNESS_LIBRARY_ROOT` for the Global Library (the wheel ships only the package).

## Configuration

All project-specific values live in `config/`; `orchestrator/` contains no project values.
All ten files are **required**, carry `version: 1`, and reject unknown keys.

| File | Content in V0 | Validated invariants |
|---|---|---|
| `project.yaml` | name, description, `root`, `stack`, `capabilities` (V1, optional) | `root` (relative to harness root) must be an existing directory; stack/capabilities are lowercase ids |
| `providers.yaml` | provider id → `kind`, all `enabled: false`; optional `base_url`, `api_key_env`, `timeout_seconds` (jev) | identifier keys; a model of a disabled provider cannot be resolved (V0.2); http(s) URL; env var name; no key values |
| `models.yaml` | logical alias → `provider` + vendor `model_id` (`decision` → jev) | each `provider` exists in `providers.yaml` |
| `agents.yaml` | roles, `model: null` | each non-null `model` exists in `models.yaml` |
| `modes.yaml` | `interactive` (enabled), `autonomous` (disabled) | exactly these two modes, both declared; `enabled` gates request admission |
| `context.yaml` | `enabled` (true; gates `context discover`/`classify`), `discovery`: `instruction_files`, `documentation_paths`, `adr_paths`, `source_roots`, `exclude_dirs`, `max_files`, `max_file_bytes`, `memory_results` (V1.1); `classification`: `probabilistic` (true), `max_decisions` (50) (V1.2; the threshold is decisions.yaml's) | paths relative POSIX, no `..`/absolute/`~`, normalized; limits bounded; unknown keys rejected |
| `memory.yaml` | `enabled` (false), `backend: mem0`, `mem0: {base_url, api_key_env, timeout_seconds}` | `enabled` requires `backend`; `mem0` backend requires its section; http(s) URL; env var name; no key values |
| `decisions.yaml` | escalation order; `model` alias + `thresholds.minimum_confidence` (V0.4) | starts with `deterministic`, no repeats, `human` last; `model` exists in `models.yaml`; `model` requires `thresholds`; threshold in 0..1 |
| `risks.yaml` | LOW → CRITICAL, default | unique levels, default is a known level |
| `pipelines.yaml` | pipeline toggles (disabled) | identifier keys |

Never put secrets in these files. Credentials are referenced by environment variable
name (e.g. `memory.mem0.api_key_env: MEM0_API_KEY`), never by value; unknown keys such as
`api_key:` are rejected.

**Adding a config file:** define its model in `orchestrator/config.py`, register it in
`CONFIG_FILES`, expose it on `HarnessConfig`, ship a default YAML and add tests.

### Providers (V0.2)

Code refers to a **logical model alias** (a `models.yaml` key); `ModelResolver` maps it
to the provider and the vendor's `model_id`, then fetches the adapter from the
`ProviderRegistry`. Changing provider or model is a config edit:

```python
from orchestrator.providers.base import LLMRequest
from orchestrator.providers.fake import FakeLLMProvider
from orchestrator.providers.registry import ProviderRegistry
from orchestrator.providers.resolution import ModelResolver

registry = ProviderRegistry()
registry.register_llm(FakeLLMProvider("openai"))      # a real adapter will go here later
resolver = ModelResolver(models=config.models, providers=config.providers, registry=registry)
provider, model = resolver.llm("reasoning")          # needs `openai` enabled in providers.yaml
result = provider.complete(LLMRequest(model=model.model_id, prompt="..."))
```

The only concrete adapter is Jev (decisions, V0.4); it is declared but disabled in the
shipped config, and `open_decisions(config)` (orchestrator/decisions/service.py) builds
it. No generative adapter exists yet. Tests use the fakes and a Jev emulator; no network
or API key is ever needed outside the opt-in live tests.

## Doctor checks

| Check | FAIL when | WARN when |
|---|---|---|
| `python` | Python < 3.12 | — |
| `harness_root` | no `config/` at resolved root | — |
| `permissions` | root/config not readable | — |
| `config_files` | a required file is missing | — |
| `config_valid` | parse/schema/reference/path error | — |
| `structure` | — | `templates/` or `docs/` missing |
| `git` | — | git not installed |
| `git_repository` | — | project root is not a git work tree |
| `memory` (only if `memory.enabled`) | API key unset, credentials rejected, bad URL | backend unreachable / failing |
| `decisions` (only if the decision model's provider is enabled) | `$JEV_API_KEY` unset, credentials rejected | provider unreachable / rate limited / 5xx |
| `library` (always, offline) | any library structure/parse/schema/duplicate/reference error | library has no artifacts |
| `context` (only if `context.enabled`; validates paths, never discovers) | a discovery path resolves outside the project | — (absent optional paths are listed in the PASS detail) |
| `classification` (with `context`; structural, offline, never classifies) | — | `probabilistic: true` but decisions.yaml has no model |

## Layout

```text
engineering/
├── orchestrator/          # generic Python core (no project values)
│   ├── __main__.py        # python -m orchestrator
│   ├── cli.py             # Typer app: doctor, intake, memory, decision, library, context
│   ├── config.py          # root resolution, YAML parsing, schemas, loader
│   ├── doctor.py          # checks, aggregation, exit code
│   ├── intake.py          # raw input -> EngineeringRequest (normalization)
│   ├── core/request.py    # modes, sources, intents, EngineeringRequest
│   ├── core/admission.py  # admit(): initial state (planned)
│   ├── core/exceptions.py # HarnessError hierarchy
│   ├── providers/         # V0.2: contracts, registry, model resolution, fakes; V0.4: jev.py
│   ├── memory/            # V0.3: MemoryProvider, Mem0 adapter, safety policy, service, fake
│   ├── decisions/         # V0.4: DecisionService, outcome/fallback/telemetry models
│   ├── library/           # V1: Global Library models, loader, GlobalLibrary (resolve)
│   ├── context/           # V1.1: candidate models, safe file access, discoverers, discovery
│   │   └── classification/ # V1.2: models, deterministic rules, Jev classifier, composition
│   └── utils/             # shell.py, files.py, logging.py, yaml_loader.py
├── config/                # project-specific declarative configuration
├── policies/              # V1 Global Library content (shared by every project):
├── guidelines/            #   one Markdown + front matter file per artifact
├── rules/
├── skills/
├── specialties/
├── templates/             # plain Markdown templates (adr, sprint, task)
├── docs/                  # as-built architecture and sprint records
└── tests/                 # unit/, integration/ (opt-in live Mem0 / Jev), contract/ suites
```

## Development

```bash
pytest                    # all tests
ruff check .              # lint
mypy                      # strict type checking of orchestrator/
```

### Debugging

- `--log-level DEBUG` shows config/command activity on stderr (never secrets or full argv).
- Config errors always include the file path and the failing field path
  (e.g. `config/risks.yaml: risks: Value error, default risk 'EXTREME' is not one of [...]`).
- `doctor` never raises: an unexpected crash inside a check is reported as FAIL.
- Memory: `memory health` tells *unavailable* (network/5xx) from *misconfigured*
  (URL, key); `--log-level DEBUG` logs each Mem0 call as method, path and status only.
- Decisions: `decision health` tells *unavailable* (network/429/5xx) from *misconfigured*
  (key). `--log-level INFO` prints one telemetry JSON line per decision (provider, model,
  choice, confidence, score, duration, fallback reason, error category — never the
  question, subject or key). A `fallback_required` outcome carries a sanitized `detail`.
