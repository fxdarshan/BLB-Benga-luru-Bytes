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
from recommender.models import Candidate, Preferences, RankedResult


def card(in_chosen_area=True, **fields):
    candidate = Candidate(make_restaurant(**fields), 4.0, 0, in_chosen_area)
    return result_card(1, RankedResult(candidate), "MG Road")


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
    assert '<span class="blb-rank">1</span>Jalsa' in html
    for text in ("North Indian", "★ 4.1 (775 votes)", "₹800 for two", "Banashankari"):
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


def test_card_lines_are_tagged_for_hover_highlighting():
    html = card(location="BTM")
    assert html.startswith('<div class="blb-card"')
    assert html.count('class="blb-line ') == 3


def test_card_shows_the_chosen_customer_review_escaped():
    candidate = Candidate(make_restaurant(), 4.0, 0, True)
    html = result_card(1, RankedResult(candidate, "Fine.", review="Best <b>dosa</b> ever"), "BTM")
    assert "A customer said" in html
    assert "“Best &lt;b&gt;dosa&lt;/b&gt; ever”" in html


def test_long_reviews_are_cut_to_about_two_lines():
    from recommender.display import MAX_REVIEW_CHARS, review_block

    block = review_block("tasty food, " * 40)
    quoted = block.split("</span>", 1)[1]
    assert len(quoted) <= MAX_REVIEW_CHARS + len("“…”</div>")
    # Cut at a whole word, with no stray comma before the ellipsis.
    assert quoted.endswith(("tasty…”</div>", "food…”</div>"))


def test_card_without_a_review_shows_no_review_line():
    assert "A customer said" not in card()


def test_results_rise_in_one_after_another():
    from recommender.display import FORM_STYLE, RISE_START_MS, RISE_STEP_MS, summary_block

    candidate = Candidate(make_restaurant(), 4.0, 0, True)
    delays = [
        result_card(position, RankedResult(candidate), "BTM").split("animation-delay: ")[1]
        for position in (1, 2, 3)
    ]
    # The chips are step 0 and the summary step 1, so the first card is step 2.
    assert [int(d.split("ms")[0]) for d in delays] == [
        RISE_START_MS + 2 * RISE_STEP_MS,
        RISE_START_MS + 3 * RISE_STEP_MS,
        RISE_START_MS + 4 * RISE_STEP_MS,
    ]
    chips = search_summary(Preferences(area="BTM"), BANDS)
    assert f"animation-delay: {RISE_START_MS}ms" in chips
    summary_delay = RISE_START_MS + RISE_STEP_MS
    assert f"animation-delay: {summary_delay}ms" in summary_block("Both are good.")
    assert "@keyframes blb-rise" in FORM_STYLE
    # Old results glide out while a new search runs, instead of vanishing in one frame.
    assert "@keyframes blb-leave" in FORM_STYLE
    # Less motion for anyone whose device asks for it.
    assert "prefers-reduced-motion: reduce" in FORM_STYLE


def test_page_header_shows_whether_ai_ranking_is_on():
    from recommender.display import page_header

    assert "AI ranking on" in page_header(True)
    assert "AI ranking off" in page_header(False)
    assert "AI ranking" not in page_header(None)
    assert "Banga-Luru Bytes" in page_header(None)


def test_page_style_highlights_hovered_and_chosen_items():
    from recommender.display import FORM_STYLE

    for rule in (
        ":hover",
        "input:checked",
        "stSelectbox",
        "stMultiSelectTagsContainer",
        ".blb-line:hover",
    ):
        assert rule in FORM_STYLE
