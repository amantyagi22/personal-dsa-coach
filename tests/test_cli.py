"""The CLI is a thin adapter and not a test seam, so this covers only the two
things a caller actually depends on: `ask` reaches the provider, and a missing
key produces an actionable message instead of a stack trace.
"""

from __future__ import annotations

import pytest

from app.cli import build_parser, cmd_ask, main
from app.llm.fake import FakeLLMProvider


def test_ask_returns_the_providers_answer():
    provider = FakeLLMProvider(texts=["A sliding window keeps a running range..."])

    answer = cmd_ask("Explain sliding window", provider)

    assert answer == "A sliding window keeps a running range..."


def test_ask_uses_the_fast_model():
    """`ask` runs often, so it must not spend the scarce reasoning quota."""
    provider = FakeLLMProvider(texts=["..."])

    cmd_ask("Explain sliding window", provider)

    assert provider.calls[0]["role"] == "fast"


def test_missing_key_exits_non_zero_with_an_actionable_message(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("app.cli.load_config", lambda: _raise_config_error())

    exit_code = main(["ask", "anything"])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "GEMINI_API_KEY" in stderr
    assert "Traceback" not in stderr


def test_ask_requires_a_question():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["ask"])


def _raise_config_error():
    from app.config import ConfigError

    raise ConfigError("GEMINI_API_KEY is not set. Copy .env.example to .env")
