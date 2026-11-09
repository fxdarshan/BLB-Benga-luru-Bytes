import subprocess
import sys

import pytest

from conftest import make_repository, make_restaurant
from fakes import FakeRanker, ranking_json
from recommender.candidates import InvalidPreferencesError
from recommender.llm import CallDetails, LLMUnavailable
from recommender.models import Preferences
from recommender.prompts import SYSTEM_PROMPT
from recommender.service import FAILURE_NOT_CONFIGURED, NOTICE_NOT_AI_RANKED, RecommendationService


def many(count, **fields):
    return [make_restaurant(f"r{i:02}", **fields) for i in range(count)]


def test_returns_at_most_five_results_by_default():
    service = RecommendationService(make_repository(*many(20)))
    result = service.recommend(Preferences(area="MG Road"))
    assert len(result.results) == 5
    assert result.diagnostics.total_matches == 20


def test_results_are_in_score_order():
    repository = make_repository(
        make_restaurant("low", rating=3.6, votes=1000),
        make_restaurant("high", rating=4.8, votes=1000),
        make_restaurant("mid", rating=4.2, votes=1000),
    )
    result = RecommendationService(repository).recommend(Preferences(area="MG Road"))
    assert [r.candidate.restaurant.restaurant_id for r in result.results] == ["high", "mid", "low"]


def test_custom_limits_are_used():
    service = RecommendationService(make_repository(*many(20)), max_candidates=8, max_results=3)
    assert len(service.recommend(Preferences(area="MG Road")).results) == 3


def test_score_ranked_results_are_marked_as_not_ai_ranked():
    service = RecommendationService(make_repository(*many(1)))
    result = service.recommend(Preferences(area="MG Road"))
    assert result.ai_ranked is False
    assert result.summary is None
    assert result.notice == NOTICE_NOT_AI_RANKED
    assert result.failure_reason == FAILURE_NOT_CONFIGURED


def test_relaxations_and_applied_limits_are_carried_through():
    repository = make_repository(*many(2, rating=4.0))
    result = RecommendationService(repository).recommend(
        Preferences(area="MG Road", min_rating=4.5)
    )
    assert [r.limit for r in result.relaxations] == ["min_rating"]
    assert result.diagnostics.applied_min_rating == 4.0


def test_empty_result_has_no_notice_or_failure():
    service = RecommendationService(make_repository(*many(3)))
    result = service.recommend(Preferences(area="BTM"))
    assert result.results == []
    assert result.notice is None
    assert result.failure_reason is None


def test_unknown_area_raises():
    service = RecommendationService(make_repository(*many(1)))
    with pytest.raises(InvalidPreferencesError):
        service.recommend(Preferences(area="Delhi"))


def test_llm_client_is_accepted_as_a_replaceable_dependency():
    fake = object()
    assert RecommendationService(make_repository(), fake).llm_client is fake


def test_service_never_imports_streamlit():
    code = "import sys, recommender.service; sys.exit('streamlit' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


# LLM ranking


def ai_service(ranker, count=6, **restaurant_fields):
    repository = make_repository(*many(count, **restaurant_fields))
    return RecommendationService(repository, ranker)


def test_ai_ranking_reorders_results_and_adds_explanations():
    ranker = FakeRanker(ranking_json(("R3", "Third by score but best fit."), ("R1", "Solid.")))
    result = ai_service(ranker).recommend(Preferences(area="MG Road", additional="quiet"))
    assert result.ai_ranked is True
    assert result.notice is None and result.failure_reason is None
    assert [r.candidate.restaurant.restaurant_id for r in result.results] == ["r02", "r00"]
    assert result.results[0].explanation == "Third by score but best fit."
    assert result.summary == "Restaurant r00 is the best fit, and Restaurant r01 is a close second."


def test_fewer_valid_results_are_not_padded_with_score_results():
    result = ai_service(FakeRanker(ranking_json(("R2", "Only one.")))).recommend(
        Preferences(area="MG Road")
    )
    assert len(result.results) == 1


def test_diagnostics_keep_raw_text_and_call_details():
    raw = ranking_json(("R1", "Fine, better than R2."), ("R77", "Invented."))
    result = ai_service(FakeRanker(raw)).recommend(Preferences(area="MG Road"))
    diagnostics = result.diagnostics
    assert diagnostics.raw_llm_text == raw
    assert "R77" in diagnostics.raw_llm_text and "R2" in diagnostics.raw_llm_text
    assert diagnostics.candidates_sent == tuple(f"r{i:02}" for i in range(6))
    assert diagnostics.results_dropped == 1
    assert diagnostics.usage == {"input_tokens": 3000, "output_tokens": 800}
    assert diagnostics.served_model == "claude-opus-5-5"
    assert result.results[0].explanation == "Fine, better than Restaurant r01."


def test_prompt_is_sent_with_the_system_prompt():
    ranker = FakeRanker(ranking_json(("R1", "Good.")))
    ai_service(ranker).recommend(Preferences(area="MG Road"))
    system, user = ranker.calls[0]
    assert system == SYSTEM_PROMPT
    assert "<candidates>" in user


@pytest.mark.parametrize(
    "reason",
    [
        "authentication",
        "bad_request",
        "rate_limited",
        "server_error",
        "timeout",
        "connection",
        "refusal",
        "max_tokens",
        "no_text_block",
        "invalid_response",
    ],
)
def test_each_llm_failure_falls_back_to_score_ranking(reason):
    error = LLMUnavailable(reason, CallDetails(raw_text="partial", latency_seconds=2.0))
    result = ai_service(FakeRanker(error=error)).recommend(Preferences(area="MG Road"))
    assert result.ai_ranked is False
    assert result.failure_reason == reason
    assert result.notice == NOTICE_NOT_AI_RANKED
    assert len(result.results) == 5
    assert all(r.explanation is None for r in result.results)
    assert result.diagnostics.raw_llm_text == "partial"
    assert result.diagnostics.candidates_sent


def test_no_valid_results_falls_back():
    ranker = FakeRanker(ranking_json(("R99", "Invented."), ("R1", "  ")))
    result = ai_service(ranker).recommend(Preferences(area="MG Road"))
    assert result.failure_reason == "no_valid_results"
    assert len(result.results) == 5


def test_unexpected_error_falls_back_without_raising():
    result = ai_service(FakeRanker(error=RuntimeError("boom"))).recommend(
        Preferences(area="MG Road")
    )
    assert result.failure_reason == "unexpected_error"
    assert len(result.results) == 5


def test_no_llm_call_when_nothing_matches():
    ranker = FakeRanker(ranking_json(("R1", "Good.")))
    result = ai_service(ranker).recommend(Preferences(area="BTM"))
    assert result.results == []
    assert ranker.calls == []
