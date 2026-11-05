import pytest

from recommender.config import PROJECT_ROOT, ConfigError, load_settings


def test_defaults():
    settings = load_settings({})
    assert settings.anthropic_api_key is None
    assert settings.llm_model == "claude-opus-5-5"
    assert settings.llm_effort == "medium"
    assert settings.llm_timeout_seconds == 45
    assert settings.max_candidates == 15
    assert settings.max_results == 5
    assert settings.data_dir == (PROJECT_ROOT / "data").resolve()
    assert settings.restaurants_path.name == "restaurants.parquet"
    assert settings.metadata_path.name == "metadata.json"


def test_blank_api_key_counts_as_missing():
    assert load_settings({"ANTHROPIC_API_KEY": "   "}).anthropic_api_key is None


def test_absolute_data_dir_is_kept(tmp_path):
    assert load_settings({"DATA_DIR": str(tmp_path)}).data_dir == tmp_path.resolve()


@pytest.mark.parametrize(
    "env",
    [
        {"LLM_EFFORT": "extreme"},
        {"MAX_CANDIDATES": "abc"},
        {"MAX_CANDIDATES": "0"},
        {"MAX_RESULTS": "-1"},
        {"LLM_TIMEOUT_SECONDS": "soon"},
        {"MAX_RESULTS": "20", "MAX_CANDIDATES": "15"},
    ],
)
def test_invalid_settings_fail(env):
    with pytest.raises(ConfigError):
        load_settings(env)
