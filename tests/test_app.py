"""Runs the Streamlit script without a browser, using small data files."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from fakes import FakeRanker, ranking_json
from recommender import ingest
from recommender.llm import LLMUnavailable
from test_ingest import run, varied_rows

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(autouse=True)
def fresh_cache():
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    rows = varied_rows()
    rows[0].update({"name": "*Bold* <b>Name</b> $x$", "rate": "4.9/5", "votes": 5000})
    ingest.write_outputs(run(rows), tmp_path / "restaurants.parquet", tmp_path / "metadata.json")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def start():
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    return app


def submit(app):
    app.button[0].click().run()
    assert not app.exception
    return app


def html_blocks(app):
    # The page's style block and header are fixed markup, not results, so they are left out.
    return [
        e.proto.body
        for e in app.get("html")
        if "<style>" not in e.proto.body and "blb-header" not in e.proto.body
    ]


def header(app):
    return next(e.proto.body for e in app.get("html") if "blb-header" in e.proto.body)


def test_form_shows_every_preference(data_dir):
    app = start()
    assert "Banga-Luru Bytes" in header(app)
    assert app.selectbox[0].options == ["BTM", "HSR", "MG Road"]
    assert len(app.radio[0].options) == 4
    assert "for two" in app.radio[0].options[1]
    assert app.multiselect[0].options == ["Italian"]
    assert app.slider[0].value == 3.5
    assert app.checkbox[0].value is False
    assert app.text_input[0].value == ""


def test_changing_a_widget_does_not_start_a_search(data_dir):
    app = start()
    app.selectbox[0].select("HSR").run()
    assert html_blocks(app) == []


def test_search_shows_cards_with_required_fields_and_notice(data_dir):
    app = submit(start())
    blocks = html_blocks(app)
    assert blocks[0].startswith('<div class="blb-search">')
    assert '<span class="blb-chip">BTM</span>' in blocks[0]
    assert len(blocks) == 6
    assert "★ 4.0 (100 votes)" in blocks[1]
    assert "Italian" in blocks[1]
    assert "for two" in blocks[1]
    assert any("AI explanations are unavailable" in w.value for w in app.warning)
    assert "fixed Zomato snapshot" in app.caption[-1].value


def test_narrow_search_shows_relaxation_notice(data_dir):
    app = start()
    app.selectbox[0].select("MG Road")
    app.slider[0].set_value(4.5)
    submit(app)
    assert any("4.5+" in notice.value and "4.0+" in notice.value for notice in app.info)
    assert len(html_blocks(app)) == 6


def test_impossible_search_shows_empty_message(data_dir):
    app = start()
    app.selectbox[0].select("HSR")
    app.slider[0].set_value(5.0)
    submit(app)
    assert any("Try a different area, budget or cuisine" in w.value for w in app.warning)
    assert not any("AI explanations" in w.value for w in app.warning)
    assert len(html_blocks(app)) == 1


def test_results_stay_when_inputs_change_until_the_next_search(data_dir):
    app = submit(start())
    first = html_blocks(app)[0]
    app.selectbox[0].select("HSR").run()
    assert html_blocks(app)[0] == first


def test_markdown_and_html_in_names_are_escaped(data_dir):
    app = start()
    app.selectbox[0].select("MG Road")
    page = "".join(html_blocks(submit(app)))
    assert "*Bold* &lt;b&gt;Name&lt;/b&gt; $x$" in page
    assert "<b>Name" not in page


def test_missing_data_shows_setup_message(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "missing"))
    app = start()
    assert "isn't ready" in app.error[0].value
    assert "recommender.ingest" in app.code[0].value
    assert not app.button


def test_damaged_data_shows_setup_message(data_dir):
    (data_dir / "restaurants.parquet").write_bytes(b"damaged")
    app = start()
    assert "isn't ready" in app.error[0].value
    assert "damaged or out of date" in app.text[0].value


def test_invalid_setting_shows_a_clear_message(data_dir, monkeypatch):
    monkeypatch.setenv("MAX_RESULTS", "many")
    app = start()
    assert "isn't valid" in app.error[0].value
    assert "MAX_RESULTS" in app.text[0].value


# LLM ranking in the app


@pytest.fixture
def fake_ranker(monkeypatch):
    def install(ranker):
        monkeypatch.setattr("recommender.rankers.make_ranker", lambda settings: ranker)
        return ranker

    return install


def test_missing_api_key_message_keeps_results_working(data_dir, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("recommender.config.load_dotenv", lambda *a, **k: False)
    app = submit(start())
    assert "AI ranking off" in header(app)
    assert any("add GROQ_API_KEY" in message.value for message in app.info)
    assert len(html_blocks(app)) == 6


def test_ai_results_show_summary_explanations_and_unconfirmed_preferences(data_dir, fake_ranker):
    text = ranking_json(
        ("R2", "Quiet <b>and</b> *cosy*.", ["family-friendly"]),
        ("R1", "Close by."),
        summary="Choose $R2$ for calm.",
    )
    fake_ranker(FakeRanker(text))
    app = start()
    app.text_input[0].input("family-friendly")
    blocks = html_blocks(submit(app))
    page = "".join(blocks)
    assert not any("no API key" in message.value for message in app.info)
    assert "AI ranking on" in header(app)
    assert not any("AI explanations" in w.value for w in app.warning)
    assert "Choose $" in blocks[1] and "for calm." in blocks[1]
    assert "Why this fits:</b> Quiet &lt;b&gt;and&lt;/b&gt; *cosy*." in page
    assert "Could not confirm: family-friendly" in page
    assert len(blocks) == 4


def test_llm_failure_shows_notice_and_score_ranked_results(data_dir, fake_ranker):
    fake_ranker(FakeRanker(error=LLMUnavailable("timeout")))
    app = submit(start())
    assert any("AI explanations are unavailable" in w.value for w in app.warning)
    assert len(html_blocks(app)) == 6
    page = "".join(html_blocks(app))
    assert "timeout" not in page and "Why this fits" not in page


def test_repeated_search_reuses_the_shared_service_cache(data_dir, fake_ranker):
    ranker = fake_ranker(FakeRanker(ranking_json(("R1", "Fine."))))
    first = start()
    submit(first)
    second = start()
    submit(second)
    assert len(ranker.calls) == 1
    assert "Why this fits" in "".join(html_blocks(second))


def test_page_styles_dropdown_options_bold_and_larger(data_dir):
    styles = [e.proto.body for e in start().get("html") if "<style>" in e.proto.body]
    assert len(styles) == 1
    assert '[role="option"]' in styles[0] and "font-weight: 600" in styles[0]


def test_form_has_a_dish_dropdown(data_dir):
    app = start()
    assert [m.label for m in app.multiselect] == ["Cuisine", "Dish"]
