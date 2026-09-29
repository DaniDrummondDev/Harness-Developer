"""Offline emulation of the TypeSafe System One routes used by `JevDecisionProvider`.

It is a `Transport` (method, path, body) -> (status, json), so the real adapter
code (request mapping, status handling, response validation) runs end to end
without sockets. Shapes mirror docs.typesafe.ai/api (verified 2026-09-29):

- POST /v1/systemone {model, state, questions} -> {model, answers, usage};
  a missing field or unknown question type -> 422 {"detail": ...};
- choice answer: {type, choice, probabilities{option: p}, confidence};
- score answer:  {type, score (0..n-1), legend{"0": level}, probabilities{"0": p}, confidence};
- GET /v1/models -> {"models": [{"name": "jev-latest"}, ...]}.

Answers are deterministic: the favoured option (`pick`, default the first)
gets probability `peak`; the rest is spread evenly. Confidence follows the
docs' approximation (n * peak - 1) / (n - 1). Semantics are not emulated;
tests assert mapping and invariants, not model judgement.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from orchestrator.core.exceptions import DecisionTimeoutError, DecisionUnavailableError

RESOLVED_MODEL = "jev-1.13.0"


def _distribution(n: int, favoured: int, peak: float) -> list[float]:
    rest = (1.0 - peak) / (n - 1)
    return [peak if i == favoured else rest for i in range(n)]


def _confidence(n: int, peak: float) -> float:
    return max(0.0, min(1.0, (n * peak - 1) / (n - 1)))


class JevEmulator:
    def __init__(self, *, pick: str | None = None, peak: float = 0.9) -> None:
        self.pick = pick
        self.peak = peak
        self.down = False  # simulate connection refused (raised like the HTTP transport)
        self.timeout = False  # simulate a timeout (raised like the HTTP transport)
        self.fail_status: tuple[int, Any] | None = None  # force a response
        self.answer: Any = None  # replace the "decision" answer (malformed/out-of-contract)
        self.body: Any = None  # replace the whole response body
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(self, method: str, path: str, body: Mapping[str, Any] | None) -> tuple[int, Any]:
        self.calls.append((method, path, copy.deepcopy(dict(body)) if body is not None else None))
        if self.down:
            raise DecisionUnavailableError("jev", "cannot reach emulator: ConnectionRefusedError")
        if self.timeout:
            raise DecisionTimeoutError("jev", "no answer from emulator within 15s")
        if self.fail_status is not None:
            return self.fail_status
        if (method, path) == ("GET", "/v1/models"):
            return 200, {"models": [{"name": "jev-latest"}, {"name": "jev-preview"}]}
        if (method, path) == ("POST", "/v1/systemone") and body is not None:
            return self._evaluate(body)
        return 404, {"detail": "Not Found"}

    @property
    def last_body(self) -> dict[str, Any]:
        body = self.calls[-1][2]
        assert body is not None
        return body

    def _evaluate(self, body: Mapping[str, Any]) -> tuple[int, Any]:
        if not {"model", "state", "questions"} <= set(body) or not body["questions"]:
            return 422, {"detail": [{"loc": ["body"], "msg": "field required"}]}
        answers: dict[str, Any] = {}
        for qid, question in body["questions"].items():
            if question.get("type") == "choice":
                answers[qid] = self._choice(list(question["criteria"]))
            elif question.get("type") == "score":
                answers[qid] = self._score(list(question["criteria"]))
            else:
                return 422, {"detail": [{"loc": ["questions", qid], "msg": "bad type"}]}
        if self.answer is not None:
            answers["decision"] = self.answer
        if self.body is not None:
            return 200, self.body
        return 200, {
            "model": RESOLVED_MODEL,
            "answers": answers,
            "usage": {"input_tokens": 296, "output_tokens": 20},
        }

    def _favoured(self, labels: list[str]) -> int:
        for i, label in enumerate(labels):
            if self.pick is not None and (label == self.pick or label.startswith(f"{self.pick}:")):
                return i
        return 0

    def _choice(self, options: list[str]) -> dict[str, Any]:
        favoured = self._favoured(options)
        probs = _distribution(len(options), favoured, self.peak)
        return {
            "type": "choice",
            "choice": options[favoured],
            "probabilities": dict(zip(options, probs, strict=True)),
            "confidence": _confidence(len(options), self.peak),
        }

    def _score(self, levels: list[str]) -> dict[str, Any]:
        favoured = self._favoured(levels)
        probs = _distribution(len(levels), favoured, self.peak)
        return {
            "type": "score",
            "score": sum(i * p for i, p in enumerate(probs)),
            "legend": {str(i): level for i, level in enumerate(levels)},
            "probabilities": {str(i): p for i, p in enumerate(probs)},
            "confidence": _confidence(len(levels), self.peak),
        }
