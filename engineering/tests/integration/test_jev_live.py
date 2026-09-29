"""V0.4 exit criterion against the REAL TypeSafe Jev API:

    DecisionRequest -> DecisionService -> JevDecisionProvider -> api.typesafe.ai
                    -> structured answer -> valid, auditable DecisionOutcome

Covers the first uses (classification, routing, severity, context relevance)
in-process, plus one full `python -m orchestrator decision classify` process.
Assertions are contract invariants (choice in options, metrics in 0..1,
provider/model metadata, telemetry), not the model's semantic judgement, so
the test does not become brittle when the `jev-latest` alias moves.

Opt-in (external service, costs tokens), skipped otherwise:

    export JEV_API_KEY=<key from console.typesafe.ai>
    export HARNESS_JEV_INTEGRATION=1
    pytest -m jev -v -s tests/integration/test_jev_live.py

`-s` prints one evidence line per decision (never the API key).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from orchestrator.config import load_config
from orchestrator.decisions.models import DecisionOutcome, DecisionStatus, FallbackReason
from orchestrator.decisions.service import DecisionService, open_decisions
from orchestrator.providers.base import PROBABILITY_SUM_TOLERANCE, DecisionKind
from orchestrator.utils.shell import run_command

pytestmark = [
    pytest.mark.jev,
    pytest.mark.skipif(
        os.environ.get("HARNESS_JEV_INTEGRATION") != "1" or not os.environ.get("JEV_API_KEY"),
        reason="real Jev test is opt-in: set HARNESS_JEV_INTEGRATION=1 and JEV_API_KEY",
    ),
]

WriteConfig = Callable[[str, str], Path]
JEV_ENABLED = """
    version: 1
    providers:
      jev: {kind: jev, enabled: true, api_key_env: JEV_API_KEY, timeout_seconds: 30}
"""


@pytest.fixture
def live(harness_root: Path, write_config: WriteConfig) -> DecisionService:
    write_config("providers.yaml", JEV_ENABLED)
    return open_decisions(load_config(harness_root))


def check(outcome: DecisionOutcome, options: tuple[str, ...], *, ordered: bool) -> None:
    """Contract invariants of a real answer; prints the evidence line."""
    print("\nEVIDENCE", json.dumps({
        "kind": outcome.kind,
        "status": outcome.status,
        "fallback_reason": outcome.fallback_reason,
        "choice": outcome.result.choice if outcome.result else None,
        "confidence": outcome.result.confidence if outcome.result else None,
        "probability": outcome.result.probability if outcome.result else None,
        "score": outcome.result.score if outcome.result else None,
        "resolved_model": outcome.result.resolved_model if outcome.result else None,
        "duration_ms": round(outcome.telemetry.duration_ms, 1),
        "input_tokens": outcome.telemetry.input_tokens,
    }))
    # A live answer is either accepted or, legitimately, below the threshold; any
    # other fallback (unavailable/timeout/invalid) means the integration failed.
    assert outcome.status is DecisionStatus.DECIDED or (
        outcome.fallback_reason is FallbackReason.LOW_CONFIDENCE
    ), outcome.detail
    result = outcome.result
    assert result is not None
    assert result.provider == "jev"
    assert result.model == "jev-latest"
    assert result.resolved_model is not None and result.resolved_model.startswith("jev-")
    assert result.choice in options
    assert 0.0 <= result.confidence <= 1.0
    assert result.probability is not None and 0.0 <= result.probability <= 1.0
    assert set(result.probabilities) == set(options)
    assert abs(sum(result.probabilities.values()) - 1) <= PROBABILITY_SUM_TOLERANCE
    assert (result.score is not None) is ordered
    if result.score is not None:
        assert 0.0 <= result.score <= 1.0
    assert outcome.telemetry.duration_ms > 0
    assert outcome.telemetry.input_tokens is None or outcome.telemetry.input_tokens > 0


def test_classification(live: DecisionService) -> None:
    options = ("bug", "feature", "refactor")
    outcome = live.decide(
        question="What kind of engineering work does this request describe?",
        options=options, kind=DecisionKind.CLASSIFICATION,
        subject="Fix failing authentication test",
    )
    check(outcome, options, ordered=False)


def test_routing(live: DecisionService) -> None:
    options = ("architect", "implementer", "reviewer")
    outcome = live.decide(
        question="Which engineering role should handle this request first?",
        options=options, kind=DecisionKind.ROUTING,
        subject="Review pull request #42 for security problems before merge",
        descriptions={
            "architect": "Designs system structure and makes architectural decisions",
            "implementer": "Writes and changes code",
            "reviewer": "Reviews existing changes for defects and risks",
        },
    )
    check(outcome, options, ordered=False)


def test_severity(live: DecisionService) -> None:
    options = ("low", "medium", "high", "critical")
    outcome = live.decide(
        question="How severe is this issue for the software project?",
        options=options, kind=DecisionKind.SEVERITY, ordered=True,
        subject="Production checkout returns HTTP 500 for every customer since the last deploy",
    )
    check(outcome, options, ordered=True)


def test_context_relevance(live: DecisionService) -> None:
    options = ("required", "high_value", "optional", "excluded")
    outcome = live.decide(
        question="How relevant is this item as context for the task?\n"
                 "Task: Add a discount field to invoices",
        options=options, kind=DecisionKind.CONTEXT_RELEVANCE,
        subject="ADR-007: all money values are stored as integers in cents",
    )
    check(outcome, options, ordered=False)


def test_cli_process_end_to_end(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("providers.yaml", JEV_ENABLED)
    result = run_command(
        [sys.executable, "-m", "orchestrator", "--root", str(harness_root),
         "decision", "classify", "Fix failing authentication test"],
        timeout=90,
    )
    assert result.exit_code in (0, 3), result.stderr  # decided | fallback (low confidence)
    outcome = json.loads(result.stdout)
    print("\nEVIDENCE cli", json.dumps({k: outcome[k] for k in ("status", "kind")}),
          json.dumps({k: outcome["result"][k] for k in ("choice", "confidence", "resolved_model")}))
    assert outcome["result"]["choice"] in ("bug", "feature", "refactor")
    assert os.environ["JEV_API_KEY"] not in result.stdout + result.stderr
