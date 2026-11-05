import random
import re

import pytest

from conftest import make_metadata, make_repository, make_restaurant
from recommender.candidates import (
    InvalidPreferencesError,
    count_keyword_hits,
    extract_keyword_patterns,
    score_restaurant,
    select_candidates,
    weighted_rating,
)
from recommender.models import Preferences


def search(repository, **preferences):
    preferences.setdefault("area", "MG Road")
    preferences.setdefault("min_rating", 0.0)
    return select_candidates(Preferences(**preferences), repository)


def ids(selection):
    return [candidate.restaurant.restaurant_id for candidate in selection.candidates]


def hits(text, **restaurant_fields):
    patterns = extract_keyword_patterns(text)
    return count_keyword_hits(make_restaurant(**restaurant_fields), patterns)


# Filters


def test_area_filter_matches_any_listed_area():
    repository = make_repository(
        make_restaurant("in", areas=frozenset({"BTM", "MG Road"})),
        make_restaurant("out", areas=frozenset({"BTM"})),
    )
    assert ids(search(repository)) == ["in"]


@pytest.mark.parametrize(
    ("budget", "expected"),
    [
        ("low", {"cost_300"}),
        ("medium", {"cost_400", "cost_600"}),
        ("high", {"cost_700"}),
        ("any", {"cost_300", "cost_400", "cost_600", "cost_700", "no_cost"}),
    ],
)
def test_budget_filter(budget, expected):
    repository = make_repository(
        make_restaurant("cost_300", cost_for_two=300),
        make_restaurant("cost_400", cost_for_two=400),
        make_restaurant("cost_600", cost_for_two=600),
        make_restaurant("cost_700", cost_for_two=700),
        make_restaurant("no_cost", cost_for_two=None),
    )
    selection = select_candidates(
        Preferences(area="MG Road", budget=budget, min_rating=0.0), repository, min_results=1
    )
    assert set(ids(selection)) == expected


def test_cuisine_filter_passes_on_any_match_ignoring_case():
    repository = make_repository(
        make_restaurant("thai", cuisines=["Thai", "Chinese"]),
        make_restaurant("bbq", cuisines=["BBQ"]),
        make_restaurant("italian", cuisines=["Italian"]),
    )
    assert set(ids(search(repository, cuisines=("thai", "bbq")))) == {"thai", "bbq"}


def test_no_cuisine_chosen_passes_everything_including_null_cuisine():
    repository = make_repository(make_restaurant("none", cuisines=[]), make_restaurant("thai"))
    assert set(ids(search(repository))) == {"none", "thai"}


def test_null_cuisine_fails_a_chosen_cuisine():
    repository = make_repository(make_restaurant("none", cuisines=[]))
    assert ids(search(repository, cuisines=("Italian",))) == []


def test_rating_filter_includes_an_exact_match():
    repository = make_repository(
        *[make_restaurant(str(i), rating=4.0) for i in range(5)],
        make_restaurant("below", rating=3.9),
    )
    assert ids(search(repository, min_rating=4.0)) == ["0", "1", "2", "3", "4"]


def test_unrated_appear_only_when_included():
    repository = make_repository(
        make_restaurant("rated", rating=4.0),
        make_restaurant("unrated", rating=None),
        make_restaurant("new", rating=None, is_new=True),
    )
    assert ids(search(repository)) == ["rated"]
    assert set(ids(search(repository, include_unrated=True))) == {"rated", "unrated", "new"}


def test_unrated_included_at_any_minimum_rating():
    repository = make_repository(make_restaurant("unrated", rating=None))
    assert ids(search(repository, min_rating=4.5, include_unrated=True)) == ["unrated"]


def test_all_filters_together():
    good = {"cuisines": ["Thai"], "cost_for_two": 500, "rating": 4.5}
    repository = make_repository(
        make_restaurant("match", **good),
        *[make_restaurant(f"other{i}", **good) for i in range(4)],
        make_restaurant("wrong_area", areas=frozenset({"BTM"}), **good),
        make_restaurant("wrong_cuisine", **{**good, "cuisines": ["Italian"]}),
        make_restaurant("wrong_cost", **{**good, "cost_for_two": 900}),
        make_restaurant("wrong_rating", **{**good, "rating": 3.0}),
    )
    selection = search(repository, budget="medium", cuisines=("Thai",), min_rating=4.0)
    assert set(ids(selection)) == {"match", "other0", "other1", "other2", "other3"}
    assert selection.relaxations == []


# Invalid searches


def test_unknown_area_is_rejected():
    with pytest.raises(InvalidPreferencesError, match="area"):
        search(make_repository(make_restaurant()), area="Delhi")


def test_unknown_cuisine_is_rejected():
    with pytest.raises(InvalidPreferencesError, match="cuisines"):
        search(make_repository(make_restaurant()), cuisines=("Martian",))


def test_known_area_with_no_restaurants_gives_empty_result():
    assert ids(search(make_repository(make_restaurant()), area="BTM")) == []


# Relaxation


def rated(prefix, count, rating, cost=500):
    return [make_restaurant(f"{prefix}{i}", rating=rating, cost_for_two=cost) for i in range(count)]


def test_no_relaxation_with_enough_results():
    selection = search(make_repository(*rated("a", 5, 4.5), *rated("b", 3, 4.0)), min_rating=4.5)
    assert selection.relaxations == []
    assert selection.applied_min_rating == 4.5
    assert selection.total_matches == 5


def test_rating_relaxes_first_and_stops_once_there_are_enough():
    repository = make_repository(
        *rated("top", 2, 4.5),
        *rated("near", 3, 4.0),
        *rated("other_band", 3, 4.5, cost=800),
    )
    selection = search(repository, budget="medium", min_rating=4.5)
    assert [r.limit for r in selection.relaxations] == ["min_rating"]
    assert selection.applied_min_rating == 4.0
    assert selection.applied_budgets == ("medium",)
    assert selection.total_matches == 5


def test_budget_relaxes_after_rating():
    repository = make_repository(
        *rated("top", 2, 4.5),
        *rated("near", 1, 4.0),
        *rated("higher_band", 3, 4.0, cost=800),
    )
    selection = search(repository, budget="medium", min_rating=4.5)
    assert [r.limit for r in selection.relaxations] == ["min_rating", "budget"]
    assert selection.applied_min_rating == 4.0
    assert selection.applied_budgets == ("medium", "high")
    assert selection.total_matches == 6


def test_widening_low_keeps_low_and_adds_medium():
    repository = make_repository(
        *rated("low", 1, 4.5, cost=200),
        *rated("medium", 4, 4.5, cost=500),
        *rated("high", 4, 4.5, cost=900),
    )
    selection = search(repository, budget="low", min_rating=4.0)
    assert selection.applied_budgets == ("low", "medium")
    assert {c.restaurant.cost_for_two for c in selection.candidates} == {200, 500}


def test_high_budget_widens_down_to_medium():
    repository = make_repository(
        *rated("high", 2, 4.5, cost=900),
        *rated("medium", 4, 4.5, cost=500),
        *rated("low", 4, 4.5, cost=200),
    )
    selection = search(repository, budget="high", min_rating=4.0)
    assert selection.applied_budgets == ("high", "medium")
    assert {c.restaurant.cost_for_two for c in selection.candidates} == {900, 500}
    relaxation = selection.relaxations[0]
    assert (relaxation.limit, relaxation.requested) == ("budget", "high")
    assert "high" in relaxation.message and "also includes medium" in relaxation.message


def test_high_budget_with_no_matches_can_still_widen_to_medium():
    selection = search(make_repository(*rated("medium", 3, 4.5, cost=500)), budget="high")
    assert selection.applied_budgets == ("high", "medium")
    assert len(selection.candidates) == 3


def test_medium_budget_widens_up_to_high():
    repository = make_repository(*rated("medium", 1, 4.5), *rated("high", 4, 4.5, cost=900))
    selection = search(repository, budget="medium", min_rating=4.0)
    assert selection.applied_budgets == ("medium", "high")


def test_requested_budget_ranks_ahead_of_widened_budget():
    repository = make_repository(
        make_restaurant("widened_best", rating=4.9, votes=5000, cost_for_two=500),
        make_restaurant("widened_next", rating=4.8, votes=5000, cost_for_two=500),
        make_restaurant("asked_for", rating=3.6, votes=10, cost_for_two=900),
    )
    selection = search(repository, budget="high", min_rating=3.5)
    assert ids(selection) == ["asked_for", "widened_best", "widened_next"]


def test_requested_budget_survives_the_candidate_cut():
    repository = make_repository(
        make_restaurant("asked_for", rating=3.6, votes=10, cost_for_two=900),
        *[make_restaurant(f"m{i}", rating=4.5, cost_for_two=500) for i in range(20)],
    )
    selection = search(repository, budget="high", min_rating=3.5)
    assert ids(selection)[0] == "asked_for"
    assert len(selection.candidates) == 15


def test_any_budget_never_relaxes():
    repository = make_repository(*rated("a", 2, 4.5, cost=900))
    assert search(repository, budget="any", min_rating=4.0).relaxations == []


def test_rating_relaxes_only_once():
    repository = make_repository(*rated("a", 2, 4.5), *rated("far", 4, 3.5))
    selection = search(repository, min_rating=4.5)
    assert selection.applied_min_rating == 4.5
    assert selection.total_matches == 2
    assert selection.relaxations == []


def test_relaxation_that_adds_nothing_is_not_reported():
    repository = make_repository(*rated("a", 2, 4.5), *rated("high", 1, 3.0, cost=900))
    selection = search(repository, budget="medium", min_rating=4.0)
    assert selection.relaxations == []
    assert selection.applied_min_rating == 4.0
    assert selection.applied_budgets == ("medium",)


def test_rating_stops_at_zero():
    repository = make_repository(make_restaurant("low", rating=0.0))
    selection = search(repository, min_rating=0.3)
    assert selection.applied_min_rating == 0.0
    assert selection.relaxations[0].applied == "0.0"


def test_zero_minimum_rating_is_not_relaxed():
    selection = search(make_repository(make_restaurant()), min_rating=0.0)
    assert selection.relaxations == []


def test_relaxed_rating_avoids_float_noise():
    repository = make_repository(make_restaurant("a", rating=3.6))
    selection = search(repository, min_rating=4.1)
    assert selection.applied_min_rating == 3.6
    assert ids(selection) == ["a"]


def test_area_and_cuisine_are_never_relaxed():
    repository = make_repository(
        *[make_restaurant(f"btm{i}", areas=frozenset({"BTM"})) for i in range(5)],
        *[make_restaurant(f"thai{i}", cuisines=["Thai"]) for i in range(5)],
        make_restaurant("only"),
    )
    selection = search(repository, cuisines=("Italian",), min_rating=3.0)
    assert ids(selection) == ["only"]
    assert selection.relaxations == []


def test_fewer_than_five_after_relaxing_returns_what_was_found():
    repository = make_repository(*rated("a", 2, 4.5))
    assert len(search(repository, min_rating=4.5).candidates) == 2


def test_no_matches_gives_empty_selection():
    selection = search(make_repository(make_restaurant()), cuisines=("Thai",))
    assert selection.candidates == []
    assert selection.total_matches == 0


def test_relaxation_messages_state_the_applied_limits():
    repository = make_repository(
        *rated("top", 1, 4.5, cost=200),
        *rated("near", 1, 4.0, cost=200),
        *rated("medium", 4, 4.0, cost=500),
    )
    rating, budget = search(repository, budget="low", min_rating=4.5).relaxations
    assert (rating.requested, rating.applied) == ("4.5", "4.0")
    assert "4.5+" in rating.message and "4.0+" in rating.message
    assert "₹100 to ₹300" in budget.message and "₹400 to ₹600" in budget.message


# Keywords


def test_whole_phrase_counts_as_one_hit():
    assert hits("quick bites", rest_types=["Quick Bites"]) == 1


def test_remaining_word_of_a_phrase_can_hit():
    assert hits("quick service", rest_types=["Quick Bites"]) == 1


def test_quick_service_gets_no_hit_from_the_word_service_alone():
    assert hits("quick service", review_snippets=["The service was great"]) == 0


def test_whole_phrase_of_only_ignored_words_gives_no_patterns():
    assert extract_keyword_patterns("good service, and with the") == []


def test_separate_phrases_each_count_once():
    fields = {"rest_types": ["Pub"], "dishes": ["Nachos", "Nachos"], "review_snippets": ["Pub pub"]}
    assert hits("pub, nachos", **fields) == 2


def test_repeated_phrase_counts_once():
    assert hits("pub, PUB , pub", rest_types=["Pub"]) == 1


@pytest.mark.parametrize(
    ("text", "field", "expected"),
    [
        ("bar", "barbecue is fine", 0),
        ("bar", "a great bar", 1),
        ("veg", "non-veg only", 0),
        ("veg", "pure veg food", 1),
        ("BUFFET", "lunch buffet", 1),
    ],
)
def test_keywords_match_whole_words_ignoring_case(text, field, expected):
    assert hits(text, review_snippets=[field]) == expected


@pytest.mark.parametrize("text", ["c++", "(", "[a-z", "*", "\\", "what?"])
def test_regex_characters_in_free_text_are_safe(text):
    assert hits(text, review_snippets=["Plain review"]) == 0


def test_literal_special_characters_can_match():
    assert hits("c++", review_snippets=["we code in c++ here"]) == 1


@pytest.mark.parametrize("text", ["", "  ,  , ", "and with the", "🍕🍕"])
def test_free_text_with_nothing_useful_gets_no_hits(text):
    assert hits(text, review_snippets=["and with the service"]) == 0


def test_hindi_free_text_is_safe_and_can_match():
    assert hits("खाना", review_snippets=["अच्छा खाना"]) == 1


def test_whole_phrase_does_not_match_across_two_fields():
    pattern = extract_keyword_patterns("masala dosa")[0]
    fields = make_restaurant(dishes=["Masala", "Dosa"]).search_text
    assert pattern.pattern.startswith(r"(?<![\w-])(?:masala\s+dosa|")
    assert not re.search(r"masala\s+dosa", fields)


# Scoring


def test_low_vote_rating_scores_below_well_supported_rating(metadata):
    few_votes = make_restaurant("few", rating=5.0, votes=3)
    many_votes = make_restaurant("many", rating=4.5, votes=2000)
    assert weighted_rating(few_votes, metadata) < weighted_rating(many_votes, metadata)


def test_zero_votes_scores_the_mean(metadata):
    assert weighted_rating(make_restaurant(rating=4.9, votes=0), metadata) == metadata.mean_rating


def test_zero_median_votes_cannot_divide_by_zero():
    with pytest.raises(ValueError):
        make_metadata(median_votes=0)


def test_keyword_match_raises_score(metadata):
    restaurant = make_restaurant()
    base = score_restaurant(restaurant, 0, metadata)
    assert score_restaurant(restaurant, 1, metadata) == pytest.approx(base + 0.25)


def test_keyword_boost_is_capped_at_two_hits(metadata):
    restaurant = make_restaurant()
    assert score_restaurant(restaurant, 5, metadata) == score_restaurant(restaurant, 2, metadata)


def test_unrated_scores_below_well_reviewed_restaurant_just_under_the_mean(metadata):
    unrated = make_restaurant("u", rating=None)
    just_under = make_restaurant("r", rating=metadata.mean_rating - 0.1, votes=1000)
    assert weighted_rating(unrated, metadata) == pytest.approx(metadata.mean_rating - 0.25)
    assert weighted_rating(unrated, metadata) < weighted_rating(just_under, metadata)


def test_keyword_match_lifts_a_lower_rated_restaurant():
    repository = make_repository(
        make_restaurant("plain", rating=4.2, votes=1000),
        make_restaurant("match", rating=4.1, votes=1000, rest_types=["Pub"]),
    )
    selection = search(repository, additional="pub")
    assert ids(selection) == ["match", "plain"]
    assert selection.candidates[0].keyword_hits == 1


# Location boost


def test_local_restaurant_scores_above_one_only_listed_in_the_area():
    repository = make_repository(
        make_restaurant("listed", location="BTM", address="1 BTM Layout", rating=4.3, votes=1000),
        make_restaurant("local", location="MG Road", rating=4.1, votes=1000),
    )
    selection = search(repository)
    assert ids(selection) == ["local", "listed"]
    assert selection.candidates[0].in_chosen_area is True
    assert selection.candidates[1].in_chosen_area is False


def test_location_boost_size(metadata):
    restaurant = make_restaurant()
    base = score_restaurant(restaurant, 0, metadata)
    boosted = score_restaurant(restaurant, 0, metadata, in_chosen_area=True)
    assert boosted == pytest.approx(base + 0.5)


def test_exceptional_nearby_restaurant_can_outrank_a_weak_local_one():
    repository = make_repository(
        make_restaurant("nearby", location="BTM", address="BTM Layout", rating=4.9, votes=5000),
        make_restaurant("local", location="MG Road", rating=3.6, votes=5000),
    )
    assert ids(search(repository)) == ["nearby", "local"]


@pytest.mark.parametrize(
    ("location", "address", "expected"),
    [
        ("MG Road", "1 Some Street", True),
        ("Ulsoor", "1 Some Street, MG Road, Bangalore", True),
        ("mg road", None, True),
        ("MG  Road", None, True),
        ("Ulsoor", "1 Some Street", False),
        ("Big MG Roadside", None, False),
        (None, None, False),
    ],
)
def test_chosen_area_is_found_in_location_or_address(location, address, expected):
    repository = make_repository(make_restaurant(location=location, address=address))
    assert search(repository).candidates[0].in_chosen_area is expected


def test_a_different_koramangala_block_is_not_local():
    area = "Koramangala 5th Block"
    other = make_restaurant(
        "other", location="Koramangala 6th Block", address=None, areas=frozenset({area})
    )
    same = make_restaurant("same", location=area, address=None, areas=frozenset({area}))
    selection = search(make_repository(other, same, areas=(area,)), area=area)
    assert {c.restaurant.restaurant_id: c.in_chosen_area for c in selection.candidates} == {
        "other": False,
        "same": True,
    }


# Order and limits


def test_no_more_than_fifteen_candidates_returned_with_the_best_first():
    restaurants = [make_restaurant(f"r{i:02}", rating=3.0 + i / 20, votes=1000) for i in range(30)]
    selection = search(make_repository(*restaurants))
    assert len(selection.candidates) == 15
    assert selection.total_matches == 30
    assert ids(selection) == [f"r{i:02}" for i in range(29, 14, -1)]


def test_order_is_repeatable_with_a_tie_break_on_restaurant_id():
    restaurants = [make_restaurant(f"r{i:02}") for i in range(20)]
    expected = [f"r{i:02}" for i in range(15)]
    for seed in range(5):
        random.Random(seed).shuffle(restaurants)
        assert ids(search(make_repository(*restaurants))) == expected


def test_rated_restaurant_wins_a_tie_with_an_unrated_one(metadata):
    unrated = make_restaurant("a_unrated", rating=None)
    rated_tie = make_restaurant("z_rated", rating=3.1, votes=metadata.median_votes)
    assert weighted_rating(unrated, metadata) == pytest.approx(weighted_rating(rated_tie, metadata))
    selection = search(make_repository(unrated, rated_tie), include_unrated=True)
    assert ids(selection) == ["z_rated", "a_unrated"]


def test_custom_limits_are_respected():
    repository = make_repository(*[make_restaurant(f"r{i}") for i in range(10)])
    selection = select_candidates(
        Preferences(area="MG Road", min_rating=0.0), repository, max_candidates=3
    )
    assert len(selection.candidates) == 3
