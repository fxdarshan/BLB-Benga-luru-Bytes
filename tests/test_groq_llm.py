import os
from types import SimpleNamespace

import groq
import httpx
import pytest

from recommender.claude_llm import ClaudeRanker
from recommender.config import load_settings
from recommender.groq_llm import MAX_COMPLETION_TOKENS, SCHEMA_NAME, GroqRanker
from recommender.llm import RANKING_SCHEMA, LLMUnavailable
from recommender.rankers import make_ranker

REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
GOOD = (
    '{"summary": "R1 wins.", "recommendations": ['
    '{"candidate_id": "R1", "explanation": "Great.", "unverified_preferences": []}]}'
)


def completion(text=GOOD, finish_reason="stop", model="openai/gpt-oss-120b", choices=True):
    message = SimpleNamespace(content=text, reasoning=None)
    return SimpleNamespace(
        id="chatcmpl-test",
        model=model,
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)] if choices else [],
        usage=SimpleNamespace(prompt_tokens=3000, completion_tokens=700),
    )


class FakeGroq:
    def __init__(self, reply=None, *, error=None, retries=0):
        self.reply, self.error, self.retries = reply, error, retries
        self.requests = []
        create = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=SimpleNamespace(with_raw_response=create))

    def _create(self, **request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(parse=lambda: self.reply, retries_taken=self.retries)


def rank(client, effort="medium"):
    return GroqRanker(client, "openai/gpt-oss-120b", effort).rank("system", "user")


def status_error(error_type, status):
    response = httpx.Response(status, request=REQUEST)
    return error_type("simulated failure", response=response, body=None)


def test_successful_ranking_and_details():
    reply = rank(FakeGroq(completion(), retries=1))
    assert reply.ranking.recommendations[0].candidate_id == "R1"
    details = reply.details
    assert details.raw_text == GOOD
    assert details.usage == {"input_tokens": 3000, "output_tokens": 700}
    assert (details.stop_reason, details.served_model) == ("stop", "openai/gpt-oss-120b")
    assert details.retry_count == 1
    assert details.request_id == "chatcmpl-test"
    assert details.fallback_model_used is False


def test_request_uses_strict_schema_and_hides_reasoning():
    client = FakeGroq(completion())
    rank(client)
    request = client.requests[0]
    assert request["model"] == "openai/gpt-oss-120b"
    assert request["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": RANKING_SCHEMA},
    }
    assert request["include_reasoning"] is False
    assert request["max_completion_tokens"] == MAX_COMPLETION_TOKENS
    assert "reasoning_format" not in request


@pytest.mark.parametrize(
    ("effort", "sent"), [("low", "low"), ("medium", "medium"), ("xhigh", "high"), ("max", "high")]
)
def test_effort_maps_to_groq_values(effort, sent):
    client = FakeGroq(completion())
    rank(client, effort=effort)
    assert client.requests[0]["reasoning_effort"] == sent


@pytest.mark.parametrize(("finish_reason", "reason"), [("length", "max_tokens")])
def test_cut_off_reply_raises(finish_reason, reason):
    with pytest.raises(LLMUnavailable) as caught:
        rank(FakeGroq(completion('{"summary": "cut', finish_reason=finish_reason)))
    assert caught.value.reason == reason
    assert caught.value.details.raw_text == '{"summary": "cut'


@pytest.mark.parametrize(
    "reply", [completion(text=None), completion(text=""), completion(choices=False)]
)
def test_empty_reply_raises(reply):
    with pytest.raises(LLMUnavailable) as caught:
        rank(FakeGroq(reply))
    assert caught.value.reason == "no_text_block"


@pytest.mark.parametrize("text", ["not json", '{"summary": "x"}'])
def test_invalid_reply_raises_and_keeps_raw_text(text):
    with pytest.raises(LLMUnavailable) as caught:
        rank(FakeGroq(completion(text)))
    assert caught.value.reason == "invalid_response"
    assert caught.value.details.raw_text == text


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (status_error(groq.AuthenticationError, 401), "authentication"),
        (status_error(groq.PermissionDeniedError, 403), "permission"),
        (status_error(groq.NotFoundError, 404), "not_found"),
        (status_error(groq.RateLimitError, 429), "rate_limited"),
        (status_error(groq.UnprocessableEntityError, 422), "invalid_response"),
        (status_error(groq.BadRequestError, 400), "bad_request"),
        (status_error(groq.APIStatusError, 498), "rate_limited"),
        (status_error(groq.InternalServerError, 503), "server_error"),
        (status_error(groq.APIStatusError, 418), "api_error"),
        (groq.APITimeoutError(request=REQUEST), "timeout"),
        (groq.APIConnectionError(request=REQUEST), "connection"),
    ],
)
def test_api_errors_map_to_reasons(error, reason):
    with pytest.raises(LLMUnavailable) as caught:
        rank(FakeGroq(error=error))
    assert caught.value.reason == reason


def test_client_settings_from_settings():
    ranker = GroqRanker.from_settings("test-key", "openai/gpt-oss-20b", "low", 45.0)
    assert ranker.client.max_retries == 1
    assert ranker.client.timeout == 45.0
    assert (ranker.model, ranker.effort) == ("openai/gpt-oss-20b", "low")


def test_make_ranker_follows_the_provider():
    assert make_ranker(load_settings({})) is None
    groq_ranker = make_ranker(load_settings({"GROQ_API_KEY": "test-key"}))
    assert isinstance(groq_ranker, GroqRanker)
    assert groq_ranker.model == "openai/gpt-oss-120b"
    claude = make_ranker(
        load_settings({"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"})
    )
    assert isinstance(claude, ClaudeRanker)
    assert make_ranker(load_settings({"LLM_PROVIDER": "anthropic", "GROQ_API_KEY": "x"})) is None


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1", reason="Calls the Groq API. Set RUN_LIVE_TESTS=1."
)
def test_live_groq_call_returns_a_valid_ranking():
    settings = load_settings()
    assert settings.llm_provider == "groq" and settings.llm_api_key, "Set GROQ_API_KEY in .env"
    ranker = GroqRanker.from_settings(
        settings.llm_api_key, settings.llm_model, "low", settings.llm_timeout_seconds
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


class ModelAwareGroq(FakeGroq):
    """Answers each model differently: a reply, or an error to raise."""

    def __init__(self, outcomes):
        super().__init__()
        self.outcomes = outcomes

    def _create(self, **request):
        self.requests.append(request)
        outcome = self.outcomes[request["model"]]
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(parse=lambda: outcome, retries_taken=0)


MAIN, SMALL = "openai/gpt-oss-120b", "openai/gpt-oss-20b"


def fallback_ranker(outcomes, fallback=SMALL):
    client = ModelAwareGroq(outcomes)
    return client, GroqRanker(client, MAIN, "low", fallback)


def test_a_rate_limit_is_retried_once_on_the_fallback_model():
    client, ranker = fallback_ranker(
        {MAIN: status_error(groq.RateLimitError, 429), SMALL: completion(model=SMALL)}
    )
    reply = ranker.rank("system", "user")
    assert [r["model"] for r in client.requests] == [MAIN, SMALL]
    assert reply.details.fallback_model_used is True
    assert reply.details.served_model == SMALL
    assert reply.ranking.recommendations[0].candidate_id == "R1"


def test_capacity_errors_count_as_rate_limits_for_the_fallback():
    client, ranker = fallback_ranker(
        {MAIN: status_error(groq.APIStatusError, 498), SMALL: completion(model=SMALL)}
    )
    assert ranker.rank("system", "user").details.fallback_model_used is True


@pytest.mark.parametrize(
    "error",
    [status_error(groq.BadRequestError, 400), status_error(groq.InternalServerError, 500)],
)
def test_other_failures_do_not_use_the_fallback(error):
    client, ranker = fallback_ranker({MAIN: error, SMALL: completion(model=SMALL)})
    with pytest.raises(LLMUnavailable):
        ranker.rank("system", "user")
    assert len(client.requests) == 1


def test_a_rate_limited_fallback_reports_the_rate_limit():
    client, ranker = fallback_ranker(
        {
            MAIN: status_error(groq.RateLimitError, 429),
            SMALL: status_error(groq.RateLimitError, 429),
        }
    )
    with pytest.raises(LLMUnavailable) as raised:
        ranker.rank("system", "user")
    assert raised.value.reason == "rate_limited"
    assert raised.value.details.fallback_model_used is True
    assert len(client.requests) == 2


@pytest.mark.parametrize("fallback", [None, MAIN])
def test_no_fallback_when_none_is_set_or_it_is_the_main_model(fallback):
    client, ranker = fallback_ranker({MAIN: status_error(groq.RateLimitError, 429)}, fallback)
    assert ranker.fallback_model is None
    with pytest.raises(LLMUnavailable):
        ranker.rank("system", "user")
    assert len(client.requests) == 1


def test_make_ranker_passes_the_fallback_model():
    assert make_ranker(load_settings({"GROQ_API_KEY": "test"})).fallback_model == SMALL
    off = load_settings({"GROQ_API_KEY": "test", "LLM_FALLBACK_MODEL": "none"})
    assert make_ranker(off).fallback_model is None
