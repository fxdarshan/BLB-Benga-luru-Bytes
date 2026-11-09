from recommender.cuisines import (
    MIN_RESTAURANTS,
    NOT_CUISINES,
    POPULAR_COUNT,
    cuisine_counts,
    menu_order,
    offered_cuisines,
)


def lists(**counts):
    """Build cuisine lists where each cuisine appears in the given number of restaurants."""
    return [[name.replace("_", " ")] for name, n in counts.items() for _ in range(n)]


def test_dishes_drinks_and_places_are_not_cuisines():
    counts = cuisine_counts([["Pizza", "Italian"], ["Bubble Tea"], ["Cafe", "Biryani"]])
    assert counts == {"Italian": 1}
    for label in ("Pizza", "Bubble Tea", "Cafe", "Biryani", "Fast Food", "Desserts"):
        assert label.casefold() in NOT_CUISINES


def test_rare_cuisines_are_left_out():
    offered, _ = offered_cuisines(lists(Thai=MIN_RESTAURANTS, Australian=MIN_RESTAURANTS - 1))
    assert offered == ["Thai"]


def test_each_restaurant_counts_once_per_cuisine():
    assert cuisine_counts([["Thai", "Thai"]]) == {"Thai": 1}


def test_offered_cuisines_are_alphabetical_and_popular_ones_ranked():
    offered, popular = offered_cuisines(
        lists(Zulu=100, Andhra=50, Chinese=300, North_Indian=500, Kerala=20)
    )
    assert offered == ["Andhra", "Chinese", "Kerala", "North Indian", "Zulu"]
    assert popular == ["North Indian", "Chinese", "Zulu", "Andhra", "Kerala"]


def test_popular_list_is_capped():
    names = {f"C{i:02}": 100 - i for i in range(15)}
    _, popular = offered_cuisines(lists(**names))
    assert len(popular) == POPULAR_COUNT
    assert popular[0] == "C00"


def test_menu_puts_popular_first_then_the_rest_alphabetically():
    menu = menu_order(
        ["Andhra", "Chinese", "Kerala", "North Indian", "Thai"], ["North Indian", "Chinese"]
    )
    assert menu == ["North Indian", "Chinese", "Andhra", "Kerala", "Thai"]


def test_menu_without_popular_cuisines_is_alphabetical():
    assert menu_order(["Thai", "andhra", "Chinese"], []) == ["andhra", "Chinese", "Thai"]
