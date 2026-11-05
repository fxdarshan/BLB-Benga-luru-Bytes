"""Loads the cleaned restaurant data into memory for searching."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import ValidationError

from recommender.models import DatasetMetadata, Restaurant

INGEST_COMMAND = "uv run python -m recommender.ingest"


class DataUnavailableError(RuntimeError):
    """Raised when the data files are missing, damaged or don't belong together."""


def _restaurant_from_row(row: dict[str, Any]) -> Restaurant:
    # Reading rows through pyarrow gives None, lists and Python numbers, with no NaN or NumPy.
    return Restaurant(
        **{
            **row,
            "areas": frozenset(row["areas"]),
            "listing_types": frozenset(row["listing_types"]),
        }
    )


class RestaurantRepository:
    """Read-only access to the restaurants, which is safe to share between threads."""

    def __init__(self, restaurants: Iterable[Restaurant], metadata: DatasetMetadata) -> None:
        self.restaurants: tuple[Restaurant, ...] = tuple(restaurants)
        self.metadata = metadata
        by_area: dict[str, list[Restaurant]] = defaultdict(list)
        for restaurant in self.restaurants:
            for area in restaurant.areas:
                by_area[area].append(restaurant)
        self._by_area = {area: tuple(rows) for area, rows in by_area.items()}

    def in_area(self, area: str) -> tuple[Restaurant, ...]:
        return self._by_area.get(area, ())

    @classmethod
    def load(cls, restaurants_path: Path, metadata_path: Path) -> RestaurantRepository:
        for path in (restaurants_path, metadata_path):
            if not path.is_file():
                raise DataUnavailableError(
                    f"Data file not found: {path}. Build it with: {INGEST_COMMAND}"
                )
        try:
            metadata = DatasetMetadata.model_validate_json(metadata_path.read_text("utf-8"))
            table = pq.read_table(restaurants_path)
            restaurants = [_restaurant_from_row(row) for row in table.to_pylist()]
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValidationError,
            pa.ArrowException,
            KeyError,
            TypeError,
        ) as error:
            raise DataUnavailableError(
                f"The data files are damaged or out of date ({type(error).__name__}). "
                f"Rebuild them with: {INGEST_COMMAND}"
            ) from error

        table_build_id = (table.schema.metadata or {}).get(b"build_id", b"").decode()
        if table_build_id != metadata.build_id:
            raise DataUnavailableError(
                f"The data files come from different builds. Rebuild them with: {INGEST_COMMAND}"
            )
        return cls(restaurants, metadata)
