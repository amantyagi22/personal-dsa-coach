import pytest

from app.config import ConfigError, load_config


def test_loads_api_key_and_models(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL_REASONING", "model-big")
    monkeypatch.setenv("GEMINI_MODEL_FAST", "model-small")

    config = load_config(use_dotenv=False)

    assert config.gemini_api_key == "test-key"
    assert config.model_reasoning == "model-big"
    assert config.model_fast == "model-small"


def test_models_have_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL_REASONING", raising=False)
    monkeypatch.delenv("GEMINI_MODEL_FAST", raising=False)

    config = load_config(use_dotenv=False)

    assert config.model_reasoning
    assert config.model_fast


def test_missing_api_key_names_the_variable_and_how_to_fix_it(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ConfigError) as excinfo:
        load_config(use_dotenv=False)

    message = str(excinfo.value)
    assert "GEMINI_API_KEY" in message
    assert ".env" in message


def test_blank_api_key_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")

    with pytest.raises(ConfigError):
        load_config(use_dotenv=False)


def test_leetcode_session_is_optional(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("LEETCODE_SESSION", raising=False)

    assert load_config(use_dotenv=False).leetcode_session is None


def test_model_for_role_selects_per_role(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL_REASONING", "model-big")
    monkeypatch.setenv("GEMINI_MODEL_FAST", "model-small")

    config = load_config(use_dotenv=False)

    assert config.model_for("reasoning") == "model-big"
    assert config.model_for("fast") == "model-small"
