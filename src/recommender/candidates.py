"""Selects the restaurants that match a search, and scores them for the LLM to rank."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from recommender.models import (
    Candidate,
    CandidateSelection,
    DatasetMetadata,
    Preferences,
    Relaxation,
    Restaurant,
)
from recommender.repository import RestaurantRepository

DEFAULT_MAX_CANDIDATES = 15
DEFAULT_MIN_RESULTS = 5
RATING_RELAXATION_STEP = 0.5
# These values are starting points, to tune during evaluation.
LOCATION_BOOST = 0.5
KEYWORD_BOOST = 0.25
MAX_KEYWORD_HITS = 2
UNRATED_PENALTY = 0.25

BUDGET_ORDER = ("low", "medium", "high")

_COMMON_WORDS = frozenset(
    "a about an and any are as at be but by can for from get good great i in is it like me my near "
    "nice no not of on or place please really restaurant somewhere that the to very want we where "
    "which with would you".split()
)
# Words found in so many reviews that matching them says nothing about a restaurant.
_COMMON_REVIEW_WORDS = frozenset(
    "ambience best experience food friends new order ordered places quality service staff taste "
    "tasty time try trying visit visited worth".split()
)
_IGNORED_WORDS = _COMMON_WORDS | _COMMON_REVIEW_WORDS


class InvalidPreferencesError(ValueError):
    """Raised when a search names an area or cuisine that isn't in the data."""


def check_preferences(preferences: Preferences, metadata: DatasetMetadata) -> None:
    if preferences.area not in metadata.areas:
        raise InvalidPreferencesError(f"Unknown area: {preferences.area!r}")
    known = {cuisine.casefold() for cuisine in metadata.cuisines}
    unknown = [c for c in preferences.cuisines if c.casefold() not in known]
    if unknown:
        raise InvalidPreferencesError(f"Unknown cuisines: {unknown}")


def _budget_bands(budget: str) -> tuple[str, ...]:
    return () if budget == "any" else (budget,)


def _meets_rating(restaurant: Restaurant, min_rating: float, include_unrated: bool) -> bool:
    if restaurant.rating is None:
        return include_unrated
    return restaurant.rating >= min_rating


def _meets_budget(
    restaurant: Restaurant, budgets: Sequence[str], metadata: DatasetMetadata
) -> bool:
    if not budgets:
        return True
    cost = restaurant.cost_for_two
    return cost is not None and any(metadata.budget_bands[b].contains(cost) for b in budgets)


def _filter(
    preferences: Preferences,
    repository: RestaurantRepository,
    min_rating: float,
    budgets: Sequence[str],
) -> list[Restaurant]:
    metadata = repository.metadata
    cuisine_keys = {cuisine.casefold() for cuisine in preferences.cuisines}
    return [
        restaurant
        for restaurant in repository.in_area(preferences.area)
        if (not cuisine_keys or cuisine_keys & restaurant.cuisine_keys)
        and _meets_budget(restaurant, budgets, metadata)
        and _meets_rating(restaurant, min_rating, preferences.include_unrated)
    ]


def _budget_label(budgets: Sequence[str], metadata: DatasetMetadata) -> str:
    return " or ".join(f"{b} ({metadata.budget_bands[b].label()})" for b in budgets)


def extract_keyword_patterns(text: str) -> list[re.Pattern[str]]:
    """Build one pattern per comma-separated phrase.

    A pattern matches the whole phrase or any of its remaining words, as whole words only, so
    that "bar" doesn't match "barbecue" and "veg" doesn't match "non-veg". A phrase made up of
    only ignored words gives no pattern.
    """
    patterns: list[re.Pattern[str]] = []
    seen: set[str] = set()
    for raw_phrase in text.casefold().split(","):
        words = raw_phrase.split()
        phrase = " ".join(words)
        remaining = [word for word in words if word.strip(".!?'\"()") not in _IGNORED_WORDS]
        if not remaining or phrase in seen:
            continue
        seen.add(phrase)
        options = [re.escape(phrase).replace(r"\ ", r"\s+"), *map(re.escape, remaining)]
        patterns.append(re.compile(rf"(?<![\w-])(?:{'|'.join(options)})(?![\w-])"))
    return patterns


def count_keyword_hits(restaurant: Restaurant, patterns: Iterable[re.Pattern[str]]) -> int:
    return sum(1 for pattern in patterns if pattern.search(restaurant.search_text))


def weighted_rating(restaurant: Restaurant, metadata: DatasetMetadata) -> float:
    """Pull a rating toward the mean when it has few votes, as it is then weak evidence."""
    mean = metadata.mean_rating
    if restaurant.rating is None:
        return mean - UNRATED_PENALTY
    votes, prior = restaurant.votes, metadata.median_votes
    return (votes / (votes + prior)) * restaurant.rating + (prior / (votes + prior)) * mean


def area_pattern(area: str) -> re.Pattern[str]:
    words = r"\s+".join(re.escape(word) for word in area.casefold().split())
    return re.compile(rf"(?<![\w-]){words}(?![\w-])")


def score_restaurant(
    restaurant: Restaurant,
    hits: int,
    metadata: DatasetMetadata,
    *,
    in_chosen_area: bool = False,
) -> float:
    keyword_boost = KEYWORD_BOOST * min(hits, MAX_KEYWORD_HITS)
    location_boost = LOCATION_BOOST if in_chosen_area else 0.0
    return weighted_rating(restaurant, metadata) + keyword_boost + location_boost


def _select_with_relaxation(
    preferences: Preferences,
    repository: RestaurantRepository,
    min_results: int,
) -> tuple[list[Restaurant], list[Relaxation], float, tuple[str, ...]]:
    """Loosen the rating, then the budget, once each, until enough restaurants match.

    A relaxation that adds no restaurants is undone and not reported. Area and cuisine are never
    relaxed, because results outside them wouldn't be what the diner asked for.
    """
    metadata = repository.metadata
    min_rating = preferences.min_rating
    budgets = _budget_bands(preferences.budget)
    matches = _filter(preferences, repository, min_rating, budgets)
    relaxations: list[Relaxation] = []

    if len(matches) < min_results and min_rating > 0:
        lower = max(0.0, round(min_rating - RATING_RELAXATION_STEP, 1))
        wider = _filter(preferences, repository, lower, budgets)
        if len(wider) > len(matches):
            relaxations.append(
                Relaxation(
                    limit="min_rating",
                    requested=f"{min_rating:.1f}",
                    applied=f"{lower:.1f}",
                    message=(
                        f"Few matches at {min_rating:.1f}+, so this includes "
                        f"restaurants rated {lower:.1f}+."
                    ),
                )
            )
            matches, min_rating = wider, lower

    if len(matches) < min_results and budgets and budgets[-1] != BUDGET_ORDER[-1]:
        next_band = BUDGET_ORDER[BUDGET_ORDER.index(budgets[-1]) + 1]
        wider_budgets = (*budgets, next_band)
        wider = _filter(preferences, repository, min_rating, wider_budgets)
        if len(wider) > len(matches):
            relaxations.append(
                Relaxation(
                    limit="budget",
                    requested=budgets[-1],
                    applied=" and ".join(wider_budgets),
                    message=(
                        f"Few matches in the {_budget_label(budgets, metadata)} budget, so this "
                        f"also includes {_budget_label((next_band,), metadata)}."
                    ),
                )
            )
            matches, budgets = wider, wider_budgets

    return matches, relaxations, min_rating, budgets


def select_candidates(
    preferences: Preferences,
    repository: RestaurantRepository,
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    min_results: int = DEFAULT_MIN_RESULTS,
) -> CandidateSelection:
    """Return the best-scoring restaurants that match, in a repeatable order."""
    metadata = repository.metadata
    check_preferences(preferences, metadata)
    matches, relaxations, min_rating, budgets = _select_with_relaxation(
        preferences, repository, min_results
    )
    patterns = extract_keyword_patterns(preferences.additional)
    area = area_pattern(preferences.area)
    scored = []
    for restaurant in matches:
        hits = count_keyword_hits(restaurant, patterns)
        # An area's listings include many restaurants located elsewhere, so favour local ones.
        local = bool(area.search(restaurant.location_text))
        score = score_restaurant(restaurant, hits, metadata, in_chosen_area=local)
        scored.append(Candidate(restaurant, score, hits, local))
    scored.sort(key=lambda c: (-c.score, c.restaurant.rating is None, c.restaurant.restaurant_id))
    return CandidateSelection(
        candidates=scored[:max_candidates],
        relaxations=relaxations,
        applied_min_rating=min_rating,
        applied_budgets=budgets,
        total_matches=len(matches),
    )
