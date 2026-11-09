"""Decides which cuisine labels diners can choose from.

The dataset's cuisine column mixes real cuisines, such as Kerala or Thai, with dishes, drinks and
types of place, such as Pizza, Bubble Tea or Cafe. Only real cuisines that enough restaurants
serve are offered, with the most popular first.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

# Labels in the data that name a dish, a drink, a type of food or a type of place, not a cuisine.
NOT_CUISINES = frozenset(
    label.casefold()
    for label in (
        "Bakery",
        "Bar Food",
        "BBQ",
        "Beverages",
        "Biryani",
        "Bubble Tea",
        "Burger",
        "Cafe",
        "Charcoal Chicken",
        "Coffee",
        "Desserts",
        "Drinks Only",
        "Fast Food",
        "Finger Food",
        "Grill",
        "Healthy Food",
        "Hot dogs",
        "Ice Cream",
        "Indian",
        "Juices",
        "Kebab",
        "Mithai",
        "Modern Indian",
        "Momos",
        "Paan",
        "Pizza",
        "Raw Meats",
        "Roast Chicken",
        "Rolls",
        "Salad",
        "Sandwich",
        "Seafood",
        "Steak",
        "Street Food",
        "Sushi",
        "Tea",
        "Vegan",
        "Wraps",
    )
)
# A cuisine must be served by at least this many restaurants to be offered.
MIN_RESTAURANTS = 20
# This many of the most widely served cuisines are listed first.
POPULAR_COUNT = 8


def cuisine_counts(cuisine_lists: Iterable[Iterable[str]]) -> Counter[str]:
    """Count the restaurants serving each real cuisine."""
    counts: Counter[str] = Counter()
    for cuisines in cuisine_lists:
        for cuisine in set(cuisines):
            if cuisine.casefold() not in NOT_CUISINES:
                counts[cuisine] += 1
    return counts


def offered_cuisines(cuisine_lists: Iterable[Iterable[str]]) -> tuple[list[str], list[str]]:
    """Return `(all_offered, popular)`: every offered cuisine in alphabetical order, and the most
    widely served ones in order of popularity."""
    counts = cuisine_counts(cuisine_lists)
    offered = [c for c, n in counts.items() if n >= MIN_RESTAURANTS]
    ranked = sorted(offered, key=lambda c: (-counts[c], c.casefold()))
    return sorted(offered, key=str.casefold), ranked[:POPULAR_COUNT]


def is_cuisine(label: str) -> bool:
    """Return False for labels that name a dish, drink or type of place, such as Pizza."""
    return label.casefold() not in NOT_CUISINES


def menu_order(cuisines: Iterable[str], popular: Iterable[str]) -> list[str]:
    """Order cuisines for the form: popular ones first, then the rest alphabetically."""
    popular_list = [c for c in popular if c in set(cuisines)]
    rest = sorted((c for c in cuisines if c not in set(popular_list)), key=str.casefold)
    return popular_list + rest
