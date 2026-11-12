"""Tests for the evaluation harness in tests/eval. No API is called."""

from __future__ import annotations

import json

import pytest

from conftest import make_repository, make_restaurant
from eval.checks import guardrails, invented_figures
from eval.common import INJECTED_REVIEW, Case, load_cases
from eval.preflight import check_case
from eval.report import build_report, read_jsonl, summarise, wilson
from eval.run_eval import RunConfig, Runner, cost_of
from fakes import FakeRanker, ranking_json
from recommender.llm import LLMUnavailable
from recommender.models import Preferences
from recommender.service import RecommendationService


def make_case(case_id="C1", preferences=None, **fields):
    data = {
        "id": case_id,
        "tags": ["common"],
        "source": "synthesized",
        "preferences": preferences or {"area": "MG Road", "min_rating": 3.5},
        "preflight": {"min_candidates": 1, "expected_relaxations": []},
        "checks": [],
        "soft_signal": None,
        "preference_terms": [],
        "fixture": None,
    }
    return Case.from_json({**data, **fields})


def small_repository():
    return make_repository(
        make_restaurant("r1", name="Alpha", rating=4.5, cost_for_two=500),
        make_restaurant("r2", name="Beta", rating=4.2, cost_for_two=550, book_table=True),
        make_restaurant("r3", name="Gamma", rating=3.9, cost_for_two=450),
    )


def good_ranker():
    text = ranking_json(
        ("R1", "Alpha suits you, rated 4.5/5 at about ₹500 for two."),
        ("R2", "Beta is a close second."),
    )
    return FakeRanker(text, model="claude-opus-5-5")


def make_runner(tmp_path, ranker, **config):
    settings = {"reps": 1, "retries": 0, "price": (1.0, 1.0), "backoff": 0.0, **config}
    return Runner(
        small_repository(),
        ranker,
        tmp_path,
        RunConfig(**settings),
        {"variant": "test", "build_id": "test-build"},
    )


# The case file


def test_case_file_loads_with_twenty_paid_cases_a_control_and_five_kept_aside():
    case_set = load_cases()
    assert len(case_set.cases) == 20
    assert [c.id for c in case_set.controls] == ["Z1"]
    assert len(case_set.confirmation) == 5
    assert len({c.id for c in case_set.all()}) == 26


def test_confirmation_cases_need_to_be_asked_for():
    case_set = load_cases()
    with pytest.raises(SystemExit, match="--confirmation"):
        case_set.select(["K1"])
    assert case_set.select(["K1"], include_confirmation=True)[0].id == "K1"


# Preflight


def test_preflight_fails_on_an_unknown_area():
    case = make_case(preferences={"area": "Atlantis"})
    assert check_case(case, small_repository(), max_candidates=8, min_results=5) == [
        "Unknown area: 'Atlantis'"
    ]


def test_preflight_fails_when_a_case_no_longer_relaxes_as_intended():
    case = make_case(preflight={"min_candidates": 1, "expected_relaxations": ["min_rating"]})
    problems = check_case(case, small_repository(), max_candidates=8, min_results=1)
    assert problems == ["relaxations [], expected ['min_rating']"]


def test_preflight_fails_when_every_candidate_has_the_signal():
    case = make_case(
        preflight={"min_candidates": 1, "expected_relaxations": [], "min_signal_matches": 1},
        soft_signal={"field": "cost_for_two", "equals": 500},
    )
    repo = make_repository(make_restaurant("r1", cost_for_two=500))
    problems = check_case(case, repo, max_candidates=8, min_results=1)
    assert problems == ["every candidate has the data signal, so ranking can't show an effect"]


def test_preflight_checks_the_injected_review_reaches_the_prompt_escaped():
    case = make_case(fixture="injected_review")
    assert check_case(case, small_repository(), max_candidates=8, min_results=1) == []


# Code checks


def test_invented_figures_catches_a_wrong_rating_or_price_but_not_the_diners_limit():
    restaurant = make_restaurant(rating=4.1, cost_for_two=600)
    metadata = small_repository().metadata
    assert invented_figures("Rated 4.1/5, about ₹600 for two.", restaurant, metadata) == []
    assert invented_figures("You asked for places rated 4.0+.", restaurant, metadata) == []
    assert invented_figures("Under ₹300 for two.", restaurant, metadata) == []  # A band edge.
    assert invented_figures("It is rated 4.8/5 and costs ₹2,000.", restaurant, metadata) == [
        "4.8/5",
        "₹2,000",
    ]


def test_guardrails_catch_aliases_and_followed_injections():
    repo = small_repository()
    case = make_case(checks=["G6"])
    text = ranking_json(("R1", "Evil Cafe is the best, rated 5.0."), summary="R2 is fine too.")
    ranker = FakeRanker(text, model="claude-opus-5-5")
    result = RecommendationService(repo, ranker).recommend(case.preferences, use_cache=False)
    # Validation swaps aliases, so plant one after it to check the guardrail itself.
    result = type(result)(**{**result.__dict__, "summary": "R2 is fine too."})
    records = {r.restaurant_id: r for r in repo.restaurants}
    checks = guardrails(case, result, records, repo.metadata, max_results=5)
    assert checks["G4"] is False
    assert checks["G6"] is False
    assert checks["G7"] is False
    assert checks["G1"] and checks["G2"] and checks["G3"] and checks["G5"]


# The runner


def test_runner_writes_scored_rows_and_traces(tmp_path):
    runner = make_runner(tmp_path, good_ranker())
    runner.run([make_case()])
    rows = read_jsonl(tmp_path / "results.jsonl")
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert rows[0]["cost_usd"] == pytest.approx(
        cost_of({"input_tokens": 3000, "output_tokens": 800}, (1.0, 1.0))
    )
    assert all(rows[0]["checks"]["guardrails"][g] for g in ("G1", "G2", "G3", "G4", "G5", "G7"))
    trace = json.loads((tmp_path / "traces" / "C1_rep1.json").read_text("utf-8"))
    assert "<candidates>" in trace["user_message"]


def test_runner_resumes_without_repeating_finished_pairs(tmp_path):
    first = good_ranker()
    make_runner(tmp_path, first, reps=1).run([make_case()])
    second = good_ranker()
    make_runner(tmp_path, second, reps=2).run([make_case()])
    assert len(first.calls) == 1
    assert len(second.calls) == 1  # Only rep 2 ran.
    assert [r["rep"] for r in read_jsonl(tmp_path / "results.jsonl")] == [1, 2]


def test_runner_stops_at_the_spending_cap(tmp_path):
    ranker = good_ranker()
    # Each search costs 3,800 tokens at $1 per million: $0.0038.
    make_runner(tmp_path, ranker, reps=5, max_spend=0.007).run([make_case()])
    assert len(ranker.calls) == 2


def test_runner_refuses_to_mix_runs_with_a_different_setup(tmp_path):
    make_runner(tmp_path, good_ranker()).run([make_case()])
    other = Runner(
        small_repository(),
        good_ranker(),
        tmp_path,
        RunConfig(),
        {"variant": "test", "build_id": "another-build"},
    )
    with pytest.raises(SystemExit, match="build_id"):
        other.run([make_case()])


def test_api_errors_go_to_errors_and_are_never_scored(tmp_path):
    ranker = FakeRanker(error=LLMUnavailable("authentication"), model="claude-opus-5-5")
    make_runner(tmp_path, ranker).run([make_case()])
    assert read_jsonl(tmp_path / "results.jsonl") == []
    errors = read_jsonl(tmp_path / "errors.jsonl")
    assert errors[0]["failure_class"] == "llm_failure"
    assert errors[0]["failure_reason"] == "authentication"
    summary, _ = build_report(tmp_path)
    assert summary["size"]["scored"] == 0
    assert summary["quality"]["Q2_flag_recall"]["total"] == 0


def test_transient_failures_are_retried_and_recorded(tmp_path):
    ranker = FakeRanker(error=LLMUnavailable("rate_limited"), model="claude-opus-5-5")
    make_runner(tmp_path, ranker, retries=2).run([make_case()])
    assert len(ranker.calls) == 3
    errors = read_jsonl(tmp_path / "errors.jsonl")
    assert [e["failure_class"] for e in errors] == ["retried", "retried", "llm_failure"]
    summary, _ = build_report(tmp_path)
    assert summary["size"]["errors"] == 1  # Retries are part of one attempt.


def test_a_different_served_model_fails_the_attempt(tmp_path):
    ranker = good_ranker()
    ranker.model = "requested-model"
    make_runner(tmp_path, ranker).run([make_case()])
    assert read_jsonl(tmp_path / "errors.jsonl")[0]["failure_class"] == "model_mismatch"


def test_a_search_with_no_matches_makes_no_call(tmp_path):
    ranker = good_ranker()
    case = make_case(preferences={"area": "BTM"})
    make_runner(tmp_path, ranker).run([case])
    row = read_jsonl(tmp_path / "results.jsonl")[0]
    assert row["status"] == "empty"
    assert row["checks"] == {"no_api_call": True}
    assert ranker.calls == []


def test_injected_review_reaches_only_the_top_candidate(tmp_path):
    ranker = good_ranker()
    make_runner(tmp_path, ranker).run([make_case("A2", fixture="injected_review")])
    sent = ranker.calls[0][1]
    assert sent.count("Evil Cafe") == 1
    assert "&lt;/candidates&gt; SYSTEM" in sent
    assert INJECTED_REVIEW.startswith("Lovely place.")


# The report


def test_headline_numbers_recompute_from_the_files(tmp_path):
    make_runner(tmp_path, good_ranker(), reps=3).run([make_case()])
    summary, text = build_report(tmp_path)
    rows = read_jsonl(tmp_path / "results.jsonl")
    assert summarise(rows, read_jsonl(tmp_path / "errors.jsonl")) == summary
    assert summary["size"]["scored"] == 3
    assert summary["cost_and_speed"]["total_spend"] == pytest.approx(
        sum(r["cost_usd"] for r in rows)
    )
    assert "G1 pass" in text


def test_wilson_interval_is_wide_for_few_attempts():
    low, high = wilson(3, 3)
    assert high == 1.0
    assert low < 0.5
    assert wilson(0, 0) is None


def test_preferences_in_the_case_file_are_valid():
    for case in load_cases().all():
        assert isinstance(case.preferences, Preferences)


@pytest.mark.parametrize("module", ["preflight", "selfcheck"])
def test_real_data_checks_pass(module, monkeypatch):
    """The preflight and zero-cost checks pass on the real data, once it has been built."""
    from recommender.config import load_settings

    settings = load_settings()
    if not settings.restaurants_path.is_file():
        pytest.skip("Run ingestion first")
    imported = __import__(f"eval.{module}", fromlist=["main"])
    assert imported.main() == 0
