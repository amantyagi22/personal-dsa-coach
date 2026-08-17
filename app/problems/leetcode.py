"""LeetCode's public GraphQL API.

Problem data needs no authentication - the catalogue and every problem's full
description are public. Only submission history requires a session cookie, and
that arrives in a later milestone.

urllib rather than requests or httpx: one POST to one endpoint does not justify
a dependency.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://leetcode.com/graphql/"
DEFAULT_TIMEOUT = 15

_PROBLEM_QUERY = """
query problem($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionFrontendId
    title
    titleSlug
    difficulty
    isPaidOnly
    topicTags { name slug }
    content
  }
}
"""


class LeetCodeError(Exception):
    """A LeetCode request failed in a way the caller should explain, not crash on."""


@dataclass(frozen=True)
class Problem:
    number: str
    title: str
    slug: str
    difficulty: str
    topic_tags: list[str]
    content: str
    url: str


class LeetCodeClient:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    def get_problem(self, slug: str) -> Problem:
        """Fetch one problem by slug.

        Two distinct failures, verified against the live API and worth separate
        messages: an unknown slug returns question: null, while a premium problem
        returns metadata with content: null. Telling a user "that problem does
        not exist" when it exists but is paid-only would send them looking for a
        typo that is not there.
        """
        data = self._query(_PROBLEM_QUERY, {"titleSlug": slug})
        question = data.get("question")
        if question is None:
            raise LeetCodeError(
                f"No LeetCode problem with the slug {slug!r}. "
                f"The slug is the last part of the problem URL, for example "
                f"'two-sum' in leetcode.com/problems/two-sum/"
            )

        if question.get("isPaidOnly") and not question.get("content"):
            raise LeetCodeError(
                f"{question.get('title', slug)!r} is a LeetCode Premium problem, "
                f"so its description is not publicly available."
            )

        return Problem(
            number=question.get("questionFrontendId") or "",
            title=question.get("title") or slug,
            slug=question.get("titleSlug") or slug,
            difficulty=question.get("difficulty") or "Unknown",
            topic_tags=[tag["name"] for tag in question.get("topicTags") or []],
            content=question.get("content") or "",
            url=f"https://leetcode.com/problems/{question.get('titleSlug') or slug}/",
        )

    def _query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(
            GRAPHQL_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                # LeetCode rejects requests without these.
                "Referer": "https://leetcode.com",
                "User-Agent": "personal-dsa-coach",
            },
        )

        logger.info("Querying LeetCode for %s", variables)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise LeetCodeError(f"LeetCode returned HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise LeetCodeError(
                f"Could not reach LeetCode: {exc.reason}. Check your internet connection."
            ) from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise LeetCodeError(f"LeetCode gave an unusable response: {exc}") from exc

        if body.get("errors"):
            message = "; ".join(e.get("message", "unknown") for e in body["errors"])
            raise LeetCodeError(f"LeetCode rejected the query: {message}")

        data = body.get("data")
        if data is None:
            raise LeetCodeError("LeetCode returned no data.")
        return dict(data)


def slug_from_url(value: str) -> str:
    """Accept a full problem URL or a bare slug.

    People paste URLs. Requiring the slug and rejecting the URL they already have
    open would be needless friction.
    """
    value = value.strip().rstrip("/")
    if "leetcode.com" not in value:
        return value

    parts = [p for p in value.split("/") if p]
    if "problems" in parts:
        index = parts.index("problems")
        if index + 1 < len(parts):
            return parts[index + 1]
    raise LeetCodeError(f"Could not find a problem slug in {value!r}")
