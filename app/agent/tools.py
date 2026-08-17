"""Tool implementations.

Each tool is a plain function over a service, wrapped with a Pydantic argument
model. Tools return text because that is what goes back to the model; the
services they call return real objects.
"""

from __future__ import annotations

import html
import re

from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolError, ToolRegistry
from app.problems.leetcode import LeetCodeClient, LeetCodeError, slug_from_url

MAX_CONTENT_CHARS = 6000


class GetLeetCodeProblemArgs(BaseModel):
    slug: str = Field(
        description=(
            "The problem's slug, for example 'two-sum'. A full LeetCode URL is also accepted."
        )
    )


def build_registry(client: LeetCodeClient | None = None) -> ToolRegistry:
    """The tools available to the agent.

    Takes its dependencies as arguments so tests can pass a stub client without
    patching module globals.
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

    return ToolRegistry(
        [
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
    )


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
