import pytest

from conftest import BANDS, make_restaurant
from recommender.display import (
    budget_option_label,
    format_cost,
    format_cuisines,
    format_rating,
    result_card,
    search_summary,
)
from recommender.models import Candidate, Preferences


def card(in_chosen_area=True, **fields):
    candidate = Candidate(make_restaurant(**fields), 4.0, 0, in_chosen_area)
    return result_card(1, candidate, "MG Road")


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
    assert format_cuisines(make_restaurant(cuisines=["Thai", "BBQ"])) == "Thai, BBQ"
    assert format_cuisines(make_restaurant(cuisines=[])) == "Cuisine: not listed"


def test_budget_labels_show_rupee_ranges():
    assert budget_option_label("any", BANDS) == "Any budget"
    assert budget_option_label("low", BANDS) == "Low (₹100 to ₹300 for two)"
    assert budget_option_label("high", BANDS) == "High (above ₹699 for two)"


def test_card_shows_every_required_field():
    html = card(
        name="Jalsa",
        cuisines=["North Indian"],
        rating=4.1,
        votes=775,
        cost_for_two=800,
        location="Banashankari",
        rest_types=["Casual Dining"],
    )
    for text in ("1. Jalsa", "North Indian", "★ 4.1 (775 votes)", "₹800 for two", "Banashankari"):
        assert text in html
    assert "Casual Dining" in html


def test_card_handles_missing_values():
    html = card(rating=None, cost_for_two=None, cuisines=[], location=None, rest_types=[])
    for text in ("Unrated", "Cost: not listed", "Cuisine: not listed", "Not listed"):
        assert text in html


def test_card_marks_restaurants_outside_the_chosen_area():
    assert "Near MG Road" in card(in_chosen_area=False)
    assert "Near MG Road" not in card(in_chosen_area=True)


@pytest.mark.parametrize("field", ["name", "location", "cuisines", "rest_types"])
def test_card_escapes_html_in_every_dataset_field(field):
    attack = '<script>alert("x")</script>'
    value = [attack] if field in ("cuisines", "rest_types") else attack
    html = card(**{field: value})
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_markdown_and_maths_characters_are_kept_as_written():
    assert "*Bold* _name_ $x$ `code`" in card(name="*Bold* _name_ $x$ `code`")


def test_search_summary_describes_the_search_and_escapes_free_text():
    preferences = Preferences(
        area="BTM",
        budget="low",
        cuisines=("Thai",),
        min_rating=4.0,
        include_unrated=True,
        additional="<b>quick</b>",
    )
    summary = search_summary(preferences, BANDS)
    for text in ("BTM", "Low (₹100 to ₹300 for two)", "Thai", "Rated 4.0+, or unrated"):
        assert text in summary
    assert "<b>" not in summary
    assert "&lt;b&gt;quick&lt;/b&gt;" in summary


def test_search_summary_defaults():
    summary = search_summary(Preferences(area="BTM"), BANDS)
    assert "Any budget" in summary and "Any cuisine" in summary and "Rated 3.5+" in summary
