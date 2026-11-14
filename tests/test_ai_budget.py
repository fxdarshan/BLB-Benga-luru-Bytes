"""Tests for the instant shortlist, shared LLM calls and the daily token cap in the service."""

from __future__ import annotations

import threading
import time

import pytest

from conftest import make_repository, make_restaurant
from fakes import FakeRanker, ranking_json
from recommender.candidates import InvalidPreferencesError
from recommender.llm import CallDetails, LLMUnavailable
from recommender.models import Preferences
from recommender.service import (
    FAILURE_DAILY_BUDGET,
    NOTICE_DAILY_BUDGET,
    RecommendationService,
)

SEARCH = Preferences(area="MG Road")
RANKING = ranking_json(("R1", "Fits well."), ("R2", "A close second."))


def repository():
    return make_repository(
        make_restaurant("low", rating=3.6, votes=1000),
        make_restaurant("high", rating=4.8, votes=1000),
        make_restaurant("mid", rating=4.2, votes=1000),
    )


class SlowRanker(FakeRanker):
    """Holds each call until released, so a test can start a second search meanwhile."""

    def __init__(self, text):
        super().__init__(text)
        self.started = threading.Event()
        self.release = threading.Event()

    def rank(self, system, user_message):
        self.started.set()
        assert self.release.wait(5)
        return super().rank(system, user_message)


def test_shortlist_ranks_by_score_at_once_without_the_llm():
    ranker = FakeRanker(RANKING)
    service = RecommendationService(repository(), ranker)
    result = service.shortlist(SEARCH)
    assert ranker.calls == []
    assert [r.candidate.restaurant.restaurant_id for r in result.results] == ["high", "mid", "low"]
    assert (result.ai_ranked, result.notice, result.failure_reason) == (False, None, None)
    assert all(r.explanation is None for r in result.results)
    # It leaves the cache alone, so the AI's ranking of the same search still happens.
    assert service.is_cached(SEARCH) is False


def test_shortlist_respects_the_result_limit_and_rejects_unknown_areas():
    many = [make_restaurant(f"r{i:02}") for i in range(12)]
    service = RecommendationService(make_repository(*many), max_results=3)
    assert len(service.shortlist(SEARCH).results) == 3
    with pytest.raises(InvalidPreferencesError):
        service.shortlist(Preferences(area="Nowhere"))


def test_identical_searches_running_together_share_one_llm_call():
    ranker = SlowRanker(RANKING)
    service = RecommendationService(repository(), ranker)
    results = {}

    def search(name):
        results[name] = service.recommend(SEARCH)

    first = threading.Thread(target=search, args=("first",))
    first.start()
    assert ranker.started.wait(5)
    second = threading.Thread(target=search, args=("second",))
    second.start()
    time.sleep(0.2)  # let the second search reach the wait
    ranker.release.set()
    first.join(5)
    second.join(5)

    assert len(ranker.calls) == 1
    assert results["first"].ai_ranked and results["second"].ai_ranked
    assert results["first"].diagnostics.cache_hit is False
    # The shared result made no call of its own.
    assert results["second"].diagnostics.cache_hit is True
    assert service._flights == {}


def test_a_shared_failure_is_not_cached():
    ranker = FakeRanker(error=LLMUnavailable("rate_limited"))
    service = RecommendationService(repository(), ranker)
    assert service.recommend(SEARCH).failure_reason == "rate_limited"
    assert service.is_cached(SEARCH) is False
    service.recommend(SEARCH)
    assert len(ranker.calls) == 2


def test_daily_token_cap_falls_back_to_score_order_until_utc_midnight():
    now = [1_794_600_000.0]  # 2026-11-13 20:00 UTC
    ranker = FakeRanker(RANKING)  # 3,000 + 800 tokens a call
    service = RecommendationService(
        repository(), ranker, daily_token_limit=5000, clock=lambda: now[0]
    )

    assert service.recommend(SEARCH, use_cache=False).ai_ranked
    assert service.tokens_used_today() == 3800
    # Under the cap when it starts, so this call is made.
    assert service.recommend(SEARCH, use_cache=False).ai_ranked
    assert service.tokens_used_today() == 7600

    capped = service.recommend(SEARCH, use_cache=False)
    assert capped.ai_ranked is False
    assert capped.failure_reason == FAILURE_DAILY_BUDGET
    assert capped.notice == NOTICE_DAILY_BUDGET
    assert [r.candidate.restaurant.restaurant_id for r in capped.results] == ["high", "mid", "low"]
    assert len(ranker.calls) == 2

    now[0] += 4 * 3600  # past midnight UTC
    assert service.tokens_used_today() == 0
    assert service.recommend(SEARCH, use_cache=False).ai_ranked
    assert len(ranker.calls) == 3


def test_failed_calls_count_towards_the_cap():
    details = CallDetails(usage={"input_tokens": 100, "output_tokens": 50})
    ranker = FakeRanker(error=LLMUnavailable("invalid_response", details))
    service = RecommendationService(repository(), ranker, daily_token_limit=1000)
    service.recommend(SEARCH)
    assert service.tokens_used_today() == 150


def test_no_cap_by_default():
    ranker = FakeRanker(RANKING)
    service = RecommendationService(repository(), ranker)
    for _ in range(3):
        assert service.recommend(SEARCH, use_cache=False).ai_ranked
    assert service.daily_token_limit == 0
    assert service.tokens_used_today() == 3 * 3800
