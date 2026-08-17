"""Tests for the database schema and repositories.

Everything runs against an in-memory SQLite database - no file, no API key, no
network. This is Seam 3 from the spec.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.storage.db import connect, initialize, open_database
from app.storage.repositories import (
    AttemptRepository,
    PatternRepository,
    ProblemRepository,
    RecommendationRepository,
    ReviewRepository,
    UserRepository,
)


@pytest.fixture
def db():
    connection = open_database(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def problems(db):
    return ProblemRepository(db)


@pytest.fixture
def patterns(db):
    return PatternRepository(db)


def make_problem(problems: ProblemRepository, slug: str = "two-sum", **overrides) -> int:
    defaults = {
        "slug": slug,
        "number": "1",
        "title": "Two Sum",
        "difficulty": "Easy",
        "url": f"https://leetcode.com/problems/{slug}/",
        "content": "Given an array of integers, return indices of two numbers.",
        "topic_tags": ["Array", "Hash Table"],
        "is_paid_only": False,
    }
    return problems.upsert(**{**defaults, **overrides})


# --- schema and initialisation ------------------------------------------------


def test_every_table_from_the_spec_exists(db):
    names = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert {
        "users",
        "problems",
        "patterns",
        "problem_patterns",
        "attempts",
        "recommendations",
        "reviews",
    } <= names


def test_initialisation_is_idempotent(db):
    before = db.execute("SELECT COUNT(*) AS n FROM patterns").fetchone()["n"]

    initialize(db)
    initialize(db)

    assert db.execute("SELECT COUNT(*) AS n FROM patterns").fetchone()["n"] == before


def test_the_canonical_patterns_are_seeded(patterns):
    names = {p["name"] for p in patterns.all()}

    assert "Sliding Window" in names
    assert "Dynamic Programming" in names
    assert len(names) >= 25


def test_a_pattern_edited_in_the_database_survives_reinitialisation(db, patterns):
    db.execute("UPDATE patterns SET description = 'my own words' WHERE slug = 'sliding-window'")
    db.commit()

    initialize(db)

    assert patterns.by_slug("sliding-window")["description"] == "my own words"


def test_a_corrected_seed_reaches_an_existing_database(tmp_path):
    """A previous release shipped wrong priorities. Plain DO NOTHING left them in
    place forever, silently misclassifying every problem that used them.
    """
    from app.storage.db import connect, initialize

    connection = connect(tmp_path / "old.db")
    connection.executescript(
        "CREATE TABLE patterns ("
        "  id INTEGER PRIMARY KEY, name TEXT UNIQUE, slug TEXT UNIQUE,"
        "  description TEXT DEFAULT '', priority INTEGER DEFAULT 500, leetcode_tag TEXT);"
        "INSERT INTO patterns (name, slug, priority) VALUES"
        "  ('Array', 'array', 980), ('Matrix', 'matrix', 985);"
    )
    connection.commit()

    initialize(connection)

    patterns = PatternRepository(connection)
    assert patterns.primary_for_tags(["Array", "Matrix"])["name"] == "Matrix"
    connection.close()


def test_an_old_database_gains_the_columns_the_schema_added(tmp_path):
    """CREATE TABLE IF NOT EXISTS skips an existing table entirely, so a new
    column would never appear without an explicit ALTER.
    """
    from app.storage.db import connect, initialize

    connection = connect(tmp_path / "old.db")
    connection.executescript(
        "CREATE TABLE patterns (id INTEGER PRIMARY KEY, name TEXT UNIQUE, "
        "slug TEXT UNIQUE, description TEXT DEFAULT '', priority INTEGER DEFAULT 500)"
    )
    connection.commit()

    initialize(connection)

    columns = {row["name"] for row in connection.execute("PRAGMA table_info(patterns)")}
    assert "seed_version" in columns
    connection.close()


def test_re_running_initialisation_leaves_the_taxonomy_alone(db, patterns):
    """Only a newer seed version rewrites a row, so repeat runs are a no-op."""
    db.execute("UPDATE patterns SET priority = 7 WHERE slug = 'array'")
    db.commit()

    initialize(db)
    initialize(db)

    assert patterns.by_slug("array")["priority"] == 7


def test_foreign_keys_are_enforced(db):
    """Without this pragma SQLite accepts orphan rows silently."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO attempts (user_id, problem_id) VALUES (1, 99999)")
        db.commit()


def test_the_single_local_user_exists(db):
    assert db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 1


# --- users --------------------------------------------------------------------


def test_the_leetcode_username_can_be_saved_and_read_back(db):
    users = UserRepository(db)

    users.set_leetcode_username("amantyagi22")

    assert users.get()["leetcode_username"] == "amantyagi22"


def test_the_leetcode_username_can_be_cleared(db):
    users = UserRepository(db)
    users.set_leetcode_username("amantyagi22")

    users.set_leetcode_username(None)

    assert users.get()["leetcode_username"] is None


# --- editing the taxonomy -----------------------------------------------------


def test_a_new_pattern_can_be_added_without_a_code_change(patterns):
    patterns.upsert(
        name="Rolling Hash", slug="rolling-hash", priority=95, leetcode_tags=("Rolling Hash",)
    )

    assert patterns.by_slug("rolling-hash")["name"] == "Rolling Hash"
    assert patterns.primary_for_tags(["Rolling Hash", "String"])["name"] == "Rolling Hash"


def test_an_existing_pattern_can_be_retuned(patterns):
    """Changing a priority is how the tag mapping gets corrected in practice."""
    patterns.upsert(name="Array", slug="array", priority=5, leetcode_tags=("Array",))

    assert patterns.primary_for_tags(["Array", "Sliding Window"])["name"] == "Array"


# --- tag to pattern mapping ---------------------------------------------------


@pytest.mark.parametrize(
    "tags,expected",
    [
        # The real tag bag for "Longest Substring Without Repeating Characters".
        # Sliding Window is what the problem teaches; the rest is what it uses.
        (["Hash Table", "String", "Sliding Window"], "Sliding Window"),
        # Two Sum: nothing distinctive, so the fallback data structure wins.
        (["Array", "Hash Table"], "Hash Table"),
        (["Array", "Two Pointers", "Sorting"], "Two Pointers"),
        (["Array", "Binary Search", "Matrix"], "Binary Search"),
        (["String", "Dynamic Programming"], "Dynamic Programming"),
        (["Array"], "Array"),
    ],
)
def test_the_tag_bag_collapses_to_the_pattern_the_problem_teaches(patterns, tags, expected):
    """LeetCode's tags are unordered and say nothing about which is primary."""
    assert patterns.primary_for_tags(tags)["name"] == expected


def test_tags_that_match_nothing_produce_no_pattern(patterns):
    assert patterns.primary_for_tags(["Quantum Entanglement"]) is None


def test_no_tags_produce_no_pattern(patterns):
    assert patterns.primary_for_tags([]) is None


def test_tag_matching_ignores_case(patterns):
    assert patterns.primary_for_tags(["sliding window"])["name"] == "Sliding Window"


def test_every_seeded_pattern_has_a_distinct_priority(patterns):
    """Two patterns at the same priority make the mapping non-deterministic."""
    priorities = [p["priority"] for p in patterns.all()]

    assert len(priorities) == len(set(priorities))


# --- problems -----------------------------------------------------------------


def test_a_problem_can_be_saved_and_read_back(problems):
    make_problem(problems)

    problem = problems.by_slug("two-sum")

    assert problem["title"] == "Two Sum"
    assert problem["difficulty"] == "Easy"


def test_saving_the_same_slug_updates_rather_than_duplicates(problems):
    make_problem(problems, title="Two Sum")
    make_problem(problems, title="Two Sum (renamed)")

    assert problems.count() == 1
    assert problems.by_slug("two-sum")["title"] == "Two Sum (renamed)"


def test_an_unknown_slug_reads_back_as_none(problems):
    assert problems.by_slug("nope") is None


def test_topic_tags_round_trip_as_a_list(problems):
    make_problem(problems, topic_tags=["Array", "Hash Table"])

    assert problems.tags_for("two-sum") == ["Array", "Hash Table"]


def test_paid_problems_are_flagged(problems):
    make_problem(problems, slug="meeting-rooms", is_paid_only=True)

    assert problems.by_slug("meeting-rooms")["is_paid_only"] == 1


def test_the_primary_pattern_records_how_it_was_decided(problems, patterns):
    sliding = patterns.by_slug("sliding-window")["id"]
    problem_id = make_problem(problems)

    problems.set_primary_pattern(problem_id, sliding, source="tags")

    problem = problems.by_slug("two-sum")
    assert problem["primary_pattern_id"] == sliding
    assert problem["pattern_source"] == "tags"


def test_an_llm_classification_overrides_a_tag_one(problems, patterns):
    """Gemini's judgement during analyze is authoritative from then on."""
    problem_id = make_problem(problems)
    problems.set_primary_pattern(problem_id, patterns.by_slug("array")["id"], source="tags")

    problems.set_primary_pattern(problem_id, patterns.by_slug("sliding-window")["id"], source="llm")

    problem = problems.by_slug("two-sum")
    assert problem["pattern_source"] == "llm"
    assert problem["primary_pattern_id"] == patterns.by_slug("sliding-window")["id"]


def test_an_invalid_pattern_source_is_rejected(problems, patterns):
    """A third value would make provenance silently unanswerable."""
    problem_id = make_problem(problems)

    with pytest.raises(sqlite3.IntegrityError):
        problems.set_primary_pattern(
            problem_id, patterns.by_slug("array")["id"], source="guesswork"
        )


def test_an_analysis_can_be_saved_and_read_back(problems):
    problem_id = make_problem(problems)

    problems.save_analysis(problem_id, {"pattern": "Sliding Window", "key_insight": "..."})

    assert problems.by_slug("two-sum")["analysis"]
    assert problems.analysis_for(problem_id)["pattern"] == "Sliding Window"


def test_problems_can_be_filtered_by_difficulty_and_paid_status(problems):
    make_problem(problems, slug="a", difficulty="Easy")
    make_problem(problems, slug="b", difficulty="Hard")
    make_problem(problems, slug="c", difficulty="Easy", is_paid_only=True)

    found = problems.search(difficulty="Easy", include_paid=False)

    assert [p["slug"] for p in found] == ["a"]


# --- full-text search ---------------------------------------------------------


def test_full_text_search_finds_a_problem_by_its_content(problems):
    make_problem(problems, slug="lru", title="LRU Cache", content="Design a cache with eviction.")

    assert [p["slug"] for p in problems.search(text="eviction")] == ["lru"]


def test_the_search_index_is_updated_when_a_problem_changes(problems):
    """A stale index is worse than no index - it silently returns the wrong set."""
    make_problem(problems, slug="p", content="original wording here")
    make_problem(problems, slug="p", content="completely different subject matter")

    assert problems.search(text="original") == []
    assert [p["slug"] for p in problems.search(text="subject")] == ["p"]


def test_the_search_index_is_cleaned_up_when_a_problem_is_deleted(problems, db):
    problem_id = make_problem(problems, slug="p", content="findable text")
    db.execute("DELETE FROM problems WHERE id = ?", (problem_id,))
    db.commit()

    assert problems.search(text="findable") == []


def test_rows_written_before_the_index_existed_are_indexed_on_initialisation(tmp_path):
    """The triggers only cover writes made while the index exists. Rows from an
    older database would be invisible to search forever, and FTS5's own
    integrity-check does not notice - it only verifies self-consistency.
    """
    from app.storage.db import connect, initialize

    connection = connect(tmp_path / "old.db")
    connection.executescript(
        "CREATE TABLE problems ("
        "  id INTEGER PRIMARY KEY, slug TEXT UNIQUE, number TEXT DEFAULT '',"
        "  title TEXT, difficulty TEXT DEFAULT '', url TEXT DEFAULT '',"
        "  content TEXT DEFAULT '', topic_tags TEXT DEFAULT '',"
        "  is_paid_only INTEGER DEFAULT 0, primary_pattern_id INTEGER,"
        "  pattern_source TEXT, analysis TEXT, analyzed_at TEXT,"
        "  created_at TEXT, updated_at TEXT)"
    )
    connection.execute(
        "INSERT INTO problems (slug, title, content) VALUES ('old', 'Old', 'findable words')"
    )
    connection.commit()

    initialize(connection)

    assert [p["slug"] for p in ProblemRepository(connection).search(text="findable")] == ["old"]
    connection.close()


def test_reinitialising_does_not_rebuild_a_healthy_index(db, problems):
    """Rebuilding 4,000 problems on every command would be a slow no-op."""
    make_problem(problems, slug="p", content="findable words")

    initialize(db)

    assert [row["slug"] for row in problems.search(text="findable")] == ["p"]


def test_search_text_with_punctuation_does_not_crash(problems):
    """FTS5 has its own query syntax. Raw user text must not reach it unescaped."""
    make_problem(problems, slug="p", content="ordinary words")

    assert problems.search(text='"unbalanced quote') == []
    assert problems.search(text="a AND OR NOT b") == []


def test_search_combines_text_with_structured_filters(problems):
    make_problem(problems, slug="easy-window", difficulty="Easy", content="sliding window scan")
    make_problem(problems, slug="hard-window", difficulty="Hard", content="sliding window scan")

    found = problems.search(text="sliding", difficulty="Easy")

    assert [p["slug"] for p in found] == ["easy-window"]


# --- attempts -----------------------------------------------------------------


def test_an_attempt_can_be_recorded_and_read_back(db, problems):
    attempts = AttemptRepository(db)
    problem_id = make_problem(problems)

    attempts.record(problem_id=problem_id, solved=True, failure_type="solved")

    history = attempts.for_problem(problem_id)
    assert len(history) == 1
    assert history[0]["solved"] == 1


def test_an_attempt_defaults_to_self_reported(db, problems):
    """An inferred outcome must never be mistaken for a considered one."""
    attempts = AttemptRepository(db)
    problem_id = make_problem(problems)

    attempts.record(problem_id=problem_id, solved=False)

    assert attempts.for_problem(problem_id)[0]["source"] == "self_reported"


def test_an_invalid_failure_type_is_rejected(db, problems):
    attempts = AttemptRepository(db)
    problem_id = make_problem(problems)

    with pytest.raises(sqlite3.IntegrityError):
        attempts.record(problem_id=problem_id, solved=False, failure_type="gave_up")


def test_a_synced_attempt_is_not_duplicated_on_a_second_sync(db, problems):
    """Re-running sync must update, not accumulate."""
    attempts = AttemptRepository(db)
    problem_id = make_problem(problems)

    attempts.record(problem_id=problem_id, solved=True, source="leetcode", external_id="sub-1")
    attempts.record(problem_id=problem_id, solved=True, source="leetcode", external_id="sub-1")

    assert len(attempts.for_problem(problem_id)) == 1


def test_repeated_attempts_at_one_problem_are_all_kept(db, problems):
    """Self-reported attempts carry no external_id. Collapsing them would erase
    exactly the history this coach exists to read - three tries before solving
    is a different story from solving first time.
    """
    attempts = AttemptRepository(db)
    problem_id = make_problem(problems)

    attempts.record(problem_id=problem_id, solved=False, failure_type="no_pattern")
    attempts.record(problem_id=problem_id, solved=False, failure_type="implementation")
    attempts.record(problem_id=problem_id, solved=True, failure_type="solved")

    stored = attempts.for_problem(problem_id)
    assert [row["failure_type"] for row in stored] == [
        "no_pattern",
        "implementation",
        "solved",
    ]


def test_an_unclassified_attempt_is_stored_as_unknown_not_guessed(db, problems):
    attempts = AttemptRepository(db)
    problem_id = make_problem(problems)

    attempts.record(problem_id=problem_id, solved=False, failure_type="unknown")

    assert attempts.for_problem(problem_id)[0]["failure_type"] == "unknown"


def test_attempts_needing_classification_can_be_counted(db, problems):
    """`stats` surfaces this so the backlog is visible without being nagging."""
    attempts = AttemptRepository(db)
    problem_id = make_problem(problems)
    attempts.record(problem_id=problem_id, solved=False, failure_type="unknown")
    attempts.record(problem_id=problem_id, solved=True, failure_type="solved")

    assert attempts.count_needing_classification() == 1


# --- recommendations ----------------------------------------------------------


def test_a_recommendation_can_be_saved_and_read_back_for_a_day(db, problems):
    recommendations = RecommendationRepository(db)
    problem_id = make_problem(problems)

    recommendations.save(
        problem_id=problem_id,
        recommended_for="2026-08-17",
        score=0.82,
        score_breakdown={"pattern_weakness": 0.3},
        reasoning="Your Sliding Window success rate is 50%.",
    )

    saved = recommendations.for_date("2026-08-17")
    assert saved["problem_id"] == problem_id
    assert saved["score"] == pytest.approx(0.82)


def test_the_score_breakdown_survives_a_round_trip(db, problems):
    """A past recommendation must stay explainable after the weights change."""
    recommendations = RecommendationRepository(db)
    problem_id = make_problem(problems)
    breakdown = {"pattern_weakness": 0.3, "review_due": 0.25}

    recommendations.save(
        problem_id=problem_id,
        recommended_for="2026-08-17",
        score=0.55,
        score_breakdown=breakdown,
        reasoning="",
    )

    assert recommendations.breakdown_for("2026-08-17") == breakdown


def test_recommending_twice_for_one_day_replaces_rather_than_duplicates(db, problems):
    """Re-running `today` shows the same day's recommendation, not a new one."""
    recommendations = RecommendationRepository(db)
    first = make_problem(problems, slug="a")
    second = make_problem(problems, slug="b")

    recommendations.save(problem_id=first, recommended_for="2026-08-17", score=0.5)
    recommendations.save(problem_id=second, recommended_for="2026-08-17", score=0.9)

    assert recommendations.for_date("2026-08-17")["problem_id"] == second


def test_no_recommendation_for_a_day_reads_back_as_none(db):
    assert RecommendationRepository(db).for_date("1999-01-01") is None


# --- reviews ------------------------------------------------------------------


def test_a_review_can_be_scheduled_and_found_when_due(db, problems):
    reviews = ReviewRepository(db)
    problem_id = make_problem(problems)

    reviews.schedule(problem_id=problem_id, due_at="2026-08-01", interval_days=1)

    due = reviews.due_on("2026-08-17")
    assert [r["problem_id"] for r in due] == [problem_id]


def test_a_review_not_yet_due_is_not_returned(db, problems):
    reviews = ReviewRepository(db)
    problem_id = make_problem(problems)

    reviews.schedule(problem_id=problem_id, due_at="2026-12-01", interval_days=30)

    assert reviews.due_on("2026-08-17") == []


def test_rescheduling_updates_the_existing_review(db, problems):
    """Two rows would mean two competing due dates for the same problem."""
    reviews = ReviewRepository(db)
    problem_id = make_problem(problems)

    reviews.schedule(problem_id=problem_id, due_at="2026-08-01", interval_days=1)
    reviews.schedule(problem_id=problem_id, due_at="2026-09-01", interval_days=7)

    assert len(reviews.all()) == 1
    assert reviews.for_problem(problem_id)["interval_days"] == 7


def test_recording_a_review_increments_the_count(db, problems):
    reviews = ReviewRepository(db)
    problem_id = make_problem(problems)
    reviews.schedule(problem_id=problem_id, due_at="2026-08-01", interval_days=1)

    reviews.record_result(problem_id=problem_id, score=80, next_due="2026-08-20", interval_days=3)

    review = reviews.for_problem(problem_id)
    assert review["review_count"] == 1
    assert review["last_score"] == 80
    assert review["interval_days"] == 3


# --- problem_patterns ---------------------------------------------------------


def test_a_problem_can_carry_several_patterns_with_one_primary(problems, patterns, db):
    problem_id = make_problem(problems)
    sliding = patterns.by_slug("sliding-window")["id"]
    hashing = patterns.by_slug("hash-table")["id"]

    problems.link_patterns(problem_id, [sliding, hashing], primary_id=sliding)

    linked = problems.patterns_for(problem_id)
    assert {row["pattern_id"] for row in linked} == {sliding, hashing}
    assert [row["pattern_id"] for row in linked if row["is_primary"]] == [sliding]


def test_relinking_patterns_replaces_the_previous_set(problems, patterns):
    problem_id = make_problem(problems)
    array = patterns.by_slug("array")["id"]
    sliding = patterns.by_slug("sliding-window")["id"]

    problems.link_patterns(problem_id, [array], primary_id=array)
    problems.link_patterns(problem_id, [sliding], primary_id=sliding)

    assert [row["pattern_id"] for row in problems.patterns_for(problem_id)] == [sliding]


# --- connection behaviour -----------------------------------------------------


def test_a_file_database_creates_its_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "coach.db"

    connection = open_database(path)
    connection.close()

    assert path.exists()


def test_a_rolled_back_transaction_leaves_nothing_behind(db, problems):
    from app.storage.db import transaction

    with pytest.raises(RuntimeError):
        with transaction(db):
            make_problem(problems, slug="doomed")
            raise RuntimeError("something went wrong")

    assert problems.by_slug("doomed") is None


def test_a_successful_transaction_keeps_everything(db, problems):
    from app.storage.db import transaction

    with transaction(db):
        make_problem(problems, slug="a")
        make_problem(problems, slug="b")

    assert problems.count() == 2


def test_a_partial_bulk_import_leaves_nothing_behind(db, problems):
    """Importing 4,000 problems must not leave half of them when row 2,000 fails."""
    from app.storage.db import transaction

    with pytest.raises(RuntimeError):
        with transaction(db):
            for i in range(10):
                make_problem(problems, slug=f"p{i}")
            raise RuntimeError("network dropped")

    assert problems.count() == 0


def test_nested_transactions_commit_once_at_the_outermost_block(db, problems):
    from app.storage.db import transaction

    with pytest.raises(RuntimeError):
        with transaction(db):
            make_problem(problems, slug="outer")
            with transaction(db):
                make_problem(problems, slug="inner")
            raise RuntimeError("failed after the inner block finished")

    assert problems.count() == 0, "the inner block must not commit on its own"


def test_an_interrupt_does_not_leave_transaction_state_behind(db):
    """KeyboardInterrupt is a BaseException, so `except Exception` misses it.

    A raised depth that is never lowered silently disables every later commit.
    """
    from app.storage.db import transaction

    with pytest.raises(KeyboardInterrupt):
        with transaction(db):
            raise KeyboardInterrupt()

    assert db.transaction_depth == 0


def test_the_depth_returns_to_zero_after_a_normal_block(db, problems):
    from app.storage.db import transaction

    with transaction(db):
        make_problem(problems, slug="a")

    assert db.transaction_depth == 0


def test_writes_still_commit_after_an_earlier_transaction_was_interrupted(db, problems):
    """The consequence that makes leaked depth dangerous: silent data loss."""
    from app.storage.db import transaction

    with pytest.raises(KeyboardInterrupt):
        with transaction(db):
            raise KeyboardInterrupt()

    make_problem(problems, slug="written-afterwards")

    db.execute("BEGIN")  # fails if an uncommitted transaction is still open
    db.execute("ROLLBACK")
    assert problems.by_slug("written-afterwards") is not None


def test_an_abandoned_transaction_does_not_raise_when_collected(tmp_path):
    """A generator suspended inside transaction() is finalised by the garbage
    collector, possibly after close(). Raising there is noise nobody can act on.
    """
    import gc

    from app.storage.db import open_database, transaction

    def suspended(connection):
        with transaction(connection):
            yield 1
            yield 2

    connection = open_database(tmp_path / "c.db")
    generator = suspended(connection)
    next(generator)
    connection.close()

    del generator
    gc.collect()  # must not raise "Cannot operate on a closed database"


def test_connect_alone_does_not_create_tables():
    """initialize is a separate step, so a caller can inspect an empty file."""
    connection = connect(":memory:")

    tables = connection.execute("SELECT name FROM sqlite_master").fetchall()

    assert tables == []
    connection.close()
