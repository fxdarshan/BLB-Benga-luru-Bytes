"""HTTP API over `RecommendationService`, for the web frontend.

Run locally with:

    uv run uvicorn --factory recommender.api:create_app --port 8000

`--factory` builds the app when the server starts, so importing this module reads no settings.

Every value returned is plain text: the frontend escapes it. Internal details, such as why the
LLM failed, stay in the logs.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

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
from recommender.models import (
    MAX_ADDITIONAL_CHARS,
    BudgetBand,
    Preferences,
    RankedResult,
    RecommendationResult,
)
from recommender.rankers import make_ranker
from recommender.repository import DataUnavailableError, RestaurantRepository
from recommender.service import RecommendationService
from recommender.usage_store import DB_FILENAME, UsageStore

logger = logging.getLogger(__name__)
# One line per piece of feedback on an explanation, for the evaluation. No free text.
feedback_logger = logging.getLogger("recommender.feedback")

BUDGET_OPTIONS = ("any", "low", "medium", "high")
DEFAULT_MIN_RATING = 3.5
DEFAULT_RATE_LIMIT_PER_MINUTE = 10
FEEDBACK_PER_MINUTE = 30
# The shortlist makes no LLM call, so it can be generous. The page asks for one per search.
SHORTLIST_PER_MINUTE = 60
# The longest shortlist the page can ask for, for "Show more matches".
MAX_SHORTLIST = 20
RATE_WINDOW_SECONDS = 60.0
MAX_LIKED_DISHES = 4
DEFAULT_WARM_INTERVAL_SECONDS = 60
UNAVAILABLE_MESSAGE = "Restaurant data isn't available right now. Please try again later."
RATE_LIMITED_MESSAGE = "Too many searches. Try again in a minute."
# The LLM provider's reason when its per-minute token limit is used up.
LLM_RATE_LIMITED = "rate_limited"


@dataclass(frozen=True)
class ApiSettings:
    """Settings for the HTTP layer only. The search itself uses `recommender.config`."""

    allowed_origins: tuple[str, ...] = ()
    allowed_origin_regex: str | None = None
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE
    # How many proxies in front of the app append to X-Forwarded-For: 1 on Railway, 0 locally.
    # Only entries those proxies added are trusted, so a client can't fake its address.
    trusted_proxy_hops: int = 0
    # Areas whose default search is kept in the cache, so it's instant and makes no LLM call
    # for diners. Each costs about one LLM search an hour. Empty turns this off.
    warm_areas: tuple[str, ...] = ()
    warm_interval_seconds: int = DEFAULT_WARM_INTERVAL_SECONDS
    # Where usage counts and feedback are kept, so they survive restarts. On Railway this is a
    # mounted volume. None keeps them in memory, so they reset when the server restarts.
    state_dir: Path | None = None

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
        warm = tuple(a.strip() for a in env.get("WARM_CACHE_AREAS", "").split(",") if a.strip())
        interval = _whole_number(env, "WARM_CACHE_INTERVAL_SECONDS", DEFAULT_WARM_INTERVAL_SECONDS)
        # A relative path starts from the project root, as DATA_DIR does.
        raw_state_dir = env.get("STATE_DIR", "").strip()
        state_dir = (PROJECT_ROOT / raw_state_dir).resolve() if raw_state_dir else None
        return cls(origins, regex, limit, hops, warm, max(1, interval), state_dir)


class Feedback(BaseModel):
    """A diner's thumbs up or down on one result's explanation."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    restaurant: str = Field(min_length=1, max_length=200)
    rank: int = Field(ge=1, le=20)
    helpful: bool
    ai_ranked: bool = True


def warm_cache(
    service: RecommendationService,
    areas: tuple[str, ...],
    interval_seconds: float,
    stop: threading.Event,
) -> None:
    """Keep each area's default search in the cache, one LLM call at a time.

    Areas already cached are skipped, so each costs about one LLM search per cache lifetime
    (an hour). Waiting between searches leaves most of the provider's per-minute token limit
    for diners.
    """
    known = [a for a in areas if a in service.repository.metadata.areas]
    unknown = sorted(set(areas) - set(known))
    if unknown:
        logger.warning("WARM_CACHE_AREAS names unknown areas, which are skipped: %s", unknown)
    if not known or service.llm_client is None:
        return
    while not stop.is_set():
        for area in known:
            preferences = Preferences(area=area, min_rating=DEFAULT_MIN_RATING)
            if service.is_cached(preferences):
                continue
            try:
                service.recommend(preferences)
            except Exception:  # noqa: BLE001 - warming must never stop the server
                logger.exception("Couldn't warm the cache for %s", area)
            if stop.wait(interval_seconds):
                return
        if stop.wait(interval_seconds):
            return


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
        daily_token_limit=settings.llm_daily_token_limit,
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


def results_json(
    preferences: Preferences, result: RecommendationResult, bands: dict[str, BudgetBand]
) -> dict[str, Any]:
    """The body of /recommend and /shortlist: the search, its notices and the result cards."""
    return {
        "search_summary": search_summary_parts(preferences, bands),
        "relaxations": [r.message for r in result.relaxations],
        "notice": result.notice,
        "ai_ranked": result.ai_ranked,
        # True when the AI was skipped only because the provider's per-minute limit was
        # reached, so the page can suggest trying again shortly.
        "ai_busy": result.failure_reason == LLM_RATE_LIMITED,
        "summary": result.summary,
        "results": [
            result_json(position, item, preferences)
            for position, item in enumerate(result.results, start=1)
        ],
    }


def too_many(message: str, wait: float) -> JSONResponse:
    return JSONResponse(
        {"detail": message}, status_code=429, headers={"Retry-After": str(int(wait + 0.999))}
    )


def create_app(
    service_factory: Callable[[], RecommendationService] = load_service,
    api_settings: ApiSettings | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own service factory and settings."""
    state: dict[str, Any] = {"service": None}
    settings = api_settings or ApiSettings.from_env()
    limiter = RateLimiter(settings.rate_limit_per_minute)
    feedback_limiter = RateLimiter(FEEDBACK_PER_MINUTE)
    shortlist_limiter = RateLimiter(SHORTLIST_PER_MINUTE)
    stats = UsageStore.open(settings.state_dir / DB_FILENAME if settings.state_dir else None)
    stop_warming = threading.Event()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        try:
            state["service"] = service_factory()
        except (DataUnavailableError, ConfigError) as error:
            # Keep serving, so /health can report the problem and the host keeps the old
            # deployment instead of this one.
            logger.error("The service couldn't start: %s", error)
        if state["service"] is not None and settings.warm_areas:
            threading.Thread(
                target=warm_cache,
                args=(state["service"], settings.warm_areas, settings.warm_interval_seconds),
                kwargs={"stop": stop_warming},
                name="warm-cache",
                daemon=True,
            ).start()
        yield
        stop_warming.set()
        stats.close()

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
        allow_methods=["GET", "POST"],  # /feedback is a POST too
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
                # True when an AI key is set. last_ai_call says whether the AI actually works:
                # how the last call went, or null before the first one.
                "ai_ranking": current.llm_client is not None,
                "last_ai_call": current.last_ai_call(),
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
            return too_many(RATE_LIMITED_MESSAGE, wait)
        try:
            result = current.recommend(preferences)
        except InvalidPreferencesError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        stats.record_search(preferences, result)
        return JSONResponse(
            results_json(preferences, result, current.repository.metadata.budget_bands)
        )

    # The same search ranked by score alone, returned at once. The page shows it while
    # /recommend has the AI rank the search. It isn't counted in /stats: /recommend is.
    @app.post("/shortlist")
    def shortlist(
        preferences: Preferences,
        request: Request,
        limit: int | None = Query(default=None, ge=1, le=MAX_SHORTLIST),
    ) -> JSONResponse:
        current = service()
        wait = shortlist_limiter.check(client_address(request, settings.trusted_proxy_hops))
        if wait is not None:
            return too_many(RATE_LIMITED_MESSAGE, wait)
        try:
            result = current.shortlist(preferences, limit)
        except InvalidPreferencesError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        body = results_json(preferences, result, current.repository.metadata.budget_bands)
        # True when /recommend will have the AI rank these, so the page says it's coming.
        body["ai_pending"] = current.llm_client is not None and bool(result.results)
        return JSONResponse(body)

    @app.post("/feedback", status_code=204)
    def feedback(item: Feedback, request: Request) -> Response:
        wait = feedback_limiter.check(client_address(request, settings.trusted_proxy_hops))
        if wait is not None:
            return too_many("Too much feedback. Try again in a minute.", wait)
        stats.record_feedback(item.restaurant, item.rank, item.helpful, item.ai_ranked)
        record = {
            "restaurant": item.restaurant,
            "rank": item.rank,
            "helpful": item.helpful,
            "ai_ranked": item.ai_ranked,
        }
        feedback_logger.info("feedback %s", json.dumps(record, sort_keys=True))
        return Response(status_code=204)

    @app.get("/stats")
    def usage() -> dict[str, Any]:
        try:
            snapshot = stats.snapshot()
        except sqlite3.Error as error:
            logger.exception("Couldn't read the usage store")
            raise HTTPException(
                status_code=503, detail="Usage counts aren't available right now."
            ) from error
        current = state["service"]
        if current is not None:
            # Counted in memory since the server started, which is fine for a daily cap.
            snapshot["ai_budget"] = {
                "tokens_today": current.tokens_used_today(),
                "daily_limit": current.daily_token_limit or None,
            }
        return snapshot

    return app
