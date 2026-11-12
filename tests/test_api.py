"""Tests for the HTTP API. A fake ranker stands in for the LLM, so nothing calls Groq."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import make_repository, make_restaurant
from fakes import FakeRanker, ranking_json
from recommender.api import ApiSettings, RateLimiter, create_app
from recommender.config import ConfigError
from recommender.llm import LLMUnavailable
from recommender.repository import DataUnavailableError
from recommender.service import NOTICE_NOT_AI_RANKED, RecommendationService

ORIGIN = "https://blb.example.com"
SEARCH = {"area": "MG Road", "budget": "medium", "min_rating": 3.5}


def repository():
    return make_repository(
        make_restaurant(
            "r1",
            name="Alpha <b>Bistro</b>",
            rating=4.5,
            votes=711,
            cost_for_two=500,
            dishes=["Mutton Biryani", "Pasta"],
            review_snippets=["The food was awesome and a clean restaurant. " * 8],
        ),
        make_restaurant(
            "r2",
            name="Beta",
            rating=4.2,
            cost_for_two=550,
            location="Indiranagar",
            dishes=["Chicken Biryani"],
        ),
        make_restaurant("r3", name="Gamma", rating=None, votes=0, cost_for_two=450),
        popular_cuisines=("Thai",),
        dishes=("Biryani", "Pasta"),
    )


def client_for(ranker=None, *, settings=None, factory=None):
    def make_service():
        return RecommendationService(repository(), ranker)

    app = create_app(factory or make_service, settings or ApiSettings(allowed_origins=(ORIGIN,)))
    return TestClient(app)


def good_ranker():
    text = ranking_json(
        ("R1", "Alpha suits you well.", ["quiet"], 1),
        ("R2", "Beta is a close second."),
        summary="Alpha leads, and Beta is close.",
    )
    return FakeRanker(text)


def test_health_reports_the_build_and_whether_ai_ranking_is_on():
    with client_for(good_ranker()) as client:
        assert client.get("/health").json() == {
            "status": "ok",
            "build_id": "test-build",
            "ai_ranking": True,
        }
    with client_for(None) as client:
        assert client.get("/health").json()["ai_ranking"] is False


def test_options_lists_areas_cuisines_in_menu_order_and_budget_labels():
    with client_for() as client:
        body = client.get("/options").json()
    assert body["areas"] == ["MG Road", "BTM"]
    assert body["cuisines"] == ["Thai", "BBQ", "Chinese", "Italian"]
    assert [b["value"] for b in body["budgets"]] == ["any", "low", "medium", "high"]
    assert body["budgets"][2]["label"].startswith("Medium (")
    assert body["budgets"][0]["name"] == "Any budget"
    assert body["budgets"][0]["range"] == "No limit"
    assert body["budgets"][2]["range"] == "₹400 to ₹600"
    assert body["defaults"] == {"min_rating": 3.5, "max_additional_chars": 300}


def test_recommend_returns_display_ready_facts_and_the_ai_text():
    with client_for(good_ranker()) as client:
        body = client.post(
            "/recommend", json={**SEARCH, "dishes": ["Biryani"], "additional": "somewhere quiet"}
        ).json()
    assert body["ai_ranked"] is True
    assert body["notice"] is None
    assert body["summary"] == "Alpha leads, and Beta is close."
    assert body["search_summary"][0] == "MG Road"
    first = body["results"][0]
    assert first["rank"] == 1
    # Text stays plain: the frontend escapes it.
    assert first["name"] == "Alpha <b>Bistro</b>"
    assert first["rating"] == "★ 4.5 (711 votes)"
    assert first["is_rated"] is True
    assert first["badges"][0] == "₹500 for two"
    assert first["liked_for"] == ["Mutton Biryani"]
    assert first["explanation"] == "Alpha suits you well."
    assert first["unverified"] == ["quiet"]
    assert first["review"].endswith("…") and len(first["review"]) <= 201
    assert first["near"] is None
    assert "failure_reason" not in body


def test_a_restaurant_outside_the_area_is_marked_near_it():
    with client_for(good_ranker()) as client:
        results = client.post("/recommend", json=SEARCH).json()["results"]
    assert results[1]["near"] == "Near MG Road"


def test_an_llm_failure_returns_score_ranked_results_without_internal_details():
    ranker = FakeRanker(error=LLMUnavailable("rate_limited"))
    with client_for(ranker) as client:
        body = client.post("/recommend", json=SEARCH).json()
    assert body["ai_ranked"] is False
    assert body["notice"] == NOTICE_NOT_AI_RANKED
    assert [r["name"] for r in body["results"]][:2] == ["Alpha <b>Bistro</b>", "Beta"]
    assert "rate_limited" not in str(body)


def test_no_matches_returns_an_empty_list():
    with client_for(good_ranker()) as client:
        body = client.post("/recommend", json={"area": "BTM"}).json()
    assert body["results"] == []


@pytest.mark.parametrize(
    "search",
    [
        {"area": "Atlantis"},
        {"area": "MG Road", "cuisines": ["Martian"]},
        {"area": "MG Road", "min_rating": 6},
        {"area": "MG Road", "additional": "x" * 301},
        {"area": "MG Road", "budget": "free"},
        {"area": "MG Road", "unknown_field": 1},
    ],
)
def test_invalid_searches_get_422(search):
    with client_for(good_ranker()) as client:
        response = client.post("/recommend", json=search)
    assert response.status_code == 422
    assert "detail" in response.json()


def test_searches_over_the_limit_get_429_with_retry_after():
    settings = ApiSettings(allowed_origins=(ORIGIN,), rate_limit_per_minute=2)
    with client_for(good_ranker(), settings=settings) as client:
        codes = [client.post("/recommend", json=SEARCH).status_code for _ in range(3)]
        response = client.post("/recommend", json=SEARCH)
    assert codes == [200, 200, 429]
    assert response.json() == {"detail": "Too many searches. Try again in a minute."}
    assert 1 <= int(response.headers["Retry-After"]) <= 60


def test_behind_a_proxy_the_limit_uses_the_address_the_proxy_saw():
    settings = ApiSettings(rate_limit_per_minute=1, trusted_proxy_hops=1)
    with client_for(good_ranker(), settings=settings) as client:
        first = client.post("/recommend", json=SEARCH, headers={"X-Forwarded-For": "1.1.1.1"})
        # A faked entry before the proxy's own doesn't give a fresh allowance.
        faked = client.post(
            "/recommend", json=SEARCH, headers={"X-Forwarded-For": "9.9.9.9, 1.1.1.1"}
        )
        other = client.post("/recommend", json=SEARCH, headers={"X-Forwarded-For": "2.2.2.2"})
    assert [first.status_code, faked.status_code, other.status_code] == [200, 429, 200]


def test_the_rate_limit_resets_after_a_minute():
    now = [0.0]
    limiter = RateLimiter(1, clock=lambda: now[0])
    assert limiter.check("a") is None
    assert limiter.check("a") == pytest.approx(60.0)
    assert limiter.check("b") is None  # Each client has its own allowance.
    now[0] = 60.0
    assert limiter.check("a") is None


def test_missing_data_returns_503_everywhere():
    def broken():
        raise DataUnavailableError("Data file not found")

    with client_for(factory=broken) as client:
        assert client.get("/health").status_code == 503
        assert client.get("/options").status_code == 503
        response = client.post("/recommend", json=SEARCH)
    assert response.status_code == 503
    assert response.json()["detail"].startswith("Restaurant data isn't available")


def test_allowed_origins_get_cors_headers_and_others_dont():
    with client_for() as client:
        allowed = client.get("/health", headers={"Origin": ORIGIN})
        other = client.get("/health", headers={"Origin": "https://evil.example.com"})
        preflight = client.options(
            "/recommend",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-origin" not in other.headers
    assert preflight.status_code == 200


def test_an_origin_pattern_allows_preview_deployments():
    settings = ApiSettings(allowed_origin_regex=r"https://blb-[a-z0-9-]+\.vercel\.app")
    with client_for(settings=settings) as client:
        preview = client.get("/health", headers={"Origin": "https://blb-git-main-me.vercel.app"})
    assert preview.headers["access-control-allow-origin"] == "https://blb-git-main-me.vercel.app"


def test_api_settings_read_the_environment():
    settings = ApiSettings.from_env(
        {
            "ALLOWED_ORIGINS": " https://a.example.com/, https://b.example.com ",
            "RATE_LIMIT_PER_MINUTE": "5",
        }
    )
    assert settings.allowed_origins == ("https://a.example.com", "https://b.example.com")
    assert settings.rate_limit_per_minute == 5
    assert ApiSettings.from_env({}).allowed_origins == ()
    with pytest.raises(ConfigError):
        ApiSettings.from_env({"RATE_LIMIT_PER_MINUTE": "lots"})
