"""Decides which dishes diners can choose from, and matches them to restaurants.

Dishes come from each restaurant's liked dishes, such as "Chicken Biryani". Drinks and broad
food groups are left out, singular and plural forms are merged, and only dishes liked at enough
restaurants are offered, with the most popular first.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable

# Liked "dishes" in the data that are drinks or broad food groups, written as matching keys.
NOT_DISHES = frozenset(
    {
        "beer",
        "buffet",
        "buttermilk",
        "cappuccino",
        "cocktail",
        "coffee",
        "cold coffee",
        "filter coffee",
        "ginger tea",
        "hot chocolate",
        "iced tea",
        "juice",
        "lassi",
        "lemonade",
        "lime soda",
        "lunch buffet",
        "masala chai",
        "milkshake",
        "mocktail",
        "mojito",
        "sangria",
        "sea food",
        "seafood",
        "shake",
        "smoothie",
        "sweet lassi",
        "tea",
        "thick shake",
        "wine",
    }
)
# Different names for the same dish, as matching keys, mapped to the key they're listed under.
ALIASES = {"french frie": "frie"}
# A dish must be liked at this many restaurants to be offered.
MIN_RESTAURANTS = 50
# This many of the most liked dishes are listed first.
POPULAR_COUNT = 10


def _stem(word: str) -> str:
    """Reduce a plural to its singular form, so that "Burgers" and "Burger" match."""
    if len(word) > 4 and word.endswith("es") and word[:-2].endswith(("ch", "sh", "x", "ss")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def dish_key(label: str) -> str:
    """Return the matching key for a dish, ignoring case, spacing and a plural last word."""
    words = label.casefold().split()
    key = " ".join([*words[:-1], _stem(words[-1])]) if words else ""
    return ALIASES.get(key, key)


def is_dish(label: str) -> bool:
    return bool(dish_key(label)) and dish_key(label) not in NOT_DISHES


def offered_dishes(dish_lists: Iterable[Iterable[str]]) -> tuple[list[str], list[str]]:
    """Return `(all_offered, popular)`: dishes liked at enough restaurants in alphabetical order,
    and the most liked ones in order of popularity.

    Each dish is shown under its most common spelling, such as "Burgers" for both "Burger" and
    "Burgers".
    """
    counts: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = defaultdict(Counter)
    for dishes in dish_lists:
        keys = set()
        for dish in dishes:
            label = " ".join(dish.split())
            if is_dish(label):
                key = dish_key(label)
                spellings[key][label] += 1
                keys.add(key)
        counts.update(keys)
    offered = {
        key: spellings[key].most_common(1)[0][0]
        for key, n in counts.items()
        if n >= MIN_RESTAURANTS
    }
    ranked = sorted(offered, key=lambda k: (-counts[k], k))
    return (
        sorted(offered.values(), key=str.casefold),
        [offered[key] for key in ranked[:POPULAR_COUNT]],
    )


def dish_pattern(label: str) -> re.Pattern[str]:
    """Match a dish as whole words, in either form, so "Biryani" also matches "Chicken Biryani"
    and "Burger" matches "Burgers"."""
    words = dish_key(label).split()
    body = r"\s+".join(re.escape(w) for w in words)
    return re.compile(rf"(?<![\w-]){body}(?:e?s)?(?![\w-])")


__all__ = [
    "MIN_RESTAURANTS",
    "NOT_DISHES",
    "POPULAR_COUNT",
    "dish_key",
    "dish_pattern",
    "is_dish",
    "offered_dishes",
]
