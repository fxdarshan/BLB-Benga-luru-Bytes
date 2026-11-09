import pytest

from recommender.config import PROJECT_ROOT, ConfigError, load_settings


def test_defaults():
    settings = load_settings({})
    assert settings.llm_provider == "groq"
    assert settings.llm_api_key is None
    assert settings.llm_model == "openai/gpt-oss-120b"
    assert settings.api_key_name == "GROQ_API_KEY"
    assert settings.llm_effort == "low"
    assert settings.llm_timeout_seconds == 45
    assert settings.max_candidates == 8
    assert settings.max_results == 5
    assert settings.data_dir == (PROJECT_ROOT / "data").resolve()
    assert settings.restaurants_path.name == "restaurants.parquet"
    assert settings.metadata_path.name == "metadata.json"


def test_blank_api_key_counts_as_missing():
    assert load_settings({"GROQ_API_KEY": "   "}).llm_api_key is None


def test_key_and_default_model_follow_the_provider():
    env = {"GROQ_API_KEY": "groq-test", "ANTHROPIC_API_KEY": "anthropic-test"}
    groq = load_settings(env)
    assert (groq.llm_api_key, groq.llm_model) == ("groq-test", "openai/gpt-oss-120b")
    claude = load_settings({**env, "LLM_PROVIDER": "Anthropic"})
    assert (claude.llm_provider, claude.llm_api_key) == ("anthropic", "anthropic-test")
    assert claude.llm_model == "claude-opus-5-5"
    assert claude.api_key_name == "ANTHROPIC_API_KEY"


def test_model_can_be_overridden():
    assert load_settings({"LLM_MODEL": "openai/gpt-oss-20b"}).llm_model == "openai/gpt-oss-20b"


def test_absolute_data_dir_is_kept(tmp_path):
    assert load_settings({"DATA_DIR": str(tmp_path)}).data_dir == tmp_path.resolve()


@pytest.mark.parametrize(
    "env",
    [
        {"LLM_EFFORT": "extreme"},
        {"LLM_PROVIDER": "openai"},
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
