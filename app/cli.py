"""Command-line interface.

A thin adapter. Every command parses arguments, calls a service, and prints the
result - no business logic lives here, because the API and the scheduler will
call the same services and must not disagree with the CLI.

`ask` is a plain passthrough to the provider, proving config, credentials and the
provider chain work end to end. It is upgraded in place into a read-only agent
once the database exists.

`problem` is the first agentic command: the model decides to call a Python tool,
reads the result, and answers from it.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.agent.loop import Agent
from app.agent.registry import ToolRegistry
from app.agent.tools import build_registry
from app.config import Config, ConfigError, load_config
from app.llm.base import LLMError, LLMProvider, RateLimitError
from app.llm.gemini import GeminiProvider
from app.problems.catalogue import CatalogueSync
from app.problems.leetcode import LeetCodeClient, LeetCodeError
from app.storage.db import open_database
from app.storage.repositories import PatternRepository, ProblemRepository

logger = logging.getLogger(__name__)

ASK_SYSTEM_PROMPT = (
    "You are a data structures and algorithms coach. Explain clearly and concisely, "
    "the way a good senior engineer would to a colleague. Prefer the core intuition "
    "over exhaustive detail. Use plain prose, not bullet-point sprawl."
)

PROBLEM_SYSTEM_PROMPT = (
    "You are a data structures and algorithms coach.\n"
    "\n"
    "When asked about a specific LeetCode problem, call get_leetcode_problem to read "
    "the actual problem statement before saying anything about it. Never guess at what "
    "a problem asks - fetch it.\n"
    "\n"
    "Then summarise, in plain prose: what the problem asks, which DSA pattern it tests, "
    "and the one clue in the statement that points to that pattern. Do not give away the "
    "full solution - the point is to teach recognition."
)

# A single lookup and a summary. Deliberately tight: this command has a small job,
# and the cap is what stops a confused model spending the daily quota on it.
PROBLEM_MAX_ITERATIONS = 4


def cmd_ask(question: str, provider: LLMProvider) -> str:
    return provider.generate(question, role="fast", system=ASK_SYSTEM_PROMPT)


def cmd_sync_problems(config: Config, client: LeetCodeClient | None = None) -> str:
    connection = open_database(config.database_path)
    try:
        sync = CatalogueSync(connection, client=client)

        # Progress on stderr: a 4,000-problem import takes about a minute, and
        # silence for a minute reads as a hang.
        def progress(stored: int) -> None:
            print(f"  {stored} stored...", file=sys.stderr)

        return sync.run(on_progress=progress).summary()
    finally:
        connection.close()


def cmd_patterns(config: Config) -> str:
    """Show the local catalogue broken down by pattern.

    The way to see what sync actually produced without writing SQL.
    """
    connection = open_database(config.database_path)
    try:
        rows = connection.execute(
            """
            SELECT p.name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN pr.difficulty = 'Easy' THEN 1 ELSE 0 END) AS easy,
                   SUM(CASE WHEN pr.difficulty = 'Medium' THEN 1 ELSE 0 END) AS medium,
                   SUM(CASE WHEN pr.difficulty = 'Hard' THEN 1 ELSE 0 END) AS hard
              FROM problems pr
              JOIN patterns p ON p.id = pr.primary_pattern_id
             WHERE pr.is_paid_only = 0
             GROUP BY p.name
             ORDER BY total DESC
            """
        ).fetchall()
        total = ProblemRepository(connection).count()
    finally:
        connection.close()

    if not total:
        return "No problems stored yet. Run: python -m app.cli sync-problems"

    lines = [f"{total} problems stored, free problems by pattern:", ""]
    lines.append(f"{'Pattern':<24}{'Total':>7}{'Easy':>7}{'Medium':>8}{'Hard':>6}")
    lines.append("-" * 52)
    for row in rows:
        lines.append(
            f"{row['name']:<24}{row['total']:>7}{row['easy']:>7}{row['medium']:>8}{row['hard']:>6}"
        )
    return "\n".join(lines)


def cmd_db_init(config: Config) -> str:
    connection = open_database(config.database_path)
    try:
        problems = ProblemRepository(connection).count()
        patterns = len(PatternRepository(connection).all())
    finally:
        connection.close()

    return (
        f"Database ready at {config.database_path}\n"
        f"  {patterns} patterns seeded\n"
        f"  {problems} problems stored"
    )


def cmd_problem(slug: str, provider: LLMProvider, registry: ToolRegistry | None = None) -> str:
    agent = Agent(
        provider,
        registry or build_registry(),
        system=PROBLEM_SYSTEM_PROMPT,
        role="fast",
        max_iterations=PROBLEM_MAX_ITERATIONS,
    )
    result = agent.run(f"Tell me about the LeetCode problem: {slug}")
    logger.info(
        "Agent finished in %d iteration(s), %d tool call(s)",
        result.iterations,
        len(result.tool_calls),
    )
    return result.answer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="A coach that tells you which one problem to solve today, and why.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show debug detail as well as model names"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask = subparsers.add_parser("ask", help="ask a DSA question")
    ask.add_argument("question", help="the question, in quotes")

    problem = subparsers.add_parser(
        "problem", help="look up a LeetCode problem and say which pattern it tests"
    )
    problem.add_argument("slug", help="a problem slug such as two-sum, or its full URL")

    subparsers.add_parser("db-init", help="create the local database and seed the patterns")

    subparsers.add_parser(
        "sync-problems", help="download the LeetCode problem catalogue into the local database"
    )

    subparsers.add_parser("patterns", help="show what is in the local catalogue, by pattern")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Logs go to stderr so stdout stays pipeable - `ask ... > answer.txt` should
    # capture the answer and nothing else.
    #
    # Only our own loggers are turned up. Rooting this at INFO would also switch
    # on the Gemini SDK's per-request chatter, which buries the one line the user
    # actually wants (which model ran).
    logging.basicConfig(format="%(message)s", stream=sys.stderr)
    logging.getLogger("app").setLevel(logging.DEBUG if args.verbose else logging.INFO)

    try:
        # Commands that never call a model must not demand an API key.
        offline = {"db-init", "sync-problems", "patterns"}
        config = load_config(require_api_key=args.command not in offline)

        # The provider is built lazily. Commands that never call a model - db-init
        # today, more later - must not fail for want of an API key they do not use.
        if args.command == "db-init":
            print(cmd_db_init(config))
        elif args.command == "sync-problems":
            print(cmd_sync_problems(config))
        elif args.command == "patterns":
            print(cmd_patterns(config))
        elif args.command == "ask":
            print(cmd_ask(args.question, GeminiProvider(config)))
        elif args.command == "problem":
            print(cmd_problem(args.slug, GeminiProvider(config)))

    except ConfigError as exc:
        print(f"Configuration problem:\n\n{exc}", file=sys.stderr)
        return 1
    except RateLimitError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2
    except LLMError as exc:
        print(f"The model call failed: {exc}", file=sys.stderr)
        return 3
    except LeetCodeError as exc:
        # Reaches here only from commands that call LeetCode directly. Inside the
        # agent loop these are already turned into tool results the model can read.
        print(f"LeetCode request failed: {exc}", file=sys.stderr)
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
