"""Tests for GeminiProvider.

The Gemini SDK is stubbed at the client boundary - no network, no API key. These
assert on what a caller sees: the right model was used, a 429 becomes a
RateLimitError naming the model, structured output comes back as the requested
type, and tool calls are surfaced as ToolCall objects.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from pydantic import BaseModel

from app.config import Config
from app.llm.base import RateLimitError, ToolCall, ToolSpec
from app.llm.gemini import GeminiProvider


class Analysis(BaseModel):
    pattern: str
    difficulty: str


def make_config(**overrides: Any) -> Config:
    from pathlib import Path

    defaults: dict[str, Any] = {
        "gemini_api_key": "test-key",
        "model_reasoning": "model-big",
        "model_fast": "model-small",
        "leetcode_session": None,
        "database_path": Path("data/test.db"),
    }
    return Config(**{**defaults, **overrides})


class StubResponse:
    def __init__(
        self,
        text: str | None = None,
        parsed: Any = None,
        function_calls: list[Any] | None = None,
    ) -> None:
        self.text = text
        self.parsed = parsed
        self.function_calls = function_calls or []


class StubFunctionCall:
    def __init__(self, name: str, args: dict[str, Any] | None) -> None:
        self.name = name
        self.args = args


class StubModels:
    """Stands in for client.models, recording each call."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class StubClient:
    def __init__(self, responses: list[Any]) -> None:
        self.models = StubModels(responses)


def make_provider(responses: list[Any], **config_overrides: Any) -> GeminiProvider:
    client = StubClient(responses)
    return GeminiProvider(make_config(**config_overrides), client=client)


def test_generate_returns_the_model_text():
    provider = make_provider([StubResponse(text="A sliding window is...")])

    assert provider.generate("Explain sliding window") == "A sliding window is..."


def test_fast_role_uses_the_fast_model():
    provider = make_provider([StubResponse(text="hi")])

    provider.generate("hello", role="fast")

    assert provider.client.models.calls[0]["model"] == "model-small"


def test_reasoning_role_uses_the_reasoning_model():
    provider = make_provider([StubResponse(text="hi")])

    provider.generate("hello", role="reasoning")

    assert provider.client.models.calls[0]["model"] == "model-big"


def test_every_call_logs_the_model_name(caplog):
    provider = make_provider([StubResponse(text="hi")])

    with caplog.at_level(logging.INFO, logger="app.llm.gemini"):
        provider.generate("hello", role="reasoning")

    assert "model-big" in caplog.text


def test_empty_response_is_an_error_not_an_empty_string():
    from app.llm.base import LLMError

    provider = make_provider([StubResponse(text=None)])

    with pytest.raises(LLMError):
        provider.generate("hello")


def test_structured_output_returns_the_requested_type():
    expected = Analysis(pattern="Sliding Window", difficulty="Medium")
    provider = make_provider([StubResponse(parsed=expected)])

    result = provider.generate_structured("Analyse this", Analysis)

    assert result == expected


def test_structured_output_asks_gemini_to_enforce_the_schema():
    provider = make_provider([StubResponse(parsed=Analysis(pattern="P", difficulty="Easy"))])

    provider.generate_structured("Analyse this", Analysis)

    config = provider.client.models.calls[0]["config"]
    assert config.response_schema is Analysis
    assert config.response_mime_type == "application/json"


def test_structured_output_falls_back_to_parsing_json_text():
    """A model may return valid JSON without the SDK populating .parsed."""
    provider = make_provider(
        [StubResponse(text='{"pattern": "Two Pointers", "difficulty": "Easy"}')]
    )

    result = provider.generate_structured("Analyse this", Analysis)

    assert result.pattern == "Two Pointers"


def test_structured_output_rejects_unparseable_text():
    from app.llm.base import LLMError

    provider = make_provider([StubResponse(text="I'm afraid I can't do that")])

    with pytest.raises(LLMError):
        provider.generate_structured("Analyse this", Analysis)


def test_tool_turn_surfaces_function_calls():
    provider = make_provider(
        [StubResponse(function_calls=[StubFunctionCall("get_problem", {"slug": "two-sum"})])]
    )

    turn = provider.generate_with_tools(
        [{"role": "user", "content": "look it up"}],
        [ToolSpec(name="get_problem", description="Fetch one", parameters={"type": "object"})],
    )

    assert turn.tool_calls == [ToolCall(name="get_problem", arguments={"slug": "two-sum"})]
    assert not turn.is_final


def test_tool_turn_with_no_calls_is_final():
    provider = make_provider([StubResponse(text="Here is your answer.")])

    turn = provider.generate_with_tools([{"role": "user", "content": "hi"}], [])

    assert turn.is_final
    assert turn.text == "Here is your answer."


def test_function_call_with_no_arguments_becomes_an_empty_dict():
    provider = make_provider([StubResponse(function_calls=[StubFunctionCall("get_stats", None)])])

    turn = provider.generate_with_tools([{"role": "user", "content": "stats"}], [])

    assert turn.tool_calls[0].arguments == {}


def test_rate_limit_names_the_exhausted_model():
    provider = make_provider([_client_error(429, "quota exceeded")])

    with pytest.raises(RateLimitError) as excinfo:
        provider.generate("hello", role="reasoning")

    assert "model-big" in str(excinfo.value)


def test_rate_limit_does_not_retry():
    """The free tier's limits are daily. Retrying burns budget and cannot succeed."""
    provider = make_provider([_client_error(429, "quota exceeded")])

    with pytest.raises(RateLimitError):
        provider.generate("hello")

    assert len(provider.client.models.calls) == 1


def test_other_client_errors_surface_as_llm_errors():
    from app.llm.base import LLMError

    provider = make_provider([_client_error(400, "bad request")])

    with pytest.raises(LLMError) as excinfo:
        provider.generate("hello")

    assert not isinstance(excinfo.value, RateLimitError)


def test_rate_limit_names_the_env_var_for_the_role_not_the_model():
    """Both roles may point at the same model - a likely config once one quota dies.

    Deriving the role back from the model name gets it wrong in exactly that case.
    """
    provider = make_provider(
        [_client_error(429, "quota exceeded")],
        model_reasoning="same-model",
        model_fast="same-model",
    )

    with pytest.raises(RateLimitError) as excinfo:
        provider.generate("hello", role="fast")

    assert "GEMINI_MODEL_FAST" in str(excinfo.value)
    assert "GEMINI_MODEL_REASONING" not in str(excinfo.value)


def test_an_invalid_api_key_says_so_instead_of_dumping_json():
    """The most likely first-run failure. Gemini returns a generic 400 for it."""
    from app.llm.base import LLMError

    provider = make_provider([_client_error(400, "API key not valid.", reason="API_KEY_INVALID")])

    with pytest.raises(LLMError) as excinfo:
        provider.generate("hello")

    message = str(excinfo.value)
    assert "GEMINI_API_KEY" in message
    assert "aistudio.google.com" in message


def test_network_failure_becomes_an_llm_error_not_a_raw_traceback():
    """No internet is the most likely real failure. It is not an APIError."""
    from app.llm.base import LLMError

    provider = make_provider([ConnectionError("getaddrinfo failed")])

    with pytest.raises(LLMError) as excinfo:
        provider.generate("hello")

    assert "connection" in str(excinfo.value).lower()


def test_the_sdk_is_never_allowed_to_run_the_tool_loop():
    """The hand-written loop is the point of this project. If the SDK's automatic
    function calling stays on, it executes tools itself and the loop never runs.
    """
    provider = make_provider([StubResponse(text="done")])

    provider.generate_with_tools(
        [{"role": "user", "content": "hi"}],
        [ToolSpec(name="t", description="d", parameters={"type": "object"})],
    )

    config = provider.client.models.calls[0]["config"]
    assert config.automatic_function_calling.disable is True


def test_tool_result_messages_are_sent_as_function_responses():
    provider = make_provider([StubResponse(text="done")])

    provider.generate_with_tools(
        [
            {"role": "user", "content": "look it up"},
            {"role": "model", "content": "", "tool_calls": [ToolCall("get_problem", {})]},
            {"role": "tool", "name": "get_problem", "content": "Two Sum"},
        ],
        [],
    )

    contents = provider.client.models.calls[0]["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[2].parts[0].function_response is not None


def test_an_unknown_message_role_is_rejected():
    """Coercing it would misattribute the turn, and the model would act on it."""
    from app.llm.base import LLMError

    provider = make_provider([StubResponse(text="done")])

    with pytest.raises(LLMError) as excinfo:
        provider.generate_with_tools([{"role": "assistant", "content": "hi"}], [])

    assert "assistant" in str(excinfo.value)


def test_an_empty_message_is_rejected_rather_than_dropped():
    from app.llm.base import LLMError

    provider = make_provider([StubResponse(text="done")])

    with pytest.raises(LLMError):
        provider.generate_with_tools([{"role": "user", "content": ""}], [])


def _client_error(code: int, message: str, reason: str | None = None) -> Exception:
    """Build a ClientError the way the SDK does.

    The SDK's second argument is the already-parsed JSON body, not a response
    object - passing the wrong shape yields an exception whose str() omits the
    message entirely, which is exactly what the provider matches on.
    """
    from google.genai import errors

    error: dict[str, Any] = {"code": code, "message": message, "status": "INVALID_ARGUMENT"}
    if reason:
        error["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}]
    return errors.ClientError(code, {"error": error})
