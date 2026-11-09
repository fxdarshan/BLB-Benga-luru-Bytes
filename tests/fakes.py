"""Stand-ins for the Anthropic client and the ranker, so tests make no API calls."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx2

from recommender.llm import CallDetails, LLMReply, LLMUnavailable
from recommender.models import RankingResponse

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def ranking_json(*items, summary="R1 is the best fit, and R2 is a close second."):
    recommendations = [
        {
            "candidate_id": item[0],
            "explanation": item[1] if len(item) > 1 else f"{item[0]} suits this search well.",
            "unverified_preferences": list(item[2]) if len(item) > 2 else [],
        }
        for item in items
    ]
    return json.dumps({"summary": summary, "recommendations": recommendations})


def message(
    text=None,
    *,
    stop_reason="end_turn",
    model="claude-opus-5-5",
    blocks=None,
    iterations=None,
):
    content = list(blocks or [])
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    usage = SimpleNamespace(
        input_tokens=3000,
        output_tokens=800,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=None,
        iterations=iterations,
    )
    result = SimpleNamespace(content=content, stop_reason=stop_reason, model=model, usage=usage)
    result._request_id = "req_test"
    return result


class FakeAnthropic:
    """Mimics `client.beta.messages.with_raw_response.create`, recording each request."""

    def __init__(self, reply=None, *, error=None, retries=0):
        self.reply = reply
        self.error = error
        self.retries = retries
        self.requests = []
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(with_raw_response=SimpleNamespace(create=self._create))
        )

    def _create(self, **request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        reply = self.reply
        return SimpleNamespace(parse=lambda: reply, retries_taken=self.retries)


class FakeRanker:
    """Mimics `ClaudeRanker.rank`: returns a fixed ranking, or raises."""

    def __init__(self, ranking_text=None, *, error=None, raw_text=None, model="fake-model"):
        self.ranking_text = ranking_text
        self.model = model
        self.effort = "medium"
        self.error = error
        self.raw_text = raw_text
        self.calls = []

    def rank(self, system, user_message):
        self.calls.append((system, user_message))
        if self.error is not None:
            raise self.error
        details = CallDetails(
            raw_text=self.raw_text or self.ranking_text,
            usage={"input_tokens": 3000, "output_tokens": 800},
            stop_reason="end_turn",
            served_model="claude-opus-5-5",
            latency_seconds=1.5,
            retry_count=0,
        )
        return LLMReply(RankingResponse.model_validate_json(self.ranking_text), details)


def status_error(error_type, status):
    response = httpx2.Response(status, request=REQUEST)
    return error_type("simulated failure", response=response, body=None)


__all__ = [
    "REQUEST",
    "FakeAnthropic",
    "FakeRanker",
    "LLMUnavailable",
    "message",
    "ranking_json",
    "status_error",
]
