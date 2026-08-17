from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolError, ToolRegistry


class SlugArgs(BaseModel):
    slug: str = Field(description="The problem's slug")


class LimitArgs(BaseModel):
    limit: int = Field(ge=1, le=100)


def make_tool(name: str = "get_problem", read_only: bool = True, handler=None) -> Tool:
    return Tool(
        name=name,
        description="Fetch a problem",
        arguments=SlugArgs,
        handler=handler or (lambda args: f"problem: {args.slug}"),
        read_only=read_only,
    )


def test_a_tool_runs_with_valid_arguments():
    assert make_tool().run({"slug": "two-sum"}) == "problem: two-sum"


def test_malformed_arguments_fail_with_a_message_naming_the_field():
    """Models do send bad arguments. The message has to be correctable."""
    with pytest.raises(ToolError) as excinfo:
        make_tool().run({"wrong_field": "x"})

    assert "slug" in str(excinfo.value)


def test_constraints_on_arguments_are_enforced():
    tool = Tool(
        name="search",
        description="d",
        arguments=LimitArgs,
        handler=lambda args: str(args.limit),
        read_only=True,
    )

    with pytest.raises(ToolError):
        tool.run({"limit": 500})


def test_the_advertised_schema_comes_from_the_pydantic_model():
    """One definition generates the schema and validates the reply."""
    spec = make_tool().spec()

    assert spec.name == "get_problem"
    assert spec.parameters["properties"]["slug"]["type"] == "string"
    assert spec.parameters["required"] == ["slug"]


def test_the_schema_carries_field_descriptions_through_to_the_model():
    assert "slug" in make_tool().spec().parameters["properties"]["slug"]["description"]


def test_registry_exposes_specs_for_every_tool():
    registry = ToolRegistry([make_tool("a"), make_tool("b")])

    assert sorted(spec.name for spec in registry.specs()) == ["a", "b"]


def test_asking_for_an_unknown_tool_lists_what_is_available():
    """The model invents tool names. It needs to know what actually exists."""
    registry = ToolRegistry([make_tool("get_problem")])

    with pytest.raises(ToolError) as excinfo:
        registry.get("get_probrem")

    assert "get_problem" in str(excinfo.value)


def test_registering_the_same_name_twice_is_rejected():
    registry = ToolRegistry([make_tool("a")])

    with pytest.raises(ValueError):
        registry.register(make_tool("a"))


def test_read_only_view_excludes_write_tools():
    registry = ToolRegistry(
        [
            make_tool("read_one", read_only=True),
            make_tool("write_one", read_only=False),
        ]
    )

    read_only = registry.read_only()

    assert "read_one" in read_only
    assert "write_one" not in read_only


def test_read_only_view_does_not_disturb_the_original():
    registry = ToolRegistry([make_tool("r", True), make_tool("w", False)])

    registry.read_only()

    assert len(registry) == 2
