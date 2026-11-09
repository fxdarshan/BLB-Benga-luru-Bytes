"""Checks the LLM's ranking against the candidates actually sent.

A JSON schema guarantees the shape of the answer, not that its content is right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from recommender.models import Candidate, RankedResult, RankingResponse

MAX_EXPLANATION_CHARS = 1000
_ALIAS = re.compile(r"\bR(\d{1,3})\b", re.IGNORECASE)


@dataclass(frozen=True)
class ValidatedRanking:
    results: list[RankedResult]
    summary: str | None
    dropped: int


def _normalise_id(value: str) -> str:
    return value.strip().upper()


def replace_aliases(text: str, candidates_by_alias: dict[str, Candidate]) -> str:
    """Swap any alias that was sent, such as R3, for that restaurant's name."""

    def swap(match: re.Match[str]) -> str:
        candidate = candidates_by_alias.get(f"R{match.group(1)}")
        return candidate.restaurant.name if candidate else match.group(0)

    return _ALIAS.sub(swap, text)


def _shorten(text: str) -> str:
    if len(text) <= MAX_EXPLANATION_CHARS:
        return text
    head = text[:MAX_EXPLANATION_CHARS].rsplit(" ", 1)[0]
    return f"{head}…"


def validate_ranking(
    ranking: RankingResponse,
    candidates_by_alias: dict[str, Candidate],
    *,
    max_results: int,
    has_free_text: bool,
) -> ValidatedRanking:
    results: list[RankedResult] = []
    seen: set[str] = set()
    dropped = 0
    for item in ranking.recommendations:
        alias = _normalise_id(item.candidate_id)
        explanation = item.explanation.strip()
        if alias not in candidates_by_alias or alias in seen or not explanation:
            dropped += 1
            continue
        seen.add(alias)
        unverified = tuple(p.strip() for p in item.unverified_preferences if p.strip())
        results.append(
            RankedResult(
                candidate=candidates_by_alias[alias],
                explanation=_shorten(replace_aliases(explanation, candidates_by_alias)),
                # Without free text, there are no soft preferences that could be unconfirmed.
                unverified_preferences=unverified if has_free_text else (),
            )
        )
    dropped += max(0, len(results) - max_results)
    results = results[:max_results]

    summary = replace_aliases(ranking.summary.strip(), candidates_by_alias)
    # A summary may describe a restaurant that was dropped, so it is only kept when nothing was.
    keep_summary = summary and dropped == 0 and results
    return ValidatedRanking(
        results=results, summary=summary if keep_summary else None, dropped=dropped
    )
