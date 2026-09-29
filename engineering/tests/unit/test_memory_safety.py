"""Safe ingestion policy: secrets are blocked, ordinary technical text is allowed.

Secret-looking fixtures are assembled at runtime so no literal credential-shaped
string lives in the repository (secret scanners stay quiet)."""

from __future__ import annotations

import pytest

from orchestrator.core.exceptions import UnsafeMemoryContentError
from orchestrator.memory.safety import Verdict, ensure_safe, evaluate

A36 = "a1B2" * 9

BLOCKED = {
    "openai_key": ("OPENAI key is " + "sk-" + "proj-" + A36, "openai_style_key"),
    "anthropic_key": ("key " + "sk-" + "ant-api03-" + A36, "openai_style_key"),
    "github_token": ("token ghp_" + A36, "github_token"),
    "aws_key": ("aws " + "AKIA" + "ABCDEFGHIJKLMNOP", "aws_access_key"),
    "slack_token": ("xoxb-" + "123456789012-abcdef", "slack_token"),
    "google_key": ("AIza" + "S" * 35, "google_api_key"),
    "nvidia_key": ("nvapi-" + A36, "nvidia_api_key"),
    "jwt": ("eyJ" + "hbGciOiJIUzI1" + ".eyJ" + "zdWIiOiIxMjM0" + ".c2lnbmF0dXJlX3Zh", "jwt"),
    "bearer_header": ('curl -H "Authorization: Bearer ' + A36 + '"', "authorization_header"),
    "basic_header": ("Authorization: Basic " + "dXNlcjpwYXNzd29yZA==", "authorization_header"),
    "private_key": ("-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n", "private_key"),
    "openssh_key": ("-----BEGIN OPENSSH PRIVATE KEY-----", "private_key"),
    "env_password": ("DB_HOST=db\nDB_PASSWORD=" + "hunter2hunter\n", "env_secret_assignment"),
    "env_export": ("export SERVICE_API_KEY=" + "q9w8e7r6t5y4", "env_secret_assignment"),
    "yaml_password": ("database:\n  password: " + "hunter2hunter\n", "yaml_secret_value"),
    "quoted_literal": (
        'client = Client(api_key="' + "q9w8e7r6t5y4" + '")',
        "quoted_secret_literal",
    ),
    "url_credentials": ("postgres://app:" + "s3cretpw" + "@db:5432/app", "url_credentials"),
}

ALLOWED = [
    "Rotate the API key every 90 days and store it in the vault.",
    "The password field must be hashed with bcrypt before persisting.",
    "Send the header Authorization: Bearer <token> to the gateway.",
    "api_key = os.environ['OPENAI_API_KEY']",
    'headers = {"Authorization": f"Bearer {token}"}',
    "password: ${DB_PASSWORD}",
    "DB_PASSWORD=<set-in-env>",
    "token: the lexer returns one token per word",
    "MAX_TOKENS=4096\nTOKEN_LIMIT=128000",
    "We use sk-learn style pipelines; see scikit-learn docs.",
    "postgres://localhost:5432/app",
    "Context budget is 8k tokens; secrets must never be stored in memory.",
    "The JWT is validated by the auth middleware (RS256).",
    "Migration 0042 adds the credentials table (no data).",
]


@pytest.mark.parametrize(("text", "rule"), BLOCKED.values(), ids=BLOCKED.keys())
def test_secret_is_blocked(text: str, rule: str) -> None:
    result = evaluate(text)
    assert result.verdict is Verdict.BLOCK
    assert rule in result.rules


@pytest.mark.parametrize("text", ALLOWED)
def test_ordinary_technical_text_is_allowed(text: str) -> None:
    result = evaluate(text)
    assert result.verdict is Verdict.ALLOW, result.rules
    assert result.allowed and result.rules == ()


def test_evaluate_is_deterministic() -> None:
    text = BLOCKED["env_password"][0]
    assert evaluate(text) == evaluate(text)


def test_ensure_safe_reports_rules_but_never_the_secret() -> None:
    leaked = "hunter2" + "hunter"
    with pytest.raises(UnsafeMemoryContentError) as excinfo:
        ensure_safe("fine text", "DB_PASSWORD=" + leaked)
    assert excinfo.value.rules == ("env_secret_assignment",)
    assert leaked not in str(excinfo.value)
    assert "nothing was stored" in str(excinfo.value)


def test_ensure_safe_accepts_safe_texts() -> None:
    ensure_safe("a", "b", "Deploys happen on Tuesdays")
