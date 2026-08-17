"""A scripted provider for tests.

Lives in app/ rather than tests/ because every later milestone's tests need it,
and because keeping it beside the interface means a change to LLMProvider breaks
the fake immediately instead of silently drifting.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.config import ModelRole
from app.llm.base import LLMProvider, ToolSpec, ToolTurn


class FakeLLMProvider(LLMProvider):
    """Returns scripted responses and records what it was asked.

    Each responses list is consumed in order. Running out is an error rather than
    a repeat of the last item - a test that makes more calls than it scripted has
    a bug worth surfacing.
    """

    def __init__(
        self,
        *,
        texts: list[str] | None = None,
        structured: list[BaseModel] | None = None,
        turns: list[ToolTurn] | None = None,
    ) -> None:
        self._texts = list(texts or [])
        self._structured = list(structured or [])
        self._turns = list(turns or [])
        self.calls: list[dict[str, Any]] = []

    def _next(self, queue: list[Any], kind: str) -> Any:
        if not queue:
            raise AssertionError(f"FakeLLMProvider ran out of scripted {kind} responses")
        return queue.pop(0)

    def generate(
        self,
        prompt: str,
        *,
        role: ModelRole = "fast",
        system: str | None = None,
    ) -> str:
        self.calls.append({"kind": "generate", "prompt": prompt, "role": role})
        return str(self._next(self._texts, "generate"))

    def generate_structured[T: BaseModel](
        self,
        prompt: str,
        schema: type[T],
        *,
        role: ModelRole = "fast",
        system: str | None = None,
    ) -> T:
        self.calls.append({"kind": "structured", "prompt": prompt, "role": role})
        value = self._next(self._structured, "structured")
        if not isinstance(value, schema):
            raise AssertionError(
                f"FakeLLMProvider was scripted with {type(value).__name__} "
                f"but the caller asked for {schema.__name__}"
            )
        return value

    def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        *,
        role: ModelRole = "fast",
        system: str | None = None,
    ) -> ToolTurn:
        self.calls.append(
            {
                "kind": "tools",
                "messages": list(messages),
                "tools": [t.name for t in tools],
                "role": role,
            }
        )
        turn: ToolTurn = self._next(self._turns, "tool")
        return turn
