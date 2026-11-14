"""Usage counts and feedback, kept in SQLite so they survive restarts and deploys.

The API records one row per search and one per piece of feedback. Nothing personal is kept: no
IP addresses, and none of the free text a diner types. A search keeps only its choices from the
fixed lists (area, budget, cuisines, dishes) and how it went.

Without a path the database lives in memory, so the counts reset when the server restarts. That
is the default locally and in tests. On Railway, STATE_DIR points at a mounted volume.

Export the feedback for the evaluation with:

    python -m recommender.usage_store /app/state/blb.sqlite3 > feedback.csv
"""

from __future__ import annotations

import csv
import logging
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)

DB_FILENAME = "blb.sqlite3"
SCHEMA_VERSION = 2
TOP = 10

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    area TEXT NOT NULL,
    budget TEXT NOT NULL,
    ai_ranked INTEGER NOT NULL,
    cache_hit INTEGER NOT NULL,
    failure_reason TEXT
);
CREATE TABLE IF NOT EXISTS search_choices (
    search_id INTEGER NOT NULL REFERENCES searches (id),
    kind TEXT NOT NULL CHECK (kind IN ('cuisine', 'dish')),
    name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS search_choices_by_name ON search_choices (kind, name);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    restaurant TEXT NOT NULL,
    rank INTEGER NOT NULL,
    helpful INTEGER NOT NULL,
    ai_ranked INTEGER NOT NULL,
    reason TEXT
);
"""


def _has_reason(db: sqlite3.Connection) -> bool:
    return any(row[1] == "reason" for row in db.execute("PRAGMA table_info(feedback)"))


def _timestamp(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def _top(rows: Iterable[tuple[str, int]]) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in rows]


class UsageStore:
    """Counts searches and feedback. One connection, used under a lock, so it is thread-safe."""

    def __init__(
        self, path: str | Path | None = None, *, clock: Callable[[], float] = time.time
    ) -> None:
        self.path = Path(path) if path is not None else None
        self._clock = clock
        self._lock = threading.Lock()
        self._db = self._connect()

    @classmethod
    def open(cls, path: str | Path | None) -> UsageStore:
        """A store at this path, or in memory if the file can't be used, so the API still starts."""
        if path is None:
            return cls()
        try:
            return cls(path)
        except (OSError, sqlite3.Error) as error:
            logger.error(
                "The usage store at %s is unavailable, so counts are kept in memory: %s",
                path,
                error,
            )
            return cls()

    @property
    def persistent(self) -> bool:
        return self.path is not None

    def _connect(self) -> sqlite3.Connection:
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(
            self.path if self.path is not None else ":memory:", check_same_thread=False
        )
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise sqlite3.DatabaseError(
                    f"the usage store has schema {version}, newer than this code's {SCHEMA_VERSION}"
                )
            if self.path is not None:
                # Readers don't block the writer, so /stats never holds up a search.
                db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            # Schema 2 adds why a diner said an explanation wasn't helpful.
            if not _has_reason(db):
                db.execute("ALTER TABLE feedback ADD COLUMN reason TEXT")
            with db:
                db.execute(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES ('created', ?)",
                    (_timestamp(self._clock()),),
                )
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except Exception:
            db.close()
            raise
        return db

    def record_search(self, preferences: Any, result: Any) -> None:
        """Count one search: its choices from the fixed lists, and how it went. Never raises."""
        try:
            with self._lock, self._db:
                cursor = self._db.execute(
                    "INSERT INTO searches (at, area, budget, ai_ranked, cache_hit, failure_reason)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        _timestamp(self._clock()),
                        preferences.area,
                        preferences.budget,
                        int(result.ai_ranked),
                        int(result.diagnostics.cache_hit),
                        result.failure_reason,
                    ),
                )
                search_id = cursor.lastrowid
                choices = [(search_id, "cuisine", name) for name in preferences.cuisines]
                choices += [(search_id, "dish", name) for name in preferences.dishes]
                self._db.executemany(
                    "INSERT INTO search_choices (search_id, kind, name) VALUES (?, ?, ?)", choices
                )
        except sqlite3.Error:
            logger.exception("Couldn't record a search in the usage store")

    def record_feedback(
        self,
        restaurant: str,
        rank: int,
        helpful: bool,
        ai_ranked: bool,
        reason: str | None = None,
    ) -> None:
        """Keep one thumbs up or down on a result's explanation, and why if given. Never raises."""
        try:
            with self._lock, self._db:
                self._db.execute(
                    "INSERT INTO feedback (at, restaurant, rank, helpful, ai_ranked, reason)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        _timestamp(self._clock()),
                        restaurant,
                        rank,
                        int(helpful),
                        int(ai_ranked),
                        reason,
                    ),
                )
        except sqlite3.Error:
            logger.exception("Couldn't record feedback in the usage store")

    def snapshot(self) -> dict[str, Any]:
        """Totals since the store was created, and the most chosen areas, cuisines and dishes."""
        with self._lock:
            run = self._db.execute
            since = run("SELECT value FROM meta WHERE key = 'created'").fetchone()[0]
            searches, ai_ranked, cache_hits = run(
                "SELECT COUNT(*), COALESCE(SUM(ai_ranked), 0), COALESCE(SUM(cache_hit), 0)"
                " FROM searches"
            ).fetchone()
            fallbacks = dict(
                run(
                    "SELECT failure_reason, COUNT(*) FROM searches"
                    " WHERE failure_reason IS NOT NULL"
                    " GROUP BY failure_reason ORDER BY failure_reason"
                ).fetchall()
            )
            budgets = dict(
                run(
                    "SELECT budget, COUNT(*) FROM searches GROUP BY budget ORDER BY budget"
                ).fetchall()
            )
            top_areas = _top(
                run(
                    "SELECT area, COUNT(*) AS n FROM searches"
                    " GROUP BY area ORDER BY n DESC, area LIMIT ?",
                    (TOP,),
                )
            )
            top_choices = {
                kind: _top(
                    run(
                        "SELECT name, COUNT(*) AS n FROM search_choices WHERE kind = ?"
                        " GROUP BY name ORDER BY n DESC, name LIMIT ?",
                        (kind, TOP),
                    )
                )
                for kind in ("cuisine", "dish")
            }
            votes = dict(run("SELECT helpful, COUNT(*) FROM feedback GROUP BY helpful").fetchall())
            reasons = dict(
                run(
                    "SELECT reason, COUNT(*) FROM feedback WHERE reason IS NOT NULL"
                    " GROUP BY reason ORDER BY reason"
                ).fetchall()
            )
        return {
            "since": since,
            "storage": "persistent" if self.persistent else "memory",
            "searches": searches,
            "ai_ranked": ai_ranked,
            "cache_hits": cache_hits,
            "fallbacks": fallbacks,
            "top_areas": top_areas,
            "top_cuisines": top_choices["cuisine"],
            "top_dishes": top_choices["dish"],
            "budgets": budgets,
            "feedback": {
                "helpful": votes.get(1, 0),
                "not_helpful": votes.get(0, 0),
                "reasons": reasons,
            },
        }

    def close(self) -> None:
        with self._lock:
            self._db.close()


def export_feedback(path: Path, out: TextIO) -> int:
    """Write every piece of feedback as CSV, oldest first. Opens the file read-only."""
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        # A store from before schema 2 has no reasons; its rows export with an empty one.
        reason = "reason" if _has_reason(db) else "NULL"
        rows = db.execute(
            f"SELECT at, restaurant, rank, helpful, ai_ranked, {reason} FROM feedback ORDER BY id"
        ).fetchall()
    finally:
        db.close()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["at", "restaurant", "rank", "helpful", "ai_ranked", "reason"])
    for at, restaurant, rank, helpful, ai_ranked, why in rows:
        writer.writerow([at, restaurant, rank, bool(helpful), bool(ai_ranked), why or ""])
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: python -m recommender.usage_store <path to blb.sqlite3>", file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.is_file():
        print(f"No usage store at {path}", file=sys.stderr)
        return 1
    count = export_feedback(path, sys.stdout)
    print(f"{count} feedback rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
