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


def test_the_model_name_is_visible_on_a_default_run(monkeypatch, capsys):
    """The acceptance criterion is that the model is logged on every call - so it
    has to survive the CLI's default log level, not just exist in the provider.
    """
    monkeypatch.setattr("app.cli.load_config", _fake_config)
    monkeypatch.setattr("app.cli.GeminiProvider", _logging_provider)
    _reset_logging()

    main(["ask", "Explain sliding window"])

    captured = capsys.readouterr()
    assert "an answer" in captured.out
    assert "model-small" in captured.err


def _reset_logging():
    """basicConfig is a no-op once the root logger has handlers, and pytest adds
    its own. Clearing them lets main() configure logging as it would in real use.
    """
    import logging

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)


def _logging_provider(config):
    """A provider that logs the way GeminiProvider does, without the SDK."""
    import logging

    class Logging(FakeLLMProvider):
        def generate(self, prompt, *, role="fast", system=None):
            logging.getLogger("app.llm.gemini").info(
                "Calling Gemini model %s", config.model_for(role)
            )
            return super().generate(prompt, role=role, system=system)

    return Logging(texts=["an answer"])


def test_the_answer_goes_to_stdout_and_logs_to_stderr(monkeypatch, capsys):
    """`ask ... > answer.txt` should capture the answer and nothing else."""
    provider = FakeLLMProvider(texts=["an answer"])
    monkeypatch.setattr("app.cli.load_config", _fake_config)
    monkeypatch.setattr("app.cli.GeminiProvider", lambda config: provider)

    main(["ask", "q"])

    captured = capsys.readouterr()
    assert captured.out.strip() == "an answer"


def _fake_config():
    from pathlib import Path

    from app.config import Config

    return Config("k", "model-big", "model-small", None, Path("data/test.db"))


def _raise_config_error():
    from app.config import ConfigError

    raise ConfigError("GEMINI_API_KEY is not set. Copy .env.example to .env")
