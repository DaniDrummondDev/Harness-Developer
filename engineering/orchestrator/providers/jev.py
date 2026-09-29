"""Jev adapter: Harness `DecisionProvider` <-> TypeSafe System One HTTP API (V0.4).

Target: the documented HTTP API (docs.typesafe.ai/api, verified 2026-09-29 against
model `jev-1.13.0`). No SDK is used: the Harness needs one endpoint, and stdlib
urllib keeps the adapter dependency-free and fully testable offline through an
injectable transport (same pattern as memory/mem0.py). Only these routes are used:

    POST /v1/systemone   evaluate {model, state, questions: {<id>: Question}}
    GET  /v1/models      connectivity + credential check (doctor), no inference

Authentication: `Authorization: Bearer <key>`; the key comes from the environment
(`JEV_API_KEY` by default, see providers.yaml `api_key_env`), never from YAML.

Translation rules (all Jev details stay in this module):

    DecisionRequest               -> Jev request
      subject (or question)       -> state
      unordered options           -> one "choice" question, criteria {option: description|null}
      ordered options (severity)  -> one "score" question, criteria [level descriptions]
    Jev answer                    -> DecisionResult
      choice.choice               -> choice          (must be one of the options)
      choice.probabilities        -> probabilities   (keys must be exactly the options)
      score.probabilities{"0"..}  -> probabilities   (level index -> option)
      argmax level (ties: lowest) -> choice          (Score has no `choice` field)
      score.score in 0..n-1       -> score = score / (n - 1), i.e. 0..1
      answer.confidence           -> confidence      (Jev: concentration of the distribution)
      probabilities[choice]       -> probability
      response.model              -> resolved_model  (e.g. jev-1.13.0 behind jev-latest)
      usage.input_tokens          -> input_tokens

Errors (vendor detail never crosses this module; messages never contain the API
key, the Authorization header, the state or the question):

    401 / 403                         -> DecisionAuthenticationError
    429 / 529 / 5xx / unreachable     -> DecisionUnavailableError
    timeout                           -> DecisionTimeoutError
    malformed body, choice not in options, probabilities or score out of
    contract                          -> DecisionInvalidResponseError
    422 (request rejected) / other    -> ProviderCallError

No retries here (no retry storms): one call, one outcome. Whether to retry or
fall back is decided by the caller (orchestrator.decisions, V5 policy engine).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from orchestrator import __version__
from orchestrator.core.exceptions import (
    DecisionAuthenticationError,
    DecisionInvalidResponseError,
    DecisionTimeoutError,
    DecisionUnavailableError,
    ProviderCallError,
)
from orchestrator.providers.base import DecisionRequest, DecisionResult

DEFAULT_PROVIDER_ID: Final = "jev"
DEFAULT_BASE_URL: Final = "https://api.typesafe.ai"
DEFAULT_API_KEY_ENV: Final = "JEV_API_KEY"
DEFAULT_TIMEOUT_SECONDS: Final = 15.0
EVALUATE_PATH: Final = "/v1/systemone"
MODELS_PATH: Final = "/v1/models"
# Question ids are never sent to the model; one decision = one question.
QUESTION_ID: Final = "decision"
# API limits (docs.typesafe.ai/api): Choice <= 255 options, Score <= 10 levels.
MAX_CHOICE_OPTIONS: Final = 255
MAX_SCORE_LEVELS: Final = 10
# Float noise allowed on a Score position before it counts as out of range.
_SCORE_EPSILON: Final = 1e-6

# (method, path, json body) -> (HTTP status, parsed JSON body or None)
Transport = Callable[[str, str, Mapping[str, Any] | None], tuple[int, Any]]


# --- transport -----------------------------------------------------------------------


class JevHttpTransport:
    """Default transport: stdlib urllib, JSON in/out, Bearer auth, hard timeout."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float, provider_id: str) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ProviderCallError(provider_id, f"base_url must be http(s): {base_url!r}")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._provider_id = provider_id

    def __call__(self, method: str, path: str, body: Mapping[str, Any] | None) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(  # noqa: S310 - scheme restricted to http(s) above
            self._base_url + path, data=data, method=method
        )
        request.add_header("Accept", "application/json")
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", f"ai-engineering-harness/{__version__}")
        request.add_header("Authorization", f"Bearer {self._api_key}")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                return response.status, _parse_json(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, _parse_json(exc.read())
        except TimeoutError as exc:
            raise self._timeout_error() from exc
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError):
                raise self._timeout_error() from exc
            raise DecisionUnavailableError(
                self._provider_id, f"cannot reach {self._base_url}: {type(reason).__name__}"
            ) from exc

    def _timeout_error(self) -> DecisionTimeoutError:
        return DecisionTimeoutError(
            self._provider_id, f"no answer from {self._base_url} within {self._timeout:g}s"
        )


def _parse_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


# --- Jev response shapes (adapter-internal; unknown vendor fields are ignored) ------------


class _JevModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _Usage(_JevModel):
    input_tokens: int | None = None


class _Response(_JevModel):
    model: str
    answers: dict[str, dict[str, Any]]
    usage: _Usage | None = None


class _ChoiceAnswer(_JevModel):
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, float]
    confidence: float


class _ScoreAnswer(_JevModel):
    type: Literal["score"]
    score: float
    probabilities: dict[str, float]
    confidence: float


# --- adapter -------------------------------------------------------------------------------


class JevDecisionProvider:
    def __init__(
        self,
        *,
        api_key: str,
        provider_id: str = DEFAULT_PROVIDER_ID,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        transport: Transport | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._api_key_env = api_key_env  # only for messages; the key itself is never shown
        if not api_key.strip():
            raise DecisionAuthenticationError(provider_id, f"${api_key_env} is empty")
        self._transport = transport or JevHttpTransport(
            base_url, api_key, timeout=timeout, provider_id=provider_id
        )

    @property
    def provider_id(self) -> str:
        return self._provider_id

    # --- DecisionProvider -------------------------------------------------------------

    def decide(self, request: DecisionRequest) -> DecisionResult:
        status, payload = self._transport("POST", EVALUATE_PATH, self._request_body(request))
        self._raise_for_status(status)
        return self._to_result(request, payload)

    # --- connectivity (doctor) ---------------------------------------------------------

    def ping(self) -> None:
        """Authenticated round trip without inference (GET /v1/models).
        Raises the same errors as `decide`."""
        status, _ = self._transport("GET", MODELS_PATH, None)
        self._raise_for_status(status)

    # --- request mapping -----------------------------------------------------------------

    def _request_body(self, request: DecisionRequest) -> dict[str, Any]:
        question: dict[str, Any]
        if request.ordered:
            if len(request.options) > MAX_SCORE_LEVELS:
                raise ProviderCallError(
                    self._provider_id,
                    f"ordered decisions support at most {MAX_SCORE_LEVELS} options",
                )
            levels = [
                f"{option}: {request.descriptions[option]}"
                if option in request.descriptions
                else option
                for option in request.options
            ]
            question = {"type": "score", "instructions": request.question, "criteria": levels}
        else:
            if len(request.options) > MAX_CHOICE_OPTIONS:
                raise ProviderCallError(
                    self._provider_id, f"decisions support at most {MAX_CHOICE_OPTIONS} options"
                )
            criteria = {option: request.descriptions.get(option) for option in request.options}
            question = {"type": "choice", "instructions": request.question, "criteria": criteria}
        return {
            "model": request.model,
            "state": request.subject if request.subject is not None else request.question,
            "questions": {QUESTION_ID: question},
        }

    # --- response mapping -------------------------------------------------------------------

    def _raise_for_status(self, status: int) -> None:
        if 200 <= status < 300:
            return
        if status in (401, 403):
            raise DecisionAuthenticationError(
                self._provider_id,
                f"credentials rejected (HTTP {status}); check ${self._api_key_env}",
            )
        if status == 429 or status >= 500:  # includes TypeSafe's 529 Overloaded
            raise DecisionUnavailableError(
                self._provider_id, f"service unavailable (HTTP {status})"
            )
        if status == 422:
            raise ProviderCallError(self._provider_id, "request rejected by provider (HTTP 422)")
        raise ProviderCallError(self._provider_id, f"unexpected HTTP status {status}")

    def _invalid(self, detail: str) -> DecisionInvalidResponseError:
        return DecisionInvalidResponseError(self._provider_id, f"invalid response: {detail}")

    def _to_result(self, request: DecisionRequest, payload: Any) -> DecisionResult:
        try:
            response = _Response.model_validate(payload)
        except PydanticValidationError as exc:
            raise self._invalid("malformed body") from exc
        raw_answer = response.answers.get(QUESTION_ID)
        if raw_answer is None:
            raise self._invalid("answer missing")

        try:
            if request.ordered:
                choice, probabilities, score, confidence = self._from_score(request, raw_answer)
            else:
                choice, probabilities, confidence = self._from_choice(request, raw_answer)
                score = None
        except PydanticValidationError as exc:
            raise self._invalid("malformed answer") from exc

        try:
            return DecisionResult(
                provider=self._provider_id,
                model=request.model,
                choice=choice,
                confidence=confidence,
                kind=request.kind,
                probability=probabilities[choice],
                probabilities=probabilities,
                score=score,
                resolved_model=response.model or None,
                input_tokens=response.usage.input_tokens if response.usage else None,
            )
        except PydanticValidationError as exc:  # confidence/probabilities out of 0..1, sum != 1
            fields = sorted({str(err["loc"][0]) for err in exc.errors() if err["loc"]})
            detail = f"values out of contract ({', '.join(fields) or 'result'})"
            raise self._invalid(detail) from exc

    def _from_choice(
        self, request: DecisionRequest, raw: dict[str, Any]
    ) -> tuple[str, dict[str, float], float]:
        answer = _ChoiceAnswer.model_validate(raw)
        if answer.choice not in request.options:
            raise self._invalid("choice is not one of the requested options")
        if set(answer.probabilities) != set(request.options):
            raise self._invalid("probabilities do not match the requested options")
        return answer.choice, dict(answer.probabilities), answer.confidence

    def _from_score(
        self, request: DecisionRequest, raw: dict[str, Any]
    ) -> tuple[str, dict[str, float], float, float]:
        answer = _ScoreAnswer.model_validate(raw)
        top = len(request.options) - 1
        if set(answer.probabilities) != {str(level) for level in range(top + 1)}:
            raise self._invalid("probabilities do not match the requested levels")
        if not -_SCORE_EPSILON <= answer.score <= top + _SCORE_EPSILON:
            raise self._invalid(f"score outside 0..{top}")
        by_option = {
            option: answer.probabilities[str(level)] for level, option in enumerate(request.options)
        }
        # First maximum in option order: on a tie the lower level wins (deterministic).
        choice = max(request.options, key=lambda option: by_option[option])
        normalized = min(max(answer.score / top, 0.0), 1.0)
        return choice, by_option, normalized, answer.confidence
