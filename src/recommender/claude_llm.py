"""Calls Claude to rank candidates. Every failure becomes `LLMUnavailable`."""

from __future__ import annotations

import time
from typing import Any

import anthropic
from pydantic import ValidationError

from recommender.llm import RANKING_SCHEMA, CallDetails, LLMReply, LLMUnavailable
from recommender.models import RankingResponse

MAX_TOKENS = 16_000
MAX_RETRIES = 1
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept `fallbacks="default"`. Others, such as Haiku 5.5, reject it.
MODELS_WITH_DEFAULT_FALLBACK = frozenset(
    {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
)


def fallback_options(model: str) -> dict[str, Any]:
    """Ask the API to retry a refused request on another model, where the model supports it."""
    if model in MODELS_WITH_DEFAULT_FALLBACK:
        return {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    return {}


def _usage(message: Any) -> dict[str, int]:
    usage = message.usage
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    return {name: getattr(usage, name) for name in fields if getattr(usage, name, None) is not None}


def _fallback_used(message: Any) -> bool:
    if any(getattr(block, "type", None) == "fallback" for block in message.content):
        return True
    iterations = getattr(message.usage, "iterations", None) or []
    return any(getattr(entry, "type", None) == "fallback_message" for entry in iterations)


def _error_reason(error: Exception) -> str:
    # Most specific first, so retryable failures stay distinct from configuration errors.
    checks: list[tuple[type[Exception], str]] = [
        (anthropic.AuthenticationError, "authentication"),
        (anthropic.PermissionDeniedError, "permission"),
        (anthropic.NotFoundError, "not_found"),
        (anthropic.RateLimitError, "rate_limited"),
        (anthropic.BadRequestError, "bad_request"),
        (anthropic.APITimeoutError, "timeout"),
        (anthropic.APIConnectionError, "connection"),
    ]
    for error_type, reason in checks:
        if isinstance(error, error_type):
            return reason
    if isinstance(error, anthropic.APIStatusError):
        return "server_error" if error.status_code >= 500 else "api_error"
    return "api_error"


class ClaudeRanker:
    """Ranks candidates with one API call. `client` can be replaced in tests."""

    def __init__(self, client: Any, model: str, effort: str) -> None:
        self.client = client
        self.model = model
        self.effort = effort

    @classmethod
    def from_settings(cls, api_key: str, model: str, effort: str, timeout: float) -> ClaudeRanker:
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=MAX_RETRIES)
        return cls(client, model, effort)

    def rank(self, system: str, user_message: str) -> LLMReply:
        start = time.perf_counter()
        try:
            raw = self.client.beta.messages.with_raw_response.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user_message}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": RANKING_SCHEMA},
                },
                **fallback_options(self.model),
            )
            message = raw.parse()
        except anthropic.AnthropicError as error:
            details = CallDetails(latency_seconds=time.perf_counter() - start)
            raise LLMUnavailable(_error_reason(error), details) from error

        # Thinking and fallback blocks can come before the answer, so select the text block.
        text = next((b.text for b in message.content if getattr(b, "type", None) == "text"), None)
        details = CallDetails(
            raw_text=text,
            usage=_usage(message),
            stop_reason=message.stop_reason,
            served_model=message.model,
            fallback_model_used=_fallback_used(message),
            latency_seconds=time.perf_counter() - start,
            retry_count=getattr(raw, "retries_taken", None),
            request_id=getattr(message, "_request_id", None),
        )
        if message.stop_reason in ("refusal", "max_tokens"):
            raise LLMUnavailable(message.stop_reason, details)
        if text is None:
            raise LLMUnavailable("no_text_block", details)
        try:
            ranking = RankingResponse.model_validate_json(text)
        except ValidationError as error:
            raise LLMUnavailable("invalid_response", details) from error
        return LLMReply(ranking=ranking, details=details)
