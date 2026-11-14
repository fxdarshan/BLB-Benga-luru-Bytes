"""Tests for the SQLite usage store: counting, persistence, safety and the feedback export."""

from __future__ import annotations

import io
import sqlite3
import threading
from types import SimpleNamespace

from recommender.models import Preferences
from recommender.usage_store import SCHEMA_VERSION, UsageStore, export_feedback, main


def search(area="BTM", budget="any", cuisines=(), dishes=()):
    return Preferences(area=area, budget=budget, cuisines=cuisines, dishes=dishes)


def outcome(ai_ranked=True, cache_hit=False, failure_reason=None):
    return SimpleNamespace(
        ai_ranked=ai_ranked,
        failure_reason=failure_reason,
        diagnostics=SimpleNamespace(cache_hit=cache_hit),
    )


def test_counts_searches_their_choices_and_how_they_went():
    store = UsageStore()
    store.record_search(search("BTM", "low", ["North Indian"], ["Biryani"]), outcome())
    store.record_search(search("BTM", dishes=["Biryani"]), outcome(cache_hit=True))
    store.record_search(
        search("Indiranagar", "high"), outcome(ai_ranked=False, failure_reason="rate_limited")
    )
    stats = store.snapshot()
    assert stats["storage"] == "memory"
    assert (stats["searches"], stats["ai_ranked"], stats["cache_hits"]) == (3, 2, 1)
    assert stats["fallbacks"] == {"rate_limited": 1}
    assert stats["top_areas"] == [
        {"name": "BTM", "count": 2},
        {"name": "Indiranagar", "count": 1},
    ]
    assert stats["top_cuisines"] == [{"name": "North Indian", "count": 1}]
    assert stats["top_dishes"] == [{"name": "Biryani", "count": 2}]
    assert stats["budgets"] == {"any": 1, "high": 1, "low": 1}


def test_counts_feedback():
    store = UsageStore()
    store.record_feedback("Alpha", 1, True, True)
    store.record_feedback("Beta", 2, True, False)
    store.record_feedback("Gamma", 3, False, True)
    store.record_feedback("Delta", 4, False, True, "too_pricey")
    store.record_feedback("Echo", 5, False, True, "too_pricey")
    store.record_feedback("Gamma", 3, False, False, "too_far")
    assert store.snapshot()["feedback"] == {
        "helpful": 2,
        "not_helpful": 4,
        "reasons": {"too_far": 1, "too_pricey": 2},
    }


V1_FEEDBACK = """
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    restaurant TEXT NOT NULL,
    rank INTEGER NOT NULL,
    helpful INTEGER NOT NULL,
    ai_ranked INTEGER NOT NULL
);
INSERT INTO feedback (at, restaurant, rank, helpful, ai_ranked)
    VALUES ('2026-11-01T10:00:00Z', 'Alpha', 1, 0, 1);
PRAGMA user_version = 1;
"""


def test_a_schema_1_store_gains_reasons_and_keeps_its_feedback(tmp_path):
    path = tmp_path / "blb.sqlite3"
    db = sqlite3.connect(path)
    db.executescript(V1_FEEDBACK)
    db.close()
    out = io.StringIO()
    export_feedback(path, out)  # an old store still exports, with empty reasons
    assert out.getvalue().splitlines()[1] == "2026-11-01T10:00:00Z,Alpha,1,False,True,"
    store = UsageStore.open(path)
    assert store.persistent is True
    store.record_feedback("Beta", 2, False, True, "wrong_cuisine")
    assert store.snapshot()["feedback"] == {
        "helpful": 0,
        "not_helpful": 2,
        "reasons": {"wrong_cuisine": 1},
    }
    store.close()
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2
    db.close()


def test_an_empty_store_reports_zeros():
    stats = UsageStore().snapshot()
    assert (stats["searches"], stats["ai_ranked"], stats["cache_hits"]) == (0, 0, 0)
    assert stats["top_areas"] == [] and stats["fallbacks"] == {} and stats["budgets"] == {}
    assert stats["feedback"] == {"helpful": 0, "not_helpful": 0, "reasons": {}}


def test_counts_survive_reopening_the_file(tmp_path):
    path = tmp_path / "state" / "blb.sqlite3"
    first = UsageStore(path, clock=lambda: 1_794_600_000.0)
    first.record_search(search(), outcome())
    first.record_feedback("Alpha", 1, True, True)
    since = first.snapshot()["since"]
    first.close()

    second = UsageStore(path, clock=lambda: 1_794_700_000.0)
    stats = second.snapshot()
    assert stats["storage"] == "persistent"
    assert stats["searches"] == 1 and stats["feedback"]["helpful"] == 1
    # "since" is when the store was first created, not when it was reopened.
    assert stats["since"] == since == "2026-11-13T20:00:00Z"
    second.close()


def test_a_file_store_uses_write_ahead_logging(tmp_path):
    store = UsageStore(tmp_path / "blb.sqlite3")
    assert store._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    store.close()


def test_top_lists_hold_ten_most_common_first_then_by_name():
    store = UsageStore()
    for _ in range(3):
        store.record_search(search("Zeta"), outcome())
    for index in range(11):
        store.record_search(search(f"Area {index:02d}"), outcome())
    top = store.snapshot()["top_areas"]
    assert len(top) == 10
    assert top[0] == {"name": "Zeta", "count": 3}
    assert [entry["name"] for entry in top[1:3]] == ["Area 00", "Area 01"]


def test_open_falls_back_to_memory_when_the_file_cant_be_used(tmp_path, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    store = UsageStore.open(blocker / "blb.sqlite3")
    assert store.persistent is False
    store.record_search(search(), outcome())
    assert store.snapshot()["searches"] == 1
    assert "kept in memory" in caplog.text


def test_open_without_a_path_is_in_memory():
    assert UsageStore.open(None).persistent is False


def test_a_newer_schema_is_left_alone(tmp_path):
    path = tmp_path / "blb.sqlite3"
    db = sqlite3.connect(path)
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    db.close()
    assert UsageStore.open(path).persistent is False
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION + 1
    assert db.execute("SELECT name FROM sqlite_master").fetchall() == []
    db.close()


def test_recording_never_raises(caplog):
    store = UsageStore()
    store.close()
    store.record_search(search(), outcome())
    store.record_feedback("Alpha", 1, True, True)
    assert "Couldn't record a search" in caplog.text
    assert "Couldn't record feedback" in caplog.text


def test_concurrent_searches_are_all_counted():
    store = UsageStore()

    def record_many():
        for _ in range(25):
            store.record_search(search(dishes=["Biryani"]), outcome())

    threads = [threading.Thread(target=record_many) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stats = store.snapshot()
    assert stats["searches"] == 200
    assert stats["top_dishes"] == [{"name": "Biryani", "count": 200}]


def test_export_writes_feedback_as_csv_oldest_first(tmp_path):
    path = tmp_path / "blb.sqlite3"
    store = UsageStore(path, clock=lambda: 1_794_600_000.0)
    store.record_feedback("Jose's Mess", 1, True, True)
    store.record_feedback("Beta, Bistro", 2, False, False, "explanation_off")
    store.close()
    out = io.StringIO()
    assert export_feedback(path, out) == 2
    assert out.getvalue().splitlines() == [
        "at,restaurant,rank,helpful,ai_ranked,reason",
        "2026-11-13T20:00:00Z,Jose's Mess,1,True,True,",
        '2026-11-13T20:00:00Z,"Beta, Bistro",2,False,False,explanation_off',
    ]


def test_command_line_exports_and_reports_problems(tmp_path, capsys):
    assert main([]) == 2
    assert main([str(tmp_path / "missing.sqlite3")]) == 1
    path = tmp_path / "blb.sqlite3"
    store = UsageStore(path)
    store.record_feedback("Alpha", 1, True, True)
    store.close()
    capsys.readouterr()
    assert main([str(path)]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("at,restaurant,rank,helpful,ai_ranked,reason\n")
    assert "1 feedback rows" in captured.err
