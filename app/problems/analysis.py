"""Problem analysis.

Fetches a problem, has the model understand it, finds conceptually similar prior
work, and saves the result. An application service, so the CLI, the API, and the
scheduler all get the same behaviour.

Two model calls, both on the reasoning tier because this is what the user learns
from and it is worth the scarce quota:

1. An agentic pass that reads the problem and produces the structured analysis.
   The model decides which tools to call - fetch the problem, search prior
   analyses for context - rather than following a fixed sequence.
2. A judgement pass over retrieved candidates, deciding which are genuinely
   similar rather than merely sharing keywords.

Editorial solutions are never fetched. The goal is teaching recognition, and
handing the model someone else's solution turns it into a summariser.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.agent.loop import Agent
from app.agent.registry import ToolRegistry
from app.agent.tools import build_registry
from app.llm.base import LLMProvider
from app.problems.leetcode import LeetCodeClient, LeetCodeError, slug_from_url
from app.schemas import ProblemAnalysis, SimilarityJudgement, SimilarityJudgements
from app.storage.db import Connection
from app.storage.repositories import PatternRepository, ProblemRepository

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """The analysis could not be produced, and no partial result was saved."""


# Enough turns to fetch the problem, look for prior work, and answer. Tight on
# purpose: every turn is a request against a small daily quota.
MAX_ITERATIONS = 6

# How many candidates the model judges. The corpus is a few thousand problems,
# so a wide set is affordable and recall matters more than precision here -
# Python retrieves generously, the model discards.
SIMILARITY_CANDIDATES = 20

RESEARCH_SYSTEM_PROMPT = """You are a data structures and algorithms coach.

Your job is to help someone learn to RECOGNISE patterns, not to hand them a
solution. The most valuable thing you produce is the set of clues that would let
them spot this pattern in a problem they have never seen.

Read the actual problem before saying anything about it - call
get_leetcode_problem. If search_problems is available, use it to see whether
similar problems have already been analysed, so your explanation can build on
what is already known.

Never reproduce or summarise an editorial solution. Explain the reasoning that
leads to the approach.

When you have what you need, produce the analysis."""

SIMILARITY_SYSTEM_PROMPT = """You judge whether DSA problems are CONCEPTUALLY
similar - whether solving one teaches you something that transfers to the other.

Sharing a data structure is not similarity. Two problems that both use a hash map
are not similar unless the insight transfers. Two problems that look different but
turn on the same realisation ARE similar.

Be strict. A short list of genuine matches is far more useful than a long list of
loose ones."""


@dataclass
class AnalysisResult:
    """A completed analysis, plus how it was produced."""

    slug: str
    title: str
    url: str
    analysis: ProblemAnalysis
    similar: list[SimilarityJudgement] = field(default_factory=list)
    pattern_matched: str | None = None
    tool_calls: int = 0
    reanalysed: bool = False


class ProblemAnalyser:
    def __init__(
        self,
        connection: Connection,
        provider: LLMProvider,
        client: LeetCodeClient | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.db = connection
        self.provider = provider
        self.client = client or LeetCodeClient()
        self.registry = registry or build_registry(client=self.client, connection=connection)
        self.problems = ProblemRepository(connection)
        self.patterns = PatternRepository(connection)

    def analyse(self, url_or_slug: str) -> AnalysisResult:
        slug = slug_from_url(url_or_slug)

        # Fetched directly rather than relying on the agent's tool call, because
        # the record has to exist before anything can be saved against it - and
        # a paid-only or missing problem should fail here, plainly, rather than
        # after spending a model call.
        problem = self.client.get_problem(slug)
        if not problem.content:
            raise LeetCodeError(
                f"{problem.title!r} has no readable description, so there is nothing to analyse."
            )

        existing = self.problems.by_slug(slug)
        reanalysed = existing is not None and existing["analysis"] is not None

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

        analysis, tool_calls = self._produce_analysis(problem.title, slug, problem.content)
        similar = self._judge_similar(slug, analysis)

        self.problems.save_analysis(problem_id, analysis.model_dump(mode="json"))
        pattern_matched = self._apply_pattern(problem_id, analysis.pattern)

        return AnalysisResult(
            slug=slug,
            title=problem.title,
            url=problem.url,
            analysis=analysis,
            similar=similar,
            pattern_matched=pattern_matched,
            tool_calls=tool_calls,
            reanalysed=reanalysed,
        )

    def _produce_analysis(
        self, title: str, slug: str, statement: str
    ) -> tuple[ProblemAnalysis, int]:
        """Let the agent gather what it needs, then produce a validated analysis.

        Two steps rather than one: tool calling and schema-constrained output are
        separate provider capabilities, and asking for both at once makes models
        drop one. The agent gathers context; a second call shapes it.
        """
        agent = Agent(
            self.provider,
            self.registry,
            system=RESEARCH_SYSTEM_PROMPT,
            role="reasoning",
            max_iterations=MAX_ITERATIONS,
        )
        gathered = agent.run(
            f"Analyse the LeetCode problem {title!r} (slug: {slug}). "
            f"Read the problem, then explain what pattern it tests and how to "
            f"recognise that pattern in future problems."
        )

        if gathered.hit_iteration_cap or gathered.hit_repetition_guard:
            # The loop bailed out, so answer is a filler message rather than an
            # analysis. Shaping that into the schema would produce a confident
            # fabrication, which is worse than admitting the run failed.
            raise AnalysisError(
                f"The model did not finish analysing {title!r} - it kept asking for "
                f"tools without reaching a conclusion. Try again."
            )

        analysis = self.provider.generate_structured(
            # The problem statement is included so the structuring call always has
            # the source material, not only the model's own prose about it.
            f"Turn this analysis of {title!r} into the required structure. "
            f"Keep the recognition clues concrete and transferable.\n\n"
            f"The problem:\n{statement}\n\n"
            f"The analysis:\n{gathered.answer}",
            ProblemAnalysis,
            role="reasoning",
            system=RESEARCH_SYSTEM_PROMPT,
        )
        return analysis, len(gathered.tool_calls)

    def _judge_similar(self, slug: str, analysis: ProblemAnalysis) -> list[SimilarityJudgement]:
        """Retrieve candidates in Python, let the model judge which are similar.

        Skipped entirely when there is no prior analysis to compare against,
        rather than spending a model call to be told nothing matches.
        """
        candidates = [
            row
            for row in self.problems.search(
                text=f"{analysis.pattern} {analysis.key_insight}",
                analysed_only=True,
                # One extra, because the problem just analysed is itself a strong
                # match and is filtered out below. Without it a re-analysis gets
                # nineteen candidates while a first analysis gets twenty.
                limit=SIMILARITY_CANDIDATES + 1,
            )
            if row["slug"] != slug
        ][:SIMILARITY_CANDIDATES]
        if not candidates:
            return []

        listed = "\n".join(f"- {row['slug']}: {row['title']}" for row in candidates)
        verdict = self.provider.generate_structured(
            f"A problem was just analysed as testing {analysis.pattern}.\n"
            f"Its key insight: {analysis.key_insight}\n"
            f"\n"
            f"Which of these previously analysed problems are conceptually similar?\n"
            f"{listed}\n"
            f"\n"
            f"Judge every candidate. Use the exact slugs given.",
            SimilarityJudgements,
            role="reasoning",
            system=SIMILARITY_SYSTEM_PROMPT,
        )

        known = {row["slug"] for row in candidates}
        # Models invent slugs. Dropping unknown ones is better than surfacing a
        # link the user cannot follow.
        return [j for j in verdict.judgements if j.is_similar and j.problem_slug in known]

    def _apply_pattern(self, problem_id: int, pattern_name: str) -> str | None:
        """Store the model's pattern judgement as authoritative.

        This overrides whatever the tag mapping decided, and records that an LLM
        decided it, so mixed provenance stays visible.

        The model answers in prose, so the name may not match the taxonomy
        exactly; PatternRepository.resolve handles the spellings worth accepting.

        An unmatched name leaves the tag-derived pattern in place rather than
        inventing a row: the taxonomy is a controlled vocabulary, and a model
        coining terms into it would make pattern statistics meaningless. The
        analysis text still records what the model actually said.
        """
        row = self.patterns.resolve(pattern_name)
        if row is None:
            logger.info(
                "Model called this %r, which is not in the taxonomy; keeping the tag pattern",
                pattern_name,
            )
            return None

        self.problems.set_primary_pattern(problem_id, int(row["id"]), source="llm")
        return str(row["name"])
