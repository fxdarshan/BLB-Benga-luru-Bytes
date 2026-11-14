import json
import re

import pytest

from conftest import make_metadata, make_repository, make_restaurant
from recommender.candidates import InvalidPreferencesError, select_candidates
from recommender.dishes import (
    MIN_RESTAURANTS,
    POPULAR_COUNT,
    dish_key,
    dish_pattern,
    is_dish,
    offered_dishes,
)
from recommender.display import matched_dishes, search_summary_parts
from recommender.models import Preferences
from recommender.prompts import MAX_DISHES_PER_CANDIDATE, build_prompt
from recommender.service import RecommendationService

DISHES = ("Biryani", "Burgers", "Fries", "Masala Dosa", "Pizza")


def repo(*restaurants):
    return make_repository(*restaurants, dishes=DISHES, popular_dishes=("Biryani",))


def search(repository, **preferences):
    preferences.setdefault("area", "MG Road")
    preferences.setdefault("min_rating", 0.0)
    return select_candidates(Preferences(**preferences), repository)


def ids(selection):
    return [c.restaurant.restaurant_id for c in selection.candidates]


# The dish list


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("Burgers", "burger"),
        ("Burger", "burger"),
        ("Sandwiches", "sandwich"),
        ("Chicken  Biryani", "chicken biryani"),
        ("French Fries", "frie"),
        ("Fries", "frie"),
    ],
)
def test_dish_keys_merge_case_spacing_and_plurals(label, key):
    assert dish_key(label) == key


@pytest.mark.parametrize(
    "label", ["Cocktails", "Coffee", "Masala Chai", "Lunch Buffet", "Sea Food", "Thick Shakes"]
)
def test_drinks_and_food_groups_are_not_dishes(label):
    assert not is_dish(label)


def test_offered_dishes_need_enough_restaurants_and_use_the_common_spelling():
    lists = (
        [["Burgers"]] * MIN_RESTAURANTS
        + [["Burger"]] * 3
        + [["Pasta"]] * (MIN_RESTAURANTS - 1)
        + [["Cocktails"]] * 99
    )
    offered, popular = offered_dishes(lists)
    assert offered == ["Burgers"]
    assert popular == ["Burgers"]


def test_each_restaurant_counts_once_per_dish():
    assert offered_dishes([["Burger", "Burgers"]] * (MIN_RESTAURANTS - 1))[0] == []


def test_popular_dishes_are_ranked_and_capped():
    lists = [[f"Dish {i:02}"] for i in range(15) for _ in range(MIN_RESTAURANTS + 15 - i)]
    offered, popular = offered_dishes(lists)
    assert len(popular) == POPULAR_COUNT
    assert popular[0] == "Dish 00"
    assert offered == sorted(offered, key=str.casefold)


@pytest.mark.parametrize(
    ("dish", "text", "matches"),
    [
        ("Biryani", "chicken biryani | north indian", True),
        ("Burgers", "veg burger", True),
        ("Fries", "french fries", True),
        ("Pizza", "pizzeria", False),
        ("Masala Dosa", "masala | dosa", False),
        ("Masala Dosa", "ghee masala dosa", True),
    ],
)
def test_dish_patterns_match_whole_words(dish, text, matches):
    assert bool(dish_pattern(dish).search(text)) is matches


# Search


def test_dish_filter_matches_liked_dishes_or_cuisine_labels():
    repository = repo(
        make_restaurant("liked", dishes=["Chicken Biryani"]),
        make_restaurant("label", cuisines=["Biryani", "North Indian"]),
        make_restaurant("other", dishes=["Pasta"]),
    )
    assert set(ids(search(repository, dishes=("Biryani",)))) == {"liked", "label"}


def test_any_chosen_dish_is_enough():
    repository = repo(
        make_restaurant("pizza", cuisines=["Pizza"]),
        make_restaurant("dosa", dishes=["Masala Dosa"]),
        make_restaurant("none"),
    )
    assert set(ids(search(repository, dishes=("Pizza", "Masala Dosa")))) == {"pizza", "dosa"}


def test_dish_and_cuisine_must_both_match():
    repository = repo(
        make_restaurant("both", cuisines=["Italian"], dishes=["Pizza"]),
        make_restaurant("dish_only", cuisines=["Thai"], dishes=["Pizza"]),
    )
    assert ids(search(repository, cuisines=("Italian",), dishes=("Pizza",))) == ["both"]


def test_dish_is_never_relaxed():
    repository = repo(*[make_restaurant(f"r{i}", rating=4.5) for i in range(5)])
    assert search(repository, dishes=("Pizza",)).candidates == []


def test_unknown_dish_is_rejected():
    with pytest.raises(InvalidPreferencesError, match="dishes"):
        search(repo(make_restaurant()), dishes=("Unicorn Steak",))


def test_preferences_clean_dish_names():
    assert Preferences(area="X", dishes=(" Pizza ", "pizza", "")).dishes == ("Pizza",)


# Prompt, cache and display


def test_prompt_sends_chosen_dishes_and_puts_matching_liked_dishes_first():
    restaurant = make_restaurant(dishes=[f"Dish {i}" for i in range(12)] + ["Chicken Biryani"])
    repository = repo(restaurant)
    preferences = Preferences(area="MG Road", min_rating=0.0, dishes=("Biryani",))
    selection = select_candidates(preferences, repository)
    prompt = build_prompt(preferences, selection, repository.metadata)
    message = prompt.user_message
    requested = re.search(r"<preferences>\n(.*?)\n</preferences>", message, re.S).group(1)
    assert json.loads(requested)["dishes"] == ["Biryani"]
    candidates = re.search(r"<candidates>\n(.*?)\n</candidates>", message, re.S).group(1)
    liked = json.loads(candidates)[0]["liked_dishes"]
    assert liked[0] == "Chicken Biryani"
    assert len(liked) == MAX_DISHES_PER_CANDIDATE


def test_dishes_are_part_of_the_cache_key():
    service = RecommendationService(repo(make_restaurant()))
    plain = service.cache_key(Preferences(area="MG Road"))
    with_dish = service.cache_key(Preferences(area="MG Road", dishes=("Pizza",)))
    reordered = service.cache_key(Preferences(area="MG Road", dishes=("pizza", "Fries")))
    assert plain != with_dish
    assert reordered == service.cache_key(Preferences(area="MG Road", dishes=("Fries", "Pizza")))


def test_matching_dishes_are_listed_from_liked_dishes_and_labels():
    restaurant = make_restaurant(
        dishes=["Chicken Biryani", "Pasta", "Mutton Biryani"], cuisines=["Biryani", "Mughlai"]
    )
    expected = ["Chicken Biryani", "Mutton Biryani", "Biryani"]
    assert matched_dishes(restaurant, ["Biryani"]) == expected
    assert matched_dishes(restaurant, []) == []


def test_search_summary_lists_chosen_dishes():
    bands = make_metadata().budget_bands
    parts = search_summary_parts(Preferences(area="BTM", dishes=("Pizza", "Fries")), bands)
    assert "Pizza, Fries" in parts
