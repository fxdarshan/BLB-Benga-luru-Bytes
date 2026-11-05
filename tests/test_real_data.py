"""Checks against the real data. These are skipped until ingestion has been run."""

import math
import statistics
import time

import pytest

from recommender.candidates import select_candidates
from recommender.config import load_settings
from recommender.models import Preferences
from recommender.repository import DataUnavailableError, RestaurantRepository


@pytest.fixture(scope="module")
def repository():
    settings = load_settings()
    try:
        return RestaurantRepository.load(settings.restaurants_path, settings.metadata_path)
    except DataUnavailableError as error:
        pytest.skip(str(error))


def test_every_area_returns_candidates_within_the_limit(repository):
    assert len(repository.metadata.areas) == 30
    for area in repository.metadata.areas:
        selection = select_candidates(Preferences(area=area, min_rating=3.5), repository)
        assert 0 < len(selection.candidates) <= 15
        assert all(area in c.restaurant.areas for c in selection.candidates)


def test_scores_are_finite_and_descending(repository):
    for area in repository.metadata.areas:
        preferences = Preferences(area=area, min_rating=0.0, include_unrated=True)
        scores = [c.score for c in select_candidates(preferences, repository).candidates]
        assert all(math.isfinite(score) for score in scores)
        assert scores == sorted(scores, reverse=True)


def test_results_meet_the_applied_limits(repository):
    bands = repository.metadata.budget_bands
    for area in repository.metadata.areas:
        preferences = Preferences(area=area, budget="low", cuisines=("Chinese",), min_rating=4.0)
        selection = select_candidates(preferences, repository)
        for candidate in selection.candidates:
            restaurant = candidate.restaurant
            assert "chinese" in restaurant.cuisine_keys
            assert restaurant.rating >= selection.applied_min_rating
            assert any(
                bands[b].contains(restaurant.cost_for_two) for b in selection.applied_budgets
            )


def test_most_top_results_are_located_in_the_chosen_area(repository):
    shares = []
    for area in repository.metadata.areas:
        top = select_candidates(Preferences(area=area), repository).candidates[:5]
        shares.append(sum(c.in_chosen_area for c in top) / len(top))
    assert statistics.mean(shares) > 0.7


def test_selection_is_under_100_ms(repository):
    searches = [
        Preferences(area="BTM", min_rating=0.0, include_unrated=True, additional="pub, buffet"),
        Preferences(area="Koramangala 7th Block", budget="medium", cuisines=("North Indian",)),
        Preferences(area="New BEL Road", budget="high", cuisines=("Thai",), min_rating=4.8),
    ]
    timings = []
    for _ in range(10):
        for preferences in searches:
            start = time.perf_counter()
            select_candidates(preferences, repository)
            timings.append(time.perf_counter() - start)
    assert statistics.median(timings) < 0.1
