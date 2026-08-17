"""Tests for the LeetCode client and the get_leetcode_problem tool.

Responses are fixtures shaped from real API replies captured during design. The
network boundary is deliberately not a test seam - real calls happen only during
manual milestone verification.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.registry import ToolError
from app.agent.tools import build_registry
from app.problems.leetcode import LeetCodeClient, LeetCodeError, slug_from_url

# Shaped from a real response for two-sum.
TWO_SUM = {
    "question": {
        "questionFrontendId": "1",
        "title": "Two Sum",
        "titleSlug": "two-sum",
        "difficulty": "Easy",
        "isPaidOnly": False,
        "topicTags": [{"name": "Array", "slug": "array"}, {"name": "Hash Table", "slug": "hash"}],
        "content": "<p>Given an array of integers <code>nums</code>&nbsp;return indices.</p>",
    }
}

# A real unknown slug returns a null question, not an error.
NOT_FOUND: dict[str, Any] = {"question": None}

# A real premium problem returns metadata with null content.
PAID_ONLY = {
    "question": {
        "questionFrontendId": "252",
        "title": "Meeting Rooms",
        "titleSlug": "meeting-rooms",
        "difficulty": "Easy",
        "isPaidOnly": True,
        "topicTags": [],
        "content": None,
    }
}


class StubClient(LeetCodeClient):
    """A client whose network layer is replaced, keeping the parsing under test."""

    def __init__(self, data: dict[str, Any] | Exception) -> None:
        super().__init__()
        self.data = data
        self.queries: list[dict[str, Any]] = []

    def _query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.queries.append(variables)
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


def test_a_problem_is_parsed_into_its_fields():
    problem = StubClient(TWO_SUM).get_problem("two-sum")

    assert problem.number == "1"
    assert problem.title == "Two Sum"
    assert problem.difficulty == "Easy"
    assert problem.topic_tags == ["Array", "Hash Table"]
    assert problem.url == "https://leetcode.com/problems/two-sum/"


def test_an_unknown_slug_says_so_and_explains_where_slugs_come_from():
    """A null question is how LeetCode reports 'no such problem'."""
    with pytest.raises(LeetCodeError) as excinfo:
        StubClient(NOT_FOUND).get_problem("does-not-exist")

    message = str(excinfo.value)
    assert "does-not-exist" in message
    assert "two-sum" in message


def test_a_paid_only_problem_is_distinguished_from_a_missing_one():
    """Saying 'does not exist' would send the user hunting for a typo."""
    with pytest.raises(LeetCodeError) as excinfo:
        StubClient(PAID_ONLY).get_problem("meeting-rooms")

    assert "Premium" in str(excinfo.value)


def test_graphql_errors_surface_as_leetcode_errors():
    client = StubClient(TWO_SUM)
    client._query = lambda *a, **k: (_ for _ in ()).throw(LeetCodeError("rejected"))  # type: ignore[method-assign]

    with pytest.raises(LeetCodeError):
        client.get_problem("two-sum")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("two-sum", "two-sum"),
        ("https://leetcode.com/problems/two-sum/", "two-sum"),
        ("https://leetcode.com/problems/two-sum", "two-sum"),
        ("leetcode.com/problems/two-sum/description/", "two-sum"),
        ("  two-sum  ", "two-sum"),
    ],
)
def test_a_url_or_a_bare_slug_both_work(value, expected):
    """People paste URLs. Rejecting them would be needless friction."""
    assert slug_from_url(value) == expected


def test_a_leetcode_url_with_no_problem_in_it_is_rejected():
    with pytest.raises(LeetCodeError):
        slug_from_url("https://leetcode.com/contest/weekly-123/")


@pytest.mark.parametrize(
    "question",
    [
        {"topicTags": ["Array"], "content": "x", "title": "T"},
        {"topicTags": [{"slug": "no-name"}], "content": "x", "title": "T"},
        {"topicTags": None, "content": None, "title": None},
        {"content": 5, "title": "T"},
    ],
)
def test_unexpected_field_shapes_degrade_instead_of_crashing(question):
    """An anti-bot page or a schema change must not produce a TypeError from
    inside a comprehension.
    """
    problem = StubClient({"question": question}).get_problem("x")

    assert isinstance(problem.topic_tags, list)
    assert isinstance(problem.content, str)


@pytest.mark.parametrize("question", [[], "oops", 42])
def test_a_question_that_is_not_an_object_is_a_clear_error(question):
    with pytest.raises(LeetCodeError):
        StubClient({"question": question}).get_problem("x")


@pytest.mark.parametrize(
    "body",
    [
        [],
        "a string",
        {"errors": "boom"},
        {"errors": [1, 2]},
        {"errors": [{"message": "bad query"}]},
        {"data": "not an object"},
        {},
    ],
)
def test_a_malformed_response_body_is_a_clear_error(body, monkeypatch):
    """LeetCode's GraphQL endpoint can return an HTML error page or a changed
    schema. Every shape must reach the user as a message.

    This drives the real _query, stubbing only the socket - so the body-validation
    logic under test is the shipped one.
    """
    import json as json_module

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResponse(json_module.dumps(body)),
    )

    with pytest.raises(LeetCodeError):
        LeetCodeClient().get_problem("x")


def test_a_response_that_is_not_json_at_all_is_a_clear_error(monkeypatch):
    """An anti-bot HTML page is the likely real-world case."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResponse("<html>Access denied</html>"),
    )

    with pytest.raises(LeetCodeError):
        LeetCodeClient().get_problem("x")


class _FakeResponse:
    """Stands in for the object urlopen returns, so _query itself is exercised."""

    def __init__(self, body: str) -> None:
        self._body = body.encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_the_tool_returns_readable_text_not_html():
    registry = build_registry(StubClient(TWO_SUM))

    output = registry.get("get_leetcode_problem").run({"slug": "two-sum"})

    assert "<p>" not in output
    assert "&nbsp;" not in output
    assert "Given an array of integers nums" in output
    assert "Two Sum" in output
    assert "Array, Hash Table" in output


def test_the_tool_accepts_a_full_url():
    client = StubClient(TWO_SUM)
    registry = build_registry(client)

    registry.get("get_leetcode_problem").run({"slug": "https://leetcode.com/problems/two-sum/"})

    assert client.queries[0]["titleSlug"] == "two-sum"


def test_a_leetcode_failure_becomes_a_tool_error_the_model_can_read():
    registry = build_registry(StubClient(NOT_FOUND))

    with pytest.raises(ToolError) as excinfo:
        registry.get("get_leetcode_problem").run({"slug": "nope"})

    assert "nope" in str(excinfo.value)


def test_the_tool_is_read_only():
    assert build_registry(StubClient(TWO_SUM)).get("get_leetcode_problem").read_only


def test_a_very_long_description_is_truncated():
    from app.agent.tools import MAX_CONTENT_CHARS

    long_problem = {
        "question": {
            **TWO_SUM["question"],
            "content": "<p>" + ("word " * 5000) + "</p>",
        }
    }
    registry = build_registry(StubClient(long_problem))

    output = registry.get("get_leetcode_problem").run({"slug": "two-sum"})

    assert "[description truncated]" in output
    assert len(output) < MAX_CONTENT_CHARS + 500


def test_html_lists_become_readable_lines():
    problem = {
        "question": {
            **TWO_SUM["question"],
            "content": "<ul><li>first</li><li>second</li></ul>",
        }
    }
    registry = build_registry(StubClient(problem))

    output = registry.get("get_leetcode_problem").run({"slug": "two-sum"})

    assert "- first" in output
    assert "- second" in output
