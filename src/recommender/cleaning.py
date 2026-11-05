"""Functions that turn raw dataset values into clean Python values."""

from __future__ import annotations

import ast
import hashlib
import re
import unicodedata
from collections import Counter
from typing import Any

import ftfy
import pandas as pd

MAX_REVIEWS = 5
MAX_REVIEW_CHARS = 300
# The longest value in the dataset is about 1.28 million characters. Parsing far larger
# strings risks exhausting memory, so they are treated as parse failures.
MAX_RAW_REVIEW_CHARS = 2_000_000

_RATE = re.compile(r"^\s*([\d.]+)\s*/\s*5\s*$")
_C1_CONTROL = re.compile(r"[\x80-\x9f]")
# Valid UTF-8 byte sequences, written as the Latin-1 characters they appear as when mis-decoded.
_UTF8_AS_LATIN1 = re.compile(
    r"[\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf4][\x80-\xbf]{3}"
)
_MAX_ENCODING_LAYERS = 12
_MOJIBAKE_RESIDUE = re.compile(r"[\x80-\x9f]|Ã|Â|â€|ð[\x80-\xbfŒ-™]")
_RATED_PREFIX = re.compile(r"^\s*RATED\s*", re.IGNORECASE)
_NON_WORD = re.compile(r"[\W_]+")


def _missing(value: Any) -> bool:
    return value is None or (not isinstance(value, (str, list, tuple)) and pd.isna(value))


def parse_rate(raw: Any) -> tuple[float | None, bool]:
    """Return `(rating, is_new)` from a value such as `4.1/5`, `3.6 /5`, `NEW` or `-`."""
    if _missing(raw):
        return None, False
    text = str(raw).strip()
    if text.casefold() == "new":
        return None, True
    match = _RATE.match(text)
    if not match:
        return None, False
    try:
        rating = float(match.group(1))
    except ValueError:  # The pattern also accepts values such as "4.1.2" and ".".
        return None, False
    return (rating, False) if 0 <= rating <= 5 else (None, False)


def parse_cost(raw: Any) -> int | None:
    """Return a positive integer from a value such as `800` or `1,300`, or `None`."""
    if _missing(raw):
        return None
    try:
        cost = int(str(raw).replace(",", "").strip())
    except ValueError:
        return None
    return cost if cost > 0 else None


def parse_yes_no(raw: Any) -> bool | None:
    """Return True for `Yes`, False for `No`, and `None` for anything else."""
    if _missing(raw):
        return None
    return {"yes": True, "no": False}.get(str(raw).strip().casefold())


def split_multi_value(raw: Any) -> list[str]:
    """Split a comma-separated value, dropping blanks and repeats but keeping the first order.

    Labels keep their original case, so that a name such as `BBQ` isn't turned into `Bbq`.
    """
    if _missing(raw):
        return []
    result: dict[str, str] = {}
    for item in str(raw).split(","):
        label = item.strip()
        if label:
            result.setdefault(label.casefold(), label)
    return list(result.values())


def repair_text(raw: Any) -> str | None:
    """Fix encoding corruption, returning `None` for a missing value.

    The dataset's text was mis-decoded repeatedly, up to 7 layers deep. `ftfy` can't undo that
    when the layers are damaged, so complete UTF-8 sequences are decoded layer by layer first.
    C1 control characters mark those layers, as they don't appear in normal text.
    """
    if _missing(raw):
        return None
    text = str(raw)
    if text.isascii():
        return text
    for _ in range(_MAX_ENCODING_LAYERS):
        if not _C1_CONTROL.search(text):
            break
        peeled = _UTF8_AS_LATIN1.sub(_decode_sequence, text)
        if peeled == text:
            break
        text = peeled
    return ftfy.fix_text(text)


def _decode_sequence(match: re.Match[str]) -> str:
    try:
        return match.group().encode("latin-1").decode("utf-8")
    except UnicodeDecodeError:
        return match.group()


def has_mojibake(text: str) -> bool:
    """Return True if text still shows signs of encoding corruption."""
    return bool(_MOJIBAKE_RESIDUE.search(text))


def _cut_at_word(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    head, space, _ = cut.rpartition(" ")
    return head if space and head else cut


def parse_reviews(
    raw: Any,
    *,
    max_reviews: int = MAX_REVIEWS,
    max_chars: int = MAX_REVIEW_CHARS,
    stats: Counter[str] | None = None,
) -> list[str]:
    """Extract short review snippets from a value such as `[('Rated 4.0', 'RATED\\n  Tasty')]`.

    Text is repaired after parsing, since some corruption is stored as escape sequences that only
    become real characters at that point. Returns an empty list if the value can't be parsed, and
    counts the failure in `stats`.
    """
    if _missing(raw):
        return []
    text = str(raw)
    try:
        if len(text) > MAX_RAW_REVIEW_CHARS:
            raise ValueError("review value is too long to parse safely")
        parsed = ast.literal_eval(text)
        if not isinstance(parsed, (list, tuple)):
            raise ValueError("review value is not a list")
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        if stats is not None:
            stats["review_parse_failures"] += 1
        return []

    snippets: list[str] = []
    for item in parsed:
        if len(snippets) == max_reviews:
            break
        if not (isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], str)):
            if stats is not None:
                stats["review_items_skipped"] += 1
            continue
        body = " ".join(_RATED_PREFIX.sub("", repair_text(item[1])).split())
        if body:
            snippets.append(_cut_at_word(body, max_chars))
    return snippets


def normalise_key(name: str, address: str | None) -> str:
    """Build the deduplication key, ignoring case, accents, punctuation and spacing."""

    def normalise(value: str | None) -> str:
        decomposed = unicodedata.normalize("NFKD", value or "")
        without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
        return _NON_WORD.sub(" ", without_accents.casefold()).strip()

    return f"{normalise(name)}|{normalise(address)}"


def restaurant_id(key: str) -> str:
    """Return a stable ID for a deduplication key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
