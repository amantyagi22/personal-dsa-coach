"""The fake provider is test infrastructure for every later milestone.

If it drifts from LLMProvider, agent tests start passing for the wrong reasons -
so it gets its own tests.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.llm.base import ToolCall, ToolTurn
from app.llm.fake import FakeLLMProvider


class Answer(BaseModel):
    value: str


class Other(BaseModel):
    value: str


def test_returns_scripted_texts_in_order():
    provider = FakeLLMProvider(texts=["first", "second"])

    assert provider.generate("a") == "first"
    assert provider.generate("b") == "second"


def test_running_out_of_script_fails_loudly():
    provider = FakeLLMProvider(texts=["only one"])
    provider.generate("a")

    with pytest.raises(AssertionError):
        provider.generate("b")


def test_records_what_it_was_asked():
    provider = FakeLLMProvider(texts=["x"])

    provider.generate("why is my code slow", role="reasoning")

    assert provider.calls[0]["prompt"] == "why is my code slow"
    assert provider.calls[0]["role"] == "reasoning"


def test_structured_returns_the_scripted_model():
    provider = FakeLLMProvider(structured=[Answer(value="ok")])

    assert provider.generate_structured("q", Answer).value == "ok"


def test_structured_rejects_a_mismatched_script():
    """A test scripting the wrong type should fail, not silently pass."""
    provider = FakeLLMProvider(structured=[Other(value="ok")])

    with pytest.raises(AssertionError):
        provider.generate_structured("q", Answer)


def test_tool_turns_are_returned_in_order():
    provider = FakeLLMProvider(
        turns=[
            ToolTurn(tool_calls=[ToolCall(name="get_problem", arguments={"slug": "two-sum"})]),
            ToolTurn(text="done"),
        ]
    )

    first = provider.generate_with_tools([], [])
    second = provider.generate_with_tools([], [])

    assert first.tool_calls[0].name == "get_problem"
    assert second.is_final


def test_returns_the_scripted_turn_itself():
    """No defensive copy is attempted, so no test should believe there is one."""
    scripted = ToolTurn(tool_calls=[ToolCall(name="x", arguments={})])
    provider = FakeLLMProvider(turns=[scripted])

    assert provider.generate_with_tools([], []) is scripted


def test_records_the_tools_it_was_offered():
    from app.llm.base import ToolSpec

    provider = FakeLLMProvider(turns=[ToolTurn(text="done")])

    provider.generate_with_tools([], [ToolSpec(name="search", description="d", parameters={})])

    assert provider.calls[0]["tools"] == ["search"]
