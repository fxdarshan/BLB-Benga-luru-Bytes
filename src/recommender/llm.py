"""Types shared by every LLM client. Each provider's SDK is imported only by its own module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from recommender.models import RankingResponse

# Written by hand, so the request doesn't depend on how a library converts the Pydantic model.
RANKING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "The candidate's id from <candidates>, such as R1",
                    },
                    "explanation": {"type": "string"},
                    "unverified_preferences": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["candidate_id", "explanation", "unverified_preferences"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "recommendations"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class CallDetails:
    """What is known about a call, whether or not it succeeded."""

    raw_text: str | None = None
    usage: dict[str, int] | None = None
    stop_reason: str | None = None
    served_model: str | None = None
    fallback_model_used: bool = False
    latency_seconds: float | None = None
    retry_count: int | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class LLMReply:
    ranking: RankingResponse
    details: CallDetails


class LLMUnavailable(Exception):
    """The LLM gave no usable ranking. `reason` is a short code for logs and evaluation."""

    def __init__(self, reason: str, details: CallDetails | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or CallDetails()
