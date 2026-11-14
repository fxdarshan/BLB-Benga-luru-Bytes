import pytest

from conftest import BANDS, make_restaurant
from recommender.display import (
    MAX_REVIEW_CHARS,
    budget_option_label,
    format_cost,
    format_cuisines,
    format_rating,
    search_summary_parts,
    shorten_review,
)
from recommender.models import Preferences


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"rating": 4.3, "votes": 1812}, "★ 4.3 (1,812 votes)"),
        ({"rating": 4.0, "votes": 1}, "★ 4.0 (1 vote)"),
        ({"rating": None, "is_new": True}, "New"),
        ({"rating": None, "is_new": False}, "Unrated"),
    ],
)
def test_format_rating(fields, expected):
    assert format_rating(make_restaurant(**fields)) == expected


def test_format_cost_is_labelled_for_two():
    assert format_cost(make_restaurant(cost_for_two=1500)) == "₹1,500 for two"
    assert format_cost(make_restaurant(cost_for_two=None)) == "Cost: not listed"


def test_format_cuisines():
    assert format_cuisines(make_restaurant(cuisines=["Thai", "Kerala"])) == "Thai, Kerala"


def test_cards_show_only_real_cuisines():
    restaurant = make_restaurant(cuisines=["Cafe", "Italian", "Pizza", "Bubble Tea", "Goan"])
    assert format_cuisines(restaurant) == "Italian, Goan"


def test_cards_fall_back_to_original_labels_without_a_real_cuisine():
    assert format_cuisines(make_restaurant(cuisines=["Biryani", "Kebab"])) == "Biryani, Kebab"


def test_format_cuisines_when_none_are_listed():
    assert format_cuisines(make_restaurant(cuisines=[])) == "Cuisine: not listed"


def test_budget_labels_show_rupee_ranges():
    assert budget_option_label("any", BANDS) == "Any budget"
    assert budget_option_label("low", BANDS) == "Low (₹100 to ₹300 for two)"
    assert budget_option_label("high", BANDS) == "High (above ₹699 for two)"


def test_search_summary_describes_the_search_as_plain_text():
    preferences = Preferences(
        area="BTM",
        budget="low",
        cuisines=("Thai",),
        min_rating=4.0,
        include_unrated=True,
        additional="<b>quick</b>",
    )
    assert search_summary_parts(preferences, BANDS) == [
        "BTM",
        "Low (₹100 to ₹300 for two)",
        "Thai",
        "Rated 4.0+, or unrated",
        # Plain text: the web page sets it with textContent, so it displays literally.
        "“<b>quick</b>”",
    ]


def test_search_summary_defaults():
    assert search_summary_parts(Preferences(area="BTM"), BANDS) == [
        "BTM",
        "Any budget",
        "Any cuisine",
        "Rated 3.5+",
    ]


def test_long_reviews_are_cut_to_about_two_lines_at_a_word():
    text = shorten_review("tasty food, " * 40)
    assert len(text) <= MAX_REVIEW_CHARS + 1
    # Cut at a whole word, with no stray comma before the ellipsis.
    assert text.endswith(("tasty…", "food…"))


def test_short_and_missing_reviews():
    assert shorten_review("  Great dosa.  ") == "Great dosa."
    assert shorten_review(None) is None
    assert shorten_review("   ") is None
