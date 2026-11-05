import json
from collections import Counter

import pandas as pd
import pyarrow.parquet as pq
import pytest

from recommender import ingest
from recommender.ingest import IngestionError


def raw_row(**overrides):
    row = {
        "url": "https://www.zomato.com/bangalore/place?context=abc",
        "address": "1 MG Road, Bangalore",
        "name": "Place",
        "online_order": "Yes",
        "book_table": "No",
        "rate": "4.0/5",
        "votes": 100,
        "phone": "080 1234",
        "location": "MG Road",
        "rest_type": "Casual Dining",
        "dish_liked": "Pasta, Pizza",
        "cuisines": "Italian",
        ingest.COST_COLUMN: "800",
        "reviews_list": "[('Rated 4.0', 'RATED\\n  Tasty')]",
        "menu_item": "[]",
        ingest.TYPE_COLUMN: "Dine-out",
        ingest.AREA_COLUMN: "MG Road",
    }
    return {**row, **overrides}


def varied_rows(count=30):
    """Distinct restaurants, with evenly spread costs across three areas."""
    return [
        raw_row(
            name=f"Place {i}",
            address=f"{i} Road, Bangalore",
            url=f"https://www.zomato.com/bangalore/place-{i}?context=x",
            **{
                ingest.COST_COLUMN: f"{(i % 6 + 1) * 200:,}",
                ingest.AREA_COLUMN: ("MG Road", "BTM", "HSR")[i % 3],
            },
        )
        for i in range(count)
    ]


def run(rows, **kwargs):
    raw = pd.DataFrame(rows)
    defaults = {"expected_rows": len(raw), "expected_areas": 3}
    return ingest.run_pipeline(raw, **{**defaults, **kwargs})


def test_deduplicate_merges_areas_and_listing_types():
    rows = ingest.clean_rows(
        pd.DataFrame(
            [
                raw_row(**{ingest.AREA_COLUMN: "MG Road", ingest.TYPE_COLUMN: "Delivery"}),
                raw_row(**{ingest.AREA_COLUMN: "Brigade Road", ingest.TYPE_COLUMN: "Dine-out"}),
                raw_row(**{ingest.AREA_COLUMN: "MG Road", ingest.TYPE_COLUMN: "Dine-out"}),
            ]
        )
    )
    merged = ingest.deduplicate(rows)
    assert len(merged) == 1
    assert merged.loc[0, "areas"] == ["Brigade Road", "MG Road"]
    assert merged.loc[0, "listing_types"] == ["Delivery", "Dine-out"]


def test_deduplicate_ignores_formatting_differences_but_keeps_branches_apart():
    rows = ingest.clean_rows(
        pd.DataFrame(
            [
                raw_row(name="Café One", address="#12, MG Road"),
                raw_row(name="CAFE ONE", address="12 MG Road"),
                raw_row(name="Cafe One", address="5 BTM Layout"),
            ]
        )
    )
    assert len(ingest.deduplicate(rows)) == 2


def test_deduplicate_keeps_the_row_with_the_most_votes():
    rows = ingest.clean_rows(
        pd.DataFrame(
            [
                raw_row(rate="3.0/5", votes=5, cuisines="Thai"),
                raw_row(rate="4.5/5", votes=500, cuisines="Italian"),
            ]
        )
    )
    merged = ingest.deduplicate(rows)
    assert merged.loc[0, "rating"] == 4.5
    assert merged.loc[0, "votes"] == 500
    assert merged.loc[0, "cuisines"] == ["Italian"]


def test_deduplicate_breaks_vote_ties_by_original_order():
    frame = pd.DataFrame([raw_row(rate="3.0/5"), raw_row(rate="4.5/5")])
    assert ingest.deduplicate(ingest.clean_rows(frame)).loc[0, "rating"] == 3.0


def test_deduplicate_fills_missing_values_from_other_rows():
    rows = ingest.clean_rows(
        pd.DataFrame(
            [
                raw_row(
                    rate=None,
                    votes=50,
                    cuisines=None,
                    reviews_list="[]",
                    **{ingest.COST_COLUMN: None},
                ),
                raw_row(rate="3.8/5", votes=2),
            ]
        )
    )
    merged = ingest.deduplicate(rows)
    assert merged.loc[0, "rating"] == 3.8
    assert merged.loc[0, "cost_for_two"] == 800
    assert merged.loc[0, "cuisines"] == ["Italian"]
    assert merged.loc[0, "reviews_raw"] != "[]"


def test_restaurant_is_new_only_when_no_listing_has_a_rating():
    new_only = ingest.clean_rows(pd.DataFrame([raw_row(rate="NEW"), raw_row(rate=None)]))
    assert bool(ingest.deduplicate(new_only).loc[0, "is_new"]) is True
    both = ingest.clean_rows(pd.DataFrame([raw_row(rate="NEW"), raw_row(rate="4.0/5")]))
    assert bool(ingest.deduplicate(both).loc[0, "is_new"]) is False


def test_deduplicate_reports_counts():
    stats = Counter()
    rows = ingest.clean_rows(
        pd.DataFrame([raw_row(rate="3.0/5"), raw_row(rate="4.0/5"), raw_row(name="Other")])
    )
    ingest.deduplicate(rows, stats)
    assert stats["raw_rows"] == 3
    assert stats["restaurants"] == 2
    assert stats["duplicates_removed"] == 1
    assert stats["restaurants_with_conflicting_ratings"] == 1


def test_budget_bands_use_inclusive_upper_edges():
    costs = pd.Series([100, 200, 300, 400, 500, 600, 700, 800, 900], dtype="Int64")
    assert ingest.budget_bands(costs) == {
        "low": {"min": 100, "max": 300},
        "medium": {"min": 400, "max": 600},
        "high": {"min": 700, "max": None},
    }


def test_budget_bands_cover_every_cost_exactly_once():
    costs = pd.Series([100, 100, 100, 300, 300, 500, 500, 800, 800, None], dtype="Int64")
    bands = ingest.budget_bands(costs)
    assert sum(ingest.band_sizes(costs, bands).values()) == 9


def test_budget_bands_fail_when_costs_are_too_clustered():
    with pytest.raises(IngestionError, match="clustered"):
        ingest.budget_bands(pd.Series([500] * 9 + [800], dtype="Int64"))


def test_budget_bands_fail_with_no_costs():
    with pytest.raises(IngestionError, match="usable cost"):
        ingest.budget_bands(pd.Series([None, None], dtype="Int64"))


def test_metadata_median_votes_is_never_zero():
    result = run([{**row, "votes": 0} for row in varied_rows()])
    assert result.metadata["median_votes"] == 1


def test_pipeline_produces_expected_output():
    result = run(varied_rows())
    assert list(result.restaurants.columns) == list(ingest.OUTPUT_COLUMNS)
    assert len(result.restaurants) == 30
    assert result.metadata["areas"] == ["BTM", "HSR", "MG Road"]
    assert result.metadata["cuisines"] == ["Italian"]
    assert result.metadata["mean_rating"] == 4.0
    assert result.metadata["dataset_revision"] == ingest.DATASET_REVISION
    assert result.restaurants.loc[0, "review_snippets"] == ["Tasty"]


def test_pipeline_drops_contact_and_url_columns():
    columns = run(varied_rows()).restaurants.columns
    assert not {"url", "url_stem", "phone", "menu_item", "reviews_raw", "key"} & set(columns)


# Each ingestion check fails when given bad data.
def test_check_fails_on_wrong_row_count():
    with pytest.raises(IngestionError, match="raw rows"):
        run(varied_rows(), expected_rows=99)


def test_real_row_count_is_expected_by_default():
    with pytest.raises(IngestionError, match="51,717"):
        ingest.check_raw(pd.DataFrame(varied_rows()))


def test_check_fails_on_missing_column():
    rows = [{k: v for k, v in row.items() if k != "rate"} for row in varied_rows()]
    with pytest.raises(IngestionError, match="rate"):
        run(rows)


def test_check_fails_when_too_few_rows_have_a_rating():
    rows = [{**row, "rate": "4.0/5" if i < 20 else "-"} for i, row in enumerate(varied_rows())]
    with pytest.raises(IngestionError, match="have a rating"):
        run(rows)


def test_check_fails_on_rating_outside_range():
    restaurants = run(varied_rows())
    bad = restaurants.restaurants.assign(rating=6.0)
    with pytest.raises(IngestionError, match="outside 0 to 5"):
        ingest.check_output(bad, restaurants.metadata, raw_rated_share=1.0, expected_areas=3)


def test_check_fails_on_wrong_area_count():
    with pytest.raises(IngestionError, match="areas"):
        run(varied_rows(), expected_areas=30)


def test_check_fails_on_nearly_empty_budget_band():
    result = run(varied_rows())
    metadata = {
        **result.metadata,
        "budget_band_sizes": {"low": 1, "medium": 14, "high": 15},
    }
    with pytest.raises(IngestionError, match="nearly empty"):
        ingest.check_output(result.restaurants, metadata, raw_rated_share=1.0, expected_areas=3)


def test_check_fails_on_duplicate_ids():
    result = run(varied_rows())
    bad = result.restaurants.assign(restaurant_id="same")
    with pytest.raises(IngestionError, match="not unique"):
        ingest.check_output(bad, result.metadata, raw_rated_share=1.0, expected_areas=3)


def test_build_id_depends_on_content_not_time():
    first = run(varied_rows()).metadata["build_id"]
    assert first == run(varied_rows()).metadata["build_id"]
    changed = varied_rows()
    changed[0]["rate"] = "2.0/5"
    assert first != run(changed).metadata["build_id"]


def test_write_outputs_round_trip_and_share_build_id(tmp_path):
    result = run(varied_rows())
    parquet, metadata = tmp_path / "out" / "r.parquet", tmp_path / "out" / "m.json"
    ingest.write_outputs(result, parquet, metadata)

    saved = json.loads(metadata.read_text(encoding="utf-8"))
    assert saved["build_id"] == result.metadata["build_id"]
    table = pq.read_table(parquet)
    assert table.schema.metadata[b"build_id"].decode() == saved["build_id"]
    assert table.num_rows == 30
    assert sorted(p.name for p in parquet.parent.iterdir()) == ["m.json", "r.parquet"]


def test_failed_write_leaves_existing_file_untouched(tmp_path):
    target = tmp_path / "keep.txt"
    target.write_text("original", encoding="utf-8")

    def explode(path):
        path.write_text("partial", encoding="utf-8")
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        ingest._replace_atomically(target, explode)
    assert target.read_text(encoding="utf-8") == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["keep.txt"]


def test_main_reports_failure_without_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ingest, "load_raw", lambda: pd.DataFrame(varied_rows()))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    assert ingest.main() == 1
    assert "Ingestion failed" in capsys.readouterr().out
    assert not (tmp_path / "data").exists()


def test_main_reports_download_failure(tmp_path, monkeypatch, capsys):
    def fail():
        raise ConnectionError("no network")

    monkeypatch.setattr(ingest, "load_raw", fail)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    assert ingest.main() == 1
    assert "Could not load the dataset" in capsys.readouterr().out


def test_report_includes_required_counts(tmp_path):
    result = run(varied_rows() + [raw_row(name="Place 0", address="0 Road, Bangalore")])
    report = ingest.format_report(result, tmp_path / "r", tmp_path / "m")
    for expected in (
        "Duplicates removed",
        "Review parse failures",
        "Missing values",
        "Budget: low",
    ):
        assert expected in report
