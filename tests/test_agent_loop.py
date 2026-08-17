"""Tests for the hand-written agent loop.

Everything runs against a fake provider returning scripted tool calls - no
network, no API key. This is the seam the spec names as making the loop testable
at all.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agent.loop import Agent
from app.agent.registry import Tool, ToolError, ToolRegistry
from app.llm.base import ToolCall, ToolTurn
from app.llm.fake import FakeLLMProvider


class SlugArgs(BaseModel):
    slug: str


def counting_tool(name: str = "get_problem", read_only: bool = True) -> tuple[Tool, list[str]]:
    """A tool that records every slug it was actually executed with."""
    seen: list[str] = []

    def handler(args: SlugArgs) -> str:
        seen.append(args.slug)
        return f"content of {args.slug}"

    return (
        Tool(
            name=name,
            description="Fetch a problem",
            arguments=SlugArgs,
            handler=handler,
            read_only=read_only,
        ),
        seen,
    )


def failing_tool(message: str = "no such problem") -> Tool:
    def handler(args: SlugArgs) -> str:
        raise ToolError(message)

    return Tool(
        name="get_problem",
        description="Fetch a problem",
        arguments=SlugArgs,
        handler=handler,
        read_only=True,
    )


def make_agent(turns: list[ToolTurn], tools: list[Tool], **kwargs) -> Agent:
    return Agent(
        FakeLLMProvider(turns=turns),
        ToolRegistry(tools),
        system="You are a coach.",
        **kwargs,
    )


def call(slug: str = "two-sum", name: str = "get_problem") -> ToolCall:
    return ToolCall(name=name, arguments={"slug": slug})


def test_a_final_answer_ends_the_loop():
    agent = make_agent([ToolTurn(text="Sliding window keeps a range.")], [])

    result = agent.run("Explain sliding window")

    assert result.answer == "Sliding window keeps a range."
    assert result.iterations == 1


def test_a_tool_call_is_executed_and_the_loop_continues():
    tool, seen = counting_tool()
    agent = make_agent(
        [ToolTurn(tool_calls=[call("two-sum")]), ToolTurn(text="Two Sum uses a hash map.")],
        [tool],
    )

    result = agent.run("What is Two Sum about?")

    assert seen == ["two-sum"]
    assert result.answer == "Two Sum uses a hash map."
    assert result.iterations == 2


def test_the_tool_result_is_sent_back_to_the_model():
    tool, _ = counting_tool()
    provider = FakeLLMProvider(
        turns=[ToolTurn(tool_calls=[call("two-sum")]), ToolTurn(text="done")]
    )
    agent = Agent(provider, ToolRegistry([tool]), system="s")

    agent.run("q")

    second_turn_messages = provider.calls[1]["messages"]
    assert any(
        message.get("role") == "tool" and "content of two-sum" in message["content"]
        for message in second_turn_messages
    )


def test_several_tool_calls_in_one_turn_all_run():
    tool, seen = counting_tool()
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("two-sum"), call("3sum")]),
            ToolTurn(text="both fetched"),
        ],
        [tool],
    )

    agent.run("compare them")

    assert seen == ["two-sum", "3sum"]


def test_a_tool_error_is_returned_to_the_model_not_raised():
    """The model can read the failure and try something else."""
    provider = FakeLLMProvider(
        turns=[ToolTurn(tool_calls=[call("nope")]), ToolTurn(text="That problem does not exist.")]
    )
    agent = Agent(provider, ToolRegistry([failing_tool()]), system="s")

    result = agent.run("tell me about nope")

    assert result.answer == "That problem does not exist."
    tool_messages = [m for m in provider.calls[1]["messages"] if m.get("role") == "tool"]
    assert "no such problem" in tool_messages[0]["content"]


def test_an_unexpected_bug_in_a_tool_does_not_crash_the_command():
    """ToolError is the expected-failure channel. A KeyError from a tool is a bug,
    but the user should get an answer, not a traceback.
    """

    def explode(args: SlugArgs) -> str:
        raise KeyError("some internal bug")

    tool = Tool(
        name="get_problem",
        description="d",
        arguments=SlugArgs,
        handler=explode,
        read_only=True,
    )
    provider = FakeLLMProvider(
        turns=[ToolTurn(tool_calls=[call("two-sum")]), ToolTurn(text="I could not fetch that.")]
    )

    result = Agent(provider, ToolRegistry([tool]), system="s").run("q")

    assert result.answer == "I could not fetch that."
    tool_messages = [m for m in provider.calls[1]["messages"] if m.get("role") == "tool"]
    assert "KeyError" in tool_messages[0]["content"]


def test_malformed_arguments_come_back_as_a_correctable_error():
    tool, seen = counting_tool()
    provider = FakeLLMProvider(
        turns=[
            ToolTurn(tool_calls=[ToolCall(name="get_problem", arguments={"wrong": "x"})]),
            ToolTurn(text="Let me try again."),
        ]
    )
    agent = Agent(provider, ToolRegistry([tool]), system="s")

    agent.run("q")

    assert seen == []
    tool_messages = [m for m in provider.calls[1]["messages"] if m.get("role") == "tool"]
    assert "slug" in tool_messages[0]["content"]


def test_an_unknown_tool_name_comes_back_as_an_error():
    tool, _ = counting_tool()
    provider = FakeLLMProvider(
        turns=[ToolTurn(tool_calls=[call(name="invented_tool")]), ToolTurn(text="sorry")]
    )
    agent = Agent(provider, ToolRegistry([tool]), system="s")

    agent.run("q")

    tool_messages = [m for m in provider.calls[1]["messages"] if m.get("role") == "tool"]
    assert "invented_tool" in tool_messages[0]["content"]


def test_identical_read_only_calls_are_served_from_cache():
    tool, seen = counting_tool(read_only=True)
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(text="done"),
        ],
        [tool],
    )

    agent.run("q")

    assert seen == ["two-sum"], "the second identical call should not have executed"


def test_write_tools_are_never_cached():
    """Caching a write would silently swallow a legitimate second write."""
    tool, seen = counting_tool(read_only=False)
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(text="done"),
        ],
        [tool],
    )

    agent.run("q")

    assert seen == ["two-sum", "two-sum"]


def test_different_arguments_are_not_served_from_cache():
    tool, seen = counting_tool()
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(tool_calls=[call("3sum")]),
            ToolTurn(text="done"),
        ],
        [tool],
    )

    agent.run("q")

    assert seen == ["two-sum", "3sum"]


def test_argument_order_does_not_defeat_the_cache():
    """Same arguments in a different order are the same call."""
    seen: list[dict] = []

    class TwoArgs(BaseModel):
        a: str
        b: str

    tool = Tool(
        name="t",
        description="d",
        arguments=TwoArgs,
        handler=lambda args: seen.append({"a": args.a, "b": args.b}) or "ok",
        read_only=True,
    )
    agent = make_agent(
        [
            ToolTurn(tool_calls=[ToolCall("t", {"a": "1", "b": "2"})]),
            ToolTurn(tool_calls=[ToolCall("t", {"b": "2", "a": "1"})]),
            ToolTurn(text="done"),
        ],
        [tool],
    )

    agent.run("q")

    assert len(seen) == 1


def test_a_failed_call_is_not_cached():
    """An error is not a result - the retry may well succeed."""
    attempts: list[str] = []

    def handler(args: SlugArgs) -> str:
        attempts.append(args.slug)
        if len(attempts) == 1:
            raise ToolError("temporarily unavailable")
        return "content"

    tool = Tool(
        name="get_problem",
        description="d",
        arguments=SlugArgs,
        handler=handler,
        read_only=True,
    )
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(text="done"),
        ],
        [tool],
    )

    agent.run("q")

    assert attempts == ["two-sum", "two-sum"]


def test_the_repetition_guard_fires_and_still_produces_an_answer():
    """A stuck model should yield a slightly thin answer, not a stack trace."""
    tool, _ = counting_tool()
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(text="Here is what I have."),
        ],
        [tool],
        repetition_limit=3,
    )

    result = agent.run("q")

    assert result.hit_repetition_guard
    assert result.answer == "Here is what I have."


def test_the_guard_withholds_tools_rather_than_just_asking_nicely():
    """A model that ignores the instruction must still be stopped. Otherwise the
    guard is a suggestion and a stuck model spends the daily quota anyway.
    """
    tool, _ = counting_tool()
    stubborn = [ToolTurn(tool_calls=[call("same")]) for _ in range(30)]
    provider = FakeLLMProvider(turns=stubborn)

    result = Agent(
        provider,
        ToolRegistry([tool]),
        system="s",
        max_iterations=20,
        repetition_limit=3,
    ).run("q")

    assert result.hit_repetition_guard
    assert len(provider.calls) <= 5, "a stuck model should not run to the iteration cap"
    assert sum(1 for c in provider.calls if c["tools"]) == 3
    assert result.answer.strip()


def test_the_guard_lets_a_cooperating_model_answer_normally():
    """Withholding tools must not prevent the answer that follows."""
    tool, _ = counting_tool()
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("same")]),
            ToolTurn(tool_calls=[call("same")]),
            ToolTurn(tool_calls=[call("same")]),
            ToolTurn(text="Here is what I found."),
        ],
        [tool],
        repetition_limit=3,
    )

    result = agent.run("q")

    assert result.answer == "Here is what I found."


def test_the_repetition_guard_does_not_fire_when_arguments_vary():
    tool, _ = counting_tool()
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(tool_calls=[call("3sum")]),
            ToolTurn(tool_calls=[call("4sum")]),
            ToolTurn(text="compared"),
        ],
        [tool],
        repetition_limit=3,
    )

    result = agent.run("q")

    assert not result.hit_repetition_guard


def test_the_repetition_limit_is_configurable():
    tool, _ = counting_tool()
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(text="done"),
        ],
        [tool],
        repetition_limit=2,
    )

    assert agent.run("q").hit_repetition_guard


def test_the_iteration_cap_stops_the_loop_and_asks_for_an_answer():
    tool, _ = counting_tool()
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("a")]),
            ToolTurn(tool_calls=[call("b")]),
            ToolTurn(text="Answer from what I gathered."),
        ],
        [tool],
        max_iterations=2,
        repetition_limit=99,
    )

    result = agent.run("q")

    assert result.hit_iteration_cap
    assert result.iterations == 2
    assert result.answer == "Answer from what I gathered."


def test_the_final_call_after_the_cap_offers_no_tools():
    """Otherwise the model just asks for another tool and the cap means nothing."""
    tool, _ = counting_tool()
    provider = FakeLLMProvider(turns=[ToolTurn(tool_calls=[call("a")]), ToolTurn(text="final")])
    agent = Agent(provider, ToolRegistry([tool]), system="s", max_iterations=1, repetition_limit=99)

    agent.run("q")

    assert provider.calls[-1]["tools"] == []


def test_the_iteration_cap_is_configurable_per_agent():
    """A deep analysis and a quick question need different budgets."""
    tool, _ = counting_tool()

    def agent_with_cap(cap: int) -> Agent:
        return make_agent(
            [ToolTurn(tool_calls=[call(f"p{i}")]) for i in range(cap)] + [ToolTurn(text="done")],
            [tool],
            max_iterations=cap,
            repetition_limit=99,
        )

    assert agent_with_cap(2).run("q").iterations == 2
    assert agent_with_cap(5).run("q").iterations == 5


def test_the_agent_only_offers_the_tools_it_was_given():
    """This is the permission boundary `ask` depends on."""
    read_tool, _ = counting_tool("read_one", read_only=True)
    write_tool, _ = counting_tool("write_one", read_only=False)
    provider = FakeLLMProvider(turns=[ToolTurn(text="done")])
    registry = ToolRegistry([read_tool, write_tool])

    Agent(provider, registry.read_only(), system="s").run("q")

    assert provider.calls[0]["tools"] == ["read_one"]


def test_the_model_role_is_passed_through():
    provider = FakeLLMProvider(turns=[ToolTurn(text="done")])
    Agent(provider, ToolRegistry([]), system="s", role="reasoning").run("q")

    assert provider.calls[0]["role"] == "reasoning"


def test_every_executed_call_is_reported():
    tool, _ = counting_tool()
    agent = make_agent(
        [
            ToolTurn(tool_calls=[call("two-sum")]),
            ToolTurn(tool_calls=[call("3sum")]),
            ToolTurn(text="done"),
        ],
        [tool],
    )

    result = agent.run("q")

    assert [c.arguments["slug"] for c in result.tool_calls] == ["two-sum", "3sum"]


def test_an_empty_final_answer_never_reaches_the_caller():
    """A model can legally reply with no tools and no text. Printing "" reads as
    a crash that swallowed the output.
    """
    agent = make_agent([ToolTurn(text="")], [])

    assert agent.run("q").answer.strip()


def test_hitting_the_cap_with_an_empty_reply_still_says_something():
    """The worst case: a model that calls tools until the cap, then says nothing."""
    tool, _ = counting_tool()
    agent = make_agent(
        [ToolTurn(tool_calls=[call(f"p{i}")]) for i in range(6)],
        [tool],
        max_iterations=3,
        repetition_limit=99,
    )

    result = agent.run("q")

    assert result.hit_iteration_cap
    assert "3 steps" in result.answer


def test_running_out_of_scripted_turns_is_a_test_bug_not_a_silent_pass():
    tool, _ = counting_tool()
    agent = make_agent([ToolTurn(tool_calls=[call("a")])], [tool], max_iterations=5)

    with pytest.raises(AssertionError):
        agent.run("q")
