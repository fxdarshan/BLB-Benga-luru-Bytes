"""HTTP API over `RecommendationService`, for the web frontend.

Run locally with:

    uv run uvicorn --factory recommender.api:create_app --port 8000

`--factory` builds the app when the server starts, so importing this module reads no settings.

Every value returned is plain text: the frontend escapes it. Internal details, such as why the
LLM failed, stay in the logs.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from recommender.candidates import InvalidPreferencesError
from recommender.config import PROJECT_ROOT, ConfigError, load_settings
from recommender.cuisines import menu_order
from recommender.display import (
    NOT_LISTED,
    budget_option_label,
    format_cost,
    format_cuisines,
    format_rating,
    matched_dishes,
    search_summary_parts,
    shorten_review,
)
from recommender.models import MAX_ADDITIONAL_CHARS, BudgetBand, Preferences, RankedResult
from recommender.rankers import make_ranker
from recommender.repository import DataUnavailableError, RestaurantRepository
from recommender.service import RecommendationService

logger = logging.getLogger(__name__)

BUDGET_OPTIONS = ("any", "low", "medium", "high")
DEFAULT_MIN_RATING = 3.5
DEFAULT_RATE_LIMIT_PER_MINUTE = 10
RATE_WINDOW_SECONDS = 60.0
MAX_LIKED_DISHES = 4
UNAVAILABLE_MESSAGE = "Restaurant data isn't available right now. Please try again later."
RATE_LIMITED_MESSAGE = "Too many searches. Try again in a minute."


@dataclass(frozen=True)
class ApiSettings:
    """Settings for the HTTP layer only. The search itself uses `recommender.config`."""

    allowed_origins: tuple[str, ...] = ()
    allowed_origin_regex: str | None = None
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE
    # How many proxies in front of the app append to X-Forwarded-For: 1 on Railway, 0 locally.
    # Only entries those proxies added are trusted, so a client can't fake its address.
    trusted_proxy_hops: int = 0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ApiSettings:
        if env is None:
            load_dotenv(PROJECT_ROOT / ".env")
            env = dict(os.environ)
        origins = tuple(
            o.strip().rstrip("/") for o in env.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
        )
        regex = env.get("ALLOWED_ORIGIN_REGEX", "").strip() or None
        limit = _whole_number(env, "RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE)
        hops = _whole_number(env, "TRUSTED_PROXY_HOPS", 0)
        return cls(origins, regex, limit, hops)


def _whole_number(env: dict[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError as error:
        raise ConfigError(f"{name} must be a whole number: {raw!r}") from error
    if value < 0:
        raise ConfigError(f"{name} can't be negative")
    return value


def client_address(request: Request, trusted_proxy_hops: int) -> str:
    """The diner's address, for the rate limit.

    Each trusted proxy appends the address it saw to X-Forwarded-For, so the entry that many
    places from the end is the one the first trusted proxy saw. Earlier entries come from the
    client and could be faked.
    """
    direct = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0:
        return direct
    entries = [
        e.strip() for e in request.headers.get("x-forwarded-for", "").split(",") if e.strip()
    ]
    if len(entries) < trusted_proxy_hops:
        return direct
    return entries[-trusted_proxy_hops]


@dataclass
class RateLimiter:
    """Allows each client a number of searches in any 60 seconds. 0 turns the limit off."""

    per_minute: int
    clock: Callable[[], float] = time.monotonic
    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, client: str) -> float | None:
        """Record a search. Return None if allowed, or the seconds to wait before retrying."""
        if self.per_minute <= 0:
            return None
        now = self.clock()
        with self._lock:
            hits = self._hits[client]
            while hits and now - hits[0] >= RATE_WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return max(1.0, RATE_WINDOW_SECONDS - (now - hits[0]))
            hits.append(now)
            # Forget clients with no recent searches, so memory stays small.
            if len(self._hits) > 10_000:
                for key in [k for k, v in self._hits.items() if not v]:
                    del self._hits[key]
            return None


def load_service() -> RecommendationService:
    """Build the shared service from the environment, as the Streamlit app does."""
    settings = load_settings()
    repository = RestaurantRepository.load(settings.restaurants_path, settings.metadata_path)
    return RecommendationService(
        repository,
        make_ranker(settings),
        max_candidates=settings.max_candidates,
        max_results=settings.max_results,
    )


def configure_logging() -> None:
    """Send the one-line search log to standard output, where the host collects it."""
    log = logging.getLogger("recommender")
    if not any(getattr(h, "_blb", False) for h in log.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler._blb = True  # type: ignore[attr-defined]
        log.addHandler(handler)
    log.setLevel(logging.INFO)


def budget_option(name: str, bands: dict[str, BudgetBand]) -> dict[str, str]:
    """One budget choice: its full label, and the name and range shown on two lines."""
    if name == "any":
        short, price_range = "Any budget", "No limit"
    else:
        short, price_range = name.capitalize(), bands[name].label().capitalize()
    return {
        "value": name,
        "label": budget_option_label(name, bands),
        "name": short,
        "range": price_range,
    }


def result_json(position: int, item: RankedResult, preferences: Preferences) -> dict[str, Any]:
    """One result card as display-ready text. Facts come from the dataset record."""
    restaurant = item.candidate.restaurant
    liked = matched_dishes(restaurant, preferences.dishes) if preferences.dishes else []
    return {
        "rank": position,
        "name": restaurant.name,
        "rating": format_rating(restaurant),
        "is_rated": restaurant.rating is not None,
        "cuisines": format_cuisines(restaurant),
        "place": restaurant.location or NOT_LISTED,
        "badges": [format_cost(restaurant), *restaurant.rest_types[:2]],
        "near": None if item.candidate.in_chosen_area else f"Near {preferences.area}",
        "liked_for": liked[:MAX_LIKED_DISHES],
        "explanation": item.explanation,
        "review": shorten_review(item.review),
        "unverified": list(item.unverified_preferences),
    }


def create_app(
    service_factory: Callable[[], RecommendationService] = load_service,
    api_settings: ApiSettings | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own service factory and settings."""
    state: dict[str, Any] = {"service": None}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        try:
            state["service"] = service_factory()
        except (DataUnavailableError, ConfigError) as error:
            # Keep serving, so /health can report the problem and the host keeps the old
            # deployment instead of this one.
            logger.error("The service couldn't start: %s", error)
        yield

    settings = api_settings or ApiSettings.from_env()
    limiter = RateLimiter(settings.rate_limit_per_minute)
    app = FastAPI(
        title="BLB API",
        summary="Restaurant recommendations for Bangalore",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_origin_regex=settings.allowed_origin_regex,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        max_age=600,
    )

    def service() -> RecommendationService:
        current = state["service"]
        if current is None:
            raise HTTPException(status_code=503, detail=UNAVAILABLE_MESSAGE)
        return current

    @app.get("/health")
    def health() -> JSONResponse:
        current = state["service"]
        if current is None:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse(
            {
                "status": "ok",
                "build_id": current.repository.metadata.build_id,
                "ai_ranking": current.llm_client is not None,
            }
        )

    @app.get("/options")
    def options() -> dict[str, Any]:
        metadata = service().repository.metadata
        return {
            "areas": list(metadata.areas),
            "cuisines": menu_order(metadata.cuisines, metadata.popular_cuisines),
            "dishes": menu_order(metadata.dishes, metadata.popular_dishes),
            "budgets": [budget_option(name, metadata.budget_bands) for name in BUDGET_OPTIONS],
            "defaults": {
                "min_rating": DEFAULT_MIN_RATING,
                "max_additional_chars": MAX_ADDITIONAL_CHARS,
            },
        }

    # A plain function, so FastAPI runs it in a worker thread while the LLM call waits.
    @app.post("/recommend")
    def recommend(preferences: Preferences, request: Request) -> JSONResponse:
        current = service()
        wait = limiter.check(client_address(request, settings.trusted_proxy_hops))
        if wait is not None:
            return JSONResponse(
                {"detail": RATE_LIMITED_MESSAGE},
                status_code=429,
                headers={"Retry-After": str(int(wait + 0.999))},
            )
        try:
            result = current.recommend(preferences)
        except InvalidPreferencesError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        bands = current.repository.metadata.budget_bands
        return JSONResponse(
            {
                "search_summary": search_summary_parts(preferences, bands),
                "relaxations": [r.message for r in result.relaxations],
                "notice": result.notice,
                "ai_ranked": result.ai_ranked,
                "summary": result.summary,
                "results": [
                    result_json(position, item, preferences)
                    for position, item in enumerate(result.results, start=1)
                ],
            }
        )

    return app
