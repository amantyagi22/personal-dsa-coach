"""The tool registry.

A tool is a plain Python function plus a Pydantic model describing its arguments.
The model does double duty: it generates the JSON Schema advertised to the LLM,
and it validates whatever the LLM sends back. One definition, so the two can
never disagree.

Every tool declares read_only. That single flag does two jobs:

1. Caching - only read-only results may be served from the per-turn cache.
   Caching a write would silently swallow a legitimate second write.
2. Permissions - `ask` is given the read-only tools only, so asking a question
   can never modify your learning history as a side effect.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.llm.base import ToolSpec


class ToolError(Exception):
    """A tool failed in a way the model should hear about and can recover from.

    Raised by tool implementations for expected failures - a problem that does
    not exist, a paid-only problem, an unreachable API. The loop turns these into
    tool results rather than propagating them, so the model can try something
    else instead of the command dying.
    """


@dataclass(frozen=True)
class Tool[A: BaseModel]:
    """One tool: its schema, its implementation, and whether it writes.

    Generic over its argument model so a handler can take the concrete type it
    actually expects (GetLeetCodeProblemArgs, not BaseModel) and still typecheck.
    """

    name: str
    description: str
    arguments: type[A]
    handler: Callable[[A], str]
    read_only: bool

    def spec(self) -> ToolSpec:
        """How this tool is advertised to the model."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=_json_schema(self.arguments),
        )

    def run(self, arguments: dict[str, Any]) -> str:
        """Validate arguments, then execute.

        Validation failures are ToolErrors so that malformed model output comes
        back as a correctable message rather than crashing the command. Models do
        send bad arguments, and the right response is to tell them what was wrong.
        """
        try:
            validated = self.arguments.model_validate(arguments)
        except ValidationError as exc:
            raise ToolError(f"Invalid arguments for {self.name}: {_readable(exc)}") from exc
        return self.handler(validated)


class ToolRegistry:
    """The set of tools available to an agent."""

    def __init__(self, tools: list[Tool[Any]] | None = None) -> None:
        # Tool[Any]: a registry holds tools with different argument models.
        self._tools: dict[str, Tool[Any]] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool[Any]) -> None:
        if tool.name in self._tools:
            raise ValueError(f"A tool named {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool[Any]:
        if name not in self._tools:
            raise ToolError(f"There is no tool named {name!r}. Available: {sorted(self._tools)}")
        return self._tools[name]

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    def read_only(self) -> ToolRegistry:
        """A registry containing only the read-only tools.

        This is the permission boundary for `ask`. Deriving it from the flag,
        rather than maintaining a second list, means a new write tool cannot be
        accidentally exposed by forgetting to update an allowlist.
        """
        return ToolRegistry([tool for tool in self._tools.values() if tool.read_only])

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools


def _json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The JSON Schema for a tool's arguments.

    Pydantic emits $defs/$ref for nested models, which Gemini's function
    declarations reject, so nothing here uses nested models. Titles are stripped
    because they add tokens without telling the model anything.
    """
    schema = model.model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    return schema


def _readable(exc: ValidationError) -> str:
    """Pydantic's error dump is verbose; the model only needs field and reason."""
    return "; ".join(
        f"{'.'.join(str(p) for p in error['loc']) or 'argument'}: {error['msg']}"
        for error in exc.errors()
    )
