"""Tests for catalogue sync and tag classification.

No network: sync is driven with fixed Problem lists, and the pagination logic is
driven with a stub client. The tag mapping cases are real tag bags copied from
the live catalogue.
"""

from __future__ import annotations

import pytest

from app.problems.catalogue import CatalogueSync
from app.problems.leetcode import CataloguePage, LeetCodeClient, LeetCodeError, Problem
from app.storage.db import open_database
from app.storage.repositories import PatternRepository, ProblemRepository


@pytest.fixture
def db():
    connection = open_database(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def sync(db):
    return CatalogueSync(db)


def problem(slug: str = "two-sum", tags: list[str] | None = None, **overrides) -> Problem:
    defaults = {
        "number": "1",
        "title": slug.replace("-", " ").title(),
        "slug": slug,
        "difficulty": "Easy",
        "topic_tags": tags if tags is not None else ["Array", "Hash Table"],
        "content": "",
        "url": f"https://leetcode.com/problems/{slug}/",
        "is_paid_only": False,
    }
    return Problem(**{**defaults, **overrides})


def pattern_of(db, slug: str) -> str | None:
    row = db.execute(
        "SELECT p.name FROM problems pr JOIN patterns p ON p.id = pr.primary_pattern_id "
        "WHERE pr.slug = ?",
        (slug,),
    ).fetchone()
    return row["name"] if row else None


# --- storing ------------------------------------------------------------------


def test_problems_are_stored_with_their_metadata(sync, db):
    sync.store([problem(slug="two-sum", difficulty="Easy")])

    stored = ProblemRepository(db).by_slug("two-sum")
    assert stored["title"] == "Two Sum"
    assert stored["difficulty"] == "Easy"


def test_topic_tags_are_stored(sync, db):
    sync.store([problem(tags=["Array", "Hash Table"])])

    assert ProblemRepository(db).tags_for("two-sum") == ["Array", "Hash Table"]


def test_the_paid_only_flag_is_stored(sync, db):
    """The recommender must not suggest a problem the user cannot open."""
    sync.store([problem(slug="meeting-rooms", is_paid_only=True)])

    assert ProblemRepository(db).by_slug("meeting-rooms")["is_paid_only"] == 1


def test_re_running_sync_updates_rather_than_duplicating(sync, db):
    sync.store([problem(slug="two-sum", difficulty="Easy")])
    sync.store([problem(slug="two-sum", difficulty="Medium")])

    problems = ProblemRepository(db)
    assert problems.count() == 1
    assert problems.by_slug("two-sum")["difficulty"] == "Medium"


def test_a_large_import_stores_every_problem(sync, db):
    """Batching must not drop the remainder that does not fill a final batch."""
    sync.store([problem(slug=f"p{i}") for i in range(250)])

    assert ProblemRepository(db).count() == 250


def test_progress_is_reported_during_a_long_import(sync):
    seen: list[int] = []

    sync.store([problem(slug=f"p{i}") for i in range(250)], on_progress=seen.append)

    assert seen, "a 250-problem import should report progress at least once"
    assert seen[-1] == 250


# --- classification -----------------------------------------------------------


@pytest.mark.parametrize(
    "tags,expected",
    [
        # Real tag bags from the live catalogue.
        (["Hash Table", "String", "Sliding Window"], "Sliding Window"),
        (["Array", "Hash Table"], "Hash Table"),
        (["Array", "Two Pointers", "Sorting"], "Two Pointers"),
        # "Add Two Numbers". Math outranks Recursion, which is the right call -
        # the problem is digit-carry arithmetic, not a recursion exercise.
        (["Linked List", "Math", "Recursion"], "Math"),
        (["Array", "Divide and Conquer", "Dynamic Programming"], "Dynamic Programming"),
        (["String", "Dynamic Programming"], "Dynamic Programming"),
        (["Array", "Binary Search"], "Binary Search"),
        (["Database"], "Database"),
        (["Union-Find", "Graph"], "Union Find"),
        (["Heap (Priority Queue)", "Array"], "Heap"),
        (["Graph Theory", "Breadth-First Search"], "Breadth-First Search"),
        (["Binary Tree", "Depth-First Search"], "Depth-First Search"),
    ],
)
def test_the_tag_bag_resolves_to_the_pattern_the_problem_teaches(sync, db, tags, expected):
    sync.store([problem(slug="p", tags=tags)])

    assert pattern_of(db, "p") == expected


def test_every_problem_gets_exactly_one_primary_pattern(sync, db):
    sync.store(
        [
            problem(slug="a", tags=["Array"]),
            problem(slug="b", tags=[]),
            problem(slug="c", tags=["Nonexistent Tag"]),
        ]
    )

    rows = db.execute("SELECT slug, primary_pattern_id FROM problems").fetchall()
    assert all(row["primary_pattern_id"] is not None for row in rows)


def test_the_classification_records_that_tags_produced_it(sync, db):
    """A later ticket lets Gemini override this, so provenance has to be visible."""
    sync.store([problem()])

    assert ProblemRepository(db).by_slug("two-sum")["pattern_source"] == "tags"


def test_a_problem_with_no_tags_is_filed_not_dropped(sync, db):
    """161 problems in the live catalogue carry no tags at all."""
    sync.store([problem(slug="untagged", tags=[])])

    assert ProblemRepository(db).by_slug("untagged") is not None
    assert pattern_of(db, "untagged") == "Other"


def test_a_problem_whose_tags_match_nothing_is_filed_not_dropped(sync, db):
    sync.store([problem(slug="strange", tags=["Quantum Entanglement"])])

    assert pattern_of(db, "strange") == "Other"


def test_unmapped_tags_are_reported_so_they_can_be_noticed(sync):
    """LeetCode adds tags. Silently filing them under Other forever hides that."""
    report = sync.store(
        [
            problem(slug="a", tags=["Brand New Tag"]),
            problem(slug="b", tags=["Brand New Tag"]),
        ]
    )

    assert report.unmapped_tags == {"Brand New Tag": 2}


def test_a_problem_is_linked_to_every_pattern_it_touches(sync, db):
    """The primary drives scoring; the full set answers "show me everything
    involving Binary Search".
    """
    sync.store([problem(slug="p", tags=["Array", "Binary Search"])])

    problems = ProblemRepository(db)
    problem_id = problems.by_slug("p")["id"]
    linked = problems.patterns_for(problem_id)

    assert len(linked) == 2
    assert sum(row["is_primary"] for row in linked) == 1


def test_reclassifying_replaces_the_previous_pattern_links(sync, db):
    sync.store([problem(slug="p", tags=["Array"])])
    sync.store([problem(slug="p", tags=["Sliding Window"])])

    problems = ProblemRepository(db)
    problem_id = problems.by_slug("p")["id"]

    assert len(problems.patterns_for(problem_id)) == 1
    assert pattern_of(db, "p") == "Sliding Window"


# --- the report ---------------------------------------------------------------


def test_the_report_counts_what_happened(sync):
    report = sync.store(
        [
            problem(slug="a", tags=["Array"]),
            problem(slug="b", tags=[]),
            problem(slug="c", tags=["Array"], is_paid_only=True),
        ]
    )

    assert report.stored == 3
    assert report.classified == 2
    assert report.unclassified == 1
    assert report.paid_only == 1


def test_the_summary_mentions_unclassified_problems(sync):
    report = sync.store([problem(slug="a", tags=[])])

    assert "Other" in report.summary()


def test_the_summary_stays_quiet_when_everything_classified(sync):
    report = sync.store([problem(slug="a", tags=["Array"])])

    assert "Other" not in report.summary()


# --- pagination ---------------------------------------------------------------


class StubClient(LeetCodeClient):
    """A client whose pages are scripted, so pagination is testable offline."""

    def __init__(self, pages: list[CataloguePage]) -> None:
        super().__init__()
        self.pages = pages
        self.requests: list[int] = []

    def get_catalogue_page(self, skip: int, limit: int = 100) -> CataloguePage:
        self.requests.append(skip)
        # Pages are consumed in order rather than indexed by skip, because a
        # scripted page can hold any number of problems.
        consumed = sum(len(p.problems) for p in self.pages[: len(self.requests) - 1])
        if consumed != skip or len(self.requests) > len(self.pages):
            return CataloguePage(problems=[], total=self.pages[0].total if self.pages else 0)
        return self.pages[len(self.requests) - 1]


def test_every_page_of_the_catalogue_is_fetched():
    pages = [
        CataloguePage(problems=[problem(slug=f"p{i}") for i in range(100)], total=250),
        CataloguePage(problems=[problem(slug=f"q{i}") for i in range(100)], total=250),
        CataloguePage(problems=[problem(slug=f"r{i}") for i in range(50)], total=250),
    ]

    fetched = list(StubClient(pages).iter_catalogue())

    assert len(fetched) == 250


def test_pagination_stops_at_the_end_rather_than_looping():
    pages = [CataloguePage(problems=[problem(slug="only")], total=1)]
    client = StubClient(pages)

    list(client.iter_catalogue())

    assert client.requests == [0]


def test_pagination_stops_on_an_empty_page_even_if_the_total_disagrees():
    """A wrong total must not spin forever."""
    pages = [CataloguePage(problems=[problem(slug="a")], total=99999)]
    client = StubClient(pages)

    assert len(list(client.iter_catalogue())) == 1


def test_a_full_sync_stores_what_the_client_yields(db):
    pages = [CataloguePage(problems=[problem(slug=f"p{i}") for i in range(5)], total=5)]

    report = CatalogueSync(db, client=StubClient(pages)).run()

    assert report.stored == 5
    assert ProblemRepository(db).count() == 5


# --- catalogue response parsing -----------------------------------------------


def test_a_catalogue_page_is_parsed_into_problems():
    client = LeetCodeClient()
    client._query = lambda q, v: {  # type: ignore[method-assign]
        "problemsetQuestionList": {
            "total": 1,
            "questions": [
                {
                    "questionFrontendId": "1",
                    "title": "Two Sum",
                    "titleSlug": "two-sum",
                    "difficulty": "Easy",
                    "isPaidOnly": False,
                    "topicTags": [{"name": "Array"}],
                }
            ],
        }
    }

    page = client.get_catalogue_page(0)

    assert page.total == 1
    assert page.problems[0].slug == "two-sum"
    assert page.problems[0].topic_tags == ["Array"]


def test_a_malformed_catalogue_response_is_a_clear_error():
    client = LeetCodeClient()
    client._query = lambda q, v: {"problemsetQuestionList": "not an object"}  # type: ignore[method-assign]

    with pytest.raises(LeetCodeError):
        client.get_catalogue_page(0)


def test_a_catalogue_page_missing_its_question_list_is_a_clear_error():
    client = LeetCodeClient()
    client._query = lambda q, v: {"problemsetQuestionList": {"total": 10}}  # type: ignore[method-assign]

    with pytest.raises(LeetCodeError):
        client.get_catalogue_page(0)


def test_the_seeded_taxonomy_covers_the_common_leetcode_tags(db):
    """Tags surveyed from the live catalogue. If a common one loses its mapping,
    thousands of problems quietly fall through to Other.
    """
    patterns = PatternRepository(db)
    common = [
        "Array",
        "String",
        "Hash Table",
        "Math",
        "Dynamic Programming",
        "Sorting",
        "Greedy",
        "Depth-First Search",
        "Binary Search",
        "Database",
        "Bit Manipulation",
        "Matrix",
        "Tree",
        "Prefix Sum",
        "Breadth-First Search",
        "Two Pointers",
        "Heap (Priority Queue)",
        "Simulation",
        "Counting",
        "Graph Theory",
        "Binary Tree",
        "Stack",
        "Sliding Window",
        "Enumeration",
        "Design",
        "Backtracking",
        "Number Theory",
        "Union-Find",
        "Linked List",
        "Monotonic Stack",
    ]

    unmapped = [tag for tag in common if patterns.by_leetcode_tag(tag) is None]

    assert unmapped == []
