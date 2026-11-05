"""Runs the Streamlit script without a browser, using small data files."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from recommender import ingest
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
    return [element.proto.body for element in app.get("html")]


def test_form_shows_every_preference(data_dir):
    app = start()
    assert app.title[0].value == "BLB (Banga-Luru_Bytes)"
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
    assert blocks[0].startswith('<div style="opacity: 0.8;">Results for: BTM')
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
