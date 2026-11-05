import pytest
from pydantic import ValidationError

from conftest import make_restaurant
from recommender.models import BudgetBand, Preferences


def test_defaults():
    preferences = Preferences(area="MG Road")
    assert preferences.budget == "any"
    assert preferences.cuisines == ()
    assert preferences.min_rating == 3.5
    assert preferences.include_unrated is False
    assert preferences.additional == ""


@pytest.mark.parametrize(
    "bad",
    [
        {"min_rating": -0.1},
        {"min_rating": 5.1},
        {"min_rating": float("nan")},
        {"budget": "cheap"},
        {"additional": "x" * 301},
        {"unknown_field": 1},
    ],
)
def test_invalid_preferences_are_rejected(bad):
    with pytest.raises(ValidationError):
        Preferences(area="MG Road", **bad)


@pytest.mark.parametrize("area", ["", "   "])
def test_blank_area_is_rejected(area):
    with pytest.raises(ValidationError):
        Preferences(area=area)


def test_free_text_limit_allows_exactly_300_characters():
    assert len(Preferences(area="MG Road", additional="x" * 300).additional) == 300


def test_spaces_only_free_text_counts_as_empty():
    assert Preferences(area="MG Road", additional="   ").additional == ""


def test_slider_rounding_noise_is_removed():
    assert Preferences(area="MG Road", min_rating=3.3000000000000003).min_rating == 3.3


def test_cuisines_drop_blanks_and_case_repeats():
    preferences = Preferences(area="MG Road", cuisines=("Thai", " thai ", "", "BBQ"))
    assert preferences.cuisines == ("Thai", "BBQ")


def test_budget_band_upper_edge_is_inclusive():
    band = BudgetBand(min=100, max=300)
    assert band.contains(100)
    assert band.contains(300)
    assert not band.contains(301)
    assert not band.contains(99)


def test_budget_band_without_upper_limit():
    band = BudgetBand(min=700, max=None)
    assert band.contains(100_000)
    assert band.label() == "₹700 and above"
    assert BudgetBand(min=1000, max=2000).label() == "₹1,000 to ₹2,000"


def test_restaurant_search_text_covers_soft_preference_fields():
    restaurant = make_restaurant(
        rest_types=["Quick Bites"],
        dishes=["Dosa"],
        listing_types=frozenset({"Buffet"}),
        review_snippets=["Lovely Staff"],
    )
    for term in ("quick bites", "dosa", "buffet", "lovely staff"):
        assert term in restaurant.search_text
