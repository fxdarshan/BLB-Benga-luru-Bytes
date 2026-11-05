"""Streamlit interface. Run with `uv run streamlit run app.py`."""

from __future__ import annotations

import streamlit as st

from recommender.config import ConfigError, Settings, load_settings
from recommender.display import budget_option_label, result_card, search_summary
from recommender.models import BudgetBand, Preferences
from recommender.repository import INGEST_COMMAND, DataUnavailableError, RestaurantRepository
from recommender.service import RecommendationService

BUDGET_OPTIONS = ("any", "low", "medium", "high")
NO_RESULTS_MESSAGE = (
    "No restaurants match this search, even after loosening the rating and budget. "
    "Try a different area or cuisine."
)
DATA_NOTE = (
    "Data comes from a fixed Zomato snapshot for Bangalore, so some places may have closed or "
    "changed. Check before you go."
)


@st.cache_resource(show_spinner="Loading restaurants...")
def load_repository(settings: Settings) -> RestaurantRepository:
    return RestaurantRepository.load(settings.restaurants_path, settings.metadata_path)


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
        area = st.selectbox("Area in Bangalore", metadata.areas)
        budget = st.radio(
            "Budget",
            BUDGET_OPTIONS,
            format_func=lambda name: budget_option_label(name, bands),
            horizontal=True,
        )
        # Without select_all=False, typing "Thai" and pressing Enter also selects every other match.
        cuisines = st.multiselect(
            "Cuisine", metadata.cuisines, placeholder="Any cuisine", select_all=False
        )
        min_rating = st.slider("Minimum rating", 0.0, 5.0, 3.5, step=0.1, format="%.1f")
        include_unrated = st.checkbox("Include new and unrated restaurants")
        additional = st.text_input(
            "Anything else? (optional)",
            placeholder="For example, family-friendly, quick service",
            max_chars=300,
        )
        submitted = st.form_submit_button("Find restaurants", type="primary")
    if not submitted:
        return None
    return Preferences(
        area=area,
        budget=budget,
        cuisines=tuple(cuisines),
        min_rating=min_rating,
        include_unrated=include_unrated,
        additional=additional,
    )


def show_results(preferences: Preferences, repository: RestaurantRepository, result) -> None:
    # Dataset and user text goes through st.html after escaping, so Markdown, maths and HTML in
    # it display literally. Results stay until the next search, with a label showing their search.
    st.html(search_summary(preferences, repository.metadata.budget_bands))
    for relaxation in result.relaxations:
        st.info(relaxation.message)
    if not result.results:
        st.warning(NO_RESULTS_MESSAGE)
        return
    if result.notice:
        st.warning(result.notice)
    for position, candidate in enumerate(result.results, start=1):
        st.html(result_card(position, candidate, preferences.area))
    st.caption(DATA_NOTE)


def main() -> None:
    st.set_page_config(page_title="Bangalore Restaurant Finder", page_icon="🍽️")
    st.title("Bangalore Restaurant Finder")
    st.caption("Tell us what you're looking for, and we'll suggest where to eat.")

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

    service = RecommendationService(
        repository, max_candidates=settings.max_candidates, max_results=settings.max_results
    )
    preferences = show_search_form(repository)
    if preferences is not None:
        st.session_state["last_search"] = (preferences, service.recommend(preferences))
    if "last_search" in st.session_state:
        last_preferences, result = st.session_state["last_search"]
        show_results(last_preferences, repository, result)


main()
