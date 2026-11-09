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


def _normalise_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _aliases_by_name(candidates_by_alias: dict[str, Candidate]) -> dict[str, str]:
    """Map each candidate's name to its alias, leaving out names that more than one shares.

    The prompt asks for names everywhere else, so the model sometimes gives a name as the id.
    A shared name, such as a chain's branches, can't say which branch was meant.
    """
    by_name: dict[str, str | None] = {}
    for alias, candidate in candidates_by_alias.items():
        name = _normalise_name(candidate.restaurant.name)
        by_name[name] = None if name in by_name else alias
    return {name: alias for name, alias in by_name.items() if alias is not None}


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


def _chosen_review(number: int, reviews: list[str]) -> str | None:
    """The review the LLM picked, by its number among those sent. Any other number shows none."""
    if 1 <= number <= len(reviews):
        return reviews[number - 1]
    return None


def validate_ranking(
    ranking: RankingResponse,
    candidates_by_alias: dict[str, Candidate],
    *,
    max_results: int,
    has_free_text: bool,
    reviews_by_alias: dict[str, list[str]] | None = None,
) -> ValidatedRanking:
    reviews_by_alias = reviews_by_alias or {}
    results: list[RankedResult] = []
    seen: set[str] = set()
    dropped = 0
    aliases_by_name = _aliases_by_name(candidates_by_alias)
    for item in ranking.recommendations:
        alias = _normalise_id(item.candidate_id)
        if alias not in candidates_by_alias:
            alias = aliases_by_name.get(_normalise_name(item.candidate_id), alias)
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
                review=_chosen_review(item.best_review, reviews_by_alias.get(alias, [])),
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
