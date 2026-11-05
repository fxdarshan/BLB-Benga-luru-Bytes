"""Formats search results for display. All dataset and user text is escaped here."""

from __future__ import annotations

from html import escape

from recommender.models import BudgetBand, Candidate, Preferences, Restaurant

NOT_LISTED = "Not listed"

_CARD_STYLE = (
    "border: 1px solid rgba(128, 128, 128, 0.35); border-radius: 0.5rem; "
    "padding: 0.9rem 1.1rem; overflow-wrap: anywhere;"
)
_TITLE_STYLE = (
    "display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.25rem 1rem; "
    "font-size: 1.1rem; font-weight: 600;"
)
_RATING_STYLE = "font-size: 0.95rem; font-weight: 500; white-space: nowrap;"
_DETAIL_STYLE = "margin-top: 0.3rem; opacity: 0.8;"
_NEARBY_STYLE = "margin-top: 0.3rem; opacity: 0.8; font-size: 0.9rem; font-style: italic;"


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
    return ", ".join(restaurant.cuisines) or f"Cuisine: {NOT_LISTED.lower()}"


def budget_option_label(name: str, bands: dict[str, BudgetBand]) -> str:
    if name == "any":
        return "Any budget"
    return f"{name.capitalize()} ({bands[name].label()} for two)"


def search_summary(preferences: Preferences, bands: dict[str, BudgetBand]) -> str:
    """Describe a search in words, returned as escaped HTML."""
    parts = [preferences.area, budget_option_label(preferences.budget, bands)]
    parts.append(", ".join(preferences.cuisines) or "Any cuisine")
    rating = f"Rated {preferences.min_rating:.1f}+"
    parts.append(f"{rating}, or unrated" if preferences.include_unrated else rating)
    if preferences.additional:
        parts.append(f"“{preferences.additional}”")
    summary = " · ".join(escape(part) for part in parts)
    return f'<div style="opacity: 0.8;">Results for: {summary}</div>'


def result_card(position: int, candidate: Candidate, chosen_area: str) -> str:
    """Build one result card as HTML, with every value escaped so that it displays literally."""
    restaurant = candidate.restaurant
    place = restaurant.location or NOT_LISTED
    details = [format_cost(restaurant), *restaurant.rest_types[:2]]
    nearby = ""
    if not candidate.in_chosen_area:
        nearby = f'<div style="{_NEARBY_STYLE}">Near {escape(chosen_area)}</div>'
    return (
        f'<div style="{_CARD_STYLE}">'
        f'<div style="{_TITLE_STYLE}">'
        f"<span>{position}. {escape(restaurant.name)}</span>"
        f'<span style="{_RATING_STYLE}">{escape(format_rating(restaurant))}</span>'
        "</div>"
        f'<div style="{_DETAIL_STYLE}">'
        f"{escape(format_cuisines(restaurant))} · {escape(place)}"
        "</div>"
        f'<div style="{_DETAIL_STYLE}">{" · ".join(escape(d) for d in details)}</div>'
        f"{nearby}"
        "</div>"
    )
