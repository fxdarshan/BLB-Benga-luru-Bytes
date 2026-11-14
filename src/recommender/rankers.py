"""Creates the ranker for the configured LLM provider."""

from __future__ import annotations

from recommender.config import Settings
from recommender.service import Ranker


def make_ranker(settings: Settings) -> Ranker | None:
    """Return a ranker, or None when the provider's API key isn't set."""
    if settings.llm_api_key is None:
        return None
    args = (
        settings.llm_api_key,
        settings.llm_model,
        settings.llm_effort,
        settings.llm_timeout_seconds,
    )
    if settings.llm_provider == "groq":
        from recommender.groq_llm import GroqRanker

        return GroqRanker.from_settings(*args, settings.llm_fallback_model)
    from recommender.claude_llm import ClaudeRanker

    return ClaudeRanker.from_settings(*args)
