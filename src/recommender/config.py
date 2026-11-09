"""Application settings, loaded from environment variables and an optional .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")
# The model used when LLM_MODEL isn't set, for each supported provider.
DEFAULT_MODELS = {"groq": "openai/gpt-oss-120b", "anthropic": "claude-opus-5-5"}
API_KEY_NAMES = {"groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


class ConfigError(ValueError):
    """Raised when a setting has an invalid value."""


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    llm_api_key: str | None
    llm_model: str
    llm_effort: str
    llm_timeout_seconds: float
    max_candidates: int
    max_results: int
    data_dir: Path

    @property
    def api_key_name(self) -> str:
        return API_KEY_NAMES[self.llm_provider]

    @property
    def restaurants_path(self) -> Path:
        return self.data_dir / "restaurants.parquet"

    @property
    def metadata_path(self) -> Path:
        return self.data_dir / "metadata.json"


def _positive_number(env: dict[str, str], name: str, default: str, kind: type) -> int | float:
    raw = env.get(name, default).strip()
    try:
        value = kind(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ConfigError(f"{name} must be greater than 0, got {raw!r}")
    return value


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Build settings from `env`, or from the process environment and `.env` if omitted."""
    if env is None:
        load_dotenv(PROJECT_ROOT / ".env")
        env = dict(os.environ)

    provider = env.get("LLM_PROVIDER", "groq").strip().lower()
    if provider not in DEFAULT_MODELS:
        raise ConfigError(f"LLM_PROVIDER must be one of {tuple(DEFAULT_MODELS)}, got {provider!r}")

    effort = env.get("LLM_EFFORT", "low").strip()
    if effort not in VALID_EFFORTS:
        raise ConfigError(f"LLM_EFFORT must be one of {VALID_EFFORTS}, got {effort!r}")

    max_candidates = _positive_number(env, "MAX_CANDIDATES", "8", int)
    max_results = _positive_number(env, "MAX_RESULTS", "5", int)
    if max_results > max_candidates:
        raise ConfigError("MAX_RESULTS must not be greater than MAX_CANDIDATES")

    # Resolving from a fixed base means the app finds its data from any working directory.
    data_dir = PROJECT_ROOT / Path(env.get("DATA_DIR", "./data").strip())

    return Settings(
        llm_provider=provider,
        llm_api_key=env.get(API_KEY_NAMES[provider], "").strip() or None,
        llm_model=env.get("LLM_MODEL", "").strip() or DEFAULT_MODELS[provider],
        llm_effort=effort,
        llm_timeout_seconds=_positive_number(env, "LLM_TIMEOUT_SECONDS", "45", float),
        max_candidates=max_candidates,
        max_results=max_results,
        data_dir=data_dir.resolve(),
    )
