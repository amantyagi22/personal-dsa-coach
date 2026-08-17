"""Command-line interface.

A thin adapter. Every command parses arguments, calls a service, and prints the
result - no business logic lives here, because the API and the scheduler will
call the same services and must not disagree with the CLI.

Milestone 1 has one command. `ask` is a plain passthrough to the provider,
proving config, credentials and the provider chain work end to end. Milestone 6
upgrades it in place into a read-only agent.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.config import ConfigError, load_config
from app.llm.base import LLMError, LLMProvider, RateLimitError
from app.llm.gemini import GeminiProvider

ASK_SYSTEM_PROMPT = (
    "You are a data structures and algorithms coach. Explain clearly and concisely, "
    "the way a good senior engineer would to a colleague. Prefer the core intuition "
    "over exhaustive detail. Use plain prose, not bullet-point sprawl."
)


def cmd_ask(question: str, provider: LLMProvider) -> str:
    return provider.generate(question, role="fast", system=ASK_SYSTEM_PROMPT)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="A coach that tells you which one problem to solve today, and why.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show which model each call uses"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask = subparsers.add_parser("ask", help="ask a DSA question")
    ask.add_argument("question", help="the question, in quotes")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    try:
        config = load_config()
        provider = GeminiProvider(config)

        if args.command == "ask":
            print(cmd_ask(args.question, provider))

    except ConfigError as exc:
        print(f"Configuration problem:\n\n{exc}", file=sys.stderr)
        return 1
    except RateLimitError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2
    except LLMError as exc:
        print(f"The model call failed: {exc}", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
