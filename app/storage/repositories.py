"""Repositories - the only code that writes SQL.

One class per table group. Everything above this layer works with rows and
plain Python values, so a schema change lands here and nowhere else.

Each repository takes a connection rather than opening one, which is what lets
every test run against an in-memory database.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, cast

from app.storage.db import Connection, save

DEFAULT_USER_ID = 1

# FTS5 treats quotes, AND/OR/NOT, and several punctuation marks as query syntax.
# User text and LLM-generated text both reach search(), and neither should be
# able to produce a syntax error - or, worse, a silently different query.
_FTS_SAFE = re.compile(r"[^\w\s]")
_FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}


class UserRepository:
    """The single local user.

    One row, id 1, created by initialisation. This exists so that the fields
    that do change - the LeetCode username sync needs - have a writer, rather
    than being reached through raw SQL from somewhere else.
    """

    def __init__(self, connection: Connection, user_id: int = DEFAULT_USER_ID) -> None:
        self.db = connection
        self.user_id = user_id

    def get(self) -> sqlite3.Row | None:
        return _one(self.db.execute("SELECT * FROM users WHERE id = ?", (self.user_id,)).fetchone())

    def set_leetcode_username(self, username: str | None) -> None:
        self.db.execute(
            "UPDATE users SET leetcode_username = ? WHERE id = ?", (username, self.user_id)
        )
        save(self.db)


class PatternRepository:
    def __init__(self, connection: Connection) -> None:
        self.db = connection

    def all(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM patterns ORDER BY priority").fetchall()

    def upsert(
        self,
        *,
        name: str,
        slug: str,
        priority: int = 500,
        leetcode_tags: tuple[str, ...] | list[str] = (),
        description: str = "",
    ) -> int:
        """Add a pattern, or update one that already exists.

        The taxonomy is data, so adding a pattern the seed did not anticipate
        should not require editing Python.
        """
        cursor = self.db.execute(
            """
            INSERT INTO patterns (name, slug, priority, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (slug) DO UPDATE SET
                name = excluded.name,
                priority = excluded.priority,
                description = excluded.description
            RETURNING id
            """,
            (name, slug, priority, description),
        )
        pattern_id = int(cursor.fetchone()["id"])
        for tag in leetcode_tags:
            self.db.execute(
                "INSERT INTO pattern_tags (tag, pattern_id) VALUES (?, ?) "
                "ON CONFLICT (tag) DO UPDATE SET pattern_id = excluded.pattern_id",
                (tag, pattern_id),
            )
        save(self.db)
        return pattern_id

    def by_slug(self, slug: str) -> sqlite3.Row | None:
        return _one(self.db.execute("SELECT * FROM patterns WHERE slug = ?", (slug,)).fetchone())

    def by_name(self, name: str) -> sqlite3.Row | None:
        return _one(
            self.db.execute(
                "SELECT * FROM patterns WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
        )

    def by_leetcode_tag(self, tag: str) -> sqlite3.Row | None:
        return _one(
            self.db.execute(
                "SELECT p.* FROM patterns p JOIN pattern_tags t ON t.pattern_id = p.id "
                "WHERE LOWER(t.tag) = ?",
                (tag.lower(),),
            ).fetchone()
        )

    def map_tag(self, tag: str, pattern_slug: str) -> None:
        """Point a LeetCode tag at a pattern, or repoint an existing one.

        LeetCode adds tags over time. This is how a new one gets classified
        without editing Python.
        """
        self.db.execute(
            "INSERT INTO pattern_tags (tag, pattern_id) "
            "VALUES (?, (SELECT id FROM patterns WHERE slug = ?)) "
            "ON CONFLICT (tag) DO UPDATE SET pattern_id = excluded.pattern_id",
            (tag, pattern_slug),
        )
        save(self.db)

    def primary_for_tags(self, tags: list[str]) -> sqlite3.Row | None:
        """Collapse LeetCode's unordered tag bag to one primary pattern.

        Lowest priority number wins, so a distinctive technique beats a generic
        data structure: "Hash Table, String, Sliding Window" resolves to Sliding
        Window, which is what the problem is actually teaching.

        Returns None when nothing matches - the caller decides what that means,
        rather than this quietly inventing a pattern.
        """
        if not tags:
            return None
        # LOWER on both sides rather than COLLATE NOCASE, which applies to the
        # comparison operator and not to the members of an IN list.
        placeholders = ",".join("?" * len(tags))
        return _one(
            self.db.execute(
                f"SELECT p.* FROM patterns p JOIN pattern_tags t ON t.pattern_id = p.id "
                f"WHERE LOWER(t.tag) IN ({placeholders}) "
                f"ORDER BY p.priority LIMIT 1",
                [tag.lower() for tag in tags],
            ).fetchone()
        )


class ProblemRepository:
    def __init__(self, connection: Connection) -> None:
        self.db = connection

    def upsert(
        self,
        *,
        slug: str,
        title: str,
        number: str = "",
        difficulty: str = "Unknown",
        url: str = "",
        content: str = "",
        topic_tags: list[str] | None = None,
        is_paid_only: bool = False,
    ) -> int:
        """Insert a problem, or update it if the slug is already known.

        The slug is the natural key - it is what LeetCode's URLs use and what a
        user pastes - so re-syncing the catalogue refreshes rows instead of
        accumulating duplicates.

        An empty content never overwrites a stored description. Catalogue pages
        carry no description - only the per-problem query does - so without this
        a routine re-sync would silently erase everything `analyze` had fetched.
        """
        tags = json.dumps(topic_tags or [])
        cursor = self.db.execute(
            """
            INSERT INTO problems (slug, number, title, difficulty, url, content,
                                  topic_tags, is_paid_only)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (slug) DO UPDATE SET
                number = excluded.number,
                title = excluded.title,
                difficulty = excluded.difficulty,
                url = excluded.url,
                content = CASE WHEN excluded.content != '' THEN excluded.content
                               ELSE problems.content END,
                topic_tags = excluded.topic_tags,
                is_paid_only = excluded.is_paid_only,
                updated_at = datetime('now')
            RETURNING id
            """,
            (slug, number, title, difficulty, url, content, tags, int(is_paid_only)),
        )
        problem_id = int(cursor.fetchone()["id"])
        save(self.db)
        return problem_id

    def by_slug(self, slug: str) -> sqlite3.Row | None:
        return _one(self.db.execute("SELECT * FROM problems WHERE slug = ?", (slug,)).fetchone())

    def by_id(self, problem_id: int) -> sqlite3.Row | None:
        return _one(
            self.db.execute("SELECT * FROM problems WHERE id = ?", (problem_id,)).fetchone()
        )

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) AS n FROM problems").fetchone()["n"])

    def count_by_pattern(self, *, include_paid: bool = False) -> list[sqlite3.Row]:
        """How many problems sit under each pattern, split by difficulty.

        What `patterns` prints. Lives here rather than in the CLI because this
        module is meant to be the only place that writes SQL.
        """
        return self.db.execute(
            """
            SELECT p.name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN pr.difficulty = 'Easy' THEN 1 ELSE 0 END) AS easy,
                   SUM(CASE WHEN pr.difficulty = 'Medium' THEN 1 ELSE 0 END) AS medium,
                   SUM(CASE WHEN pr.difficulty = 'Hard' THEN 1 ELSE 0 END) AS hard
              FROM problems pr
              JOIN patterns p ON p.id = pr.primary_pattern_id
             WHERE (? OR pr.is_paid_only = 0)
             GROUP BY p.name
             ORDER BY total DESC
            """,
            (int(include_paid),),
        ).fetchall()

    def tags_for(self, slug: str) -> list[str]:
        row = self.by_slug(slug)
        return json.loads(row["topic_tags"]) if row else []

    def set_primary_pattern(self, problem_id: int, pattern_id: int, *, source: str) -> None:
        """Record the primary pattern and how it was decided.

        source is 'tags' or 'llm'. The database enforces that, because a third
        value would silently make provenance unanswerable.
        """
        self.db.execute(
            "UPDATE problems SET primary_pattern_id = ?, pattern_source = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (pattern_id, source, problem_id),
        )
        save(self.db)

    def link_patterns(
        self, problem_id: int, pattern_ids: list[int], *, primary_id: int | None = None
    ) -> None:
        """Replace the problem's pattern links.

        Replace rather than merge: re-classifying a problem should not leave the
        previous classification behind as a ghost.
        """
        self.db.execute("DELETE FROM problem_patterns WHERE problem_id = ?", (problem_id,))
        self.db.executemany(
            "INSERT INTO problem_patterns (problem_id, pattern_id, is_primary) VALUES (?, ?, ?)",
            [(problem_id, pid, int(pid == primary_id)) for pid in pattern_ids],
        )
        save(self.db)

    def patterns_for(self, problem_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM problem_patterns WHERE problem_id = ?", (problem_id,)
        ).fetchall()

    def save_analysis(self, problem_id: int, analysis: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE problems SET analysis = ?, analyzed_at = datetime('now'), "
            "updated_at = datetime('now') WHERE id = ?",
            (json.dumps(analysis), problem_id),
        )
        save(self.db)

    def analysis_for(self, problem_id: int) -> dict[str, Any] | None:
        row = self.by_id(problem_id)
        if row is None or not row["analysis"]:
            return None
        return dict(json.loads(row["analysis"]))

    def search(
        self,
        *,
        text: str | None = None,
        difficulty: str | None = None,
        pattern_id: int | None = None,
        include_paid: bool = False,
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        """Find problems by full-text match and structured filters.

        The retrieval half of finding similar problems. It deliberately returns a
        wide candidate set - the LLM judges which are genuinely similar, and at a
        few thousand problems a generous recall is cheaper than a vector index.
        """
        conditions: list[str] = []
        params: list[Any] = []
        source = "problems p"

        if query := _fts_query(text):
            source = "problems p JOIN problems_fts f ON f.rowid = p.id"
            conditions.append("problems_fts MATCH ?")
            params.append(query)
        elif text:
            # The text was entirely punctuation or operators, so there is nothing
            # left to match. Returning everything would be a surprising answer to
            # a search that asked for something specific.
            return []

        if difficulty:
            conditions.append("p.difficulty = ?")
            params.append(difficulty)
        if pattern_id is not None:
            conditions.append("p.primary_pattern_id = ?")
            params.append(pattern_id)
        if not include_paid:
            conditions.append("p.is_paid_only = 0")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order = "ORDER BY rank" if query else "ORDER BY p.id"
        params.append(limit)

        return self.db.execute(
            f"SELECT p.* FROM {source} {where} {order} LIMIT ?", params
        ).fetchall()


class AttemptRepository:
    def __init__(self, connection: Connection, user_id: int = DEFAULT_USER_ID) -> None:
        self.db = connection
        self.user_id = user_id

    def record(
        self,
        *,
        problem_id: int,
        solved: bool,
        failure_type: str | None = None,
        source: str = "self_reported",
        time_spent_minutes: int | None = None,
        notes: str = "",
        attempted_at: str | None = None,
        external_id: str | None = None,
    ) -> int:
        """Record one attempt.

        external_id is the LeetCode submission id when this came from sync. It is
        UNIQUE, so re-running sync updates the row rather than adding a second
        copy of the same submission.

        The ON CONFLICT clause is deliberately inert for self-reported attempts,
        which have no external_id: SQLite treats NULLs as distinct, so each one
        inserts a new row. That is required, not incidental - three attempts at a
        problem before solving it is exactly the history this coach reads, and
        collapsing them into one row would erase it. Do not "fix" this with a
        partial unique index on (user_id, problem_id).
        """
        cursor = self.db.execute(
            """
            INSERT INTO attempts (user_id, problem_id, solved, failure_type, source,
                                  time_spent_minutes, notes, external_id, attempted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))
            ON CONFLICT (external_id) DO UPDATE SET
                solved = excluded.solved,
                failure_type = excluded.failure_type,
                attempted_at = excluded.attempted_at
            RETURNING id
            """,
            (
                self.user_id,
                problem_id,
                int(solved),
                failure_type,
                source,
                time_spent_minutes,
                notes,
                external_id,
                attempted_at,
            ),
        )
        attempt_id = int(cursor.fetchone()["id"])
        save(self.db)
        return attempt_id

    def for_problem(self, problem_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM attempts WHERE problem_id = ? AND user_id = ? ORDER BY attempted_at",
            (problem_id, self.user_id),
        ).fetchall()

    def all(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM attempts WHERE user_id = ? ORDER BY attempted_at DESC",
            (self.user_id,),
        ).fetchall()

    def count_needing_classification(self) -> int:
        """Attempts whose failure type nobody has decided yet.

        Surfaced by `stats` so the backlog is visible. These are excluded from
        failure-driven scoring rather than treated as an average, which would
        quietly drag every statistic toward the middle.
        """
        return int(
            self.db.execute(
                "SELECT COUNT(*) AS n FROM attempts "
                "WHERE user_id = ? AND (failure_type IS NULL OR failure_type = 'unknown')",
                (self.user_id,),
            ).fetchone()["n"]
        )


class RecommendationRepository:
    def __init__(self, connection: Connection, user_id: int = DEFAULT_USER_ID) -> None:
        self.db = connection
        self.user_id = user_id

    def save(
        self,
        *,
        problem_id: int,
        recommended_for: str,
        score: float,
        score_breakdown: dict[str, Any] | None = None,
        reasoning: str = "",
    ) -> int:
        """Save the recommendation for a date, replacing any existing one.

        The breakdown is stored as JSON so a past recommendation stays
        explainable after the weights are retuned. Without it, "why did it pick
        this?" becomes unanswerable the moment configuration changes.
        """
        cursor = self.db.execute(
            """
            INSERT INTO recommendations (user_id, problem_id, recommended_for, score,
                                         score_breakdown, reasoning)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, recommended_for) DO UPDATE SET
                problem_id = excluded.problem_id,
                score = excluded.score,
                score_breakdown = excluded.score_breakdown,
                reasoning = excluded.reasoning
            RETURNING id
            """,
            (
                self.user_id,
                problem_id,
                recommended_for,
                score,
                json.dumps(score_breakdown or {}),
                reasoning,
            ),
        )
        recommendation_id = int(cursor.fetchone()["id"])
        save(self.db)
        return recommendation_id

    def for_date(self, date: str) -> sqlite3.Row | None:
        return _one(
            self.db.execute(
                "SELECT * FROM recommendations WHERE user_id = ? AND recommended_for = ?",
                (self.user_id, date),
            ).fetchone()
        )

    def breakdown_for(self, date: str) -> dict[str, Any]:
        row = self.for_date(date)
        return dict(json.loads(row["score_breakdown"])) if row else {}

    def recent(self, limit: int = 30) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM recommendations WHERE user_id = ? ORDER BY recommended_for DESC LIMIT ?",
            (self.user_id, limit),
        ).fetchall()


class ReviewRepository:
    def __init__(self, connection: Connection, user_id: int = DEFAULT_USER_ID) -> None:
        self.db = connection
        self.user_id = user_id

    def schedule(self, *, problem_id: int, due_at: str, interval_days: int = 1) -> int:
        """Schedule or reschedule a problem's review.

        One row per problem: a second would mean two competing due dates for the
        same thing.
        """
        cursor = self.db.execute(
            """
            INSERT INTO reviews (user_id, problem_id, due_at, interval_days)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (user_id, problem_id) DO UPDATE SET
                due_at = excluded.due_at,
                interval_days = excluded.interval_days
            RETURNING id
            """,
            (self.user_id, problem_id, due_at, interval_days),
        )
        review_id = int(cursor.fetchone()["id"])
        save(self.db)
        return review_id

    def record_result(
        self, *, problem_id: int, score: int, next_due: str, interval_days: int
    ) -> None:
        self.db.execute(
            """
            UPDATE reviews
               SET last_reviewed_at = datetime('now'),
                   last_score = ?,
                   due_at = ?,
                   interval_days = ?,
                   review_count = review_count + 1
             WHERE user_id = ? AND problem_id = ?
            """,
            (score, next_due, interval_days, self.user_id, problem_id),
        )
        save(self.db)

    def due_on(self, date: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM reviews WHERE user_id = ? AND due_at <= ? ORDER BY due_at",
            (self.user_id, date),
        ).fetchall()

    def for_problem(self, problem_id: int) -> sqlite3.Row | None:
        return _one(
            self.db.execute(
                "SELECT * FROM reviews WHERE user_id = ? AND problem_id = ?",
                (self.user_id, problem_id),
            ).fetchone()
        )

    def all(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM reviews WHERE user_id = ? ORDER BY due_at", (self.user_id,)
        ).fetchall()


def _one(row: Any) -> sqlite3.Row | None:
    """sqlite3's fetchone() is typed Any; this pins it to the row type we use."""
    return row if row is None else cast(sqlite3.Row, row)


def _fts_query(text: str | None) -> str:
    """Turn arbitrary text into a safe FTS5 MATCH query.

    Everything that is not a word character is stripped, and bare boolean
    operators are dropped, so a stray quote or an "AND" in a problem title cannot
    produce a syntax error or silently change the query's meaning.
    """
    if not text:
        return ""
    words = [w for w in _FTS_SAFE.sub(" ", text).split() if w.upper() not in _FTS_OPERATORS]
    return " ".join(words)
