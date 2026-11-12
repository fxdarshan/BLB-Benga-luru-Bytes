"""Run the evaluation cases through the real app: `service.recommend(use_cache=False)`.

Paid runs need a spending cap. Examples:

    uv run python tests/eval/run_eval.py --cases C1,S2,R1 --reps 1 --max-spend 0.05
    uv run python tests/eval/run_eval.py --reps 3 --max-spend 0.50 --pace 30

Rows are written as each attempt finishes, and finished (case, rep) pairs are skipped on restart.
See Doc/eval.md section 5 for the requirements this meets.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import random
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.checks import grade  # noqa: E402
from eval.common import (  # noqa: E402
    CASES_PATH,
    LOCK_PATH,
    PROJECT_ROOT,
    Case,
    file_hash,
    load_cases,
    with_injected_review,
)
from eval.report import build_report, read_jsonl  # noqa: E402
from recommender.candidates import select_candidates  # noqa: E402
from recommender.config import load_settings  # noqa: E402
from recommender.models import RecommendationResult  # noqa: E402
from recommender.prompts import PROMPT_VERSION, build_prompt  # noqa: E402
from recommender.rankers import make_ranker  # noqa: E402
from recommender.repository import RestaurantRepository  # noqa: E402
from recommender.service import Ranker, RecommendationService  # noqa: E402

OUTPUT_ROOT = PROJECT_ROOT / ".claude" / "hillclimb" / "recommendation"
ATTEMPT_TIMEOUT_SECONDS = 120.0
# Dollars per million tokens, as (input, output). Others are passed with --price.
PRICES = {"openai/gpt-oss-120b": (0.15, 0.60)}
# Failures worth retrying after a pause. Others won't change on a retry.
TRANSIENT = {"rate_limited", "timeout", "connection", "server_error"}
# Fallbacks that are still model output, so they go to results.jsonl, not errors.jsonl.
OUTPUT_STATUSES = {"max_tokens": "truncated", "refusal": "refusal"}


@dataclasses.dataclass
class RunConfig:
    reps: int = 1
    concurrency: int = 1
    timeout: float = ATTEMPT_TIMEOUT_SECONDS
    max_spend: float | None = None
    price: tuple[float, float] | None = None
    retries: int = 2
    pace: float = 0.0
    backoff: float = 20.0
    max_candidates: int = 8
    max_results: int = 5


def cost_of(usage: dict[str, int] | None, price: tuple[float, float] | None) -> float | None:
    if not usage or price is None:
        return None
    return (
        usage.get("input_tokens", 0) * price[0] + usage.get("output_tokens", 0) * price[1]
    ) / 1_000_000


def _with_timeout(fn: Callable[[], RecommendationResult], seconds: float) -> RecommendationResult:
    """Run one search, giving up after `seconds`. The thread is left to finish on its own."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["result"] = fn()
        except BaseException as error:  # noqa: BLE001 - reported to the caller
            box["error"] = error

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise TimeoutError(f"no result after {seconds:.0f} seconds")
    if "error" in box:
        raise box["error"]
    return box["result"]


class Runner:
    """Runs (case, rep) attempts, writing results, errors and traces as each one finishes."""

    def __init__(
        self,
        repository: RestaurantRepository,
        ranker: Ranker | None,
        out_dir: Path,
        config: RunConfig,
        run_info: dict[str, Any],
    ) -> None:
        self.repository = repository
        self.ranker = ranker
        self.out_dir = out_dir
        self.config = config
        self.run_info = run_info
        self._lock = threading.Lock()
        self._pace_lock = threading.Lock()
        self._last_call = 0.0
        self._repositories: dict[str, RestaurantRepository] = {}
        self.spent = 0.0
        self.stopped_for_spend = False

    # Files

    def _append(self, name: str, row: dict[str, Any]) -> None:
        with self._lock, (self.out_dir / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_trace(self, case: Case, rep: int, trace: dict[str, Any]) -> None:
        traces = self.out_dir / "traces"
        traces.mkdir(exist_ok=True)
        path = traces / f"{case.id}_rep{rep}.json"
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), "utf-8")

    def prepare(self) -> None:
        """Create the folder, and refuse to mix results from a different configuration."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        run_path = self.out_dir / "run.json"
        if run_path.is_file():
            stored = json.loads(run_path.read_text("utf-8"))
            changed = [
                key
                for key, value in self.run_info.items()
                if key != "created" and stored.get(key) != value
            ]
            if changed:
                raise SystemExit(
                    f"{self.out_dir} holds a run with different {changed}. "
                    "Use a new --variant, since scores are only comparable on the same setup."
                )
        else:
            run_path.write_text(json.dumps(self.run_info, indent=2), "utf-8")
        priced = read_jsonl(self.out_dir / "results.jsonl") + read_jsonl(
            self.out_dir / "errors.jsonl"
        )
        self.spent = sum(r.get("cost_usd") or 0.0 for r in priced)

    def finished(self) -> set[tuple[str, int]]:
        rows = read_jsonl(self.out_dir / "results.jsonl")
        return {(r["case"], r["rep"]) for r in rows}

    # One attempt

    def _repository_for(self, case: Case) -> RestaurantRepository:
        if case.fixture != "injected_review":
            return self.repository
        if case.id not in self._repositories:
            selection = self._select(case, self.repository)
            top = selection.candidates[0].restaurant.restaurant_id
            self._repositories[case.id] = with_injected_review(self.repository, top)
        return self._repositories[case.id]

    def _select(self, case: Case, repository: RestaurantRepository):
        return select_candidates(
            case.preferences,
            repository,
            max_candidates=self.config.max_candidates,
            min_results=self.config.max_results,
        )

    def _wait_for_pace(self) -> None:
        if self.config.pace <= 0:
            return
        with self._pace_lock:
            wait = self._last_call + self.config.pace - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _over_budget(self) -> bool:
        cap = self.config.max_spend
        return cap is not None and self.spent >= cap

    def attempt(self, case: Case, rep: int) -> None:
        if self._over_budget():
            self.stopped_for_spend = True
            return
        repository = self._repository_for(case)
        service = RecommendationService(
            repository,
            self.ranker,
            max_candidates=self.config.max_candidates,
            max_results=self.config.max_results,
        )
        tries = 0
        while True:
            tries += 1
            self._wait_for_pace()
            started = time.perf_counter()
            try:
                result = _with_timeout(
                    lambda: service.recommend(case.preferences, use_cache=False),
                    self.config.timeout,
                )
            except TimeoutError as error:
                self._record_error(case, rep, "timeout", str(error), tries, None)
                return
            except Exception as error:  # noqa: BLE001 - a crash is a failure, not a score
                self._record_error(case, rep, "crash", type(error).__name__, tries, None)
                return
            seconds = time.perf_counter() - started
            reason = result.failure_reason
            cost = cost_of(
                None if result.diagnostics.cache_hit else result.diagnostics.usage,
                self.config.price,
            )
            with self._lock:
                self.spent += cost or 0.0
            if reason in TRANSIENT and tries <= self.config.retries and not self._over_budget():
                self._note_retry(case, rep, reason, cost)
                time.sleep(self.config.backoff * (2 ** (tries - 1)) * random.uniform(0.5, 1.5))
                continue
            self._record(case, rep, repository, result, seconds, tries, cost)
            return

    def _note_retry(self, case: Case, rep: int, reason: str, cost: float | None) -> None:
        # Kept as an error row so its spend still counts, though the pair is retried.
        self._append(
            "errors.jsonl",
            {
                "case": case.id,
                "rep": rep,
                "failure_class": "retried",
                "failure_reason": reason,
                "cost_usd": cost,
            },
        )

    def _record_error(
        self,
        case: Case,
        rep: int,
        failure_class: str,
        detail: str,
        tries: int,
        result: RecommendationResult | None,
        cost: float | None = None,
    ) -> None:
        d = result.diagnostics if result is not None else None
        self._append(
            "errors.jsonl",
            {
                "case": case.id,
                "rep": rep,
                "failure_class": failure_class,
                "failure_reason": detail,
                "tries": tries,
                "retry_count": d.retry_count if d else None,
                "served_model": d.served_model if d else None,
                "cost_usd": cost,
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )

    def _record(
        self,
        case: Case,
        rep: int,
        repository: RestaurantRepository,
        result: RecommendationResult,
        seconds: float,
        tries: int,
        cost: float | None,
    ) -> None:
        d = result.diagnostics
        selection = self._select(case, repository)
        trace = {
            "case": case.id,
            "rep": rep,
            "prompt_version": PROMPT_VERSION,
            "user_message": (
                build_prompt(case.preferences, selection, repository.metadata).user_message
                if selection.candidates
                else None
            ),
            "raw_llm_text": d.raw_llm_text,
            "diagnostics": dataclasses.asdict(d),
        }
        reason = result.failure_reason
        requested = getattr(self.ranker, "model", None)
        mismatch = (
            result.ai_ranked
            and d.served_model
            and requested
            and d.served_model != requested
            and not d.fallback_model_used
        )
        if not selection.candidates:
            status = "empty"
        elif reason in OUTPUT_STATUSES:
            status = OUTPUT_STATUSES[reason]
        elif mismatch:
            self._record_error(
                case, rep, "model_mismatch", f"served {d.served_model}", tries, result, cost
            )
            self._write_trace(case, rep, trace)
            return
        elif not result.ai_ranked:
            failure_class = "not_ai_ranked" if reason == "llm_not_configured" else "llm_failure"
            self._record_error(case, rep, failure_class, reason or "unknown", tries, result, cost)
            self._write_trace(case, rep, trace)
            return
        else:
            status = "ok"

        records = {r.restaurant_id: r for r in repository.restaurants}
        checks: dict[str, Any] = {}
        if status == "ok":
            checks = grade(
                case,
                result,
                selection.candidates,
                records,
                repository.metadata,
                self.config.max_results,
            )
        if status == "empty":
            # The control must finish without calling the API (EVL-03).
            checks = {"no_api_call": not d.candidates_sent and d.usage is None}
        row = {
            "case": case.id,
            "rep": rep,
            "tags": list(case.tags),
            "status": status,
            "ai_ranked": result.ai_ranked,
            "failure_reason": reason,
            "tries": tries,
            "passed_on_retry": tries > 1 or bool(d.retry_count),
            "requested_model": requested,
            "served_model": d.served_model,
            "fallback_model_used": d.fallback_model_used,
            "stop_reason": d.stop_reason,
            "latency_seconds": d.latency_seconds,
            "total_seconds": round(seconds, 3),
            "usage": d.usage,
            "cost_usd": cost,
            "relaxations": [r.limit for r in result.relaxations],
            "sent": list(d.candidates_sent),
            "summary": result.summary,
            "results": [
                {
                    "id": r.candidate.restaurant.restaurant_id,
                    "name": r.candidate.restaurant.name,
                    "rating": r.candidate.restaurant.rating,
                    "cost_for_two": r.candidate.restaurant.cost_for_two,
                    "explanation": r.explanation,
                    "unverified_preferences": list(r.unverified_preferences),
                    "review": r.review,
                }
                for r in result.results
            ],
            "checks": checks,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._append("results.jsonl", row)
        self._write_trace(case, rep, {**trace, "row": row})

    # Whole run

    def run(self, cases: list[Case]) -> None:
        self.prepare()
        done = self.finished()
        todo = [
            (c, rep)
            for rep in range(1, self.config.reps + 1)
            for c in cases
            if (c.id, rep) not in done
        ]
        skipped = len(cases) * self.config.reps - len(todo)
        if skipped:
            print(f"Skipping {skipped} finished attempts.")
        with ThreadPoolExecutor(max_workers=max(1, self.config.concurrency)) as pool:
            for future in [pool.submit(self.attempt, c, rep) for c, rep in todo]:
                future.result()
        if self.stopped_for_spend:
            print(f"Stopped at the spending cap: ${self.spent:.4f} of ${self.config.max_spend}.")


def run_info(settings, ranker: Ranker | None, repository: RestaurantRepository, variant: str):
    return {
        "variant": variant,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "build_id": repository.metadata.build_id,
        "prompt_version": PROMPT_VERSION,
        "provider": settings.llm_provider,
        "model": getattr(ranker, "model", None),
        "effort": getattr(ranker, "effort", None),
        "max_candidates": settings.max_candidates,
        "max_results": settings.max_results,
        "lock_hash": file_hash(LOCK_PATH),
        "cases_hash": file_hash(CASES_PATH),
        "judge": None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", default="baseline", help="Output folder name")
    parser.add_argument("--cases", help="Comma-separated case ids. Default: the 20 paid cases")
    parser.add_argument(
        "--confirmation",
        action="store_true",
        help="Allow the confirmation cases K1 to K5, for the final check only",
    )
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-spend", type=float, help="Stop at this many dollars. Required.")
    parser.add_argument(
        "--price",
        type=float,
        nargs=2,
        metavar=("IN", "OUT"),
        help="Dollars per million input and output tokens, if not built in",
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=0.0,
        help="Seconds between API calls, such as 30 on Groq's free plan",
    )
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--allow-no-llm",
        action="store_true",
        help="Run without an API key, for the zero-cost 'LLM off' check",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = load_settings()
    repository = RestaurantRepository.load(settings.restaurants_path, settings.metadata_path)
    ranker = make_ranker(settings)
    if ranker is None and not args.allow_no_llm:
        print("No API key is set. Add one to .env, or pass --allow-no-llm for the free check.")
        return 2
    price = tuple(args.price) if args.price else PRICES.get(getattr(ranker, "model", ""))
    if ranker is not None:
        if price is None:
            print(f"No price is known for {ranker.model}. Pass --price IN OUT per million tokens.")
            return 2
        if args.max_spend is None:
            print("A paid run needs --max-spend, the most it may spend in dollars.")
            return 2
    ids = [i.strip() for i in args.cases.split(",")] if args.cases else None
    cases = load_cases().select(ids, include_confirmation=args.confirmation)
    out_dir = OUTPUT_ROOT / args.variant
    config = RunConfig(
        reps=args.reps,
        concurrency=args.concurrency,
        max_spend=args.max_spend,
        price=price,
        retries=args.retries,
        pace=args.pace,
        max_candidates=settings.max_candidates,
        max_results=settings.max_results,
    )
    runner = Runner(
        repository, ranker, out_dir, config, run_info(settings, ranker, repository, args.variant)
    )
    runner.run(cases)
    summary, text = build_report(out_dir)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), "utf-8")
    (out_dir / "summary.txt").write_text(text + "\n", "utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
