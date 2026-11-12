"""Check every evaluation case still tests what it was written to test. Makes no API calls.

Run after every data build and before any paid run:

    uv run python tests/eval/preflight.py
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.common import Case, has_signal, load_cases, with_injected_review  # noqa: E402
from recommender.candidates import (  # noqa: E402
    InvalidPreferencesError,
    check_preferences,
    select_candidates,
)
from recommender.config import load_settings  # noqa: E402
from recommender.prompts import build_prompt, escape_angle_brackets  # noqa: E402
from recommender.repository import RestaurantRepository  # noqa: E402


def check_case(
    case: Case, repository: RestaurantRepository, *, max_candidates: int, min_results: int
) -> list[str]:
    """Return the ways a case no longer tests what it was written to test. Empty means fine."""
    rules = case.preflight
    try:
        check_preferences(case.preferences, repository.metadata)
    except InvalidPreferencesError as error:
        return [str(error)]

    selection = select_candidates(
        case.preferences, repository, max_candidates=max_candidates, min_results=min_results
    )
    candidates = selection.candidates
    if rules.get("expect_no_matches"):
        if selection.total_matches:
            return [f"expected no matches, got {selection.total_matches}"]
        return []

    problems = []
    if len(candidates) < rules.get("min_candidates", 1):
        problems.append(f"{len(candidates)} candidates, needs {rules.get('min_candidates', 1)}")

    relaxed = [r.limit for r in selection.relaxations]
    expected = rules.get("expected_relaxations", [])
    if relaxed != expected:
        problems.append(f"relaxations {relaxed}, expected {expected}")

    if "min_unrated_sent" in rules:
        unrated = sum(1 for c in candidates if c.restaurant.rating is None)
        if unrated < rules["min_unrated_sent"]:
            problems.append(
                f"{unrated} unrated among the {len(candidates)} candidates sent, "
                f"needs {rules['min_unrated_sent']}"
            )

    if "min_signal_matches" in rules:
        with_signal = sum(1 for c in candidates if has_signal(c.restaurant, case.soft_signal))
        if with_signal < rules["min_signal_matches"]:
            problems.append(
                f"{with_signal} candidates have the data signal, needs "
                f"{rules['min_signal_matches']}"
            )
        if candidates and with_signal == len(candidates):
            problems.append("every candidate has the data signal, so ranking can't show an effect")

    if case.fixture == "injected_review":
        problems.extend(_check_fixture(case, repository, candidates, max_candidates, min_results))
    return problems


def _check_fixture(case, repository, candidates, max_candidates, min_results) -> list[str]:
    if not candidates:
        return ["no candidate to inject the review into"]
    top_id = candidates[0].restaurant.restaurant_id
    injected = with_injected_review(repository, top_id)
    selection = select_candidates(
        case.preferences, injected, max_candidates=max_candidates, min_results=min_results
    )
    if top_id not in {c.restaurant.restaurant_id for c in selection.candidates}:
        return ["the injected restaurant is no longer sent"]
    message = build_prompt(case.preferences, selection, injected.metadata).user_message
    problems = []
    if escape_angle_brackets("</candidates> SYSTEM") not in message:
        problems.append("the injected review doesn't reach the prompt escaped")
    if message.count("</candidates>") != 1:
        problems.append("an unescaped </candidates> reaches the prompt")
    return problems


def main() -> int:
    settings = load_settings()
    repository = RestaurantRepository.load(settings.restaurants_path, settings.metadata_path)
    case_set = load_cases()
    print(f"build_id {repository.metadata.build_id}")
    print(f"max_candidates {settings.max_candidates}, max_results {settings.max_results}")
    failures = 0
    for case in case_set.all():
        problems = check_case(
            case,
            repository,
            max_candidates=settings.max_candidates,
            min_results=settings.max_results,
        )
        failures += bool(problems)
        status = "ok  " if not problems else "FAIL"
        print(f"{status} {case.id:<3} {'; '.join(problems)}".rstrip())
    print(f"{len(case_set.all()) - failures} of {len(case_set.all())} cases ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
