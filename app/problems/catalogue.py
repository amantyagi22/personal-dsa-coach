"""Catalogue sync.

Fetches the LeetCode catalogue and stores it locally with a primary pattern per
problem, so the recommender has something to recommend without a network call.

An application service, not a CLI command: the API and the scheduler will call
this same code, and a rule about how problems get classified must not live in
one adapter where the others cannot see it.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from app.problems.leetcode import LeetCodeClient, Problem
from app.storage.db import Connection, transaction
from app.storage.repositories import PatternRepository, ProblemRepository

logger = logging.getLogger(__name__)

# Where a problem lands when its tags match no canonical pattern. The catalogue
# has 161 problems with no tags at all, so this is a real case, not a defensive
# one - and dropping them would silently shrink the catalogue.
UNCLASSIFIED_SLUG = "other"

# How often to commit while importing. One transaction for all 4,000 would hold
# a write lock for the whole run and lose everything on a failure at row 3,900;
# one per problem would be 4,000 fsyncs.
BATCH_SIZE = 100


@dataclass
class SyncReport:
    """What a sync run did, in terms a user can act on."""

    fetched: int = 0
    stored: int = 0
    classified: int = 0
    unclassified: int = 0
    paid_only: int = 0
    unmapped_tags: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"Synced {self.stored} problems from LeetCode.",
            f"  {self.classified} classified by topic tags",
            f"  {self.paid_only} paid-only (excluded from recommendations)",
        ]
        if self.unclassified:
            lines.append(f"  {self.unclassified} had no matching pattern, filed under 'Other'")
        if self.unmapped_tags:
            top = sorted(self.unmapped_tags.items(), key=lambda kv: -kv[1])[:5]
            listed = ", ".join(f"{tag} ({count})" for tag, count in top)
            lines.append(f"  Unmapped tags worth a look: {listed}")
        return "\n".join(lines)


class CatalogueSync:
    """Imports the LeetCode catalogue into the local database."""

    def __init__(
        self,
        connection: Connection,
        client: LeetCodeClient | None = None,
    ) -> None:
        self.db = connection
        self.client = client or LeetCodeClient()
        self.problems = ProblemRepository(connection)
        self.patterns = PatternRepository(connection)

    def run(self, on_progress: Callable[[int], None] | None = None) -> SyncReport:
        """Fetch and store the whole catalogue."""
        return self.store(self.client.iter_catalogue(), on_progress=on_progress)

    def store(
        self,
        problems: Iterable[Problem],
        on_progress: Callable[[int], None] | None = None,
    ) -> SyncReport:
        """Store problems that are already fetched.

        Separated from run() so the storage and classification logic is testable
        with a fixed list and no network.
        """
        report = SyncReport()
        # Cached because primary_for_tags is called once per problem and the
        # taxonomy does not change mid-run.
        fallback = self.patterns.by_slug(UNCLASSIFIED_SLUG)
        known_tags = {row["tag"].lower() for row in self._all_tags()}

        batch: list[Problem] = []
        for problem in problems:
            batch.append(problem)
            report.fetched += 1
            if len(batch) >= BATCH_SIZE:
                self._store_batch(batch, report, fallback, known_tags)
                batch = []
                if on_progress:
                    on_progress(report.stored)

        if batch:
            self._store_batch(batch, report, fallback, known_tags)
            if on_progress:
                on_progress(report.stored)

        return report

    def _store_batch(
        self,
        batch: list[Problem],
        report: SyncReport,
        fallback: sqlite3.Row | None,
        known_tags: set[str],
    ) -> None:
        """Write one batch atomically.

        A network failure part way through leaves whole batches, never half a
        problem - the row and its classification land together or not at all.
        """
        with transaction(self.db):
            for problem in batch:
                problem_id = self.problems.upsert(
                    slug=problem.slug,
                    number=problem.number,
                    title=problem.title,
                    difficulty=problem.difficulty,
                    url=problem.url,
                    content=problem.content,
                    topic_tags=problem.topic_tags,
                    is_paid_only=problem.is_paid_only,
                )
                report.stored += 1
                if problem.is_paid_only:
                    report.paid_only += 1

                self._classify(problem, problem_id, report, fallback, known_tags)

    def _classify(
        self,
        problem: Problem,
        problem_id: int,
        report: SyncReport,
        fallback: sqlite3.Row | None,
        known_tags: set[str],
    ) -> None:
        """Give the problem exactly one primary pattern.

        Every problem gets one, including those whose tags match nothing: the
        fallback pattern makes that visible in the data rather than leaving a
        NULL that every later query has to remember to handle.
        """
        pattern = self.patterns.primary_for_tags(problem.topic_tags)

        if pattern is None:
            for tag in problem.topic_tags:
                if tag.lower() not in known_tags:
                    # Surfaced in the report so a new LeetCode tag is noticed
                    # rather than silently filed under Other forever.
                    report.unmapped_tags[tag] = report.unmapped_tags.get(tag, 0) + 1
            pattern = fallback
            report.unclassified += 1
        else:
            report.classified += 1

        if pattern is None:
            logger.warning("No fallback pattern; %s left unclassified", problem.slug)
            return

        pattern_id = int(pattern["id"])
        self.problems.set_primary_pattern(problem_id, pattern_id, source="tags")

        # Every pattern the problem touches, with the primary marked. Keeps
        # "show me everything involving Binary Search" answerable without
        # losing the single primary that scoring depends on.
        linked = {
            int(row["id"])
            for tag in problem.topic_tags
            if (row := self.patterns.by_leetcode_tag(tag)) is not None
        }
        linked.add(pattern_id)
        self.problems.link_patterns(problem_id, sorted(linked), primary_id=pattern_id)

    def _all_tags(self) -> list[dict[str, str]]:
        return [dict(row) for row in self.db.execute("SELECT tag FROM pattern_tags")]
