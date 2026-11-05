"""Orchestrates one search. This module has no Streamlit imports, so other clients can reuse it."""

from __future__ import annotations

from typing import Any

from recommender.candidates import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MIN_RESULTS,
    select_candidates,
)
from recommender.models import Diagnostics, Preferences, RecommendationResult
from recommender.repository import RestaurantRepository

NOTICE_NOT_AI_RANKED = (
    "AI explanations are unavailable right now, so these results are ranked by score."
)
FAILURE_NOT_CONFIGURED = "llm_not_configured"


class RecommendationService:
    def __init__(
        self,
        repository: RestaurantRepository,
        llm_client: Any | None = None,
        *,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        max_results: int = DEFAULT_MIN_RESULTS,
    ) -> None:
        self.repository = repository
        self.llm_client = llm_client  # Used from Phase 4.
        self.max_candidates = max_candidates
        self.max_results = max_results

    def recommend(self, preferences: Preferences) -> RecommendationResult:
        """Return the best matches for a search, or no results if nothing matches.

        Raises `InvalidPreferencesError` for an area or cuisine that isn't in the data.
        """
        selection = select_candidates(
            preferences,
            self.repository,
            max_candidates=self.max_candidates,
            min_results=self.max_results,
        )
        diagnostics = Diagnostics(
            applied_min_rating=selection.applied_min_rating,
            applied_budgets=selection.applied_budgets,
            total_matches=selection.total_matches,
        )
        if not selection.candidates:
            return RecommendationResult(
                results=[], relaxations=selection.relaxations, diagnostics=diagnostics
            )
        return RecommendationResult(
            results=selection.candidates[: self.max_results],
            relaxations=selection.relaxations,
            ai_ranked=False,
            notice=NOTICE_NOT_AI_RANKED,
            failure_reason=FAILURE_NOT_CONFIGURED,
            diagnostics=diagnostics,
        )
