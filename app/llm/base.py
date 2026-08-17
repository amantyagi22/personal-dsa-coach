"""The LLM provider interface.

Nothing outside app/llm imports a vendor SDK. Callers depend on this interface
only, which is what makes every agent test runnable with a fake provider and no
API key.

Three capabilities, because that is everything the coach needs from a model:

1. generate           - free-form text in, free-form text out
2. generate_structured - text in, a validated Pydantic model out
3. generate_with_tools - the agent loop's single step

Structured output is deliberately the *provider's* problem, not the caller's.
Gemini enforces a schema natively; a local model would need prompt-and-parse with
retries. Callers should never have to know which, or duplicate the retry logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.config import ModelRole


class LLMError(Exception):
    """Base for provider failures that callers are expected to handle."""


class RateLimitError(LLMError):
    """The model's quota is exhausted.

    Raised without retrying. The free tier's limits are daily, so a retry storm
    burns the remaining budget without ever succeeding.
    """


@dataclass(frozen=True)
class ToolCall:
    """A model's request to run one tool."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """The outcome of running one tool, fed back to the model."""

    name: str
    content: str


@dataclass(frozen=True)
class ToolSpec:
    """A tool as advertised to the model.

    parameters is a JSON Schema object, generated from a Pydantic model rather
    than hand-written, so the schema and the validation can never disagree.
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolTurn:
    """One turn of the agent loop.

    Either the model asked for tools, or it answered. Both fields populated is
    legal - some models narrate before calling.
    """

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def is_final(self) -> bool:
        return not self.tool_calls


class LLMProvider(ABC):
    """What the rest of the application is allowed to know about an LLM."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        role: ModelRole = "fast",
        system: str | None = None,
    ) -> str:
        """Free-form text completion."""

    @abstractmethod
    def generate_structured[T: BaseModel](
        self,
        prompt: str,
        schema: type[T],
        *,
        role: ModelRole = "fast",
        system: str | None = None,
    ) -> T:
        """A completion validated against a Pydantic model."""

    @abstractmethod
    def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        *,
        role: ModelRole = "fast",
        system: str | None = None,
    ) -> ToolTurn:
        """One turn of a tool-calling conversation.

        The provider does not loop. Looping, tool execution, and the conversation
        history all belong to the agent, so the loop stays ours and stays testable.
        """
