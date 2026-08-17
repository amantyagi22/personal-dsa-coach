"""Tool implementations.

Each tool is a plain function over a service, wrapped with a Pydantic argument
model. Tools return text because that is what goes back to the model; the
services they call return real objects.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
from typing import Any

from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolError, ToolRegistry
from app.problems.leetcode import LeetCodeClient, LeetCodeError, slug_from_url
from app.storage.db import Connection
from app.storage.repositories import PatternRepository, ProblemRepository

MAX_CONTENT_CHARS = 6000


MAX_SEARCH_RESULTS = 20
MAX_SNIPPET_CHARS = 300


class GetLeetCodeProblemArgs(BaseModel):
    slug: str = Field(
        description=(
            "The problem's slug, for example 'two-sum'. A full LeetCode URL is also accepted."
        )
    )


class SearchProblemsArgs(BaseModel):
    query: str = Field(
        default="",
        description="Words to match against problem titles and descriptions. Optional.",
    )
    pattern: str = Field(
        default="",
        description="Restrict to one DSA pattern, for example 'Sliding Window'. Optional.",
    )
    difficulty: str = Field(
        default="",
        description="Restrict to Easy, Medium, or Hard. Optional.",
    )
    analysed_only: bool = Field(
        default=False,
        description=(
            "Only problems that have already been analysed. Use this when looking "
            "for prior work to compare against."
        ),
    )


def build_registry(
    client: LeetCodeClient | None = None,
    connection: Connection | None = None,
) -> ToolRegistry:
    """The tools available to the agent.

    Takes its dependencies as arguments so tests can pass a stub client and an
    in-memory database without patching module globals.

    Without a connection only the LeetCode tool is registered, which is what the
    `problem` command needs. The database tools appear when there is a database
    to serve them - a tool that would always fail is worse than an absent one,
    because the model wastes a turn discovering it.
    """
    leetcode = client or LeetCodeClient()

    def get_leetcode_problem(args: GetLeetCodeProblemArgs) -> str:
        try:
            problem = leetcode.get_problem(slug_from_url(args.slug))
        except LeetCodeError as exc:
            # Becomes a tool result, so the model can correct the slug itself.
            raise ToolError(str(exc)) from exc

        return "\n".join(
            [
                f"Problem {problem.number}: {problem.title}",
                f"Difficulty: {problem.difficulty}",
                f"Topic tags: {', '.join(problem.topic_tags) or 'none'}",
                f"URL: {problem.url}",
                "",
                _to_text(problem.content),
            ]
        )

    tools: list[Tool[Any]] = [
        Tool(
            name="get_leetcode_problem",
            description=(
                "Fetch a LeetCode problem's full description, difficulty, and "
                "topic tags. Use this whenever you need to know what a problem "
                "actually asks before reasoning about it."
            ),
            arguments=GetLeetCodeProblemArgs,
            handler=get_leetcode_problem,
            read_only=True,
        )
    ]

    if connection is not None:
        tools.append(_search_problems_tool(connection))

    return ToolRegistry(tools)


def _search_problems_tool(connection: Connection) -> Tool[SearchProblemsArgs]:
    """The retrieval half of finding similar problems.

    Python retrieves a deliberately wide candidate set; the model judges which
    are genuinely similar. At a few thousand problems that beats a vector index,
    because handing the model twenty candidates to read costs less than
    maintaining an embedding pipeline.
    """
    problems = ProblemRepository(connection)
    patterns = PatternRepository(connection)

    def search_problems(args: SearchProblemsArgs) -> str:
        pattern_id: int | None = None
        if args.pattern:
            row = patterns.resolve(args.pattern)
            if row is None:
                known = ", ".join(p["name"] for p in patterns.all()[:12])
                raise ToolError(f"No pattern named {args.pattern!r}. Some valid ones: {known}")
            pattern_id = int(row["id"])

        difficulty = args.difficulty.strip().title() or None
        if difficulty and difficulty not in {"Easy", "Medium", "Hard"}:
            raise ToolError(f"Difficulty must be Easy, Medium, or Hard, not {args.difficulty!r}.")

        found = problems.search(
            text=args.query or None,
            pattern_id=pattern_id,
            difficulty=difficulty,
            analysed_only=args.analysed_only,
            limit=MAX_SEARCH_RESULTS,
        )
        if not found:
            return "No problems matched. Try fewer filters or different words."

        return "\n".join(_describe(row) for row in found)

    return Tool(
        name="search_problems",
        description=(
            "Search the local problem catalogue by words, pattern, and difficulty. "
            "Use analysed_only to find problems you have already analysed, which is "
            "how you find prior work to compare a new problem against."
        ),
        arguments=SearchProblemsArgs,
        handler=search_problems,
        read_only=True,
    )


def _describe(row: sqlite3.Row) -> str:
    """One search result, compact enough that twenty of them fit in a prompt."""
    parts = [f"- {row['title']} ({row['slug']}) [{row['difficulty']}]"]
    if row["analysis"]:
        analysis = json.loads(row["analysis"])
        if insight := analysis.get("key_insight"):
            parts.append(f"    analysed - key insight: {_truncate(insight)}")
        if pattern := analysis.get("pattern"):
            parts[0] += f" pattern: {pattern}"
    elif tags := json.loads(row["topic_tags"] or "[]"):
        parts[0] += f" tags: {', '.join(tags[:4])}"
    return "\n".join(parts)


def _truncate(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def _to_text(content: str) -> str:
    """Turn LeetCode's HTML into plain text.

    The model reads prose, not markup - and the tags are perhaps a third of the
    payload, which matters when every request counts against a daily quota.
    """
    if not content:
        return "(no description available)"

    text = re.sub(r"<(br|/p|/div|/li)\s*/?>", "\n", content, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) > MAX_CONTENT_CHARS:
        text = text[:MAX_CONTENT_CHARS] + "\n\n[description truncated]"
    return text
