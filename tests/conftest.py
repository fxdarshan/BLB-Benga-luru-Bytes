import pytest

from recommender.models import BudgetBand, DatasetMetadata, Restaurant
from recommender.repository import RestaurantRepository

BANDS = {
    "low": BudgetBand(min=100, max=300),
    "medium": BudgetBand(min=400, max=600),
    "high": BudgetBand(min=700, max=None),
}


def make_restaurant(identifier="r1", **overrides):
    values = {
        "restaurant_id": identifier,
        "name": f"Restaurant {identifier}",
        "address": f"{identifier} Road, Bangalore",
        "location": "MG Road",
        "areas": frozenset({"MG Road"}),
        "listing_types": frozenset({"Dine-out"}),
        "cuisines": ["Italian"],
        "rest_types": ["Casual Dining"],
        "dishes": [],
        "rating": 4.0,
        "votes": 100,
        "is_new": False,
        "cost_for_two": 500,
        "online_order": False,
        "book_table": False,
        "review_snippets": [],
    }
    return Restaurant(**{**values, **overrides})


def make_metadata(**overrides):
    values = {
        "build_id": "test-build",
        "areas": ("MG Road", "BTM"),
        "cuisines": ("BBQ", "Chinese", "Italian", "Thai"),
        "budget_bands": BANDS,
        "mean_rating": 3.6,
        "median_votes": 25,
    }
    return DatasetMetadata(**{**values, **overrides})


def make_repository(*restaurants, **metadata_overrides):
    return RestaurantRepository(restaurants, make_metadata(**metadata_overrides))


@pytest.fixture
def metadata():
    return make_metadata()
