"""Configuration loading.

Everything the app needs from the environment is read here, once, into a frozen
Config. Nothing else reads os.environ.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_MODEL_REASONING = "gemini-2.5-pro"
DEFAULT_MODEL_FAST = "gemini-2.5-flash"
DEFAULT_DATABASE_PATH = "data/coach.db"

ModelRole = Literal["reasoning", "fast"]


class ConfigError(Exception):
    """Raised when configuration is missing or unusable."""


@dataclass(frozen=True)
class Config:
    gemini_api_key: str
    model_reasoning: str
    model_fast: str
    leetcode_session: str | None
    database_path: Path

    def model_for(self, role: ModelRole) -> str:
        """The model name to use for a given role.

        Roles exist because the free tier allows far fewer requests per day on the
        reasoning model. Callers pick a role; config decides the model.
        """
        if role == "reasoning":
            return self.model_reasoning
        if role == "fast":
            return self.model_fast
        raise ConfigError(f"Unknown model role: {role!r}. Expected 'reasoning' or 'fast'.")


def _optional(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def load_config(use_dotenv: bool = True, *, require_api_key: bool = True) -> Config:
    """Read configuration from the environment, loading .env first by default.

    Tests pass use_dotenv=False so a developer's real .env can never leak into a
    test run and make a failing test pass.

    require_api_key=False is for commands that never call a model - setting up
    the database should not demand a key it will not use.
    """
    if use_dotenv:
        from dotenv import load_dotenv

        load_dotenv()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key and require_api_key:
        raise ConfigError(
            "GEMINI_API_KEY is not set.\n"
            "\n"
            "Get a free key at https://aistudio.google.com/apikey, then:\n"
            "  cp .env.example .env\n"
            "and paste the key into .env as GEMINI_API_KEY=your-key-here"
        )

    return Config(
        gemini_api_key=api_key,
        model_reasoning=_optional("GEMINI_MODEL_REASONING", DEFAULT_MODEL_REASONING),
        model_fast=_optional("GEMINI_MODEL_FAST", DEFAULT_MODEL_FAST),
        leetcode_session=os.environ.get("LEETCODE_SESSION", "").strip() or None,
        database_path=Path(_optional("DATABASE_PATH", DEFAULT_DATABASE_PATH)),
    )
