import json
import math

import pandas as pd
import pytest

from recommender import ingest
from recommender.repository import DataUnavailableError, RestaurantRepository
from test_ingest import run, varied_rows


@pytest.fixture
def data_files(tmp_path):
    rows = varied_rows()
    rows[0].update({"rate": None, "location": None, ingest.COST_COLUMN: None, "dish_liked": None})
    result = run(rows)
    paths = tmp_path / "restaurants.parquet", tmp_path / "metadata.json"
    ingest.write_outputs(result, *paths)
    return paths


def test_records_use_plain_python_values(data_files):
    repository = RestaurantRepository.load(*data_files)
    assert len(repository.restaurants) == 30
    for restaurant in repository.restaurants:
        assert restaurant.rating is None or type(restaurant.rating) is float
        assert restaurant.cost_for_two is None or type(restaurant.cost_for_two) is int
        assert type(restaurant.votes) is int
        assert type(restaurant.is_new) is bool
        assert type(restaurant.online_order) is bool
        for values in (
            restaurant.cuisines,
            restaurant.rest_types,
            restaurant.dishes,
            restaurant.review_snippets,
        ):
            assert type(values) is list
        assert type(restaurant.areas) is frozenset


def test_missing_values_load_as_none_not_nan(data_files):
    # This row is the one with the missing values, and also shows they were stored as nulls.
    frame = pd.read_parquet(data_files[0])
    assert frame["rating"].isna().sum() == 1
    repository = RestaurantRepository.load(*data_files)
    missing = [r for r in repository.restaurants if r.name == "Place 0"][0]
    assert missing.rating is None
    assert missing.cost_for_two is None
    assert missing.location is None
    assert missing.dishes == []
    for restaurant in repository.restaurants:
        assert not (isinstance(restaurant.rating, float) and math.isnan(restaurant.rating))


def test_in_area_finds_restaurants_by_any_listed_area(data_files):
    repository = RestaurantRepository.load(*data_files)
    assert {r.areas for r in repository.in_area("BTM")} == {frozenset({"BTM"})}
    assert repository.in_area("Nowhere") == ()


def test_metadata_is_loaded(data_files):
    metadata = RestaurantRepository.load(*data_files).metadata
    assert metadata.areas == ("BTM", "HSR", "MG Road")
    assert set(metadata.budget_bands) == {"low", "medium", "high"}


@pytest.mark.parametrize("missing_index", [0, 1])
def test_missing_file_names_the_ingest_command(data_files, missing_index):
    data_files[missing_index].unlink()
    with pytest.raises(DataUnavailableError, match="recommender.ingest"):
        RestaurantRepository.load(*data_files)


def test_damaged_parquet_gives_a_clear_error(data_files):
    data_files[0].write_bytes(b"not a parquet file")
    with pytest.raises(DataUnavailableError, match="damaged or out of date"):
        RestaurantRepository.load(*data_files)


@pytest.mark.parametrize("content", ["{not json", '{"build_id": "only this"}'])
def test_damaged_metadata_gives_a_clear_error(data_files, content):
    data_files[1].write_text(content, encoding="utf-8")
    with pytest.raises(DataUnavailableError, match="damaged or out of date"):
        RestaurantRepository.load(*data_files)


def test_parquet_from_an_older_format_gives_a_clear_error(data_files):
    frame = pd.read_parquet(data_files[0]).drop(columns="votes")
    frame.to_parquet(data_files[0])
    with pytest.raises(DataUnavailableError, match="damaged or out of date"):
        RestaurantRepository.load(*data_files)


def test_files_from_different_builds_are_rejected(data_files):
    metadata = json.loads(data_files[1].read_text(encoding="utf-8"))
    metadata["build_id"] = "another-build"
    data_files[1].write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(DataUnavailableError, match="different builds"):
        RestaurantRepository.load(*data_files)
