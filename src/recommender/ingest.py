"""Build clean restaurant data from the raw dataset. Run with `python -m recommender.ingest`."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from recommender import cleaning
from recommender.config import load_settings
from recommender.cuisines import offered_cuisines
from recommender.dishes import offered_dishes
from recommender.models import BudgetBand

DATASET = "ManikaSaini/zomato-restaurant-recommendation"
DATASET_REVISION = "5738e9eda2fad49ad51c6e0ed26e761d9b947133"
EXPECTED_ROWS = 51_717
EXPECTED_AREAS = 30
MIN_RATED_SHARE = 0.75
# Costs for two, in rupees: below 500, 500 to 1,500, and above 1,500.
BUDGET_BANDS = {
    "low": {"min": None, "max": 499},
    "medium": {"min": 500, "max": 1500},
    "high": {"min": 1501, "max": None},
}

COST_COLUMN = "approx_cost(for two people)"
TYPE_COLUMN = "listed_in(type)"
AREA_COLUMN = "listed_in(city)"
REQUIRED_COLUMNS = (
    "url",
    "address",
    "name",
    "online_order",
    "book_table",
    "rate",
    "votes",
    "location",
    "rest_type",
    "dish_liked",
    "cuisines",
    COST_COLUMN,
    "reviews_list",
    TYPE_COLUMN,
    AREA_COLUMN,
)
LIST_COLUMNS = ("areas", "listing_types", "cuisines", "rest_types", "dishes", "review_snippets")
OUTPUT_COLUMNS = (
    "restaurant_id",
    "name",
    "address",
    "location",
    "areas",
    "listing_types",
    "cuisines",
    "rest_types",
    "dishes",
    "rating",
    "votes",
    "is_new",
    "cost_for_two",
    "online_order",
    "book_table",
    "review_snippets",
)


class IngestionError(RuntimeError):
    """Raised when the data fails a check, so that no output files are written."""


@dataclass
class IngestResult:
    restaurants: pd.DataFrame
    metadata: dict[str, Any]
    stats: Counter[str] = field(default_factory=Counter)


def load_raw() -> pd.DataFrame:
    """Download the pinned dataset revision, or reuse it from the Hugging Face cache."""
    from datasets import load_dataset  # Imported here because it is slow and only needed here.

    return load_dataset(DATASET, split="train", revision=DATASET_REVISION).to_pandas()


def check_raw(raw: pd.DataFrame, *, expected_rows: int = EXPECTED_ROWS) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in raw.columns]
    if missing:
        raise IngestionError(f"Required columns are missing: {missing}")
    if len(raw) != expected_rows:
        raise IngestionError(f"Expected {expected_rows:,} raw rows, found {len(raw):,}")


def clean_rows(raw: pd.DataFrame) -> pd.DataFrame:
    """Parse every field except reviews, which are only parsed for the rows that are kept."""
    rates = raw["rate"].map(cleaning.parse_rate)
    names = raw["name"].map(cleaning.repair_text)
    addresses = raw["address"].map(cleaning.repair_text)
    keys = [cleaning.normalise_key(n or "", a) for n, a in zip(names, addresses, strict=True)]
    return pd.DataFrame(
        {
            "key": keys,
            "name": names,
            "address": addresses,
            "location": raw["location"].map(cleaning.repair_text),
            "area": raw[AREA_COLUMN],
            "listing_type": raw[TYPE_COLUMN],
            "cuisines": raw["cuisines"].map(cleaning.split_multi_value),
            "rest_types": raw["rest_type"].map(cleaning.split_multi_value),
            "dishes": raw["dish_liked"].map(cleaning.split_multi_value),
            "rating": pd.Series([r[0] for r in rates], index=raw.index, dtype="float64"),
            "is_new": pd.Series([r[1] for r in rates], index=raw.index, dtype="bool"),
            "votes": raw["votes"],
            "cost_for_two": raw[COST_COLUMN].map(cleaning.parse_cost).astype("Int64"),
            "online_order": raw["online_order"].map(cleaning.parse_yes_no).astype("boolean"),
            "book_table": raw["book_table"].map(cleaning.parse_yes_no).astype("boolean"),
            "reviews_raw": raw["reviews_list"],
            "url_stem": raw["url"].astype("str").str.split("?").str[0],
        },
        index=raw.index,
    )


def _first_present(values: pd.Series) -> Any:
    present = values.dropna()
    return present.iloc[0] if len(present) else None


def _first_non_empty_list(values: pd.Series) -> list[str]:
    return next((value for value in values if len(value)), [])


def _first_with_reviews(values: pd.Series) -> Any:
    for value in values:
        if isinstance(value, str) and value.strip() not in ("", "[]"):
            return value
    return None


def _distinct_count(values: pd.Series) -> int:
    return values.dropna().nunique()


def deduplicate(rows: pd.DataFrame, stats: Counter[str] | None = None) -> pd.DataFrame:
    """Merge repeated listings into one row per restaurant.

    The row with the most votes wins, since it is the most developed listing. A value it lacks is
    filled from the restaurant's other rows, and all areas and listing types are merged.
    """
    ordered = rows.assign(_row=range(len(rows))).sort_values(
        ["key", "votes", "_row"], ascending=[True, False, True], kind="mergesort"
    )
    grouped = ordered.groupby("key", sort=True, dropna=False)
    merged = grouped.agg(
        name=("name", "first"),
        address=("address", _first_present),
        location=("location", _first_present),
        areas=("area", lambda v: sorted(set(v.dropna()))),
        listing_types=("listing_type", lambda v: sorted(set(v.dropna()))),
        cuisines=("cuisines", _first_non_empty_list),
        rest_types=("rest_types", _first_non_empty_list),
        dishes=("dishes", _first_non_empty_list),
        rating=("rating", _first_present),
        is_new_any=("is_new", "any"),
        votes=("votes", "max"),
        cost_for_two=("cost_for_two", _first_present),
        online_order=("online_order", _first_present),
        book_table=("book_table", _first_present),
        reviews_raw=("reviews_raw", _first_with_reviews),
    ).reset_index()

    merged["rating"] = pd.to_numeric(merged["rating"], errors="coerce").astype("float64")
    # A restaurant is only "new" if none of its listings has a rating.
    merged["is_new"] = merged["is_new_any"] & merged["rating"].isna()
    merged["cost_for_two"] = merged["cost_for_two"].astype("Int64")
    merged["online_order"] = merged["online_order"].astype("boolean").fillna(False).astype("bool")
    merged["book_table"] = merged["book_table"].astype("boolean").fillna(False).astype("bool")
    merged["restaurant_id"] = merged["key"].map(cleaning.restaurant_id)

    if stats is not None:
        stats["raw_rows"] = len(rows)
        stats["restaurants"] = len(merged)
        stats["duplicates_removed"] = len(rows) - len(merged)
        counts = grouped.agg(
            rating=("rating", _distinct_count),
            cost=("cost_for_two", _distinct_count),
            cuisines=("cuisines", lambda v: len({tuple(i) for i in v})),
        )
        stats["restaurants_with_conflicting_ratings"] = int((counts["rating"] > 1).sum())
        stats["restaurants_with_conflicting_costs"] = int((counts["cost"] > 1).sum())
        stats["restaurants_with_conflicting_cuisines"] = int((counts["cuisines"] > 1).sum())
        if "url_stem" in rows:
            stats["keys_with_several_urls"] = int(
                (rows.groupby("key")["url_stem"].nunique() > 1).sum()
            )
            stats["urls_with_several_keys"] = int(
                (rows.groupby("url_stem")["key"].nunique() > 1).sum()
            )
    return merged


def add_reviews(restaurants: pd.DataFrame, stats: Counter[str]) -> pd.DataFrame:
    """Parse reviews for the kept rows, then remove the raw values."""
    snippets = [cleaning.parse_reviews(v, stats=stats) for v in restaurants["reviews_raw"]]
    return restaurants.assign(review_snippets=snippets).drop(columns="reviews_raw")


def band_sizes(costs: pd.Series) -> dict[str, int]:
    known = costs.dropna().astype(int)
    return {
        name: sum(BudgetBand(**band).contains(cost) for cost in known)
        for name, band in BUDGET_BANDS.items()
    }


def build_metadata(restaurants: pd.DataFrame) -> dict[str, Any]:
    rated = restaurants["rating"].dropna()
    cuisines, popular = offered_cuisines(restaurants["cuisines"])
    dishes, popular_dishes = offered_dishes(restaurants["dishes"])
    return {
        "dataset": DATASET,
        "dataset_revision": DATASET_REVISION,
        "areas": sorted({area for areas in restaurants["areas"] for area in areas}),
        "cuisines": cuisines,
        "popular_cuisines": popular,
        "dishes": dishes,
        "popular_dishes": popular_dishes,
        "budget_bands": BUDGET_BANDS,
        "budget_band_sizes": band_sizes(restaurants["cost_for_two"]),
        "mean_rating": round(float(rated.mean()), 4) if len(rated) else None,
        # At least 1, so that the weighted rating can never divide by zero.
        "median_votes": max(1, int(restaurants["votes"].median())),
        "restaurant_count": len(restaurants),
    }


def check_output(
    restaurants: pd.DataFrame,
    metadata: dict[str, Any],
    *,
    raw_rated_share: float,
    expected_areas: int = EXPECTED_AREAS,
) -> None:
    if raw_rated_share < MIN_RATED_SHARE:
        raise IngestionError(
            f"Only {raw_rated_share:.1%} of raw rows have a rating, below {MIN_RATED_SHARE:.0%}"
        )
    rated = restaurants["rating"].dropna()
    if not rated.between(0, 5).all():
        raise IngestionError("A parsed rating falls outside 0 to 5")
    if len(metadata["areas"]) != expected_areas:
        raise IngestionError(f"Expected {expected_areas} areas, found {len(metadata['areas'])}")
    if not restaurants["restaurant_id"].is_unique:
        raise IngestionError("Restaurant IDs are not unique")
    for name, size in metadata["budget_band_sizes"].items():
        if size == 0:
            raise IngestionError(f"Budget band '{name}' has no restaurants")


def run_pipeline(
    raw: pd.DataFrame,
    *,
    expected_rows: int = EXPECTED_ROWS,
    expected_areas: int = EXPECTED_AREAS,
) -> IngestResult:
    """Run every step except file writing. Raises `IngestionError` if a check fails."""
    check_raw(raw, expected_rows=expected_rows)
    stats: Counter[str] = Counter()
    rows = clean_rows(raw)
    raw_rated_share = float(rows["rating"].notna().mean())
    stats["raw_rows_with_rating"] = int(rows["rating"].notna().sum())

    merged = deduplicate(rows, stats)
    restaurants = add_reviews(merged, stats)[list(OUTPUT_COLUMNS)]
    metadata = build_metadata(restaurants)
    check_output(
        restaurants, metadata, raw_rated_share=raw_rated_share, expected_areas=expected_areas
    )
    text_columns = [restaurants["name"], restaurants["address"].dropna()]
    stats["names_or_addresses_with_mojibake"] = sum(
        int(column.map(cleaning.has_mojibake).sum()) for column in text_columns
    )
    stats["review_snippets"] = sum(len(s) for s in restaurants["review_snippets"])
    stats["review_snippets_with_mojibake"] = sum(
        cleaning.has_mojibake(s) for snippets in restaurants["review_snippets"] for s in snippets
    )
    stats["restaurants_without_reviews"] = sum(
        1 for snippets in restaurants["review_snippets"] if not snippets
    )
    metadata["build_id"] = content_hash(restaurants)
    metadata["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return IngestResult(restaurants=restaurants, metadata=metadata, stats=stats)


def content_hash(restaurants: pd.DataFrame) -> str:
    """Identify the data by its content, so that an identical rebuild keeps the same ID."""
    digest = hashlib.sha256(DATASET_REVISION.encode())
    digest.update(json.dumps(BUDGET_BANDS, sort_keys=True).encode())
    columns = restaurants[list(OUTPUT_COLUMNS)].astype("object")
    for row in columns.itertuples(index=False, name=None):
        digest.update(json.dumps(row, default=_json_value, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()[:16]


def _json_value(value: Any) -> Any:
    return None if pd.isna(value) else str(value)


def _replace_atomically(target: Path, write: Any) -> None:
    """Write through a temporary file, so that a crash can't leave a partial output file."""
    handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    os.close(handle)
    temp = Path(temp_name)
    try:
        write(temp)
        os.replace(temp, target)
    finally:
        with suppress(FileNotFoundError):
            temp.unlink()


def write_outputs(result: IngestResult, restaurants_path: Path, metadata_path: Path) -> None:
    restaurants_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(result.restaurants, preserve_index=False)
    build_id = result.metadata["build_id"].encode()
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), b"build_id": build_id})
    _replace_atomically(restaurants_path, lambda path: pq.write_table(table, path))
    text = json.dumps(result.metadata, indent=2, ensure_ascii=False)
    _replace_atomically(metadata_path, lambda path: path.write_text(text, encoding="utf-8"))


def format_report(result: IngestResult, restaurants_path: Path, metadata_path: Path) -> str:
    frame, meta, stats = result.restaurants, result.metadata, result.stats
    count = len(frame)

    def row(label: str, value: Any) -> str:
        return f"  {label:<44} {value:,}" if isinstance(value, int) else f"  {label:<44} {value}"

    def missing(label: str, column: str) -> str:
        nulls = int(frame[column].isna().sum())
        return row(label, f"{nulls:,} ({nulls / count:.1%})")

    def empty(label: str, column: str) -> str:
        blanks = sum(1 for value in frame[column] if not len(value))
        return row(label, f"{blanks:,} ({blanks / count:.1%})")

    bands = meta["budget_bands"]
    sizes = meta["budget_band_sizes"]
    band_lines = []
    for name, band in bands.items():
        label = BudgetBand(**band).label()
        band_lines.append(row(f"Budget: {name}", f"{label} ({sizes[name]:,} restaurants)"))

    return "\n".join(
        [
            "Ingestion report",
            row("Dataset revision", DATASET_REVISION),
            row("Build ID", meta["build_id"]),
            "",
            "Rows",
            row("Raw rows", stats["raw_rows"]),
            row("Duplicates removed", stats["duplicates_removed"]),
            row("Restaurants", stats["restaurants"]),
            row("Areas", len(meta["areas"])),
            row("Cuisines offered", len(meta["cuisines"])),
            row("Most popular", ", ".join(meta["popular_cuisines"])),
            row("Dishes offered", len(meta["dishes"])),
            row("Most popular dishes", ", ".join(meta["popular_dishes"])),
            "",
            "Missing values, per restaurant",
            missing("Rating", "rating"),
            row("  of which marked as new", int(frame["is_new"].sum())),
            missing("Cost", "cost_for_two"),
            missing("Location", "location"),
            empty("Cuisines", "cuisines"),
            empty("Restaurant types", "rest_types"),
            empty("Liked dishes", "dishes"),
            empty("Reviews", "review_snippets"),
            "",
            "Reviews and text",
            row("Review parse failures", stats["review_parse_failures"]),
            row("Malformed review items skipped", stats["review_items_skipped"]),
            row("Review snippets kept", stats["review_snippets"]),
            row("Snippets still showing mojibake", stats["review_snippets_with_mojibake"]),
            row("Names or addresses showing mojibake", stats["names_or_addresses_with_mojibake"]),
            "",
            "Deduplication quality",
            row("Conflicting ratings merged", stats["restaurants_with_conflicting_ratings"]),
            row("Conflicting costs merged", stats["restaurants_with_conflicting_costs"]),
            row("Conflicting cuisines merged", stats["restaurants_with_conflicting_cuisines"]),
            row("Merged restaurants with several URLs", stats["keys_with_several_urls"]),
            row("URLs split across several restaurants", stats["urls_with_several_keys"]),
            "",
            "Scoring and budgets",
            row("Mean rating (C)", meta["mean_rating"]),
            row("Median votes (m)", meta["median_votes"]),
            *band_lines,
            "",
            "Output",
            f"  {restaurants_path}",
            f"  {metadata_path}",
        ]
    )


def main() -> int:
    # The default Windows console encoding can't print every character in the report.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    settings = load_settings()
    try:
        print(f"Loading {DATASET} (574 MB on first run)...", flush=True)
        raw = load_raw()
        print(f"Cleaning {len(raw):,} rows...", flush=True)
        result = run_pipeline(raw)
    except IngestionError as error:
        print(f"Ingestion failed: {error}. Existing output files were left unchanged.")
        return 1
    except OSError as error:
        print(f"Could not load the dataset: {error}. Existing output files were left unchanged.")
        return 1
    write_outputs(result, settings.restaurants_path, settings.metadata_path)
    print(format_report(result, settings.restaurants_path, settings.metadata_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
