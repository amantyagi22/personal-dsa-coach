"""Tests for problem analysis.

Everything runs against a fake provider and a stub LeetCode client - no network,
no API key. This is Seam 2 from the spec.
"""

from __future__ import annotations

import pytest

from app.llm.base import ToolTurn
from app.llm.fake import FakeLLMProvider
from app.problems.analysis import ProblemAnalyser
from app.problems.leetcode import LeetCodeClient, LeetCodeError, Problem
from app.schemas import (
    Difficulty,
    ProblemAnalysis,
    SimilarityJudgement,
    SimilarityJudgements,
)
from app.storage.db import open_database
from app.storage.repositories import PatternRepository, ProblemRepository


@pytest.fixture
def db():
    connection = open_database(":memory:")
    yield connection
    connection.close()


class StubClient(LeetCodeClient):
    """Returns a fixed problem, so no network is touched."""

    def __init__(self, problem: Problem | Exception) -> None:
        super().__init__()
        self.problem = problem
        self.requested: list[str] = []

    def get_problem(self, slug: str) -> Problem:
        self.requested.append(slug)
        if isinstance(self.problem, Exception):
            raise self.problem
        return self.problem


def make_problem(slug: str = "longest-substring", **overrides) -> Problem:
    defaults = {
        "number": "3",
        "title": "Longest Substring Without Repeating Characters",
        "slug": slug,
        "difficulty": "Medium",
        "topic_tags": ["Hash Table", "String", "Sliding Window"],
        "content": "Given a string s, find the length of the longest substring...",
        "url": f"https://leetcode.com/problems/{slug}/",
        "is_paid_only": False,
    }
    return Problem(**{**defaults, **overrides})


def make_analysis(pattern: str = "Sliding Window", **overrides) -> ProblemAnalysis:
    defaults = {
        "pattern": pattern,
        "pattern_reasoning": "The answer is a contiguous range that grows and shrinks.",
        "secondary_techniques": ["Hash Table"],
        "difficulty": Difficulty.MEDIUM,
        "key_insight": "Shrink the window from the left when a duplicate appears.",
        "algorithm": ["Expand right", "Shrink left on duplicate", "Track the best length"],
        "time_complexity": "O(n)",
        "space_complexity": "O(k)",
        "recognition_clues": [
            "Asks for a contiguous substring or subarray",
            "Asks for the longest or shortest such range",
        ],
        "common_mistakes": ["Forgetting to move the left pointer past the duplicate"],
    }
    return ProblemAnalysis(**{**defaults, **overrides})


def make_analyser(
    db,
    *,
    analysis: ProblemAnalysis | None = None,
    similar: SimilarityJudgements | None = None,
    problem: Problem | Exception | None = None,
    turns: list[ToolTurn] | None = None,
) -> tuple[ProblemAnalyser, FakeLLMProvider]:
    structured: list = [analysis or make_analysis()]
    if similar is not None:
        structured.append(similar)

    provider = FakeLLMProvider(
        turns=turns or [ToolTurn(text="This problem tests the sliding window pattern.")],
        structured=structured,
    )
    analyser = ProblemAnalyser(db, provider, client=StubClient(problem or make_problem()))
    return analyser, provider


# --- the analysis itself ------------------------------------------------------


def test_an_analysis_covers_everything_the_spec_asks_for(db):
    analyser, _ = make_analyser(db)

    result = analyser.analyse("https://leetcode.com/problems/longest-substring/")

    analysis = result.analysis
    assert analysis.pattern == "Sliding Window"
    assert analysis.pattern_reasoning
    assert analysis.secondary_techniques
    assert analysis.key_insight
    assert analysis.algorithm
    assert analysis.time_complexity
    assert analysis.space_complexity
    assert analysis.common_mistakes


def test_recognition_clues_are_present(db):
    """The point of the product: what transfers to an unseen problem."""
    analyser, _ = make_analyser(db)

    result = analyser.analyse("longest-substring")

    assert len(result.analysis.recognition_clues) >= 1


def test_a_full_url_is_accepted(db):
    analyser, _ = make_analyser(db)

    result = analyser.analyse("https://leetcode.com/problems/longest-substring/description/")

    assert result.slug == "longest-substring"


def test_the_analysis_is_saved_and_retrievable(db):
    analyser, _ = make_analyser(db)

    analyser.analyse("longest-substring")

    problems = ProblemRepository(db)
    problem_id = problems.by_slug("longest-substring")["id"]
    saved = problems.analysis_for(problem_id)
    assert saved["pattern"] == "Sliding Window"
    assert saved["recognition_clues"]


def test_re_analysing_updates_rather_than_duplicating(db):
    analyser, _ = make_analyser(db)
    analyser.analyse("longest-substring")

    second, _ = make_analyser(db, analysis=make_analysis(key_insight="A fresh explanation."))
    result = second.analyse("longest-substring")

    problems = ProblemRepository(db)
    assert problems.count() == 1
    assert result.reanalysed is True
    problem_id = problems.by_slug("longest-substring")["id"]
    assert problems.analysis_for(problem_id)["key_insight"] == "A fresh explanation."


def test_a_first_analysis_is_not_marked_as_a_reanalysis(db):
    analyser, _ = make_analyser(db)

    assert analyser.analyse("longest-substring").reanalysed is False


def test_analysis_runs_on_the_reasoning_model(db):
    """Quality matters most here, so it is worth the scarce reasoning quota."""
    analyser, provider = make_analyser(db)

    analyser.analyse("longest-substring")

    assert all(call["role"] == "reasoning" for call in provider.calls)


def test_the_structured_output_is_validated_against_the_schema(db):
    """The provider enforces the schema, so a caller cannot receive junk."""
    analyser, provider = make_analyser(db)

    result = analyser.analyse("longest-substring")

    assert isinstance(result.analysis, ProblemAnalysis)


# --- the agent decides what to fetch -----------------------------------------


def test_the_model_chooses_its_own_tools(db):
    """Tool choice is the model's, not a hard-coded sequence."""
    from app.llm.base import ToolCall

    analyser, provider = make_analyser(
        db,
        turns=[
            ToolTurn(tool_calls=[ToolCall("get_leetcode_problem", {"slug": "longest-substring"})]),
            ToolTurn(text="Having read it, this is a sliding window problem."),
        ],
    )

    result = analyser.analyse("longest-substring")

    assert result.tool_calls == 1


def test_search_problems_is_offered_when_a_database_is_available(db):
    """It is how the agent finds prior work to build on."""
    analyser, provider = make_analyser(db)

    analyser.analyse("longest-substring")

    assert "search_problems" in provider.calls[0]["tools"]


def test_editorial_solutions_are_never_fetched(db):
    """The goal is teaching recognition, not summarising someone's answer."""
    analyser, _ = make_analyser(db)

    tool_names = {spec.name for spec in analyser.registry.specs()}

    assert not any("solution" in name or "editorial" in name for name in tool_names)


# --- the pattern override ----------------------------------------------------


def test_the_models_pattern_overrides_the_tag_derived_one(db):
    """Gemini's judgement is authoritative from then on."""
    problems = ProblemRepository(db)
    patterns = PatternRepository(db)
    problem_id = problems.upsert(slug="longest-substring", title="X")
    problems.set_primary_pattern(problem_id, patterns.by_slug("hash-table")["id"], source="tags")

    analyser, _ = make_analyser(db, analysis=make_analysis(pattern="Sliding Window"))
    analyser.analyse("longest-substring")

    stored = problems.by_slug("longest-substring")
    assert stored["pattern_source"] == "llm"
    assert stored["primary_pattern_id"] == patterns.by_slug("sliding-window")["id"]


def test_a_pattern_name_outside_the_taxonomy_leaves_the_tag_pattern_alone(db):
    """Inventing a taxonomy row from model prose would corrupt the vocabulary."""
    problems = ProblemRepository(db)
    patterns = PatternRepository(db)
    problem_id = problems.upsert(slug="longest-substring", title="X")
    tag_pattern = patterns.by_slug("hash-table")["id"]
    problems.set_primary_pattern(problem_id, tag_pattern, source="tags")

    analyser, _ = make_analyser(db, analysis=make_analysis(pattern="Vibes-Based Heuristics"))
    result = analyser.analyse("longest-substring")

    stored = problems.by_slug("longest-substring")
    assert result.pattern_matched is None
    assert stored["pattern_source"] == "tags"
    assert stored["primary_pattern_id"] == tag_pattern


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("sliding window", "Sliding Window"),
        ("Sliding-Window", "Sliding Window"),
        ("Binary  Search", "Binary Search"),
        # Spellings the model reasonably produces because they are the LeetCode
        # tags. The tag table already knows how to resolve them.
        ("Graph Theory", "Graph"),
        ("Heap (Priority Queue)", "Heap"),
        ("Union-Find", "Union Find"),
    ],
)
def test_a_pattern_the_model_names_loosely_still_resolves(db, spoken, expected):
    analyser, _ = make_analyser(db, analysis=make_analysis(pattern=spoken))

    assert analyser.analyse("longest-substring").pattern_matched == expected


# --- similarity --------------------------------------------------------------


def test_similar_problems_are_surfaced_from_prior_analyses(db):
    problems = ProblemRepository(db)
    prior = problems.upsert(
        slug="minimum-window-substring",
        title="Minimum Window Substring",
        content="smallest substring containing all characters",
    )
    problems.save_analysis(prior, {"pattern": "Sliding Window", "key_insight": "Shrink left."})

    analyser, _ = make_analyser(
        db,
        similar=SimilarityJudgements(
            judgements=[
                SimilarityJudgement(
                    problem_slug="minimum-window-substring",
                    is_similar=True,
                    reason="Both shrink a window from the left.",
                )
            ]
        ),
    )

    result = analyser.analyse("longest-substring")

    assert [j.problem_slug for j in result.similar] == ["minimum-window-substring"]


def test_problems_judged_dissimilar_are_not_surfaced(db):
    problems = ProblemRepository(db)
    prior = problems.upsert(slug="two-sum", title="Two Sum", content="indices summing to target")
    problems.save_analysis(prior, {"pattern": "Hash Table", "key_insight": "Complement lookup."})

    analyser, _ = make_analyser(
        db,
        similar=SimilarityJudgements(
            judgements=[
                SimilarityJudgement(
                    problem_slug="two-sum",
                    is_similar=False,
                    reason="Both use a hash map, but nothing transfers.",
                )
            ]
        ),
    )

    result = analyser.analyse("longest-substring")

    assert result.similar == []


def test_an_invented_slug_is_dropped(db):
    """Models invent slugs. A link the user cannot follow is worse than none."""
    problems = ProblemRepository(db)
    prior = problems.upsert(slug="two-sum", title="Two Sum", content="target sum")
    problems.save_analysis(prior, {"pattern": "Hash Table", "key_insight": "Complement."})

    analyser, _ = make_analyser(
        db,
        similar=SimilarityJudgements(
            judgements=[
                SimilarityJudgement(
                    problem_slug="a-problem-that-does-not-exist",
                    is_similar=True,
                    reason="Sounds plausible.",
                )
            ]
        ),
    )

    assert analyser.analyse("longest-substring").similar == []


def test_the_problem_being_analysed_is_never_similar_to_itself(db):
    problems = ProblemRepository(db)
    problem_id = problems.upsert(
        slug="longest-substring", title="Longest Substring", content="sliding window substring"
    )
    problems.save_analysis(problem_id, {"pattern": "Sliding Window", "key_insight": "Shrink."})

    analyser, provider = make_analyser(db, similar=SimilarityJudgements(judgements=[]))
    analyser.analyse("longest-substring")

    similarity_prompt = provider.calls[-1]["prompt"]
    assert "longest-substring" not in similarity_prompt


def test_no_model_call_is_spent_when_there_is_nothing_to_compare(db):
    """An empty corpus should not cost a request to be told nothing matches."""
    analyser, provider = make_analyser(db)

    result = analyser.analyse("longest-substring")

    assert result.similar == []
    assert sum(1 for call in provider.calls if call["kind"] == "structured") == 1


# --- the rendered output ------------------------------------------------------


def test_the_output_leads_with_recognition_not_the_algorithm(db):
    """The clues transfer to the next problem; the algorithm only explains this one."""
    from app.cli import format_analysis

    analyser, _ = make_analyser(db)
    output = format_analysis(analyser.analyse("longest-substring"))

    assert output.index("HOW TO RECOGNISE IT NEXT TIME") < output.index("APPROACH")


def test_the_output_contains_every_section_the_spec_asks_for(db):
    from app.cli import format_analysis

    analyser, _ = make_analyser(db)
    output = format_analysis(analyser.analyse("longest-substring"))

    for heading in [
        "WHY THIS PATTERN",
        "HOW TO RECOGNISE IT NEXT TIME",
        "KEY INSIGHT",
        "APPROACH",
        "COMPLEXITY",
        "ALSO USES",
        "COMMON MISTAKES",
    ]:
        assert heading in output


def test_the_output_says_when_the_pattern_was_not_recognised(db):
    """Otherwise the user would think the taxonomy had been updated."""
    from app.cli import format_analysis

    analyser, _ = make_analyser(db, analysis=make_analysis(pattern="Made Up Pattern"))
    output = format_analysis(analyser.analyse("longest-substring"))

    assert "not in the pattern taxonomy" in output


def test_empty_sections_are_omitted_rather_than_left_blank(db):
    from app.cli import format_analysis

    analyser, _ = make_analyser(
        db, analysis=make_analysis(secondary_techniques=[], common_mistakes=[])
    )
    output = format_analysis(analyser.analyse("longest-substring"))

    assert "ALSO USES" not in output
    assert "COMMON MISTAKES" not in output


# --- failures ----------------------------------------------------------------


def test_a_model_that_never_concludes_produces_no_analysis(db):
    """Hitting the iteration cap leaves a filler message, not an analysis. Shaping
    that into the schema would produce a confident fabrication.
    """
    from app.llm.base import ToolCall
    from app.problems.analysis import MAX_ITERATIONS, AnalysisError

    analyser, provider = make_analyser(
        db,
        turns=[
            ToolTurn(tool_calls=[ToolCall("get_leetcode_problem", {"slug": f"s{i}"})])
            for i in range(MAX_ITERATIONS + 2)
        ],
    )

    with pytest.raises(AnalysisError):
        analyser.analyse("longest-substring")

    assert ProblemRepository(db).by_slug("longest-substring")["analysis"] is None


def test_the_structuring_call_always_sees_the_problem_statement(db):
    """So it has the source material, not only the model's prose about it."""
    analyser, provider = make_analyser(db)

    analyser.analyse("longest-substring")

    structuring = next(c for c in provider.calls if c["kind"] == "structured")
    assert "find the length of the longest substring" in structuring["prompt"]


def test_a_failed_model_call_leaves_no_half_written_analysis(db):
    """The problem row is a legitimate catalogue entry; the analysis is not
    written at all, so re-running simply works.
    """
    from app.llm.base import RateLimitError

    class Failing(FakeLLMProvider):
        def generate_structured(self, *args, **kwargs):
            raise RateLimitError("quota exhausted")

    analyser = ProblemAnalyser(
        db,
        Failing(turns=[ToolTurn(text="gathered")]),
        client=StubClient(make_problem()),
    )

    with pytest.raises(RateLimitError):
        analyser.analyse("longest-substring")

    stored = ProblemRepository(db).by_slug("longest-substring")
    assert stored is not None
    assert stored["analysis"] is None
    assert stored["pattern_source"] is None


def test_the_candidate_set_handed_to_the_model_is_bounded(db):
    """FTS matches broadly by design, so the cap is what keeps the prompt sane."""
    from app.problems.analysis import SIMILARITY_CANDIDATES

    problems = ProblemRepository(db)
    for i in range(SIMILARITY_CANDIDATES + 20):
        prior = problems.upsert(
            slug=f"prior{i}", title=f"Prior {i}", content="sliding window duplicate left edge"
        )
        problems.save_analysis(prior, {"pattern": "Sliding Window", "key_insight": "Shrink."})

    analyser, provider = make_analyser(db, similar=SimilarityJudgements(judgements=[]))
    analyser.analyse("longest-substring")

    listed = provider.calls[-1]["prompt"]
    assert listed.count("- prior") == SIMILARITY_CANDIDATES


def test_a_missing_problem_fails_before_spending_a_model_call(db):
    analyser, provider = make_analyser(db, problem=LeetCodeError("No such problem"))

    with pytest.raises(LeetCodeError):
        analyser.analyse("nope")

    assert provider.calls == []


def test_a_problem_with_no_description_is_refused(db):
    analyser, provider = make_analyser(db, problem=make_problem(content=""))

    with pytest.raises(LeetCodeError) as excinfo:
        analyser.analyse("meeting-rooms")

    assert "nothing to analyse" in str(excinfo.value)
    assert provider.calls == []
