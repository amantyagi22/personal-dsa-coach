"""The agent loop, written by hand.

No framework. Each turn: prompt the model with the conversation so far and the
tools it may use, receive tool calls, validate the arguments, execute the Python
function, feed the results back, repeat until the model answers.

The model chooses which tools to call and in what order - that is the agency.
It never computes anything; the tools do, in plain Python.

Three safety mechanisms, all of which double as cost controls because the Gemini
free tier is measured in requests per day:

- an iteration cap, configurable per command, since a deep analysis and a quick
  question deserve different budgets
- a per-turn cache of read-only results, so the same lookup is never paid for
  twice within one command
- a repetition guard that tells a stuck model to answer with what it has, rather
  than raising and losing the work
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agent.registry import ToolError, ToolRegistry
from app.config import ModelRole
from app.llm.base import LLMProvider, ToolCall

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 8
DEFAULT_REPETITION_LIMIT = 3

_WRAP_UP_INSTRUCTION = (
    "You have now called the same tool with the same arguments several times and "
    "are not making progress. Do not call any more tools. Answer the question with "
    "the information you already have, and say plainly if something is missing."
)


@dataclass
class AgentResult:
    """What a completed loop produced, and how it got there."""

    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    iterations: int = 0
    hit_iteration_cap: bool = False
    hit_repetition_guard: bool = False


class Agent:
    """A tool-calling agent over one registry.

    One instance per command rather than one shared: max_iterations differs by
    command, and the result cache must not outlive a single turn.
    """

    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        *,
        system: str,
        role: ModelRole = "fast",
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        repetition_limit: int = DEFAULT_REPETITION_LIMIT,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.system = system
        self.role = role
        self.max_iterations = max_iterations
        self.repetition_limit = repetition_limit

    def run(self, question: str) -> AgentResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        specs = self.registry.specs()

        # Both are per-turn, deliberately. A cache that outlived the turn would
        # serve yesterday's data; counts that did would fire the guard spuriously.
        cache: dict[str, str] = {}
        counts: dict[str, int] = {}

        result = AgentResult(answer="")
        warned = False

        for iteration in range(1, self.max_iterations + 1):
            result.iterations = iteration
            turn = self.provider.generate_with_tools(
                messages, specs, role=self.role, system=self.system
            )

            if turn.is_final:
                result.answer = turn.text
                return result

            messages.append({"role": "model", "content": turn.text, "tool_calls": turn.tool_calls})

            for call in turn.tool_calls:
                result.tool_calls.append(call)
                key = _cache_key(call)
                counts[key] = counts.get(key, 0) + 1

                messages.append(
                    {
                        "role": "tool",
                        "name": call.name,
                        "content": self._execute(call, key, cache),
                    }
                )

            # Checked after executing, so the model still sees the results it
            # asked for before being told to stop.
            if not warned and any(n >= self.repetition_limit for n in counts.values()):
                warned = True
                result.hit_repetition_guard = True
                messages.append({"role": "user", "content": _WRAP_UP_INSTRUCTION})
                logger.info("Repetition guard fired; asking the model to wrap up")

        # Out of iterations. One last call with no tools, so the work already done
        # becomes an answer instead of being discarded.
        result.hit_iteration_cap = True
        logger.info("Reached the %d-iteration cap; asking for a final answer", self.max_iterations)
        messages.append({"role": "user", "content": _WRAP_UP_INSTRUCTION})
        final = self.provider.generate_with_tools(
            [*messages], [], role=self.role, system=self.system
        )
        result.answer = final.text
        return result

    def _execute(self, call: ToolCall, key: str, cache: dict[str, str]) -> str:
        """Run one tool call, returning what the model should see.

        Tool failures come back as text rather than raising: the model can read
        "that problem does not exist" and try a different slug, which is a better
        outcome than the command dying.
        """
        if key in cache:
            logger.info("Serving %s from cache", call.name)
            return cache[key]

        try:
            tool = self.registry.get(call.name)
            output = tool.run(call.arguments)
        except ToolError as exc:
            # Not cached - an error is not a result, and the retry may succeed.
            logger.info("Tool %s failed: %s", call.name, exc)
            return f"Error: {exc}"

        logger.info("Ran %s", call.name)
        if tool.read_only:
            # Only read-only results are cacheable. Caching a write would swallow
            # a legitimate second write.
            cache[key] = output
        return output


def _cache_key(call: ToolCall) -> str:
    """Identity of a call: the tool plus its arguments.

    sort_keys so that argument order never makes two identical calls look
    different - which would defeat both the cache and the repetition guard.
    """
    return f"{call.name}:{json.dumps(call.arguments, sort_keys=True, default=str)}"
