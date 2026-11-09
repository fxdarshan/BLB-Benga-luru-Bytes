"""Calls a model on Groq to rank candidates. Every failure becomes `LLMUnavailable`."""

from __future__ import annotations

import time
from typing import Any

import groq
from pydantic import ValidationError

from recommender.llm import RANKING_SCHEMA, CallDetails, LLMReply, LLMUnavailable
from recommender.models import RankingResponse

MAX_RETRIES = 1
# Reasoning counts toward this limit. 2,048 leaves room for low-effort reasoning and 5 short
# explanations, while keeping each call well inside the 8,000 tokens a minute allowed.
MAX_COMPLETION_TOKENS = 2048
SCHEMA_NAME = "restaurant_ranking"
# Groq's GPT-OSS models accept low, medium and high, so higher settings use high.
EFFORT_FOR_GROQ = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}
# Groq returns finish reasons in OpenAI's terms. These map them to the shared failure reasons.
FAILED_FINISH_REASONS = {"length": "max_tokens", "content_filter": "refusal"}


def _usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    # Named as for Claude, so diagnostics and evaluation read the same fields for both.
    return {"input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens}


def _error_reason(error: Exception) -> str:
    checks: list[tuple[type[Exception], str]] = [
        (groq.AuthenticationError, "authentication"),
        (groq.PermissionDeniedError, "permission"),
        (groq.NotFoundError, "not_found"),
        (groq.RateLimitError, "rate_limited"),
        # Groq answers 422 when the model's output can't be used, such as a schema mismatch.
        (groq.UnprocessableEntityError, "invalid_response"),
        (groq.BadRequestError, "bad_request"),
        (groq.APITimeoutError, "timeout"),
        (groq.APIConnectionError, "connection"),
    ]
    for error_type, reason in checks:
        if isinstance(error, error_type):
            return reason
    if isinstance(error, groq.APIStatusError):
        if error.status_code == 498:  # Groq's code for capacity exceeded
            return "rate_limited"
        return "server_error" if error.status_code >= 500 else "api_error"
    return "api_error"


class GroqRanker:
    """Ranks candidates with one Groq API call. `client` can be replaced in tests."""

    def __init__(self, client: Any, model: str, effort: str) -> None:
        self.client = client
        self.model = model
        self.effort = EFFORT_FOR_GROQ.get(effort, "medium")

    @classmethod
    def from_settings(cls, api_key: str, model: str, effort: str, timeout: float) -> GroqRanker:
        client = groq.Groq(api_key=api_key, timeout=timeout, max_retries=MAX_RETRIES)
        return cls(client, model, effort)

    def rank(self, system: str, user_message: str) -> LLMReply:
        start = time.perf_counter()
        try:
            raw = self.client.chat.completions.with_raw_response.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": RANKING_SCHEMA},
                },
                reasoning_effort=self.effort,
                # Keep the model's reasoning out of the reply, which must be JSON only.
                include_reasoning=False,
                max_completion_tokens=MAX_COMPLETION_TOKENS,
            )
            response = raw.parse()
        except groq.GroqError as error:
            details = CallDetails(latency_seconds=time.perf_counter() - start)
            raise LLMUnavailable(_error_reason(error), details) from error

        choice = response.choices[0] if response.choices else None
        text = choice.message.content if choice else None
        finish_reason = choice.finish_reason if choice else None
        details = CallDetails(
            raw_text=text,
            usage=_usage(response),
            stop_reason=finish_reason,
            served_model=response.model,
            latency_seconds=time.perf_counter() - start,
            retry_count=getattr(raw, "retries_taken", None),
            request_id=getattr(response, "id", None),
        )
        if finish_reason in FAILED_FINISH_REASONS:
            raise LLMUnavailable(FAILED_FINISH_REASONS[finish_reason], details)
        if not text:
            raise LLMUnavailable("no_text_block", details)
        try:
            ranking = RankingResponse.model_validate_json(text)
        except ValidationError as error:
            raise LLMUnavailable("invalid_response", details) from error
        return LLMReply(ranking=ranking, details=details)
