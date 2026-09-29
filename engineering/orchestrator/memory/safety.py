"""Safe ingestion policy: decides, deterministically, whether text may be persisted.

Two verdicts only (no REDACT):

    ALLOW  nothing secret-looking was found
    BLOCK  at least one rule matched -> the whole write is refused

A masked secret has no operational value in memory and a partial mask can still
leak structure, so blocked content is never stored in any form (fail closed,
RNF-006 / RF-020). The caller must rewrite the text without the secret.

The policy is pragmatic, not a DLP: it targets unambiguous evidence of
credentials — well-known key/token formats, private key blocks, authorization
headers, credentials inside URLs, and secret-named assignments (`.env` lines,
quoted literals, YAML values). Prose about secrets ("rotate the API key",
"Authorization: Bearer <token>", `api_key = os.environ[...]`) is allowed.

Findings name the rule, never the matched text, so a verdict can be logged or
shown safely. To add a rule: append a `_Rule` to `RULES` and add positive and
negative examples to tests/unit/test_memory_safety.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from orchestrator.core.exceptions import UnsafeMemoryContentError


class Verdict(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class _Rule:
    name: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class SafetyResult:
    verdict: Verdict
    rules: tuple[str, ...]  # names of matched rules; empty when allowed

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


_SENSITIVE_NAME_RE = (
    r"[A-Za-z0-9_.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key"
    r"|private[_-]?key|credentials?)[A-Za-z0-9_.-]*"
)
# `.env` variables are UPPERCASE by convention; matching them case-sensitively keeps
# code such as `api_key = os.environ[...]` out of this rule.
_ENV_SENSITIVE_NAME_RE = (
    r"[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|ACCESS_KEY|PRIVATE_KEY"
    r"|CREDENTIALS?)[A-Z0-9_]*"
)
# Values that are clearly not secrets: placeholders and references.
_PLACEHOLDER = re.compile(
    r"^(?:<[^>]*>|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\*+|x+|changeme|redacted|none|null|"
    r"true|false|required|optional|example|your[_-].*|\.\.\.)$",
    re.IGNORECASE,
)

RULES: tuple[_Rule, ...] = (
    _Rule("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    _Rule(
        "authorization_header",
        re.compile(
            r"(?i)\bauthorization[\"']?\s*[:=]\s*[\"']?(?:bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}"
        ),
    ),
    _Rule("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}=*")),
    _Rule("openai_style_key", re.compile(r"\bsk-(?:[A-Za-z0-9]+-)*[A-Za-z0-9_-]{20,}")),
    _Rule(
        "github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})")
    ),
    _Rule("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    _Rule("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    _Rule("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    _Rule("nvidia_api_key", re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}")),
    _Rule("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    _Rule(
        "url_credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s:/@]+@", re.IGNORECASE)
    ),
)

# `.env` style (`export DB_PASSWORD=...`), YAML/INI (`password: ...`) and quoted
# literals in code (`password = "..."`). Checked separately because the value
# must be compared against placeholders.
_ASSIGNMENT_RULES: tuple[_Rule, ...] = (
    _Rule(
        "env_secret_assignment",
        re.compile(rf"(?m)^\s*(?:export\s+)?{_ENV_SENSITIVE_NAME_RE}\s*=\s*[\"']?(?P<value>[^\s\"'#]+)"),
    ),
    _Rule(
        "yaml_secret_value",
        re.compile(rf"(?im)^\s*[\"']?{_SENSITIVE_NAME_RE}[\"']?\s*:\s*[\"']?(?P<value>[^\s\"'#]+)[\"']?\s*(?:#.*)?$"),
    ),
    _Rule(
        "quoted_secret_literal",
        re.compile(rf"(?i)\b{_SENSITIVE_NAME_RE}\s*[:=]\s*[\"'](?P<value>[^\"'\s]{{6,}})[\"']"),
    ),
)


# References to where a secret lives (not the secret itself).
_REFERENCE = re.compile(r"[(\[{]|^(?:os|env|settings|config|process)\.", re.IGNORECASE)


def _looks_like_value(value: str) -> bool:
    # Purely numeric values are limits/ports/counts (`TOKEN_LIMIT=128000`), not secrets.
    return (
        len(value) >= 6
        and not value.isdigit()
        and not _PLACEHOLDER.match(value)
        and not _REFERENCE.search(value)
    )


def evaluate(text: str) -> SafetyResult:
    """Classify `text`. Pure and deterministic; never logs or returns the text."""
    matched = [rule.name for rule in RULES if rule.pattern.search(text)]
    for rule in _ASSIGNMENT_RULES:
        if any(_looks_like_value(m.group("value")) for m in rule.pattern.finditer(text)):
            matched.append(rule.name)
    if matched:
        return SafetyResult(Verdict.BLOCK, tuple(dict.fromkeys(matched)))
    return SafetyResult(Verdict.ALLOW, ())


def ensure_safe(*texts: str) -> None:
    """Raise `UnsafeMemoryContentError` if any text is blocked (checked before persisting)."""
    rules: list[str] = []
    for text in texts:
        rules.extend(evaluate(text).rules)
    if rules:
        raise UnsafeMemoryContentError(tuple(dict.fromkeys(rules)))
