"""Pydantic models - the single source of truth for structured data.

Every schema the LLM is asked to fill, and every shape passed between layers,
is defined here once. Tool parameter schemas are generated from these models
(model_json_schema()) rather than hand-written, so the schema advertised to the
model and the validation applied to its reply can never drift apart.

Milestone 1 defines the vocabulary the later milestones fill in. Only
FailureType and Difficulty are load-bearing today; the rest exist so that no
later ticket has to invent a second definition of the same concept.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Difficulty(StrEnum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"


class FailureType(StrEnum):
    """How an attempt went.

    The distinction this whole coach is built on: failing to *recognise* a pattern
    and failing to *implement* it need completely different next problems.

    Sync can only ever infer TOO_SLOW and SOLVED. A, B and C need you to say so,
    because A and B usually produce no submission at all.
    """

    NO_PATTERN = "no_pattern"  # A - couldn't identify the pattern
    NO_ALGORITHM = "no_algorithm"  # B - knew the pattern, couldn't derive the algorithm
    IMPLEMENTATION = "implementation"  # C - knew the approach, code failed
    TOO_SLOW = "too_slow"  # D - correct but too slow
    SOLVED = "solved"  # E - correct
    UNKNOWN = "unknown"  # not classified; excluded from failure-driven scoring


class ProblemAnalysis(BaseModel):
    """The LLM's breakdown of one problem.

    Field order is deliberate: Gemini fills a schema in order, so the pattern and
    the reasoning for it come before the algorithm. Deciding what the problem
    *is* before explaining how to solve it produces better classifications than
    the reverse.

    recognition_clues is the point of the whole product. Everything else explains
    one problem; the clues are what transfer to the next one.
    """

    pattern: str = Field(description="The single primary DSA pattern this problem tests")
    pattern_reasoning: str = Field(
        description=(
            "Why this pattern applies to this problem, in one or two sentences. "
            "Make it arguable, not asserted."
        )
    )
    secondary_techniques: list[str] = Field(
        default_factory=list,
        description="Other techniques the problem combines, beyond the primary pattern",
    )
    difficulty: Difficulty
    key_insight: str = Field(description="The one realisation that unlocks the problem")
    algorithm: list[str] = Field(
        description="The approach as ordered steps, in plain prose - never code"
    )
    time_complexity: str
    space_complexity: str
    recognition_clues: list[str] = Field(
        description=(
            "Concrete signals in the problem statement that point to this pattern. "
            "Written so they would help on an unseen problem, not just this one."
        )
    )
    common_mistakes: list[str]


class SimilarityJudgement(BaseModel):
    """Whether one candidate problem is conceptually similar, and why."""

    problem_slug: str
    is_similar: bool
    reason: str = Field(description="What the two problems share, or why they only look alike")


class SimilarityJudgements(BaseModel):
    """The model's verdict on a whole candidate set.

    A wrapper because Gemini's schema enforcement needs an object at the top
    level, not a bare array.
    """

    judgements: list[SimilarityJudgement] = Field(default_factory=list)


class ReviewGrade(BaseModel):
    """The LLM's assessment of a free-text review answer."""

    is_correct: bool
    score: int = Field(ge=0, le=100)
    feedback: str
    missed_points: list[str] = Field(default_factory=list)
