import subprocess
import sys

import pytest

from conftest import make_repository, make_restaurant
from recommender.candidates import InvalidPreferencesError
from recommender.models import Preferences
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
    assert [c.restaurant.restaurant_id for c in result.results] == ["high", "mid", "low"]


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
