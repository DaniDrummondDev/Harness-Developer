"""Command-line interface (Typer).

Entry points: `python -m orchestrator` and the `harness` console script.

Output conventions:
- primary output (tables, messages) -> stdout via `console`;
- logs -> stderr via utils/logging.py (silent by default);
- `doctor`: exit 0 when no check FAILs, 1 otherwise (it never raises);
- `intake`: admitted request as JSON on stdout, exit 0; a rejected request or
  invalid configuration -> `error: ...` on stderr, exit 1;
- `memory ...`: result as JSON on stdout, exit 0; any Harness error (disabled
  memory, missing key, unsafe content, unknown id, backend down) -> `error: ...`
  on stderr, exit 1; `memory health` exits 1 unless the backend is healthy;
- `decision ...` (V0.4): DecisionOutcome as JSON on stdout; exit 0 when DECIDED,
  3 when FALLBACK_REQUIRED (low confidence, provider unavailable/timeout, invalid
  response), 1 on a Harness error (not configured, disabled, missing/rejected key);
  `decision health` exits 1 unless the provider is healthy. Decision telemetry is
  logged as JSON at INFO (`--log-level INFO`), on stderr;
- `library inspect|resolve` (V1): JSON on stdout, exit 0; an invalid library or
  config -> `error: ...` on stderr, exit 1; unknown --type or malformed
  --stack/--capability -> usage error, exit 2;
- usage errors (unknown command/option, bad --log-level) -> Typer/Click, exit 2.

Commands: root (identity + help), `doctor` (V0), `intake` (V0.1), the
`memory` group (V0.3: health, add, search, update, delete), the `decision`
group (V0.4: classify, route, severity, relevance, health) and the `library`
group (V1: inspect, resolve). New
commands are added as `@app.command()` functions here, delegating logic to
their own module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError as PydanticValidationError
from rich.console import Console
from rich.table import Table

from orchestrator import HARNESS_NAME, __version__
from orchestrator.config import HARNESS_ROOT_ENV, load_config, resolve_harness_root
from orchestrator.core.admission import admit
from orchestrator.core.exceptions import HarnessError
from orchestrator.core.request import Intent, RequestSource
from orchestrator.decisions.service import open_decisions
from orchestrator.doctor import CheckStatus, DoctorReport, run_doctor
from orchestrator.intake import normalize_request
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.loader import resolve_library_root
from orchestrator.library.models import ArtifactType, ProjectProfile
from orchestrator.memory.service import MemoryService, open_memory
from orchestrator.providers.base import DecisionKind
from orchestrator.utils.logging import LEVELS, configure_logging

console = Console()

app = typer.Typer(
    name="harness",
    help=f"{HARNESS_NAME} — engineering control plane for LLM-assisted software delivery.",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode=None,
)

_STATUS_STYLE = {
    CheckStatus.PASS: "green",
    CheckStatus.WARN: "yellow",
    CheckStatus.FAIL: "bold red",
}


@dataclass(frozen=True, slots=True)
class CliState:
    root: Path | None


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"{HARNESS_NAME} {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def root_command(
    ctx: typer.Context,
    root: Annotated[
        Path | None,
        typer.Option(
            "--root",
            help=f"Harness root containing config/. Overrides ${HARNESS_ROOT_ENV}.",
            file_okay=False,
        ),
    ] = None,
    log_level: Annotated[
        str,
        typer.Option("--log-level", help=f"Log level for stderr: {', '.join(LEVELS)}."),
    ] = "WARNING",
    version: Annotated[
        bool,
        typer.Option(
            "--version", help="Show version and exit.", callback=_version_callback, is_eager=True
        ),
    ] = False,
) -> None:
    """AI Engineering Harness — engineering control plane (V1 global library)."""
    try:
        configure_logging(log_level)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--log-level") from exc
    ctx.obj = CliState(root=root)

    if ctx.invoked_subcommand is None:
        console.print(f"[bold]{HARNESS_NAME}[/bold] {__version__}")
        console.print("Engineering control plane: the workflow governs agents; LLMs are pluggable.")
        console.print()
        console.print(ctx.get_help(), markup=False, highlight=False)


def _render_report(report: DoctorReport) -> None:
    table = Table(title=f"{HARNESS_NAME} — doctor", show_lines=False)
    table.add_column("Status", no_wrap=True)
    table.add_column("Check", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    for result in report.results:
        style = _STATUS_STYLE[result.status]
        table.add_row(f"[{style}]{result.status}[/{style}]", result.name, result.detail)
    console.print(table)
    style = _STATUS_STYLE[report.status]
    console.print(
        f"Overall: [{style}]{report.status}[/{style}] "
        f"({report.count(CheckStatus.PASS)} pass, {report.count(CheckStatus.WARN)} warn, "
        f"{report.count(CheckStatus.FAIL)} fail)"
    )


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Verify the local environment, configuration and project foundation.

    Exit code 0 when no check fails (warnings allowed), 1 otherwise.
    """
    state: CliState = ctx.obj
    report = run_doctor(state.root)
    _render_report(report)
    raise typer.Exit(code=report.exit_code)


@app.command()
def intake(
    ctx: typer.Context,
    instruction: Annotated[str, typer.Argument(help="What is being asked, in natural language.")],
    intent: Annotated[
        str | None,
        typer.Option(
            "--intent",
            help=f"Kind of work: {', '.join(Intent)}. Default: {Intent.UNCLASSIFIED}.",
        ),
    ] = None,
    ref: Annotated[
        str | None,
        typer.Option("--ref", help="Originating artifact, e.g. a task or sprint id."),
    ] = None,
) -> None:
    """Normalize an interactive CLI request and admit it into the workflow.

    Prints the admitted request (initial state) as JSON. Nothing is executed:
    no LLM, provider or task runs in this version.
    """
    state: CliState = ctx.obj
    try:
        config = load_config(resolve_harness_root(state.root))
        request = normalize_request(
            source=RequestSource.CLI, instruction=instruction, intent=intent, origin_ref=ref
        )
        admitted = admit(request, config.enabled_modes)
    except HarnessError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(admitted.model_dump_json(indent=2))


# --- memory (V0.3) -------------------------------------------------------------------

memory_app = typer.Typer(
    help="Long-term operational memory (Mem0 self-hosted). Explicit operations only; "
    "memory is auxiliary context, never a source of truth.",
    no_args_is_help=True,
    rich_markup_mode=None,
)
app.add_typer(memory_app, name="memory")

_SCOPE_HELP = "project | task:<id> | run:<id> | agent:<id> | release:<id>"


def _memory_service(ctx: typer.Context) -> MemoryService:
    state: CliState = ctx.find_root().obj
    return open_memory(load_config(resolve_harness_root(state.root)))


def _fail(exc: HarnessError) -> NoReturn:
    typer.echo(f"error: {exc}", err=True)
    raise typer.Exit(code=1) from exc


def _echo_json(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


@memory_app.command("health")
def memory_health(ctx: typer.Context) -> None:
    """Check connectivity and credentials of the memory backend. Exit 0 only when healthy."""
    try:
        health = _memory_service(ctx).health()
    except HarnessError as exc:
        _fail(exc)
    _echo_json(health.model_dump(mode="json"))
    raise typer.Exit(code=0 if health.ok else 1)


@memory_app.command("add")
def memory_add(
    ctx: typer.Context,
    content: Annotated[str, typer.Argument(help="Text to remember (checked for secrets first).")],
    scope: Annotated[str, typer.Option("--scope", help=_SCOPE_HELP)],
    source: Annotated[
        str, typer.Option("--source", help="Lineage <type>:<id>, e.g. task_result:T-12.")
    ],
) -> None:
    """Store one memory in a scope, with its origin (lineage)."""
    try:
        service = _memory_service(ctx)
        record = service.add(content, scope=service.scope(scope), source=service.source(source))
    except HarnessError as exc:
        _fail(exc)
    _echo_json(record.model_dump(mode="json"))


@memory_app.command("search")
def memory_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="What to look for.")],
    scope: Annotated[str, typer.Option("--scope", help=_SCOPE_HELP)],
    limit: Annotated[int, typer.Option("--limit", help="Maximum results (1-50).")] = 5,
) -> None:
    """Search memories of exactly one scope (most relevant first)."""
    try:
        service = _memory_service(ctx)
        hits = service.search(query, scope=service.scope(scope), limit=limit)
    except HarnessError as exc:
        _fail(exc)
    _echo_json([hit.model_dump(mode="json") for hit in hits])


@memory_app.command("update")
def memory_update(
    ctx: typer.Context,
    memory_id: Annotated[str, typer.Argument(help="Id returned by add/search.")],
    content: Annotated[str, typer.Argument(help="New text (checked for secrets first).")],
) -> None:
    """Replace the text of a memory; scope and lineage are kept."""
    try:
        record = _memory_service(ctx).update(memory_id, content)
    except HarnessError as exc:
        _fail(exc)
    _echo_json(record.model_dump(mode="json"))


@memory_app.command("delete")
def memory_delete(
    ctx: typer.Context,
    memory_id: Annotated[str, typer.Argument(help="Id returned by add/search.")],
) -> None:
    """Delete one memory."""
    try:
        _memory_service(ctx).delete(memory_id)
    except HarnessError as exc:
        _fail(exc)
    _echo_json({"deleted": memory_id})


# --- decision (V0.4) -----------------------------------------------------------------

decision_app = typer.Typer(
    help="Probabilistic decisions (Jev). Each command returns a DecisionOutcome as JSON; "
    "a fallback is only signalled, never executed. Jev is probabilistic, never a rule.",
    no_args_is_help=True,
    rich_markup_mode=None,
)
app.add_typer(decision_app, name="decision")

# Exit code when the decision layer answered but requires a fallback (see module doc).
EXIT_FALLBACK_REQUIRED = 3


@dataclass(frozen=True, slots=True)
class _DecisionPreset:
    """CLI defaults only (not Harness domain): every value can be overridden."""

    kind: DecisionKind
    question: str
    options: tuple[str, ...]
    ordered: bool = False


_PRESETS = {
    "classify": _DecisionPreset(
        DecisionKind.CLASSIFICATION,
        "What kind of engineering work does this request describe?",
        ("bug", "feature", "refactor"),
    ),
    "route": _DecisionPreset(
        DecisionKind.ROUTING,
        "Which engineering role should handle this request first?",
        ("architect", "implementer", "reviewer"),
    ),
    "severity": _DecisionPreset(
        DecisionKind.SEVERITY,
        "How severe is this issue for the software project?",
        ("low", "medium", "high", "critical"),
        ordered=True,
    ),
    "relevance": _DecisionPreset(
        DecisionKind.CONTEXT_RELEVANCE,
        "How relevant is this item as context for the task?",
        ("required", "high_value", "optional", "excluded"),
    ),
}

_SubjectArg = Annotated[str, typer.Argument(help="The text being judged.")]
_OptionOpt = Annotated[
    list[str] | None,
    typer.Option("--option", "-o", help="An allowed answer (repeat). Default: preset options."),
]
_QuestionOpt = Annotated[
    str | None, typer.Option("--question", "-q", help="Override the preset question.")
]


def _decide(
    ctx: typer.Context, preset: _DecisionPreset, subject: str,
    options: list[str] | None, question: str | None,
) -> None:
    state: CliState = ctx.find_root().obj
    try:
        service = open_decisions(load_config(resolve_harness_root(state.root)))
        outcome = service.decide(
            question=question or preset.question,
            options=tuple(options) if options else preset.options,
            kind=preset.kind,
            subject=subject,
            ordered=preset.ordered,
        )
    except HarnessError as exc:
        _fail(exc)
    _echo_json(outcome.model_dump(mode="json"))
    raise typer.Exit(code=EXIT_FALLBACK_REQUIRED if outcome.fallback_required else 0)


@decision_app.command("classify")
def decision_classify(
    ctx: typer.Context, subject: _SubjectArg, option: _OptionOpt = None,
    question: _QuestionOpt = None,
) -> None:
    """Classify a request (default options: bug, feature, refactor)."""
    _decide(ctx, _PRESETS["classify"], subject, option, question)


@decision_app.command("route")
def decision_route(
    ctx: typer.Context, subject: _SubjectArg, option: _OptionOpt = None,
    question: _QuestionOpt = None,
) -> None:
    """Pick the role that should handle a request (default: architect, implementer, reviewer)."""
    _decide(ctx, _PRESETS["route"], subject, option, question)


@decision_app.command("severity")
def decision_severity(
    ctx: typer.Context, subject: _SubjectArg, option: _OptionOpt = None,
    question: _QuestionOpt = None,
) -> None:
    """Rate severity on an ordered scale, lowest first (default: low..critical). Reports score."""
    _decide(ctx, _PRESETS["severity"], subject, option, question)


@decision_app.command("relevance")
def decision_relevance(
    ctx: typer.Context,
    subject: Annotated[str, typer.Argument(help="The candidate context item.")],
    task: Annotated[str, typer.Option("--task", help="The task the context is for.")],
    option: _OptionOpt = None,
    question: _QuestionOpt = None,
) -> None:
    """Judge how relevant a context item is for a task (no Context Engine: one item, one call)."""
    preset = _PRESETS["relevance"]
    base = question or preset.question
    _decide(ctx, preset, subject, option, f"{base}\nTask: {task}")


@decision_app.command("health")
def decision_health(ctx: typer.Context) -> None:
    """Check decision provider connectivity and credentials (no inference).
    Exit 0 only when healthy."""
    state: CliState = ctx.find_root().obj
    try:
        health = open_decisions(load_config(resolve_harness_root(state.root))).health()
    except HarnessError as exc:
        _fail(exc)
    _echo_json(health.model_dump(mode="json"))
    raise typer.Exit(code=0 if health.ok else 1)


# --- library (V1) --------------------------------------------------------------------

library_app = typer.Typer(
    help="Global Library: skills, guidelines, policies, rules and specialties owned by the "
    "Harness installation and inherited by every project. Read-only, offline, deterministic.",
    no_args_is_help=True,
    rich_markup_mode=None,
)
app.add_typer(library_app, name="library")


def _load_library() -> GlobalLibrary:
    return GlobalLibrary.load(resolve_library_root())


@library_app.command("inspect")
def library_inspect(
    type_: Annotated[
        str | None,
        typer.Option("--type", help=f"Only one artifact type: {', '.join(ArtifactType)}."),
    ] = None,
) -> None:
    """List validated artifacts (metadata only) as JSON, policies first."""
    try:
        artifact_type = ArtifactType(type_) if type_ is not None else None
    except ValueError as exc:
        raise typer.BadParameter(f"unknown type '{type_}'", param_hint="--type") from exc
    try:
        library = _load_library()
    except HarnessError as exc:
        _fail(exc)
    artifacts = library.artifacts() if artifact_type is None else library.by_type(artifact_type)
    _echo_json({"root": str(library.root), "artifacts": [a.summary() for a in artifacts]})


@library_app.command("resolve")
def library_resolve(
    ctx: typer.Context,
    stack: Annotated[
        list[str] | None,
        typer.Option("--stack", help="A stack entry (repeat). Replaces project.yaml's profile."),
    ] = None,
    capability: Annotated[
        list[str] | None,
        typer.Option(
            "--capability", help="A capability (repeat). Replaces project.yaml's profile."
        ),
    ] = None,
) -> None:
    """Show the artifacts that apply to the project profile, with the reason for each.

    Without --stack/--capability the profile comes from project.yaml (under --root).
    """
    state: CliState = ctx.find_root().obj
    try:
        if stack or capability:
            profile = ProjectProfile(stack=tuple(stack or ()), capabilities=tuple(capability or ()))
        else:
            project = load_config(resolve_harness_root(state.root)).project
            profile = ProjectProfile(
                stack=tuple(project.stack), capabilities=tuple(project.capabilities)
            )
    except PydanticValidationError as exc:
        raise typer.BadParameter("stack/capability entries must match ^[a-z][a-z0-9_-]*$") from exc
    except HarnessError as exc:
        _fail(exc)
    try:
        library = _load_library()
    except HarnessError as exc:
        _fail(exc)
    _echo_json({
        "root": str(library.root),
        "profile": profile.model_dump(mode="json"),
        "matches": [m.summary() for m in library.resolve(profile)],
    })


def main() -> None:
    app(prog_name="harness")
