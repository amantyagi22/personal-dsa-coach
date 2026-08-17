"""Database connection and initialisation.

sqlite3 from the standard library, no ORM. The schema is small, fixed, and
single-user; an ORM would add a dependency and a layer of indirection over
queries that are already the clearest way to say what they do.

Initialisation is idempotent, so it can run on every command. A single local
file with one user does not need a migration framework - and pretending it does
would mean maintaining migrations nobody ever runs against anybody else's data.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.storage.patterns import CANONICAL_PATTERNS

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with the settings every caller wants.

    ":memory:" is passed straight through, which is how the tests run.
    """
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    # Rows behave like dicts, so callers read row["title"] rather than row[3] -
    # which silently breaks the moment a column is added.
    connection.row_factory = sqlite3.Row
    # Off by default in sqlite3, and the schema depends on it.
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    """Create the schema and seed the patterns. Safe to run repeatedly."""
    connection.executescript(SCHEMA_PATH.read_text())
    seed_patterns(connection)
    ensure_user(connection)
    connection.commit()


def seed_patterns(connection: sqlite3.Connection) -> None:
    """Insert the canonical patterns, leaving any existing row untouched.

    ON CONFLICT DO NOTHING rather than REPLACE: a pattern edited in the database
    is a deliberate act, and re-running initialisation must not undo it.
    """
    connection.executemany(
        """
        INSERT INTO patterns (name, slug, priority, leetcode_tag, description)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (slug) DO NOTHING
        """,
        [(p.name, p.slug, p.priority, p.leetcode_tag, p.description) for p in CANONICAL_PATTERNS],
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
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on any exception.

    Used for multi-statement writes - importing 4,000 problems should not leave
    half of them behind when the network drops at row 2,000.

    Repository methods call save() so a single write is one call; inside this
    block save() becomes a no-op and the whole body commits once at the end.
    Without that, a rollback could only undo statements since the last
    repository call, which is not what "roll back on any exception" means.
    """
    depth = _open_transactions.get(id(connection), 0)
    _open_transactions[id(connection)] = depth + 1
    try:
        yield connection
    except Exception:
        _set_depth(connection, depth)
        if depth == 0:
            connection.rollback()
        raise
    else:
        _set_depth(connection, depth)
        if depth == 0:
            connection.commit()


def save(connection: sqlite3.Connection) -> None:
    """Commit, unless a transaction() block is managing the boundary.

    Repositories call this instead of commit() so that both usage styles work:
    one write is one call, and a batch is atomic.
    """
    if not _open_transactions.get(id(connection)):
        connection.commit()


# sqlite3.Connection has no __dict__, so the nesting depth cannot live on the
# object. Keyed by id() and always removed at depth 0, so a closed connection
# leaves nothing behind.
_open_transactions: dict[int, int] = {}


def _set_depth(connection: sqlite3.Connection, depth: int) -> None:
    if depth:
        _open_transactions[id(connection)] = depth
    else:
        _open_transactions.pop(id(connection), None)


def open_database(path: Path | str) -> sqlite3.Connection:
    """Connect and initialise in one call. What application code uses."""
    connection = connect(path)
    initialize(connection)
    return connection
