"""Data types shared across the application."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Budget = Literal["low", "medium", "high", "any"]
MAX_ADDITIONAL_CHARS = 300


class Preferences(BaseModel):
    """What a diner is looking for."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    area: str = Field(min_length=1)
    budget: Budget = "any"
    cuisines: tuple[str, ...] = ()
    min_rating: float = Field(default=3.5, ge=0.0, le=5.0)
    include_unrated: bool = False
    additional: str = Field(default="", max_length=MAX_ADDITIONAL_CHARS)

    @field_validator("min_rating")
    @classmethod
    def _round_rating(cls, value: float) -> float:
        # Sliders can produce values such as 3.3000000000000003.
        return round(value, 1)

    @field_validator("cuisines")
    @classmethod
    def _clean_cuisines(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unique: dict[str, str] = {}
        for cuisine in value:
            label = cuisine.strip()
            if label:
                unique.setdefault(label.casefold(), label)
        return tuple(unique.values())


@dataclass(frozen=True)
class Restaurant:
    """One restaurant from the cleaned dataset, using only plain Python values."""

    restaurant_id: str
    name: str
    address: str | None
    location: str | None
    areas: frozenset[str]
    listing_types: frozenset[str]
    cuisines: list[str]
    rest_types: list[str]
    dishes: list[str]
    rating: float | None
    votes: int
    is_new: bool
    cost_for_two: int | None
    online_order: bool
    book_table: bool
    review_snippets: list[str]

    # Derived once when loading, since every search reads these.
    cuisine_keys: frozenset[str] = field(init=False, repr=False, compare=False)
    search_text: str = field(init=False, repr=False, compare=False)
    location_text: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cuisine_keys", frozenset(c.casefold() for c in self.cuisines))
        parts = [
            *self.rest_types,
            *self.dishes,
            *sorted(self.listing_types),
            *self.review_snippets,
        ]
        # The separator stops a phrase from matching across two different values.
        object.__setattr__(self, "search_text", " | ".join(parts).casefold())
        place = f"{self.location or ''} | {self.address or ''}".casefold()
        object.__setattr__(self, "location_text", place)


class BudgetBand(BaseModel):
    """A range of costs for two, in rupees. A `max` of `None` means no upper limit."""

    model_config = ConfigDict(frozen=True)

    min: int
    max: int | None

    def contains(self, cost: int) -> bool:
        return cost >= self.min and (self.max is None or cost <= self.max)

    def label(self) -> str:
        if self.max is None:
            return f"₹{self.min:,} and above"
        return f"₹{self.min:,} to ₹{self.max:,}"


class DatasetMetadata(BaseModel):
    """Facts about the cleaned dataset, as computed during ingestion."""

    model_config = ConfigDict(frozen=True)

    build_id: str
    areas: tuple[str, ...]
    cuisines: tuple[str, ...]
    budget_bands: dict[str, BudgetBand]
    mean_rating: float
    median_votes: int = Field(ge=1)


@dataclass(frozen=True)
class Relaxation:
    """One limit that was loosened because too few restaurants matched."""

    limit: Literal["min_rating", "budget"]
    requested: str
    applied: str
    message: str


@dataclass(frozen=True)
class Candidate:
    """A restaurant that matched a search, with how it scored."""

    restaurant: Restaurant
    score: float
    keyword_hits: int
    in_chosen_area: bool


@dataclass(frozen=True)
class CandidateSelection:
    """The outcome of selecting candidates for one search."""

    candidates: list[Candidate]
    relaxations: list[Relaxation]
    applied_min_rating: float
    applied_budgets: tuple[str, ...]  # Empty when the search has no budget limit.
    total_matches: int
