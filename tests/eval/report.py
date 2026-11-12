"""Build the run summary from results.jsonl and errors.jsonl alone, so it can be recomputed.

uv run python tests/eval/report.py .claude/hillclimb/recommendation/baseline
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.checks import GUARDRAILS  # noqa: E402

# Targets from Doc/eval.md section 3.
TARGETS = {"Q2": 0.9, "Q3": 0.9}
JUDGE_METRICS = (
    "Q1_grounded",
    "Q5_relax_honest",
    "Q6_conflict_honest",
    "Q7_personalised",
    "Q8_unrated_honest",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """A 95% interval for a pass rate, which stays sensible for small counts."""
    if total == 0:
        return None
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, centre - half), min(1.0, centre + half)


def _rate(successes: int, total: int, target: float | None = None) -> dict[str, Any]:
    interval = wilson(successes, total)
    return {
        "successes": successes,
        "total": total,
        "score": None if total == 0 else successes / total,
        "interval": interval,
        "target": target,
    }


def _spread(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {"min": min(values), "median": statistics.median(values), "max": max(values)}


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)
    return ordered[max(index, 0)]


def summarise(rows: list[dict[str, Any]], errors: list[dict[str, Any]]) -> dict[str, Any]:
    """Headline numbers for a run. Only `ok` rows are scored; errors are never zeros."""
    # Every row and error row counts toward spend, including retried attempts.
    priced = [r for r in rows + errors if r.get("cost_usd") is not None]
    # A pair that failed and later finished on a resumed run counts once, as finished. Retries
    # are part of an attempt, not attempts of their own.
    finished = {(r["case"], r["rep"]) for r in rows}
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    for error in errors:
        key = (error["case"], error["rep"])
        if error["failure_class"] != "retried" and key not in finished:
            latest[key] = error
    errors = list(latest.values())
    scored = [r for r in rows if r["status"] == "ok"]
    # The free control makes no API call, so it is left out of the AI-ranked rate.
    paid_rows = [r for r in rows if r["status"] != "empty"]
    attempts = len(paid_rows) + len(errors)

    guardrails = {}
    for name in GUARDRAILS:
        applicable = [r for r in scored if r["checks"]["guardrails"][name] is not None]
        failures = [
            f"{r['case']} rep {r['rep']}" for r in applicable if not r["checks"]["guardrails"][name]
        ]
        guardrails[name] = {"checked": len(applicable), "failures": failures}

    def total(metric: str, hit: str) -> dict[str, Any]:
        values = [r["checks"][metric] for r in scored if r["checks"].get(metric)]
        return _rate(
            sum(v[hit] for v in values), sum(v["total"] for v in values), TARGETS.get(metric)
        )

    lifts = [r["checks"]["Q4"] for r in scored if r["checks"].get("Q4")]
    q4 = {
        "attempts": len(lifts),
        "ai_top3_mean": statistics.mean(v["ai_top3"] for v in lifts) if lifts else None,
        "baseline_top3_mean": statistics.mean(v["baseline_top3"] for v in lifts) if lifts else None,
        "beats_baseline": sum(v["ai_top3"] > v["baseline_top3"] for v in lifts),
        "at_least_2_of_3": sum(v["ai_top3"] >= 2 for v in lifts),
    }

    searches = [r for r in rows if r.get("usage")]
    latencies = [r["latency_seconds"] for r in scored if r.get("latency_seconds") is not None]
    raw_ids = [r["checks"]["D1_raw_invalid_ids"] for r in scored]
    leaks = [r["checks"]["D2_raw_alias_leaks"] for r in scored]
    return {
        "size": {
            "attempts": attempts,
            "scored": len(scored),
            "errors": len(errors),
            "truncated": sum(r["status"] == "truncated" for r in rows),
            "refusals": sum(r["status"] == "refusal" for r in rows),
            "passed_on_retry": sum(bool(r.get("passed_on_retry")) for r in scored),
        },
        "error_classes": dict(Counter(e["failure_class"] for e in errors)),
        "guardrails": guardrails,
        "quality": {
            "Q2_flag_recall": total("Q2", "flagged"),
            "Q3_flag_specificity": total("Q3", "ok"),
            "Q4_soft_lift": q4,
            **{name: "pending judge" for name in JUDGE_METRICS},
        },
        "diagnostics": {
            "D1_raw_invalid_ids": sum(v for v in raw_ids if v is not None),
            "D2_raw_alias_leaks": sum(v for v in leaks if v is not None),
            "D3_rank_changed": _rate(
                sum(r["checks"]["D3_rank_changed"] for r in scored), len(scored)
            ),
            "D4_ai_ranked_rate": _rate(len(scored), attempts),
            "D5_refusals": dict(Counter(r["case"] for r in rows if r["status"] == "refusal")),
            "D5_fallback_model_used": sum(bool(r.get("fallback_model_used")) for r in rows),
            "D6_truncated_rate": _rate(sum(r["status"] == "truncated" for r in rows), attempts),
        },
        "cost_and_speed": {
            "latency_p50": _percentile(latencies, 0.5),
            "latency_p95": _percentile(latencies, 0.95),
            "input_tokens": _spread([r["usage"].get("input_tokens", 0) for r in searches]),
            "output_tokens": _spread([r["usage"].get("output_tokens", 0) for r in searches]),
            "cost_per_search": (
                statistics.mean(r["cost_usd"] for r in searches if r.get("cost_usd") is not None)
                if any(r.get("cost_usd") is not None for r in searches)
                else None
            ),
            "total_spend": sum(r["cost_usd"] for r in priced),
            "judge_spend": None,
        },
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _rate_line(name: str, rate: dict[str, Any]) -> str:
    interval = rate["interval"]
    span = "n/a" if interval is None else f"{_pct(interval[0])} to {_pct(interval[1])}"
    target = "" if rate.get("target") is None else f"   target {_pct(rate['target'])}"
    return (
        f"{name:<22} {_pct(rate['score']):>5}  ({rate['successes']}/{rate['total']}, "
        f"interval {span}){target}"
    )


def render(summary: dict[str, Any], run: dict[str, Any]) -> str:
    size, cost, diag = summary["size"], summary["cost_and_speed"], summary["diagnostics"]
    quality = summary["quality"]
    lines = [
        f"Run:     {run.get('variant')}, {run.get('created')}",
        f"Config:  {run.get('provider')} {run.get('model')}, effort {run.get('effort')}, "
        f"prompt {run.get('prompt_version')}, build {run.get('build_id')}, "
        f"cases {run.get('cases_hash')}",
        f"Size:    {size['attempts']} attempts | scored {size['scored']} | errors {size['errors']}"
        f" | truncated {size['truncated']} | refusals {size['refusals']}"
        f" | passed only on retry {size['passed_on_retry']}",
    ]
    if summary["error_classes"]:
        lines.append(f"Errors:  {summary['error_classes']}")
    marks = []
    for name, g in summary["guardrails"].items():
        mark = "n/a" if g["checked"] == 0 else ("pass" if not g["failures"] else "FAIL")
        marks.append(f"{name} {mark}")
    lines += ["", "Guardrails:  " + "  ".join(marks)]
    for name, g in summary["guardrails"].items():
        if g["failures"]:
            lines.append(f"  {name} failed on: {', '.join(g['failures'])}")
    q4 = quality["Q4_soft_lift"]
    lines += [
        "",
        "Quality",
        _rate_line("Q2_flag_recall", quality["Q2_flag_recall"]),
        _rate_line("Q3_flag_specificity", quality["Q3_flag_specificity"]),
    ]
    if q4["attempts"]:
        lines.append(
            f"{'Q4_soft_lift':<22} AI top 3 holds {q4['ai_top3_mean']:.2f} with the signal, "
            f"score order {q4['baseline_top3_mean']:.2f}; beats it in {q4['beats_baseline']}"
            f"/{q4['attempts']}, at least 2 of 3 in {q4['at_least_2_of_3']}/{q4['attempts']}"
        )
    else:
        lines.append(f"{'Q4_soft_lift':<22} n/a")
    lines += [f"{name:<22} pending judge" for name in JUDGE_METRICS]

    def money(value: float | None) -> str:
        return "n/a" if value is None else f"${value:.4f}"

    def secs(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.1f}s"

    def spread(value: dict[str, float] | None) -> str:
        return (
            "n/a"
            if value is None
            else f"{value['min']:.0f}/{value['median']:.0f}/{value['max']:.0f}"
        )

    lines += [
        "",
        f"Cost and speed:  latency p50 {secs(cost['latency_p50'])}, p95 {secs(cost['latency_p95'])}"
        f" | tokens in {spread(cost['input_tokens'])}, out {spread(cost['output_tokens'])}"
        f" (min/median/max) | per search {money(cost['cost_per_search'])}"
        f" | total {money(cost['total_spend'])} | judge pending",
        f"Diagnostics:     raw invalid ids {diag['D1_raw_invalid_ids']}"
        f" | alias leaks {diag['D2_raw_alias_leaks']}"
        f" | rank changed {_pct(diag['D3_rank_changed']['score'])}"
        f" | AI-ranked {_pct(diag['D4_ai_ranked_rate']['score'])}"
        f" | refusals {diag['D5_refusals'] or 0}"
        f" | fallback model {diag['D5_fallback_model_used']}"
        f" | truncated {_pct(diag['D6_truncated_rate']['score'])}",
        "Human review:    pending",
        "Decision:        pending",
    ]
    return "\n".join(lines)


def build_report(out_dir: Path) -> tuple[dict[str, Any], str]:
    rows = read_jsonl(out_dir / "results.jsonl")
    errors = read_jsonl(out_dir / "errors.jsonl")
    run_path = out_dir / "run.json"
    run = json.loads(run_path.read_text("utf-8")) if run_path.is_file() else {}
    summary = summarise(rows, errors)
    return summary, render(summary, run)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out_dir = Path(sys.argv[1])
    summary, text = build_report(out_dir)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
