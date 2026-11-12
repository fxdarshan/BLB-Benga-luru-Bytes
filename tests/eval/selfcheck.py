"""The zero-cost checks of Doc/eval.md section 6, run on the real data with scripted rankers.

No API is called. Each check runs the real runner and grading on all 21 cases and compares
the summary with what that check expects:

    uv run python tests/eval/selfcheck.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.common import Case, has_signal, load_cases  # noqa: E402
from eval.report import build_report, read_jsonl, summarise  # noqa: E402
from eval.run_eval import RunConfig, Runner  # noqa: E402
from recommender.config import load_settings  # noqa: E402
from recommender.llm import CallDetails, LLMReply, LLMUnavailable  # noqa: E402
from recommender.models import RankingResponse  # noqa: E402
from recommender.repository import RestaurantRepository  # noqa: E402

MODEL = "scripted-model"
CANDIDATES = re.compile(r"<candidates>\n(.*)\n</candidates>", re.DOTALL)
NOTES = re.compile(r"<diner_notes>(.*?)</diner_notes>", re.DOTALL)
SIGNAL_FIELDS = ("rest_types", "listing_types", "book_table", "online_order")

Responder = Callable[[Case, list[dict[str, Any]]], dict[str, Any]]


class ScriptedRanker:
    """Answers with a response built from the prompt's own candidates, or raises."""

    model = MODEL
    effort = "low"

    def __init__(self, responder: Responder | None, cases: dict[str, Case], error=None):
        self.responder = responder
        self.cases = cases
        self.error = error

    def _case_for(self, message: str) -> Case:
        notes = NOTES.search(message).group(1)
        area = json.loads(message.split("<preferences>\n", 1)[1].split("\n", 1)[0])["area"]
        for case in self.cases.values():
            wanted = case.preferences.additional or "(none)"
            if case.preferences.area == area and wanted.replace("<", "&lt;") == notes:
                return case
        raise LookupError(f"no case for area {area!r} and notes {notes!r}")

    def rank(self, system: str, user_message: str) -> LLMReply:
        if self.error is not None:
            raise self.error
        candidates = json.loads(CANDIDATES.search(user_message).group(1))
        payload = self.responder(self._case_for(user_message), candidates)
        text = json.dumps(payload)
        details = CallDetails(
            raw_text=text,
            usage={"input_tokens": 3000, "output_tokens": 800},
            stop_reason="stop",
            served_model=MODEL,
            latency_seconds=0.01,
            retry_count=0,
        )
        return LLMReply(RankingResponse.model_validate_json(text), details)


def _signal(case: Case, data: dict[str, Any]) -> bool:
    fields = {
        name: data.get(name, [] if name.endswith("types") else False) for name in SIGNAL_FIELDS
    }
    return has_signal(SimpleNamespace(**fields), case.soft_signal)


def oracle(case: Case, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """An ideal response: true facts only, honest flags, signal-holders first."""
    ordered = sorted(candidates, key=lambda c: not _signal(case, c))[:5]
    picks = []
    for data in ordered:
        rating = (
            f"It is rated {data['rating']}/5 by {data['votes']} diners."
            if data["rating"] is not None
            else "It is unrated so far."
        )
        cost = (
            f" A meal for two costs about ₹{data['cost_for_two']}." if data["cost_for_two"] else ""
        )
        flags = [g["terms"][0] for g in case.preference_terms if not g["data_can_confirm"]]
        flags += [
            g["terms"][0]
            for g in case.preference_terms
            if g["data_can_confirm"] and not _signal(case, data)
        ]
        picks.append(
            {
                "candidate_id": data["id"],
                "explanation": f"{data['name']} serves {', '.join(data.get('cuisines', []))}. "
                f"{rating}{cost}",
                "unverified_preferences": flags,
                "best_review": 0,
            }
        )
    return {"summary": f"{ordered[0]['name']} leads these picks.", "recommendations": picks}


def same_sentence(case: Case, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """A null response: one sentence for every restaurant, and nothing flagged."""
    return {
        "summary": "These are all good.",
        "recommendations": [
            {
                "candidate_id": c["id"],
                "explanation": "A good place to eat.",
                "unverified_preferences": [],
                "best_review": 0,
            }
            for c in candidates[:5]
        ],
    }


def empty_text(case: Case, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    payload = same_sentence(case, candidates)
    for pick in payload["recommendations"]:
        pick["explanation"] = ""
    return payload


def wrong_facts(case: Case, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Good text with an invented rating and price on the first pick."""
    payload = oracle(case, candidates)
    first = payload["recommendations"][0]
    first["explanation"] += " It is rated 4.9/5 and costs ₹9,999 for two."
    return payload


def run_check(
    name: str, ranker: Any, repository: RestaurantRepository, cases: list[Case], settings
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as folder:
        out_dir = Path(folder)
        config = RunConfig(
            reps=1,
            retries=0,
            price=(0.0, 0.0),
            max_candidates=settings.max_candidates,
            max_results=settings.max_results,
        )
        runner = Runner(repository, ranker, out_dir, config, {"variant": name})
        runner.run(cases)
        summary, _ = build_report(out_dir)
        rows = read_jsonl(out_dir / "results.jsonl")
        errors = read_jsonl(out_dir / "errors.jsonl")
        # Recalculation: recomputing from the files gives the same numbers.
        assert summarise(rows, errors) == summary
        return {"summary": summary, "rows": rows, "errors": errors}


def guardrail_failures(summary: dict[str, Any]) -> dict[str, list[str]]:
    return {k: v["failures"] for k, v in summary["guardrails"].items() if v["failures"]}


def main() -> int:
    settings = load_settings()
    repository = RestaurantRepository.load(settings.restaurants_path, settings.metadata_path)
    case_set = load_cases()
    cases = list(case_set.cases + case_set.controls)
    by_id = {c.id: c for c in cases}
    outcomes: list[tuple[str, bool | None, str]] = []

    def check(name: str, ok: bool | None, detail: str) -> None:
        outcomes.append((name, ok, detail))

    run = run_check("oracle", ScriptedRanker(oracle, by_id), repository, cases, settings)
    s = run["summary"]
    q = s["quality"]
    q4 = q["Q4_soft_lift"]
    z1 = [r for r in run["rows"] if r["case"] == "Z1"]
    check("Oracle: guardrails pass", not guardrail_failures(s), str(guardrail_failures(s)))
    check(
        "Oracle: Q2 and Q3 at 100%",
        q["Q2_flag_recall"]["score"] == 1 and q["Q3_flag_specificity"]["score"] == 1,
        f"Q2 {q['Q2_flag_recall']['score']}, Q3 {q['Q3_flag_specificity']['score']}",
    )
    check(
        "Oracle: Q4 at least 2 of 3 everywhere",
        q4["at_least_2_of_3"] == q4["attempts"],
        f"{q4['at_least_2_of_3']}/{q4['attempts']}",
    )
    check("Oracle: every case scored", s["size"]["scored"] == 20, str(s["size"]))
    check(
        "Control Z1: empty, no API call",
        len(z1) == 1 and z1[0]["status"] == "empty" and z1[0]["checks"]["no_api_call"],
        str(z1[0]["checks"] if z1 else "missing"),
    )

    run = run_check("same", ScriptedRanker(same_sentence, by_id), repository, cases, settings)
    s = run["summary"]
    q2 = s["quality"]["Q2_flag_recall"]["score"]
    check("Null, same sentence: Q2 at 0%", q2 == 0, f"Q2 {q2}; Q7 needs the judge")

    run = run_check("empty", ScriptedRanker(empty_text, by_id), repository, cases, settings)
    s = run["summary"]
    check(
        "Null, empty text: no results scored, all in errors",
        s["size"]["scored"] == 0 and s["error_classes"] == {"llm_failure": 20},
        f"{s['size']}, {s['error_classes']}",
    )

    run = run_check("wrong", ScriptedRanker(wrong_facts, by_id), repository, cases, settings)
    g7 = run["summary"]["guardrails"]["G7"]
    check(
        "Wrong facts: G7 fails on every case",
        len(g7["failures"]) == 20,
        f"{len(g7['failures'])} of 20; the invented dish needs the judge",
    )

    error = LLMUnavailable("authentication")
    run = run_check(
        "api-error", ScriptedRanker(None, by_id, error=error), repository, cases, settings
    )
    s = run["summary"]
    check(
        "Induced API error: in errors, no zero scores",
        s["size"]["scored"] == 0
        and s["error_classes"] == {"llm_failure": 20}
        and all(e["failure_reason"] == "authentication" for e in run["errors"]),
        f"{s['size']}, {s['error_classes']}",
    )

    run = run_check("llm-off", None, repository, cases, settings)
    s = run["summary"]
    d4 = s["diagnostics"]["D4_ai_ranked_rate"]["score"]
    check(
        "LLM off: D4 is 0, nothing scored",
        d4 == 0 and s["size"]["scored"] == 0 and s["error_classes"] == {"not_ai_ranked": 20},
        f"D4 {d4}, {s['size']}",
    )

    check("Recalculation: summaries match the files", True, "checked on every run above")
    check("Prompt rule removed: Q5 responds", None, "needs the judge, which isn't built yet")

    failed = sum(ok is False for _, ok, _ in outcomes)
    skipped = sum(ok is None for _, ok, _ in outcomes)
    for name, ok, detail in outcomes:
        mark = "skip" if ok is None else ("ok  " if ok else "FAIL")
        print(f"{mark} {name}  [{detail}]")
    print(f"{len(outcomes) - failed - skipped} ok, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
