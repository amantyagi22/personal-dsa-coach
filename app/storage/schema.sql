-- The database schema.
--
-- Plain SQL rather than an ORM's model classes: the schema is the thing later
-- milestones reason about, and it is easier to check a table definition than to
-- infer one from decorators.
--
-- Everything here is idempotent. Running it against an existing database is a
-- no-op, so initialisation can be called on every command without a migration
-- framework - which a single-user local file does not need.

PRAGMA foreign_keys = ON;

-- One local user. No authentication, no multi-tenancy: the brief is explicit
-- that this is a personal tool. The table exists so that attempts, reviews, and
-- recommendations have an owner, keeping the schema honest if that ever changes.
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY,
    leetcode_username   TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The canonical DSA vocabulary, as rows rather than a Python enum, so the
-- taxonomy can be edited without a code change.
--
-- priority orders the tag-to-pattern mapping. LeetCode's topic tags are an
-- unordered bag: a problem tagged "Hash Table, String, Sliding Window" does not
-- say which is primary. The lowest priority number wins, so the specific
-- (Sliding Window) beats the generic (String).
CREATE TABLE IF NOT EXISTS patterns (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    slug          TEXT NOT NULL UNIQUE,
    description   TEXT NOT NULL DEFAULT '',
    priority      INTEGER NOT NULL DEFAULT 500
);

CREATE INDEX IF NOT EXISTS idx_patterns_priority ON patterns(priority);

-- The LeetCode tags that map to each pattern.
--
-- A separate table rather than a column because the relationship is genuinely
-- one-to-many: LeetCode uses 175 distinct tags, and several mean the same thing
-- to a learner - "Graph Theory", "Graph", and "Bipartite Graph" are all graph
-- problems. Surveyed against the live catalogue rather than guessed.
CREATE TABLE IF NOT EXISTS pattern_tags (
    tag         TEXT PRIMARY KEY,
    pattern_id  INTEGER NOT NULL REFERENCES patterns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pattern_tags_pattern ON pattern_tags(pattern_id);

CREATE TABLE IF NOT EXISTS problems (
    id                INTEGER PRIMARY KEY,
    slug              TEXT NOT NULL UNIQUE,
    number            TEXT NOT NULL DEFAULT '',
    title             TEXT NOT NULL,
    difficulty        TEXT NOT NULL DEFAULT 'Unknown',
    url               TEXT NOT NULL DEFAULT '',
    content           TEXT NOT NULL DEFAULT '',
    topic_tags        TEXT NOT NULL DEFAULT '',

    -- Paid problems cannot be read or solved without a subscription, so they are
    -- excluded from recommendations rather than silently recommended and useless.
    is_paid_only      INTEGER NOT NULL DEFAULT 0,

    -- The primary pattern, and how it was decided. 'tags' is the deterministic
    -- mapping applied to the whole catalogue at no cost; 'llm' is Gemini's
    -- judgement during analyze, which overrides it and is authoritative after.
    -- Recording which produced the value keeps mixed provenance visible.
    primary_pattern_id INTEGER REFERENCES patterns(id) ON DELETE SET NULL,
    pattern_source     TEXT CHECK (pattern_source IN ('tags', 'llm')),

    analysis          TEXT,
    analyzed_at       TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_problems_pattern ON problems(primary_pattern_id);
CREATE INDEX IF NOT EXISTS idx_problems_difficulty ON problems(difficulty);
CREATE INDEX IF NOT EXISTS idx_problems_paid ON problems(is_paid_only);

-- A problem can exercise several patterns even though exactly one is primary.
-- Kept separate so "show me every problem touching Binary Search" stays possible
-- without losing the single primary that scoring depends on.
CREATE TABLE IF NOT EXISTS problem_patterns (
    problem_id  INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    pattern_id  INTEGER NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (problem_id, pattern_id)
);

CREATE INDEX IF NOT EXISTS idx_problem_patterns_pattern ON problem_patterns(pattern_id);

-- The heart of the learning model.
--
-- failure_type is nullable and holds one of the five outcomes, or 'unknown'.
-- Sync can only ever infer 'too_slow' and 'solved'; the recognition failures
-- (no_pattern, no_algorithm) usually produce zero submissions, because the user
-- never got far enough to submit. Only the user can supply those.
--
-- source distinguishes what was imported from what was self-reported, so an
-- inferred outcome is never mistaken for a considered one.
CREATE TABLE IF NOT EXISTS attempts (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_id    INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    attempted_at  TEXT NOT NULL DEFAULT (datetime('now')),
    solved        INTEGER NOT NULL DEFAULT 0,
    failure_type  TEXT CHECK (
        failure_type IN (
            'no_pattern', 'no_algorithm', 'implementation',
            'too_slow', 'solved', 'unknown'
        )
    ),
    source        TEXT NOT NULL DEFAULT 'self_reported'
                  CHECK (source IN ('leetcode', 'self_reported')),
    time_spent_minutes INTEGER,
    notes         TEXT NOT NULL DEFAULT '',

    -- The LeetCode submission this came from, when it came from LeetCode.
    -- UNIQUE so re-running sync updates rather than duplicating.
    external_id   TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_attempts_problem ON attempts(problem_id);
CREATE INDEX IF NOT EXISTS idx_attempts_date ON attempts(attempted_at);
CREATE INDEX IF NOT EXISTS idx_attempts_failure_type ON attempts(failure_type);

CREATE TABLE IF NOT EXISTS recommendations (
    id                INTEGER PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_id        INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    recommended_for   TEXT NOT NULL,
    score             REAL NOT NULL DEFAULT 0,

    -- The per-component breakdown, as JSON. Stored so a past recommendation can
    -- still be explained after the weights have been retuned - otherwise "why
    -- did it pick this?" becomes unanswerable the moment configuration changes.
    score_breakdown   TEXT NOT NULL DEFAULT '{}',
    reasoning         TEXT NOT NULL DEFAULT '',
    accepted          INTEGER,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),

    -- One recommendation per day. Re-running `today` shows the same problem
    -- rather than quietly picking a new one each time it is called.
    UNIQUE (user_id, recommended_for)
);

CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_id      INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    due_at          TEXT NOT NULL,
    interval_days   INTEGER NOT NULL DEFAULT 1,
    last_reviewed_at TEXT,
    last_score      INTEGER,
    review_count    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),

    -- One review schedule per problem: a second row would mean two competing
    -- due dates for the same thing.
    UNIQUE (user_id, problem_id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_due ON reviews(due_at);

-- Full-text search over problem text.
--
-- FTS5 ships inside Python's standard library sqlite3, so this costs no
-- dependency, no service, and no API calls. It is the retrieval half of finding
-- similar problems; the LLM judges which of the retrieved candidates are
-- genuinely similar. At a few thousand problems this beats a vector index on
-- every axis that matters here.
--
-- content='problems' makes this an external-content table: the text lives once,
-- in problems, and FTS5 stores only the index.
CREATE VIRTUAL TABLE IF NOT EXISTS problems_fts USING fts5(
    title,
    content,
    topic_tags,
    content='problems',
    content_rowid='id'
);

-- Triggers keep the index in sync. Doing this in SQL rather than in the
-- repository means a write from anywhere - a later milestone, a migration, a
-- manual fix - cannot leave the index stale.
CREATE TRIGGER IF NOT EXISTS problems_fts_insert AFTER INSERT ON problems BEGIN
    INSERT INTO problems_fts(rowid, title, content, topic_tags)
    VALUES (new.id, new.title, new.content, new.topic_tags);
END;

CREATE TRIGGER IF NOT EXISTS problems_fts_delete AFTER DELETE ON problems BEGIN
    INSERT INTO problems_fts(problems_fts, rowid, title, content, topic_tags)
    VALUES ('delete', old.id, old.title, old.content, old.topic_tags);
END;

CREATE TRIGGER IF NOT EXISTS problems_fts_update AFTER UPDATE ON problems BEGIN
    INSERT INTO problems_fts(problems_fts, rowid, title, content, topic_tags)
    VALUES ('delete', old.id, old.title, old.content, old.topic_tags);
    INSERT INTO problems_fts(rowid, title, content, topic_tags)
    VALUES (new.id, new.title, new.content, new.topic_tags);
END;
