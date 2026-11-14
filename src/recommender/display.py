"""Formats search results as plain text for the API. The web page sets every value with
textContent, so dataset, review and LLM text always displays literally."""

from __future__ import annotations

from collections.abc import Sequence

from recommender.cuisines import is_cuisine
from recommender.dishes import dish_pattern
from recommender.models import BudgetBand, Preferences, Restaurant

NOT_LISTED = "Not listed"
# About two lines on a card. Longer reviews are cut at a word, with an ellipsis.
MAX_REVIEW_CHARS = 200


def format_rating(restaurant: Restaurant) -> str:
    if restaurant.rating is not None:
        votes = f"{restaurant.votes:,} vote{'' if restaurant.votes == 1 else 's'}"
        return f"★ {restaurant.rating:.1f} ({votes})"
    return "New" if restaurant.is_new else "Unrated"


def format_cost(restaurant: Restaurant) -> str:
    if restaurant.cost_for_two is None:
        return f"Cost: {NOT_LISTED.lower()}"
    return f"₹{restaurant.cost_for_two:,} for two"


def format_cuisines(restaurant: Restaurant) -> str:
    """List real cuisines, leaving out labels such as Pizza or Cafe. A restaurant listed only with
    such labels, such as a biryani place, shows them instead, so its card still says what it
    serves."""
    cuisines = [c for c in restaurant.cuisines if is_cuisine(c)] or restaurant.cuisines
    return ", ".join(cuisines) or f"Cuisine: {NOT_LISTED.lower()}"


def budget_option_label(name: str, bands: dict[str, BudgetBand]) -> str:
    if name == "any":
        return "Any budget"
    return f"{name.capitalize()} ({bands[name].label()} for two)"


def search_summary_parts(preferences: Preferences, bands: dict[str, BudgetBand]) -> list[str]:
    """Describe a search in words, one plain-text chip per part."""
    parts = [preferences.area, budget_option_label(preferences.budget, bands)]
    parts.append(", ".join(preferences.cuisines) or "Any cuisine")
    if preferences.dishes:
        parts.append(", ".join(preferences.dishes))
    rating = f"Rated {preferences.min_rating:.1f}+"
    parts.append(f"{rating}, or unrated" if preferences.include_unrated else rating)
    if preferences.additional:
        parts.append(f"“{preferences.additional}”")
    return parts


def shorten_review(review: str | None) -> str | None:
    """A customer's review cut to about two lines, at a word, as plain text."""
    if not review or not review.strip():
        return None
    text = review.strip()
    if len(text) > MAX_REVIEW_CHARS:
        text = text[:MAX_REVIEW_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"
    return text


def matched_dishes(restaurant: Restaurant, chosen: Sequence[str]) -> list[str]:
    """Return the restaurant's liked dishes or labels that match the chosen dishes."""
    patterns = [dish_pattern(d) for d in chosen]
    labels = [*restaurant.dishes, *restaurant.cuisines]
    found = [label for label in labels if any(p.search(label.casefold()) for p in patterns)]
    return list(dict.fromkeys(found))
