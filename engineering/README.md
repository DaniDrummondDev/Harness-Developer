# AI Engineering Harness — `engineering/`

Engineering control plane for LLM-assisted software delivery. The Harness governs the
workflow; LLMs and other providers are pluggable components, never the sole authority.

**Current version: V0.2 — Provider Abstraction.** It provides only:

- CLI (`python -m orchestrator` / `harness`)
- declarative configuration (`config/*.yaml`) with typed validation (Pydantic v2)
- `doctor` command (deterministic environment and foundation checks)
- logging, subprocess and filesystem helpers
- error model and unit tests
- **V0.1:** Interactive/Autonomous modes, the normalized `EngineeringRequest` contract,
  input normalization and request admission (`intake` command)
- **V0.2:** `LLMProvider` / `DecisionProvider` contracts, provider registry, model
  resolution from `models.yaml`/`providers.yaml`, deterministic offline fake adapters

No real provider integration (OpenAI, Anthropic, NVIDIA, Jev), memory, context, agent,
gate or state-machine capability exists yet; `intake` normalizes and admits a request but
executes nothing. See the official docs in
[`../docs/`](../docs/) (vision, requirements, architecture, roadmap).

## Requirements

- Python 3.12+
- Git (optional in V0; `doctor` warns if it is missing)
- No network access, API keys or external services are needed.

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

### Harness root resolution

The harness root is the folder containing `config/`. It is resolved **without depending on
the current working directory**:

1. `--root PATH`
2. `$HARNESS_ROOT`
3. the directory that contains the `orchestrator/` package (this `engineering/` folder,
   which works for source checkouts and editable installs)

If the chosen directory has no `config/`, the command fails with a clear message. A
non-editable (wheel) install must use `--root` or `$HARNESS_ROOT`.

## Configuration

All project-specific values live in `config/`; `orchestrator/` contains no project values.
All ten files are **required**, carry `version: 1`, and reject unknown keys.

| File | Content in V0 | Validated invariants |
|---|---|---|
| `project.yaml` | name, description, `root`, stack | `root` (relative to harness root) must be an existing directory |
| `providers.yaml` | provider id → `kind`, all `enabled: false` | identifier keys; a model of a disabled provider cannot be resolved (V0.2) |
| `models.yaml` | logical alias → `provider` + vendor `model_id` (empty) | each `provider` exists in `providers.yaml` |
| `agents.yaml` | roles, `model: null` | each non-null `model` exists in `models.yaml` |
| `modes.yaml` | `interactive` (enabled), `autonomous` (disabled) | exactly these two modes, both declared; `enabled` gates request admission |
| `context.yaml` | feature toggle (disabled) | — |
| `memory.yaml` | feature toggle (disabled) | `enabled: true` requires `backend` |
| `decisions.yaml` | escalation order | starts with `deterministic`, no repeats, `human` last |
| `risks.yaml` | LOW → CRITICAL, default | unique levels, default is a known level |
| `pipelines.yaml` | pipeline toggles (disabled) | identifier keys |

Never put secrets in these files. Future provider credentials will be referenced by
environment variable name, not by value.

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

No vendor adapter exists yet, so the shipped config keeps every provider disabled and
declares no models. Tests use the fakes; no network or API key is ever needed.

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

## Layout

```text
engineering/
├── orchestrator/          # generic Python core (no project values)
│   ├── __main__.py        # python -m orchestrator
│   ├── cli.py             # Typer app: root command, doctor, intake
│   ├── config.py          # root resolution, YAML parsing, schemas, loader
│   ├── doctor.py          # checks, aggregation, exit code
│   ├── intake.py          # raw input -> EngineeringRequest (normalization)
│   ├── core/request.py    # modes, sources, intents, EngineeringRequest
│   ├── core/admission.py  # admit(): initial state (planned)
│   ├── core/exceptions.py # HarnessError hierarchy
│   ├── providers/         # V0.2: contracts, registry, model resolution, fakes
│   └── utils/             # shell.py, files.py, logging.py
├── config/                # project-specific declarative configuration
├── templates/             # plain Markdown templates (adr, sprint, task)
├── docs/                  # as-built architecture and sprint records
└── tests/                 # unit/, integration/ and contract/ (reusable provider contract suites)
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
