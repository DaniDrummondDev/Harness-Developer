"""JevDecisionProvider: request mapping, response mapping, error translation, HTTP transport."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest
from jev_emulator import RESOLVED_MODEL, JevEmulator

from orchestrator.core.exceptions import (
    DecisionAuthenticationError,
    DecisionInvalidResponseError,
    DecisionTimeoutError,
    DecisionUnavailableError,
    ProviderCallError,
)
from orchestrator.providers.base import DecisionKind, DecisionRequest
from orchestrator.providers.jev import (
    MAX_SCORE_LEVELS,
    JevDecisionProvider,
    JevHttpTransport,
)

KEY = "test-key-not-a-secret"
CLASSIFY = DecisionRequest(
    model="jev-latest",
    question="What kind of engineering work is this?",
    options=("bug", "feature", "refactor"),
    subject="Fix failing authentication test",
    descriptions={"bug": "Something that used to work is broken"},
)
SEVERITY = DecisionRequest(
    model="jev-latest",
    question="How severe is this issue?",
    options=("low", "medium", "high", "critical"),
    kind=DecisionKind.SEVERITY,
    subject="Checkout is down for all customers",
    ordered=True,
    descriptions={"critical": "Production outage"},
)


def jev(emulator: JevEmulator) -> JevDecisionProvider:
    return JevDecisionProvider(api_key=KEY, transport=emulator)


# --- request mapping ------------------------------------------------------------------------


def test_unordered_request_maps_to_one_choice_question() -> None:
    emulator = JevEmulator()
    jev(emulator).decide(CLASSIFY)

    method, path, _ = emulator.calls[0]
    assert (method, path) == ("POST", "/v1/systemone")
    assert emulator.last_body == {
        "model": "jev-latest",
        "state": "Fix failing authentication test",
        "questions": {
            "decision": {
                "type": "choice",
                "instructions": "What kind of engineering work is this?",
                "criteria": {
                    "bug": "Something that used to work is broken",
                    "feature": None,
                    "refactor": None,
                },
            }
        },
    }


def test_ordered_request_maps_to_a_score_question() -> None:
    emulator = JevEmulator()
    jev(emulator).decide(SEVERITY)

    question = emulator.last_body["questions"]["decision"]
    assert question["type"] == "score"
    assert question["criteria"] == ["low", "medium", "high", "critical: Production outage"]


def test_question_is_the_state_when_there_is_no_subject() -> None:
    emulator = JevEmulator()
    jev(emulator).decide(DecisionRequest(model="m", question="Is it a bug?", options=("y", "n")))
    assert emulator.last_body["state"] == "Is it a bug?"


def test_request_carries_only_what_the_decision_needs() -> None:
    emulator = JevEmulator()
    jev(emulator).decide(CLASSIFY)
    assert set(emulator.last_body) == {"model", "state", "questions"}
    assert KEY not in json.dumps(emulator.last_body)


def test_too_many_levels_fail_before_any_call() -> None:
    emulator = JevEmulator()
    options = tuple(f"l{i}" for i in range(MAX_SCORE_LEVELS + 1))
    request = DecisionRequest(model="m", question="q?", options=options, ordered=True)
    with pytest.raises(ProviderCallError, match="at most 10"):
        jev(emulator).decide(request)
    assert emulator.calls == []


# --- response mapping -----------------------------------------------------------------------


def test_choice_answer_maps_to_result() -> None:
    result = jev(JevEmulator(pick="bug", peak=0.88)).decide(CLASSIFY)

    assert result.provider == "jev"
    assert result.model == "jev-latest"
    assert result.resolved_model == RESOLVED_MODEL
    assert result.kind is DecisionKind.CLASSIFICATION
    assert result.choice == "bug"
    assert result.probability == pytest.approx(0.88)
    assert result.probabilities == pytest.approx({"bug": 0.88, "feature": 0.06, "refactor": 0.06})
    assert result.confidence == pytest.approx((3 * 0.88 - 1) / 2)
    assert result.score is None
    assert result.input_tokens == 296


def test_score_answer_is_normalized_and_choice_is_the_most_probable_level() -> None:
    emulator = JevEmulator()
    emulator.answer = {
        "type": "score",
        "score": 2.1,
        "legend": {"0": "low", "1": "medium", "2": "high", "3": "critical"},
        "probabilities": {"0": 0.0, "1": 0.1, "2": 0.7, "3": 0.2},
        "confidence": 0.61,
    }
    result = jev(emulator).decide(SEVERITY)

    assert result.choice == "high"
    assert result.score == pytest.approx(2.1 / 3)  # 0 = first option, 1 = last option
    assert result.probability == pytest.approx(0.7)
    assert result.probabilities["critical"] == pytest.approx(0.2)
    assert result.confidence == pytest.approx(0.61)
    assert result.kind is DecisionKind.SEVERITY


def test_score_tie_resolves_to_the_lower_level() -> None:
    emulator = JevEmulator()
    emulator.answer = {
        "type": "score",
        "score": 1.5,
        "probabilities": {"0": 0.0, "1": 0.5, "2": 0.5, "3": 0.0},
        "confidence": 0.3,
    }
    assert jev(emulator).decide(SEVERITY).choice == "medium"


@pytest.mark.parametrize("score", [0.0, 3.0])
def test_score_bounds_map_to_zero_and_one(score: float) -> None:
    emulator = JevEmulator()
    top = "0" if score == 0 else "3"
    emulator.answer = {
        "type": "score",
        "score": score,
        "probabilities": {level: 1.0 if level == top else 0.0 for level in "0123"},
        "confidence": 1.0,
    }
    assert jev(emulator).decide(SEVERITY).score == score / 3


def test_unknown_vendor_fields_are_ignored() -> None:
    emulator = JevEmulator()
    emulator.answer = {
        "type": "choice",
        "choice": "feature",
        "probabilities": {"bug": 0.1, "feature": 0.8, "refactor": 0.1},
        "confidence": 0.7,
        "new_vendor_field": {"x": 1},
    }
    assert jev(emulator).decide(CLASSIFY).choice == "feature"


# --- malformed / out-of-contract responses -----------------------------------------------------

GOOD_CHOICE = {
    "type": "choice",
    "choice": "bug",
    "probabilities": {"bug": 0.8, "feature": 0.1, "refactor": 0.1},
    "confidence": 0.7,
}


@pytest.mark.parametrize(
    ("answer", "body", "expected"),
    [
        (None, {"no": "model"}, "malformed body"),
        (None, "not json object", "malformed body"),
        (None, {"model": "jev-1.13.0", "answers": {}}, "answer missing"),
        ({"type": "noul", "noul": 0.9}, None, "malformed answer"),
        ({**GOOD_CHOICE, "choice": "security"}, None, "not one of the requested options"),
        ({**GOOD_CHOICE, "probabilities": {"bug": 1.0}}, None, "do not match"),
        ({**GOOD_CHOICE, "confidence": 1.5}, None, "confidence"),
        ({**GOOD_CHOICE, "confidence": "high"}, None, "malformed answer"),
        (
            {**GOOD_CHOICE, "probabilities": {"bug": 0.3, "feature": 0.1, "refactor": 0.1}},
            None,
            "out of contract",
        ),
        (
            {**GOOD_CHOICE, "probabilities": {"bug": 1.4, "feature": -0.2, "refactor": -0.2}},
            None,
            "probabilit",
        ),
    ],
)
def test_malformed_choice_answers_are_rejected(
    answer: Any, body: Any, expected: str
) -> None:
    emulator = JevEmulator()
    emulator.answer, emulator.body = answer, body
    with pytest.raises(DecisionInvalidResponseError, match=expected) as excinfo:
        jev(emulator).decide(CLASSIFY)
    assert CLASSIFY.subject is not None and CLASSIFY.subject not in str(excinfo.value)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"type": "score", "score": 3.5, "probabilities": dict.fromkeys("0123", 0.25),
          "confidence": 0.1}, "score outside 0..3"),
        ({"type": "score", "score": -0.5, "probabilities": dict.fromkeys("0123", 0.25),
          "confidence": 0.1}, "score outside"),
        ({"type": "score", "score": 1.0, "probabilities": {"0": 0.5, "1": 0.5},
          "confidence": 0.1}, "levels"),
        (GOOD_CHOICE, "malformed answer"),  # a choice answer to a score question
    ],
)
def test_malformed_score_answers_are_rejected(answer: Any, expected: str) -> None:
    emulator = JevEmulator()
    emulator.answer = answer
    with pytest.raises(DecisionInvalidResponseError, match=expected):
        jev(emulator).decide(SEVERITY)


# --- status translation ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (401, DecisionAuthenticationError, r"rejected \(HTTP 401\); check \$JEV_API_KEY"),
        (403, DecisionAuthenticationError, "HTTP 403"),
        (429, DecisionUnavailableError, "HTTP 429"),
        (529, DecisionUnavailableError, "HTTP 529"),
        (500, DecisionUnavailableError, "HTTP 500"),
        (422, ProviderCallError, "request rejected by provider"),
        (418, ProviderCallError, "unexpected HTTP status 418"),
    ],
)
def test_http_status_is_translated(status: int, error: type[Exception], expected: str) -> None:
    emulator = JevEmulator()
    emulator.fail_status = (status, {"detail": "secret-looking vendor detail"})
    with pytest.raises(error, match=expected) as excinfo:
        jev(emulator).decide(CLASSIFY)
    assert "vendor detail" not in str(excinfo.value)
    assert KEY not in str(excinfo.value)


def test_422_is_not_a_fallback_error() -> None:
    emulator = JevEmulator()
    emulator.fail_status = (422, {})
    with pytest.raises(ProviderCallError) as excinfo:
        jev(emulator).decide(CLASSIFY)
    assert not isinstance(
        excinfo.value, DecisionUnavailableError | DecisionInvalidResponseError
    )


def test_empty_api_key_is_rejected_at_construction() -> None:
    with pytest.raises(DecisionAuthenticationError, match=r"\$JEV_API_KEY is empty"):
        JevDecisionProvider(api_key="  ", transport=JevEmulator())


def test_ping_uses_models_route_without_inference() -> None:
    emulator = JevEmulator()
    jev(emulator).ping()
    assert [(m, p) for m, p, _ in emulator.calls] == [("GET", "/v1/models")]


def test_ping_translates_rejected_credentials() -> None:
    emulator = JevEmulator()
    emulator.fail_status = (401, {"detail": "invalid key"})
    with pytest.raises(DecisionAuthenticationError):
        jev(emulator).ping()


# --- real HTTP transport (local server, no internet) ----------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, Any]]] = []
    delay: ClassVar[float] = 0.0

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        type(self).seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
        time.sleep(type(self).delay)
        status, payload = JevEmulator()("POST", self.path, body)
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:  # silence test output
        return


@pytest.fixture
def server() -> Iterator[str]:
    _Handler.seen.clear()
    _Handler.delay = 0.0
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_transport_sends_bearer_auth_and_json(server: str) -> None:
    provider = JevDecisionProvider(api_key=KEY, base_url=server, timeout=5)
    result = provider.decide(CLASSIFY)

    assert result.choice in CLASSIFY.options
    (seen,) = _Handler.seen
    assert seen["path"] == "/v1/systemone"
    assert seen["headers"]["Authorization"] == f"Bearer {KEY}"
    assert seen["headers"]["Content-Type"] == "application/json"
    assert seen["headers"]["User-Agent"].startswith("ai-engineering-harness/")
    assert seen["body"]["model"] == "jev-latest"


def test_http_transport_times_out(server: str) -> None:
    _Handler.delay = 1.0
    provider = JevDecisionProvider(api_key=KEY, base_url=server, timeout=0.2)
    with pytest.raises(DecisionTimeoutError, match=r"within 0.2s") as excinfo:
        provider.decide(CLASSIFY)
    assert KEY not in str(excinfo.value)


def test_http_transport_unreachable_is_unavailable() -> None:
    with socket.socket() as sock:  # a port that nothing listens on
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    provider = JevDecisionProvider(api_key=KEY, base_url=f"http://127.0.0.1:{port}", timeout=2)
    with pytest.raises(DecisionUnavailableError, match="cannot reach") as excinfo:
        provider.decide(CLASSIFY)
    assert not isinstance(excinfo.value, DecisionTimeoutError)
    assert KEY not in str(excinfo.value)


def test_http_transport_rejects_non_http_base_url() -> None:
    with pytest.raises(ProviderCallError, match="base_url must be http"):
        JevHttpTransport("file:///etc/passwd", KEY, timeout=1, provider_id="jev")
