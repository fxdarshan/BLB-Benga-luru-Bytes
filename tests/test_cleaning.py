from collections import Counter

import pytest

from recommender import cleaning


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4.1/5", (4.1, False)),
        ("3.6 /5", (3.6, False)),
        ("5/5", (5.0, False)),
        ("0/5", (0.0, False)),
        ("NEW", (None, True)),
        (" new ", (None, True)),
        ("-", (None, False)),
        (None, (None, False)),
        (float("nan"), (None, False)),
        ("6.0/5", (None, False)),
        ("4.1.2/5", (None, False)),
        ("./5", (None, False)),
        ("great", (None, False)),
    ],
)
def test_parse_rate(raw, expected):
    assert cleaning.parse_rate(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("800", 800),
        ("1,300", 1300),
        (" 6,000 ", 6000),
        (None, None),
        (float("nan"), None),
        ("about 500", None),
        ("0", None),
        ("-200", None),
    ],
)
def test_parse_cost(raw, expected):
    assert cleaning.parse_cost(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"), [("Yes", True), ("no", False), ("Maybe", None), (None, None)]
)
def test_parse_yes_no(raw, expected):
    assert cleaning.parse_yes_no(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("North Indian, Mughlai, Chinese", ["North Indian", "Mughlai", "Chinese"]),
        ("Chinese, , Chinese,", ["Chinese"]),
        ("BBQ, bbq", ["BBQ"]),
        (None, []),
        (float("nan"), []),
        ("", []),
    ],
)
def test_split_multi_value(raw, expected):
    assert cleaning.split_multi_value(raw) == expected


# A review apostrophe exactly as it is corrupted in the dataset, once parsed.
LAYERED_APOSTROPHE = "Ã\x83\x83Ã\x82\x83Ã\x83\x82Ã\x82\x82Ã\x83\x83Ã\x82\x82Ã\x83\x82Ã\x82\x92"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Plain text", "Plain text"),
        (None, None),
        ("Café Delight", "Café Delight"),
        ("CafÃ©", "Café"),
        (f"It{LAYERED_APOSTROPHE}s small", "It's small"),
        ("Bar Ã\x83Â\x82Ã\x82Â°C", "Bar °C"),
    ],
)
def test_repair_text(raw, expected):
    assert cleaning.repair_text(raw) == expected


def test_repair_text_leaves_no_residue_on_layered_corruption():
    assert not cleaning.has_mojibake(cleaning.repair_text(f"It{LAYERED_APOSTROPHE}s"))


def test_has_mojibake_detects_corruption():
    assert cleaning.has_mojibake(f"It{LAYERED_APOSTROPHE}s")
    assert not cleaning.has_mojibake("A clean café review")


def test_parse_reviews_extracts_text_without_prefix():
    raw = "[('Rated 4.0', 'RATED\\n  Tasty food'), ('Rated 3.0', 'RATED\\n  Slow\\nservice')]"
    assert cleaning.parse_reviews(raw) == ["Tasty food", "Slow service"]


def test_parse_reviews_handles_empty_list():
    stats = Counter()
    assert cleaning.parse_reviews("[]", stats=stats) == []
    assert stats["review_parse_failures"] == 0


@pytest.mark.parametrize("raw", ["[('Rated 4.0', 'unterminated", "not a list", "{'a': 1}", "42"])
def test_parse_reviews_counts_malformed_input(raw):
    stats = Counter()
    assert cleaning.parse_reviews(raw, stats=stats) == []
    assert stats["review_parse_failures"] == 1


def test_parse_reviews_does_not_execute_code():
    assert cleaning.parse_reviews("__import__('os').getcwd()") == []


def test_parse_reviews_repairs_escaped_mojibake_after_parsing():
    # In the raw value, `\\x83` is a literal backslash sequence that only becomes a real
    # character once parsed, so repairing before parsing can't fix it.
    escaped = "Ã\\x83\\x83Ã\\x82\\x83Ã\\x83\\x82Ã\\x82\\x82"
    escaped += "Ã\\x83\\x83Ã\\x82\\x82Ã\\x83\\x82Ã\\x82\\x92"
    raw = f"[('Rated 5.0', 'RATED\\n  It{escaped}s good')]"
    assert cleaning.parse_reviews(raw) == ["It's good"]


def test_parse_reviews_skips_bad_items_and_empty_text():
    stats = Counter()
    raw = "[('Rated 4.0', 'RATED\\n  '), ('only one',), 7, ('Rated 5.0', 'RATED\\n  Good')]"
    assert cleaning.parse_reviews(raw, stats=stats) == ["Good"]
    assert stats["review_items_skipped"] == 2


def test_parse_reviews_keeps_at_most_five():
    raw = repr([("Rated 4.0", f"RATED\n  Review {i}") for i in range(8)])
    assert cleaning.parse_reviews(raw) == [f"Review {i}" for i in range(5)]


def test_parse_reviews_cuts_at_a_word_boundary():
    raw = repr([("Rated 4.0", "RATED\n  " + "word " * 100)])
    snippet = cleaning.parse_reviews(raw)[0]
    assert len(snippet) <= cleaning.MAX_REVIEW_CHARS
    assert snippet.endswith("word")


def test_parse_reviews_rejects_oversized_values():
    stats = Counter()
    raw = "[" + " " * (cleaning.MAX_RAW_REVIEW_CHARS + 1) + "]"
    assert cleaning.parse_reviews(raw, stats=stats) == []
    assert stats["review_parse_failures"] == 1


def test_parse_reviews_survives_deep_nesting():
    assert cleaning.parse_reviews("[" * 100_000) == []


def test_normalise_key_ignores_case_accents_punctuation_and_spacing():
    first = cleaning.normalise_key("Café  Mor'ish", "#12, MG Road, Bangalore")
    second = cleaning.normalise_key("CAFE MOR ISH", "12 MG road Bangalore")
    assert first == second


def test_normalise_key_keeps_different_branches_apart():
    assert cleaning.normalise_key("Chain", "MG Road") != cleaning.normalise_key("Chain", "BTM")


def test_restaurant_id_is_stable():
    key = cleaning.normalise_key("Jalsa", "Banashankari")
    assert cleaning.restaurant_id(key) == cleaning.restaurant_id(key)
    assert len(cleaning.restaurant_id(key)) == 16
    assert cleaning.restaurant_id("a") != cleaning.restaurant_id("b")
