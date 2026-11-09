import json
import logging
import threading
import time

import pytest

from conftest import make_repository, make_restaurant
from fakes import FakeRanker, ranking_json
from recommender import service as service_module
from recommender.llm import LLMUnavailable
from recommender.models import Preferences
from recommender.service import RecommendationService

GOOD = ranking_json(("R1", "Good fit."), ("R2", "Also good."))


def restaurants():
    return [make_restaurant(f"r{i}", cuisines=["Thai", "BBQ"]) for i in range(6)]


def make_service(ranker=None, *, build_id="test-build", **options):
    repository = make_repository(*restaurants(), build_id=build_id)
    return RecommendationService(repository, ranker or FakeRanker(GOOD), **options)


def search(service, **preferences):
    preferences.setdefault("area", "MG Road")
    return service.recommend(Preferences(**preferences))


def log_records(caplog):
    return [
        json.loads(r.getMessage().removeprefix("search "))
        for r in caplog.records
        if r.name == "recommender.search"
    ]


# Cache


def test_identical_searches_make_one_llm_call():
    ranker = FakeRanker(GOOD)
    service = make_service(ranker)
    first = search(service)
    second = search(service)
    assert len(ranker.calls) == 1
    assert first.diagnostics.cache_hit is False
    assert second.diagnostics.cache_hit is True
    assert second.results == first.results
    assert second.summary == first.summary


def test_equivalent_searches_share_a_cache_entry():
    ranker = FakeRanker(GOOD)
    service = make_service(ranker)
    search(service, cuisines=("Thai", "BBQ"), additional="Quiet  Place")
    search(service, cuisines=("bbq", "thai"), additional="  quiet place ")
    assert len(ranker.calls) == 1


def test_different_searches_get_separate_entries():
    ranker = FakeRanker(GOOD)
    service = make_service(ranker)
    search(service, min_rating=3.5)
    search(service, min_rating=4.0)
    search(service, additional="quiet, place")
    search(service, additional="quiet place")
    assert len(ranker.calls) == 4


@pytest.mark.parametrize(
    "error",
    [LLMUnavailable("rate_limited"), RuntimeError("boom")],
)
def test_failed_llm_calls_are_not_cached(error):
    ranker = FakeRanker(error=error)
    service = make_service(ranker)
    search(service)
    search(service)
    assert len(ranker.calls) == 2


def test_score_ranked_results_without_an_llm_are_not_cached():
    service = RecommendationService(make_repository(*restaurants()))
    search(service)
    assert search(service).diagnostics.cache_hit is False


def test_no_results_are_not_cached():
    ranker = FakeRanker(GOOD)
    service = make_service(ranker)
    assert search(service, area="BTM").results == []
    assert search(service, area="BTM").diagnostics.cache_hit is False
    assert ranker.calls == []


@pytest.mark.parametrize("change", ["build_id", "model", "effort", "prompt_version"])
def test_changing_data_model_effort_or_prompt_makes_a_new_call(change, monkeypatch):
    ranker = FakeRanker(GOOD)
    service = make_service(ranker)
    search(service)
    if change == "build_id":
        service.repository = make_repository(*restaurants(), build_id="new-build")
    elif change == "model":
        ranker.model = "another-model"
    elif change == "effort":
        ranker.effort = "high"
    else:
        monkeypatch.setattr(service_module, "PROMPT_VERSION", "next")
    search(service)
    assert len(ranker.calls) == 2


def test_use_cache_false_calls_the_llm_and_stores_nothing():
    ranker = FakeRanker(GOOD)
    service = make_service(ranker)
    search_options = {"area": "MG Road"}
    service.recommend(Preferences(**search_options), use_cache=False)
    service.recommend(Preferences(**search_options), use_cache=False)
    assert len(ranker.calls) == 2
    search(service)
    assert len(ranker.calls) == 3


def test_use_cache_false_ignores_an_existing_entry():
    ranker = FakeRanker(GOOD)
    service = make_service(ranker)
    search(service)
    result = service.recommend(Preferences(area="MG Road"), use_cache=False)
    assert result.diagnostics.cache_hit is False
    assert len(ranker.calls) == 2


def test_entries_expire_after_the_ttl():
    ranker = FakeRanker(GOOD)
    service = make_service(ranker, cache_ttl_seconds=0.05)
    search(service)
    time.sleep(0.1)
    search(service)
    assert len(ranker.calls) == 2


def test_oldest_entries_are_evicted_when_full():
    ranker = FakeRanker(GOOD)
    service = make_service(ranker, cache_max_entries=2)
    for rating in (3.0, 3.5, 4.0):
        search(service, min_rating=rating)
    search(service, min_rating=4.0)
    assert len(ranker.calls) == 3
    search(service, min_rating=3.0)
    assert len(ranker.calls) == 4


class SlowRanker(FakeRanker):
    def rank(self, system, user_message):
        time.sleep(0.05)
        return super().rank(system, user_message)


def test_searches_from_several_threads_raise_no_errors():
    service = make_service(SlowRanker(GOOD))
    errors, results = [], []

    def run(rating):
        try:
            results.append(search(service, min_rating=rating))
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=run, args=(r,)) for r in (3.0, 3.5, 4.0, 3.0, 3.5) * 4]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(results) == 20
    assert all(r.ai_ranked for r in results)


def test_lock_is_not_held_during_the_llm_call():
    service = make_service(SlowRanker(GOOD))
    started = time.perf_counter()
    threads = [
        threading.Thread(target=search, args=(service,), kwargs={"min_rating": r})
        for r in (3.0, 3.1, 3.2, 3.3, 3.4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Five 0.05-second calls in parallel take far less than the 0.25 seconds they would in turn.
    assert time.perf_counter() - started < 0.2


def test_cached_search_is_fast():
    service = make_service(SlowRanker(GOOD))
    search(service)
    started = time.perf_counter()
    search(service)
    assert time.perf_counter() - started < 0.2


# Logging


def test_one_log_line_per_search_with_the_expected_fields(caplog):
    caplog.set_level(logging.INFO, logger="recommender.search")
    service = make_service()
    search(service)
    search(service)
    first, second = log_records(caplog)
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert first["search"] == second["search"]
    expected = {
        "search",
        "cache_hit",
        "ai_ranked",
        "failure_reason",
        "matches",
        "candidates_sent",
        "results",
        "relaxations",
        "latency_seconds",
        "llm_seconds",
        "input_tokens",
        "output_tokens",
        "stop_reason",
        "model",
        "fallback_model_used",
        "retries",
        "request_id",
    }
    assert set(first) == expected
    assert (first["input_tokens"], first["output_tokens"]) == (3000, 800)
    assert (second["input_tokens"], second["output_tokens"], second["llm_seconds"]) == (
        None,
        None,
        None,
    )
    assert first["ai_ranked"] is True and first["candidates_sent"] == 6


def test_failures_are_logged_with_their_reason(caplog):
    caplog.set_level(logging.INFO, logger="recommender.search")
    search(make_service(FakeRanker(error=LLMUnavailable("timeout"))))
    (record,) = log_records(caplog)
    assert (record["ai_ranked"], record["failure_reason"]) == (False, "timeout")


def test_logs_hold_neither_the_free_text_nor_the_api_key(caplog, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value_for_test")
    caplog.set_level(logging.DEBUG)
    search(make_service(), additional="my private note about allergies")
    text = caplog.text
    assert "private note" not in text and "allergies" not in text
    assert "gsk_secret_value_for_test" not in text


def test_a_logging_failure_never_breaks_the_search(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(service_module.search_logger, "info", broken)
    assert search(make_service()).ai_ranked is True
