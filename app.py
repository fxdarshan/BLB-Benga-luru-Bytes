"""Streamlit interface. Run with `uv run streamlit run app.py`."""

from __future__ import annotations

import logging

import streamlit as st

from recommender.config import ConfigError, Settings, load_settings
from recommender.cuisines import menu_order
from recommender.display import (
    FORM_STYLE,
    budget_option_label,
    page_header,
    result_card,
    search_summary,
    summary_block,
)
from recommender.models import BudgetBand, Preferences
from recommender.rankers import make_ranker
from recommender.repository import INGEST_COMMAND, DataUnavailableError, RestaurantRepository
from recommender.service import RecommendationService

APP_NAME = "BLB (Banga-Luru_Bytes)"
BUDGET_OPTIONS = ("any", "low", "medium", "high")
NO_RESULTS_MESSAGE = (
    "No restaurants match this search, even after loosening the rating and budget. "
    "Try a different area, budget or cuisine."
)
MISSING_KEY_MESSAGE = (
    "AI ranking is off because no API key is set. Results are ranked by score. "
    "To turn it on, add {key_name} to a .env file and restart the app."
)
EMPTY_RESULTS_MESSAGE = (
    "**Your restaurant picks will appear here.** Choose an area and what you feel like eating, "
    "then press **Find restaurants**."
)
DATA_NOTE = (
    "Data comes from a fixed Zomato snapshot for Bangalore, so some places may have closed or "
    "changed. Check before you go."
)


@st.cache_resource(show_spinner="Loading restaurants...")
def load_repository(settings: Settings) -> RestaurantRepository:
    return RestaurantRepository.load(settings.restaurants_path, settings.metadata_path)


@st.cache_resource
def load_service(settings: Settings, _repository: RestaurantRepository) -> RecommendationService:
    """Create one service for every session, so that they all share its result cache.

    The leading underscore stops Streamlit hashing the repository, which comes from its own
    cache for the same settings.
    """
    return RecommendationService(
        _repository,
        make_ranker(settings),
        max_candidates=settings.max_candidates,
        max_results=settings.max_results,
    )


@st.cache_resource
def configure_logging() -> None:
    """Print one line per search to the terminal running the app."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("recommender")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def show_setup_message(error: DataUnavailableError) -> None:
    st.error("The restaurant data isn't ready yet.")
    st.write("Run this command in the project folder, then reload this page:")
    st.code(INGEST_COMMAND, language="bash")
    st.text(str(error))


def show_search_form(repository: RestaurantRepository) -> Preferences | None:
    """Show the form, and return the preferences once it is submitted.

    A form only reruns the search on Submit, so changing a widget can't start a search.
    """
    metadata = repository.metadata
    bands: dict[str, BudgetBand] = metadata.budget_bands
    with st.form("search"):
        st.subheader("Find a place to eat")
        area = st.selectbox("Area in Bangalore", metadata.areas)
        budget = st.radio(
            "Budget",
            BUDGET_OPTIONS,
            format_func=lambda name: budget_option_label(name, bands),
            horizontal=True,
        )
        # Without select_all=False, typing "Thai" and pressing Enter also selects every other match.
        cuisines = st.multiselect(
            "Cuisine",
            menu_order(metadata.cuisines, metadata.popular_cuisines),
            placeholder="Any cuisine",
            select_all=False,
            help="The most popular cuisines in Bangalore come first, then the rest from A to Z.",
        )
        dishes = st.multiselect(
            "Dish",
            menu_order(metadata.dishes, metadata.popular_dishes),
            placeholder="Any dish",
            select_all=False,
            help="For a great dish, whatever else the restaurant serves. The most popular "
            "dishes come first, then the rest from A to Z.",
        )
        min_rating = st.slider("Minimum rating", 0.0, 5.0, 3.5, step=0.1, format="★ %.1f")
        include_unrated = st.checkbox("Include new and unrated restaurants")
        additional = st.text_input(
            "Anything else? (optional)",
            placeholder="For example, family-friendly, quick service",
            max_chars=300,
        )
        submitted = st.form_submit_button(
            "Find restaurants", type="primary", icon=":material/search:", width="stretch"
        )
    if not submitted:
        return None
    return Preferences(
        area=area,
        budget=budget,
        cuisines=tuple(cuisines),
        dishes=tuple(dishes),
        min_rating=min_rating,
        include_unrated=include_unrated,
        additional=additional,
    )


def show_results(preferences: Preferences, repository: RestaurantRepository, result) -> None:
    # Dataset and user text goes through st.html after escaping, so Markdown, maths and HTML in
    # it display literally. Results stay until the next search, with a label showing their search.
    count = len(result.results)
    heading, count_column = st.columns([3, 1], vertical_alignment="bottom")
    heading.subheader("Top picks for you")
    count_column.markdown(
        f"<div style='text-align: right; color: #A3ACB9; font-size: 0.85rem;'>"
        f"{count} result{'' if count == 1 else 's'}</div>",
        unsafe_allow_html=True,
    )
    st.html(search_summary(preferences, repository.metadata.budget_bands))
    for relaxation in result.relaxations:
        st.info(relaxation.message)
    if not result.results:
        st.warning(NO_RESULTS_MESSAGE)
        return
    if result.notice:
        st.warning(result.notice)
    if result.summary:
        st.html(summary_block(result.summary))
    for position, item in enumerate(result.results, start=1):
        st.html(result_card(position, item, preferences.area, preferences.dishes))
    st.caption(DATA_NOTE)


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="🍽️", layout="wide")
    # Fixed CSS and header markup from this app, with no dataset or user text in them.
    st.html(FORM_STYLE)
    # The header shows whether AI ranking is on once the settings have loaded.
    header = st.empty()
    header.html(page_header(None))

    try:
        settings = load_settings()
    except ConfigError as error:
        st.error("A setting in your .env file isn't valid.")
        st.text(str(error))
        return
    try:
        repository = load_repository(settings)
    except DataUnavailableError as error:
        show_setup_message(error)
        return

    configure_logging()
    service = load_service(settings, repository)
    ranker = service.llm_client
    header.html(page_header(ranker is not None))
    if ranker is None:
        st.info(MISSING_KEY_MESSAGE.format(key_name=settings.api_key_name))
    # The form on the left and results on the right. On a phone the columns stack.
    form_column, results_column = st.columns([5, 7], gap="large")
    with form_column:
        preferences = show_search_form(repository)
        # The spinner sits under the form, so it never pushes the results up and down.
        if preferences is not None:
            message = "Ranking restaurants with AI..." if ranker else "Finding restaurants..."
            with st.spinner(message):
                st.session_state["last_search"] = (preferences, service.recommend(preferences))
    with results_column:
        if "last_search" in st.session_state:
            last_preferences, result = st.session_state["last_search"]
            show_results(last_preferences, repository, result)
        else:
            st.markdown(EMPTY_RESULTS_MESSAGE)


main()
