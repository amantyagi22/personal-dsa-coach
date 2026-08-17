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
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://leetcode.com/graphql/"
DEFAULT_TIMEOUT = 15

# LeetCode caps a page at 100 regardless of what limit is requested. Verified
# against the live API: asking for 500 or 1000 still returns 100.
CATALOGUE_PAGE_SIZE = 100

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

_CATALOGUE_QUERY = """
query catalogue($categorySlug: String, $limit: Int, $skip: Int,
                $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(categorySlug: $categorySlug, limit: $limit,
                                       skip: $skip, filters: $filters) {
    total: totalNum
    questions: data {
      questionFrontendId
      title
      titleSlug
      difficulty
      isPaidOnly
      topicTags { name slug }
    }
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
    # Paid problems cannot be opened without a subscription, so the recommender
    # needs to know rather than suggesting something unreadable.
    is_paid_only: bool = False


@dataclass(frozen=True)
class CataloguePage:
    """One page of the catalogue, plus how many problems exist in total."""

    problems: list[Problem]
    total: int


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

        # Everything below treats the payload as untrusted. An anti-bot page or a
        # schema change should produce a message, not a TypeError from deep inside
        # a comprehension.
        if not isinstance(question, dict):
            raise LeetCodeError(f"LeetCode returned an unexpected shape for {slug!r}.")

        if question.get("isPaidOnly") and not question.get("content"):
            raise LeetCodeError(
                f"{_text(question.get('title')) or slug!r} is a LeetCode Premium problem, "
                f"so its description is not publicly available."
            )

        return _to_problem(question, fallback_slug=slug)

    def get_catalogue_page(self, skip: int, limit: int = CATALOGUE_PAGE_SIZE) -> CataloguePage:
        """Fetch one page of the problem catalogue.

        No authentication needed - only submission history requires a cookie.
        Pages carry metadata and tags but no problem descriptions; those are
        fetched per problem on demand, because 4,000 full descriptions is a lot
        of text nobody has asked to read.
        """
        data = self._query(
            _CATALOGUE_QUERY,
            {"categorySlug": "", "limit": limit, "skip": skip, "filters": {}},
        )
        page = data.get("problemsetQuestionList")
        if not isinstance(page, dict):
            raise LeetCodeError("LeetCode returned an unexpected shape for the catalogue.")

        questions = page.get("questions")
        if not isinstance(questions, list):
            raise LeetCodeError("LeetCode returned no problem list.")

        return CataloguePage(
            problems=[_to_problem(q) for q in questions if isinstance(q, dict)],
            total=int(page.get("total") or 0),
        )

    def iter_catalogue(self) -> Iterator[Problem]:
        """Yield every problem in the catalogue, one page at a time.

        A generator rather than a list: the caller can write each page to the
        database as it arrives and report progress, instead of holding 4,000
        problems in memory and showing nothing for a minute.

        Stops on an empty page rather than trusting the reported total, which is
        the only termination condition that cannot loop forever if the total is
        wrong.
        """
        skip = 0
        while True:
            page = self.get_catalogue_page(skip)
            if not page.problems:
                return
            yield from page.problems
            skip += len(page.problems)
            if skip >= page.total:
                return

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

        # An anti-bot page or a schema change can put any shape here. Nothing
        # below may assume a dict without checking.
        if not isinstance(body, dict):
            raise LeetCodeError("LeetCode returned something that was not a GraphQL response.")

        if errors := body.get("errors"):
            raise LeetCodeError(f"LeetCode rejected the query: {_error_messages(errors)}")

        data = body.get("data")
        if not isinstance(data, dict):
            raise LeetCodeError("LeetCode returned no usable data.")
        return data


def _to_problem(question: dict[str, Any], fallback_slug: str = "") -> Problem:
    """Build a Problem from an untrusted question payload.

    Shared by the single-problem and catalogue queries, which return the same
    fields except that catalogue pages carry no content.
    """
    slug = _text(question.get("titleSlug")) or fallback_slug
    return Problem(
        number=_text(question.get("questionFrontendId")),
        title=_text(question.get("title")) or slug,
        slug=slug,
        difficulty=_text(question.get("difficulty")) or "Unknown",
        topic_tags=_tag_names(question.get("topicTags")),
        content=_text(question.get("content")),
        url=f"https://leetcode.com/problems/{slug}/",
        is_paid_only=bool(question.get("isPaidOnly")),
    )


def _error_messages(errors: Any) -> str:
    """Readable text from a GraphQL errors field of any shape."""
    if not isinstance(errors, list):
        return str(errors)
    return "; ".join(
        _text(e.get("message")) or "unknown" if isinstance(e, dict) else str(e) for e in errors
    )


def _text(value: Any) -> str:
    """A string from an untrusted field, or empty.

    LeetCode's schema says these are strings. A changed schema, or an anti-bot
    page, should degrade to a missing field rather than a TypeError downstream.
    """
    return value if isinstance(value, str) else ""


def _tag_names(tags: Any) -> list[str]:
    """Topic tag names, skipping anything that is not the documented shape."""
    if not isinstance(tags, list):
        return []
    return [name for tag in tags if isinstance(tag, dict) and (name := _text(tag.get("name")))]


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
