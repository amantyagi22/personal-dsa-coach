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
    """The LLM's breakdown of one problem."""

    pattern: str = Field(description="The single primary DSA pattern this problem tests")
    difficulty: Difficulty
    key_insight: str = Field(description="The one realisation that unlocks the problem")
    algorithm: str = Field(description="The approach, in plain prose - not code")
    time_complexity: str
    space_complexity: str
    recognition_clues: list[str] = Field(
        description="Signals in the problem statement that point to this pattern next time"
    )
    common_mistakes: list[str]


class SimilarityJudgement(BaseModel):
    """Whether two problems are conceptually similar, and why."""

    problem_slug: str
    is_similar: bool
    reason: str


class ReviewGrade(BaseModel):
    """The LLM's assessment of a free-text review answer."""

    is_correct: bool
    score: int = Field(ge=0, le=100)
    feedback: str
    missed_points: list[str] = Field(default_factory=list)
