"""Command-line interface (Typer).

Entry points: `python -m orchestrator` and the `harness` console script.

Output conventions:
- primary output (tables, messages) -> stdout via `console`;
- logs -> stderr via utils/logging.py (silent by default);
- `doctor`: exit 0 when no check FAILs, 1 otherwise (it never raises);
- `intake`: admitted request as JSON on stdout, exit 0; a rejected request or
  invalid configuration -> `error: ...` on stderr, exit 1;
- usage errors (unknown command/option, bad --log-level) -> Typer/Click, exit 2.

Commands: root (identity + help), `doctor` (V0) and `intake` (V0.1). New
commands are added as `@app.command()` functions here, delegating logic to
their own module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from orchestrator import HARNESS_NAME, __version__
from orchestrator.config import HARNESS_ROOT_ENV, load_config, resolve_harness_root
from orchestrator.core.admission import admit
from orchestrator.core.exceptions import HarnessError
from orchestrator.core.request import Intent, RequestSource
from orchestrator.doctor import CheckStatus, DoctorReport, run_doctor
from orchestrator.intake import normalize_request
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
    """AI Engineering Harness — engineering control plane (V0.2 provider abstraction)."""
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


def main() -> None:
    app(prog_name="harness")
