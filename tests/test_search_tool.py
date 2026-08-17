"""Tests for the search_problems tool.

The tool is what the model sees, so these assert on its text output and its
error messages - the things that determine whether the model can use it.
"""

from __future__ import annotations

import pytest

from app.agent.registry import ToolError
from app.agent.tools import build_registry
from app.storage.db import open_database
from app.storage.repositories import PatternRepository, ProblemRepository


@pytest.fixture
def db():
    connection = open_database(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def search(db):
    return build_registry(connection=db).get("search_problems")


def add(db, slug: str, title: str, content: str = "", **overrides) -> int:
    problems = ProblemRepository(db)
    return problems.upsert(
        slug=slug,
        title=title,
        content=content,
        difficulty=overrides.get("difficulty", "Medium"),
        topic_tags=overrides.get("topic_tags", []),
        is_paid_only=overrides.get("is_paid_only", False),
    )


def test_the_tool_is_absent_without_a_database():
    """A tool that would always fail wastes a turn being discovered."""
    registry = build_registry()

    assert "search_problems" not in registry


def test_the_tool_is_read_only(search):
    """It has to be usable by `ask`, which must never write."""
    assert search.read_only


def test_a_word_search_finds_a_matching_problem(db, search):
    add(db, "lru-cache", "LRU Cache", "design a cache with eviction")

    output = search.run({"query": "eviction"})

    assert "LRU Cache" in output


def test_a_search_that_matches_nothing_says_so_usefully(search):
    output = search.run({"query": "quantum entanglement"})

    assert "No problems matched" in output


def test_results_can_be_filtered_by_difficulty(db, search):
    add(db, "easy-one", "Easy One", "sliding window", difficulty="Easy")
    add(db, "hard-one", "Hard One", "sliding window", difficulty="Hard")

    output = search.run({"query": "sliding", "difficulty": "Easy"})

    assert "Easy One" in output
    assert "Hard One" not in output


def test_difficulty_is_accepted_in_any_case(db, search):
    add(db, "easy-one", "Easy One", "sliding window", difficulty="Easy")

    assert "Easy One" in search.run({"query": "sliding", "difficulty": "easy"})


def test_an_invalid_difficulty_is_a_correctable_error(search):
    with pytest.raises(ToolError) as excinfo:
        search.run({"difficulty": "trivial"})

    assert "Easy" in str(excinfo.value)


def test_results_can_be_filtered_by_pattern(db, search):
    patterns = PatternRepository(db)
    problems = ProblemRepository(db)
    window = add(db, "window", "Window Problem", "text")
    other = add(db, "other", "Other Problem", "text")
    problems.set_primary_pattern(window, patterns.by_slug("sliding-window")["id"], source="tags")
    problems.set_primary_pattern(other, patterns.by_slug("hash-table")["id"], source="tags")

    output = search.run({"pattern": "Sliding Window"})

    assert "Window Problem" in output
    assert "Other Problem" not in output


def test_an_unknown_pattern_lists_some_valid_ones(search):
    """The model invents pattern names; it needs to know what exists."""
    with pytest.raises(ToolError) as excinfo:
        search.run({"pattern": "Vibes"})

    assert "Sliding Window" in str(excinfo.value)


def test_a_pattern_slug_works_as_well_as_a_name(db, search):
    patterns = PatternRepository(db)
    problems = ProblemRepository(db)
    window = add(db, "window", "Window Problem", "text")
    problems.set_primary_pattern(window, patterns.by_slug("sliding-window")["id"], source="tags")

    assert "Window Problem" in search.run({"pattern": "sliding window"})


def test_analysed_only_returns_prior_work(db, search):
    problems = ProblemRepository(db)
    analysed = add(db, "analysed", "Analysed One", "sliding window")
    add(db, "raw", "Raw One", "sliding window")
    problems.save_analysis(
        analysed, {"pattern": "Sliding Window", "key_insight": "Shrink from the left."}
    )

    output = search.run({"query": "sliding", "analysed_only": True})

    assert "Analysed One" in output
    assert "Raw One" not in output


def test_an_analysed_result_shows_its_pattern_and_insight(db, search):
    """Enough context for the model to judge similarity without another lookup."""
    problems = ProblemRepository(db)
    analysed = add(db, "analysed", "Analysed One", "sliding window")
    problems.save_analysis(
        analysed, {"pattern": "Sliding Window", "key_insight": "Shrink from the left."}
    )

    output = search.run({"query": "sliding", "analysed_only": True})

    assert "Sliding Window" in output
    assert "Shrink from the left" in output


def test_an_unanalysed_result_shows_its_topic_tags(db, search):
    add(db, "raw", "Raw One", "sliding window", topic_tags=["Array", "Hash Table"])

    output = search.run({"query": "sliding"})

    assert "Array" in output


def test_a_long_key_insight_is_truncated(db, search):
    """Twenty results have to fit in a prompt."""
    problems = ProblemRepository(db)
    analysed = add(db, "analysed", "Analysed One", "sliding window")
    problems.save_analysis(analysed, {"pattern": "P", "key_insight": "word " * 200})

    output = search.run({"query": "sliding", "analysed_only": True})

    assert "..." in output
    assert len(output) < 1000


def test_paid_problems_are_excluded(db, search):
    """The recommender must not surface something the user cannot open."""
    add(db, "free", "Free One", "sliding window")
    add(db, "paid", "Paid One", "sliding window", is_paid_only=True)

    output = search.run({"query": "sliding"})

    assert "Free One" in output
    assert "Paid One" not in output


def test_the_result_count_is_bounded(db, search):
    from app.agent.tools import MAX_SEARCH_RESULTS

    for i in range(MAX_SEARCH_RESULTS + 15):
        add(db, f"p{i}", f"Problem {i}", "sliding window")

    output = search.run({"query": "sliding"})

    assert output.count("- Problem") == MAX_SEARCH_RESULTS


def test_search_with_no_filters_at_all_still_returns_something(db, search):
    add(db, "anything", "Anything", "text")

    assert "Anything" in search.run({})
