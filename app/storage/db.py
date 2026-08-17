"""Database connection and initialisation.

sqlite3 from the standard library, no ORM. The schema is small, fixed, and
single-user; an ORM would add a dependency and a layer of indirection over
queries that are already the clearest way to say what they do.

Initialisation is idempotent, so it can run on every command. A single local
file with one user does not need a migration framework - and pretending it does
would mean maintaining migrations nobody ever runs against anybody else's data.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.storage.patterns import CANONICAL_PATTERNS

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Bumped whenever the seeded taxonomy in patterns.py is corrected. Rows still
# carrying an older version are refreshed on the next initialisation; rows a
# user has edited carry NULL and are left alone.
SEED_VERSION = 2


class Connection(sqlite3.Connection):
    """A connection that can carry its own transaction depth.

    sqlite3.Connection has no __dict__, but a subclass does. Tracking the depth
    on the object rather than in a dict keyed by id() matters: CPython recycles
    id() once a connection is freed, so a stale entry could attach itself to an
    unrelated new connection and make every write silently stop committing.
    """

    transaction_depth: int = 0


def connect(path: Path | str) -> Connection:
    """Open a connection with the settings every caller wants.

    ":memory:" is passed straight through, which is how the tests run.
    """
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, factory=Connection)
    # Rows behave like dicts, so callers read row["title"] rather than row[3] -
    # which silently breaks the moment a column is added.
    connection.row_factory = sqlite3.Row
    # Off by default in sqlite3, and the schema depends on it.
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    """Create the schema and seed the patterns. Safe to run repeatedly."""
    connection.executescript(SCHEMA_PATH.read_text())
    _add_missing_columns(connection)
    seed_patterns(connection)
    ensure_user(connection)
    rebuild_search_index_if_stale(connection)
    connection.commit()


def rebuild_search_index_if_stale(connection: sqlite3.Connection) -> None:
    """Reindex if the search index has fallen behind the problems table.

    The triggers keep the index current for every write made while the index
    exists - but rows written before it was created are never indexed, and
    FTS5's own integrity-check will not notice, because it only verifies that
    the index is self-consistent.

    That failure is invisible and consequential: search is the retrieval half of
    finding similar problems, so a short index quietly degrades recommendations
    rather than raising anything.

    Detection has one subtlety worth naming: COUNT(*) on an external-content FTS
    table reads the *content* table, so it always agrees with problems and can
    never reveal a stale index. The docsize shadow table holds one row per
    genuinely indexed document, so it is the thing to ask.
    """
    problems = connection.execute("SELECT COUNT(*) AS n FROM problems").fetchone()["n"]
    if not problems:
        return

    indexed = connection.execute("SELECT COUNT(*) AS n FROM problems_fts_docsize").fetchone()["n"]
    if indexed != problems:
        logger.info("Search index has %d of %d problems; rebuilding", indexed, problems)
        connection.execute("INSERT INTO problems_fts(problems_fts) VALUES ('rebuild')")


def _add_missing_columns(connection: sqlite3.Connection) -> None:
    """Add columns that CREATE TABLE IF NOT EXISTS cannot add to an existing table.

    The one concession to migration this project makes. A local single-user file
    does not need a migration framework, but a table that already exists is
    skipped entirely by the schema script, so a new column would never appear.
    """
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(patterns)")}
    if "seed_version" not in existing:
        connection.execute("ALTER TABLE patterns ADD COLUMN seed_version INTEGER")
        # Rows predating versioning were written by seed version 1, not edited by
        # hand, so they are eligible for the corrected values.
        connection.execute("UPDATE patterns SET seed_version = 1 WHERE seed_version IS NULL")


def seed_patterns(connection: sqlite3.Connection) -> None:
    """Insert the canonical patterns and their tag mappings.

    Two competing needs: a taxonomy edited in the database is a deliberate act
    that re-running initialisation must not undo, but a *corrected* seed has to
    reach existing databases. Plain DO NOTHING serves only the first, and left
    an earlier release's wrong priorities in place permanently - "Union Find"
    spelled without LeetCode's hyphen matched nothing at all, silently.

    seed_version resolves it: a row is only refreshed when the shipped seed is
    newer than the version stored on it, so re-running initialisation is a no-op
    and hand edits survive every run at the current version.

    The honest limitation: a hand edit does *not* survive a version bump, since
    nothing marks a row as user-owned. Setting seed_version to NULL by hand
    pins a row permanently. That is enough for a single-user local file, and
    tag mappings - the thing most likely to be retargeted deliberately - are
    left untouched by design.
    """
    connection.executemany(
        """
        INSERT INTO patterns (name, slug, priority, description, seed_version)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (slug) DO UPDATE SET
            name = excluded.name,
            priority = excluded.priority,
            description = excluded.description,
            seed_version = excluded.seed_version
        WHERE patterns.seed_version IS NOT NULL
          AND patterns.seed_version < excluded.seed_version
        """,
        [(p.name, p.slug, p.priority, p.description, SEED_VERSION) for p in CANONICAL_PATTERNS],
    )
    connection.executemany(
        """
        INSERT INTO pattern_tags (tag, pattern_id)
        VALUES (?, (SELECT id FROM patterns WHERE slug = ?))
        ON CONFLICT (tag) DO NOTHING
        """,
        [(tag, p.slug) for p in CANONICAL_PATTERNS for tag in p.leetcode_tags],
    )


def ensure_user(connection: sqlite3.Connection) -> int:
    """The single local user, created on demand.

    One row, id 1. The brief is explicit that there is no authentication and one
    user; this exists so the rows that belong to someone have someone to belong
    to.
    """
    connection.execute("INSERT OR IGNORE INTO users (id) VALUES (1)")
    return 1


@contextmanager
def transaction(connection: Connection) -> Iterator[Connection]:
    """Commit on success, roll back on any exception.

    Used for multi-statement writes - importing 4,000 problems should not leave
    half of them behind when the network drops at row 2,000.

    Repository methods call save() so a single write is one call; inside this
    block save() becomes a no-op and the whole body commits once at the end.
    Without that, a rollback could only undo statements since the last
    repository call, which is not what "roll back on any exception" means.
    """
    depth = connection.transaction_depth
    connection.transaction_depth = depth + 1
    committed = False
    try:
        yield connection
        committed = True
    finally:
        # finally, not except: KeyboardInterrupt is a BaseException and would
        # otherwise leave the depth raised, silently disabling every later commit.
        connection.transaction_depth = depth
        if depth == 0:
            _finish(connection, commit=committed)


def save(connection: Connection) -> None:
    """Commit, unless a transaction() block is managing the boundary.

    Repositories call this instead of commit() so that both usage styles work:
    one write is one call, and a batch is atomic.
    """
    if connection.transaction_depth == 0:
        connection.commit()


def _finish(connection: Connection, *, commit: bool) -> None:
    """Commit or roll back, tolerating an already-closed connection.

    A transaction abandoned inside a generator is finalised by the garbage
    collector, which may run after close(). Raising there produces noise nobody
    can act on, and the database has already discarded the work anyway.
    """
    try:
        if commit:
            connection.commit()
        else:
            connection.rollback()
    except sqlite3.ProgrammingError:
        logger.debug("Transaction ended on an already-closed connection")


def open_database(path: Path | str) -> Connection:
    """Connect and initialise in one call. What application code uses."""
    connection = connect(path)
    initialize(connection)
    return connection
