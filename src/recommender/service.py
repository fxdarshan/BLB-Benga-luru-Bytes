"""Orchestrates one search. This module has no Streamlit imports, so other clients can reuse it."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from cachetools import TTLCache

from recommender.candidates import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MIN_RESULTS,
    select_candidates,
)
from recommender.llm import CallDetails, LLMReply, LLMUnavailable
from recommender.models import (
    CandidateSelection,
    Diagnostics,
    Preferences,
    RankedResult,
    RecommendationResult,
)
from recommender.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_prompt
from recommender.repository import RestaurantRepository
from recommender.validation import validate_ranking

logger = logging.getLogger(__name__)
# One line per search, for measuring cost and failures. It never holds free text or keys.
search_logger = logging.getLogger("recommender.search")

NOTICE_NOT_AI_RANKED = (
    "AI explanations are unavailable right now, so these results are ranked by score."
)
NOTICE_DAILY_BUDGET = (
    "AI explanations are paused until tomorrow to keep within today's budget, so these results "
    "are ranked by score."
)
FAILURE_NOT_CONFIGURED = "llm_not_configured"
FAILURE_NO_VALID_RESULTS = "no_valid_results"
FAILURE_UNEXPECTED = "unexpected_error"
FAILURE_DAILY_BUDGET = "daily_budget"

CACHE_TTL_SECONDS = 3600
CACHE_MAX_ENTRIES = 500
# How long a search waits for an identical one already running before making its own call.
# Longer than one LLM call with its retry.
SHARED_WAIT_SECONDS = 120.0


class Ranker(Protocol):
    def rank(self, system: str, user_message: str) -> LLMReply: ...


@dataclass
class _Flight:
    """A search in progress, which identical searches wait for instead of calling the LLM."""

    done: threading.Event = field(default_factory=threading.Event)
    result: RecommendationResult | None = None


def preferences_key(preferences: Preferences) -> dict[str, Any]:
    """Normalise a search, so that searches meaning the same thing share a cache entry."""
    return {
        "area": preferences.area,
        "budget": preferences.budget,
        "cuisines": sorted(c.casefold() for c in preferences.cuisines),
        "dishes": sorted(d.casefold() for d in preferences.dishes),
        "min_rating": preferences.min_rating,
        "include_unrated": preferences.include_unrated,
        "additional": " ".join(preferences.additional.casefold().split()),
    }


def _short_hash(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class RecommendationService:
    """Runs searches. One instance should be shared, so that its cache is shared."""

    def __init__(
        self,
        repository: RestaurantRepository,
        llm_client: Ranker | None = None,
        *,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        max_results: int = DEFAULT_MIN_RESULTS,
        cache_ttl_seconds: float = CACHE_TTL_SECONDS,
        cache_max_entries: int = CACHE_MAX_ENTRIES,
        daily_token_limit: int = 0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repository = repository
        self.llm_client = llm_client
        self.max_candidates = max_candidates
        self.max_results = max_results
        # Tokens the LLM may use per UTC day. 0 means no cap.
        self.daily_token_limit = daily_token_limit
        self._clock = clock
        self._cache: TTLCache[str, RecommendationResult] = TTLCache(
            maxsize=cache_max_entries, ttl=cache_ttl_seconds
        )
        # TTLCache isn't thread-safe, and Streamlit runs each session in its own thread.
        self._cache_lock = threading.Lock()
        self._flights: dict[str, _Flight] = {}
        self._flights_lock = threading.Lock()
        self._budget_lock = threading.Lock()
        self._budget_day = ""
        self._tokens_today = 0

    def cache_key(self, preferences: Preferences) -> str:
        """Identify a search. Changing the data, model, effort or prompt gives a new key."""
        ranker = self.llm_client
        return _short_hash(
            {
                "preferences": preferences_key(preferences),
                "build_id": self.repository.metadata.build_id,
                "ranker": type(ranker).__name__,
                "model": getattr(ranker, "model", None),
                "effort": getattr(ranker, "effort", None),
                "prompt_version": PROMPT_VERSION,
                "limits": [self.max_candidates, self.max_results],
            }
        )

    def is_cached(self, preferences: Preferences) -> bool:
        """True if this search has an unexpired AI-ranked result in the cache."""
        key = self.cache_key(preferences)
        with self._cache_lock:
            return key in self._cache

    def recommend(
        self, preferences: Preferences, *, use_cache: bool = True
    ) -> RecommendationResult:
        """Return the best matches for a search, ranked by the LLM when it is available.

        Repeated searches come from the cache, unless `use_cache` is False. Raises
        `InvalidPreferencesError` for an area or cuisine that isn't in the data. Every LLM
        failure returns the score-ranked results instead, with a `failure_reason`.
        """
        start = time.perf_counter()
        key = self.cache_key(preferences)
        result = self._from_cache(key) if use_cache else None
        if result is None:
            # No lock is held here, so one slow LLM call never blocks other searches.
            result = self._search_once(key, preferences) if use_cache else self._search(preferences)
        self._log_search(key, result, time.perf_counter() - start)
        return result

    def shortlist(self, preferences: Preferences) -> RecommendationResult:
        """The best matches in score order, at once: no LLM call, no cache and no log line.

        The web page shows these while `recommend` has the LLM rank the same search. Raises
        `InvalidPreferencesError` as `recommend` does.
        """
        selection, base = self._select(preferences)
        results = [RankedResult(candidate=c) for c in selection.candidates[: self.max_results]]
        return RecommendationResult(
            results=results, relaxations=selection.relaxations, diagnostics=base
        )

    def tokens_used_today(self) -> int:
        """LLM tokens used so far this UTC day, counted only in this process."""
        with self._budget_lock:
            self._roll_budget_day()
            return self._tokens_today

    def _from_cache(self, key: str) -> RecommendationResult | None:
        with self._cache_lock:
            cached = self._cache.get(key)
        if cached is None:
            return None
        return dataclasses.replace(
            cached, diagnostics=dataclasses.replace(cached.diagnostics, cache_hit=True)
        )

    def _search_once(self, key: str, preferences: Preferences) -> RecommendationResult:
        """Run a search, unless an identical one is already running: then share its result.

        A shared result made no LLM call of its own, so it is marked as a cache hit. Only
        AI-ranked results are cached, so a temporary failure isn't repeated for an hour.
        """
        with self._flights_lock:
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = self._flights[key] = _Flight()
        if not leader:
            if flight.done.wait(SHARED_WAIT_SECONDS) and flight.result is not None:
                shared = flight.result
                return dataclasses.replace(
                    shared, diagnostics=dataclasses.replace(shared.diagnostics, cache_hit=True)
                )
            # The first search raised or took too long, so make this one's own call.
            return self._search(preferences)
        try:
            result = self._search(preferences)
            if result.ai_ranked:
                with self._cache_lock:
                    self._cache[key] = result
            flight.result = result
            return result
        finally:
            with self._flights_lock:
                self._flights.pop(key, None)
            flight.done.set()

    def _select(self, preferences: Preferences) -> tuple[CandidateSelection, Diagnostics]:
        selection = select_candidates(
            preferences,
            self.repository,
            max_candidates=self.max_candidates,
            min_results=self.max_results,
        )
        base = Diagnostics(
            applied_min_rating=selection.applied_min_rating,
            applied_budgets=selection.applied_budgets,
            total_matches=selection.total_matches,
        )
        return selection, base

    def _roll_budget_day(self) -> None:
        """Start a new count at UTC midnight. Call with the budget lock held."""
        today = time.strftime("%Y-%m-%d", time.gmtime(self._clock()))
        if today != self._budget_day:
            self._budget_day, self._tokens_today = today, 0

    def _within_budget(self) -> bool:
        if self.daily_token_limit <= 0:
            return True
        with self._budget_lock:
            self._roll_budget_day()
            return self._tokens_today < self.daily_token_limit

    def _spend(self, call: CallDetails | None) -> None:
        usage = (call.usage if call else None) or {}
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        if tokens:
            with self._budget_lock:
                self._roll_budget_day()
                self._tokens_today += tokens

    def _search(self, preferences: Preferences) -> RecommendationResult:
        selection, base = self._select(preferences)
        if not selection.candidates:
            return RecommendationResult(
                results=[], relaxations=selection.relaxations, diagnostics=base
            )
        if self.llm_client is None:
            return self._score_ranked(selection, FAILURE_NOT_CONFIGURED, base)
        if not self._within_budget():
            return self._score_ranked(
                selection, FAILURE_DAILY_BUDGET, base, notice=NOTICE_DAILY_BUDGET
            )

        prompt = build_prompt(preferences, selection, self.repository.metadata)
        sent = tuple(c.restaurant.restaurant_id for c in prompt.candidates_by_alias.values())
        try:
            reply = self.llm_client.rank(SYSTEM_PROMPT, prompt.user_message)
        except LLMUnavailable as error:
            self._spend(error.details)
            details = self._with_call(base, sent, error.details)
            return self._score_ranked(selection, error.reason, details)
        except Exception as error:  # noqa: BLE001 - a search must never show a stack trace
            logger.exception("Unexpected error during LLM ranking: %s", type(error).__name__)
            return self._score_ranked(selection, FAILURE_UNEXPECTED, self._with_call(base, sent))

        self._spend(reply.details)
        validated = validate_ranking(
            reply.ranking,
            prompt.candidates_by_alias,
            max_results=self.max_results,
            has_free_text=bool(preferences.additional),
            reviews_by_alias=prompt.reviews_by_alias,
        )
        details = self._with_call(base, sent, reply.details, dropped=validated.dropped)
        if not validated.results:
            return self._score_ranked(selection, FAILURE_NO_VALID_RESULTS, details)
        return RecommendationResult(
            results=validated.results,
            relaxations=selection.relaxations,
            summary=validated.summary,
            ai_ranked=True,
            diagnostics=details,
        )

    def _log_search(self, key: str, result: RecommendationResult, seconds: float) -> None:
        """Write one line per search. A logging failure never breaks the search."""
        try:
            d = result.diagnostics
            # A cache hit made no LLM call, so its tokens and LLM time are left out, so that
            # adding up the log lines gives the real cost.
            usage = {} if d.cache_hit else d.usage or {}
            llm_seconds = None if d.cache_hit or d.latency_seconds is None else d.latency_seconds
            record = {
                "search": key,
                "cache_hit": d.cache_hit,
                "ai_ranked": result.ai_ranked,
                "failure_reason": result.failure_reason,
                "matches": d.total_matches,
                "candidates_sent": len(d.candidates_sent),
                "results": len(result.results),
                "relaxations": [r.limit for r in result.relaxations],
                "latency_seconds": round(seconds, 3),
                "llm_seconds": None if llm_seconds is None else round(llm_seconds, 3),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "stop_reason": d.stop_reason,
                "model": d.served_model,
                "fallback_model_used": d.fallback_model_used,
                "retries": d.retry_count,
                "request_id": None if d.cache_hit else d.request_id,
            }
            search_logger.info("search %s", json.dumps(record, sort_keys=True))
        except Exception:  # noqa: BLE001
            logger.debug("Couldn't write the search log line", exc_info=True)

    @staticmethod
    def _with_call(
        base: Diagnostics,
        sent: tuple[str, ...],
        call: CallDetails | None = None,
        *,
        dropped: int = 0,
    ) -> Diagnostics:
        call = call or CallDetails()
        return Diagnostics(
            applied_min_rating=base.applied_min_rating,
            applied_budgets=base.applied_budgets,
            total_matches=base.total_matches,
            candidates_sent=sent,
            raw_llm_text=call.raw_text,
            usage=call.usage,
            stop_reason=call.stop_reason,
            served_model=call.served_model,
            fallback_model_used=call.fallback_model_used,
            latency_seconds=call.latency_seconds,
            retry_count=call.retry_count,
            request_id=call.request_id,
            results_dropped=dropped,
        )

    def _score_ranked(
        self,
        selection: CandidateSelection,
        reason: str,
        diagnostics: Diagnostics,
        *,
        notice: str = NOTICE_NOT_AI_RANKED,
    ) -> RecommendationResult:
        results = [RankedResult(candidate=c) for c in selection.candidates[: self.max_results]]
        return RecommendationResult(
            results=results,
            relaxations=selection.relaxations,
            ai_ranked=False,
            notice=notice,
            failure_reason=reason,
            diagnostics=diagnostics,
        )
