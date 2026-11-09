import os
from types import SimpleNamespace

import anthropic
import pytest

from fakes import REQUEST, FakeAnthropic, message, ranking_json, status_error
from recommender.claude_llm import (
    ClaudeRanker,
    fallback_options,
)
from recommender.llm import RANKING_SCHEMA, LLMUnavailable
from recommender.models import RankingResponse

GOOD = ranking_json(("R1", "Great fit."), ("R2", "Also good.", ["family-friendly"]))


def rank(client, model="claude-opus-5-5"):
    return ClaudeRanker(client, model, "medium").rank("system", "user")


def test_successful_ranking_and_details():
    client = FakeAnthropic(message(GOOD), retries=1)
    reply = rank(client)
    assert [r.candidate_id for r in reply.ranking.recommendations] == ["R1", "R2"]
    assert reply.ranking.recommendations[1].unverified_preferences == ["family-friendly"]
    details = reply.details
    assert details.raw_text == GOOD
    assert details.usage == {
        "input_tokens": 3000,
        "output_tokens": 800,
        "cache_read_input_tokens": 0,
    }
    assert (details.stop_reason, details.served_model) == ("end_turn", "claude-opus-5-5")
    assert details.retry_count == 1
    assert details.request_id == "req_test"
    assert details.latency_seconds is not None
    assert details.fallback_model_used is False


def test_request_uses_schema_effort_and_no_sampling_settings():
    client = FakeAnthropic(message(GOOD))
    rank(client)
    request = client.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": RANKING_SCHEMA},
    }
    assert request["system"] == "system"
    assert request["messages"] == [{"role": "user", "content": "user"}]
    assert not {"temperature", "thinking", "top_p"} & set(request)


def test_fallback_options_sent_for_opus_and_left_out_for_haiku():
    assert fallback_options("claude-opus-5-5") == {
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }
    assert fallback_options("claude-haiku-5-5") == {}
    opus, haiku = (
        FakeAnthropic(message(GOOD)),
        FakeAnthropic(message(GOOD, model="claude-haiku-5-5")),
    )
    rank(opus)
    rank(haiku, model="claude-haiku-5-5")
    assert opus.requests[0]["fallbacks"] == "default"
    assert "fallbacks" not in haiku.requests[0] and "betas" not in haiku.requests[0]


def test_schema_matches_the_pydantic_model():
    def fields(schema):
        return set(schema["properties"]), set(schema["required"])

    assert fields(RANKING_SCHEMA) == (set(RankingResponse.model_fields),) * 2
    item = RANKING_SCHEMA["properties"]["recommendations"]["items"]
    recommendation = RankingResponse.model_fields["recommendations"].annotation.__args__[0]
    assert fields(item) == (set(recommendation.model_fields),) * 2


def test_text_block_is_found_after_thinking_and_fallback_blocks():
    blocks = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="fallback")]
    reply = rank(FakeAnthropic(message(GOOD, blocks=blocks)))
    assert reply.details.fallback_model_used is True
    assert len(reply.ranking.recommendations) == 2


def test_fallback_detected_from_usage_iterations():
    iterations = [SimpleNamespace(type="message"), SimpleNamespace(type="fallback_message")]
    reply = rank(FakeAnthropic(message(GOOD, iterations=iterations, model="claude-opus-4-8")))
    assert reply.details.fallback_model_used is True
    assert reply.details.served_model == "claude-opus-4-8"


def test_missing_text_block_raises_llm_unavailable():
    with pytest.raises(LLMUnavailable) as caught:
        rank(FakeAnthropic(message(blocks=[SimpleNamespace(type="thinking", thinking="")])))
    assert caught.value.reason == "no_text_block"


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refusal_and_truncation_raise_with_details(stop_reason):
    with pytest.raises(LLMUnavailable) as caught:
        rank(FakeAnthropic(message('{"summary": "cut', stop_reason=stop_reason)))
    assert caught.value.reason == stop_reason
    assert caught.value.details.raw_text == '{"summary": "cut'


@pytest.mark.parametrize(
    "text", ["not json", '{"summary": "x"}', '{"summary": 1, "recommendations": []}']
)
def test_invalid_response_raises_and_keeps_raw_text(text):
    with pytest.raises(LLMUnavailable) as caught:
        rank(FakeAnthropic(message(text)))
    assert caught.value.reason == "invalid_response"
    assert caught.value.details.raw_text == text


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (status_error(anthropic.AuthenticationError, 401), "authentication"),
        (status_error(anthropic.PermissionDeniedError, 403), "permission"),
        (status_error(anthropic.NotFoundError, 404), "not_found"),
        (status_error(anthropic.RateLimitError, 429), "rate_limited"),
        (status_error(anthropic.BadRequestError, 400), "bad_request"),
        (status_error(anthropic.InternalServerError, 500), "server_error"),
        (status_error(anthropic.APIStatusError, 529), "server_error"),
        (status_error(anthropic.APIStatusError, 418), "api_error"),
        (anthropic.APITimeoutError(request=REQUEST), "timeout"),
        (anthropic.APIConnectionError(request=REQUEST), "connection"),
    ],
)
def test_api_errors_map_to_reasons(error, reason):
    with pytest.raises(LLMUnavailable) as caught:
        rank(FakeAnthropic(error=error))
    assert caught.value.reason == reason
    assert caught.value.details.latency_seconds is not None


def test_client_settings_from_settings():
    ranker = ClaudeRanker.from_settings("test-key", "claude-opus-5-5", "low", 45.0)
    assert ranker.client.max_retries == 1
    assert ranker.client.timeout == 45.0
    assert (ranker.model, ranker.effort) == ("claude-opus-5-5", "low")


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1", reason="Makes a paid API call. Set RUN_LIVE_TESTS=1."
)
def test_live_api_call_returns_a_valid_ranking():
    from recommender.config import load_settings

    settings = load_settings()
    assert settings.anthropic_api_key, "Set ANTHROPIC_API_KEY in .env"
    ranker = ClaudeRanker.from_settings(
        settings.anthropic_api_key, settings.llm_model, "low", settings.llm_timeout_seconds
    )
    user = (
        '<preferences>{"area": "MG Road"}</preferences>\n<applied_limits>{}</applied_limits>\n'
        "<diner_notes>(none)</diner_notes>\n<candidates>"
        '[{"id": "R1", "name": "Test Cafe", "rating": 4.2, "votes": 300, "cuisines": ["Cafe"]}]'
        "</candidates>"
    )
    reply = ranker.rank("Rank the candidates. Use only the data given.", user)
    assert reply.ranking.recommendations
    assert reply.details.usage["input_tokens"] > 0
